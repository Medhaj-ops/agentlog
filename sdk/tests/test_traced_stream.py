from agentlog.stream import TracedStream
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from .conftest import MockStream, make_chunk


def _start_span():
    tracer = trace.get_tracer("test")
    return tracer.start_span("chat.completions.create")


def _attrs(exporter):
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    return spans[0]


def test_normal_exhaustion(span_exporter):
    chunks = [
        make_chunk(role="assistant", content="", model="gpt-4o"),
        make_chunk(content="Hello"),
        make_chunk(content=" there", finish_reason="stop", usage=(10, 5)),
    ]
    stream = TracedStream(MockStream(chunks), _start_span())

    collected = list(stream)

    assert len(collected) == 3
    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream"] is True
    assert "gen_ai.stream.partial" not in span.attributes
    assert span.attributes["gen_ai.response.model"] == "gpt-4o"
    assert span.attributes["gen_ai.response.finish_reason"] == "stop"
    assert span.attributes["gen_ai.usage.input_tokens"] == 10
    assert span.attributes["gen_ai.usage.output_tokens"] == 5
    assert "Hello there" in span.attributes["gen_ai.completion"]


def test_provider_error_after_partial_output(span_exporter):
    chunks = [
        make_chunk(role="assistant", content="Hel"),
        make_chunk(content="lo"),
    ]
    stream = TracedStream(MockStream(chunks, error_after=2), _start_span())

    collected = []
    try:
        for chunk in stream:
            collected.append(chunk)  # noqa: PERF402 — must catch mid-loop, list(stream) would lose partial results
    except ConnectionError:
        pass

    assert len(collected) == 2
    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.ERROR
    assert "gen_ai.stream.partial" not in span.attributes
    assert "Hello" in span.attributes["gen_ai.completion"]


def test_provider_error_on_first_chunk(span_exporter):
    stream = TracedStream(MockStream([], error_after=0), _start_span())

    try:
        next(stream)
        assert False, "expected ConnectionError"
    except ConnectionError:
        pass

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.ERROR
    import json

    completion = json.loads(span.attributes["gen_ai.completion"])
    assert completion["content"] is None


def test_caller_calls_close(span_exporter):
    chunks = [make_chunk(content="partial")]
    stream = TracedStream(MockStream(chunks), _start_span())

    next(stream)
    stream.close()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream.partial"] is True


def test_context_manager_normal_exit(span_exporter):
    chunks = [
        make_chunk(role="assistant", content="hi", finish_reason="stop"),
    ]
    with TracedStream(MockStream(chunks), _start_span()) as stream:
        collected = list(stream)

    assert collected
    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert "gen_ai.stream.partial" not in span.attributes


def test_context_manager_early_exit(span_exporter):
    chunks = [make_chunk(content="a"), make_chunk(content="b")]
    with TracedStream(MockStream(chunks), _start_span()) as stream:
        next(stream)  # only consume one chunk, then exit

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream.partial"] is True


def test_consumer_exception_in_with_block(span_exporter):
    chunks = [make_chunk(content="a"), make_chunk(content="b")]

    try:
        with TracedStream(MockStream(chunks), _start_span()) as stream:
            for _ in stream:
                raise ValueError("caller's own bug")
    except ValueError:
        pass

    span = _attrs(span_exporter)
    # Consumer's own exception must not be reported as a provider ERROR.
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream.partial"] is True


def test_double_finalization_exhaust_then_close(span_exporter):
    chunks = [make_chunk(content="a", finish_reason="stop")]
    stream = TracedStream(MockStream(chunks), _start_span())

    list(stream)
    stream.close()  # no-op, already finalized on exhaustion

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert "gen_ai.stream.partial" not in span.attributes


def test_double_finalization_close_then_close(span_exporter):
    stream = TracedStream(MockStream([make_chunk(content="a")]), _start_span())
    stream.close()
    stream.close()  # must not raise or double-set attributes

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK


def test_double_finalization_exit_then_close(span_exporter):
    chunks = [make_chunk(content="a")]
    stream = TracedStream(MockStream(chunks), _start_span())
    with stream:
        pass
    stream.close()  # no-op

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK


def test_double_finalization_provider_error_then_close(span_exporter):
    stream = TracedStream(MockStream([], error_after=0), _start_span())
    try:
        next(stream)
    except ConnectionError:
        pass
    stream.close()  # no-op, already finalized as ERROR

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.ERROR


def test_chunks_pass_through_unchanged(span_exporter):
    chunks = [make_chunk(content="a"), make_chunk(content="b")]
    stream = TracedStream(MockStream(chunks), _start_span())

    collected = list(stream)

    assert collected == chunks
    for original, passed in zip(chunks, collected):
        assert original is passed
