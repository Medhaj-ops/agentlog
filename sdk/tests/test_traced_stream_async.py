import json

import pytest
from agentlog.stream import TracedAsyncStream
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from .conftest import MockAsyncStream, make_chunk

pytestmark = pytest.mark.asyncio


def _start_span():
    tracer = trace.get_tracer("test")
    return tracer.start_span("chat.completions.create")


def _attrs(exporter):
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    return spans[0]


async def _collect(stream):
    return [chunk async for chunk in stream]


async def test_normal_exhaustion(span_exporter):
    chunks = [
        make_chunk(role="assistant", content="", model="gpt-4o"),
        make_chunk(content="Hello"),
        make_chunk(content=" there", finish_reason="stop", usage=(10, 5)),
    ]
    stream = TracedAsyncStream(MockAsyncStream(chunks), _start_span())

    collected = await _collect(stream)

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


async def test_provider_error_after_partial_output(span_exporter):
    chunks = [
        make_chunk(role="assistant", content="Hel"),
        make_chunk(content="lo"),
    ]
    stream = TracedAsyncStream(MockAsyncStream(chunks, error_after=2), _start_span())

    collected = []
    try:
        async for chunk in stream:
            collected.append(chunk)
    except ConnectionError:
        pass

    assert len(collected) == 2
    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.ERROR
    assert "gen_ai.stream.partial" not in span.attributes
    assert "Hello" in span.attributes["gen_ai.completion"]


async def test_provider_error_on_first_chunk(span_exporter):
    stream = TracedAsyncStream(MockAsyncStream([], error_after=0), _start_span())

    try:
        await stream.__anext__()
        assert False, "expected ConnectionError"
    except ConnectionError:
        pass

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.ERROR
    completion = json.loads(span.attributes["gen_ai.completion"])
    assert completion["content"] is None


async def test_caller_calls_close(span_exporter):
    chunks = [make_chunk(content="partial")]
    stream = TracedAsyncStream(MockAsyncStream(chunks), _start_span())

    await stream.__anext__()
    await stream.close()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream.partial"] is True


async def test_context_manager_normal_exit(span_exporter):
    chunks = [make_chunk(role="assistant", content="hi", finish_reason="stop")]
    async with TracedAsyncStream(MockAsyncStream(chunks), _start_span()) as stream:
        collected = await _collect(stream)

    assert collected
    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert "gen_ai.stream.partial" not in span.attributes


async def test_context_manager_early_exit(span_exporter):
    chunks = [make_chunk(content="a"), make_chunk(content="b")]
    async with TracedAsyncStream(MockAsyncStream(chunks), _start_span()) as stream:
        await stream.__anext__()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream.partial"] is True


async def test_consumer_exception_in_with_block(span_exporter):
    chunks = [make_chunk(content="a"), make_chunk(content="b")]

    try:
        async with TracedAsyncStream(MockAsyncStream(chunks), _start_span()) as stream:
            async for _ in stream:
                raise ValueError("caller's own bug")
    except ValueError:
        pass

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream.partial"] is True


async def test_double_finalization_exhaust_then_close(span_exporter):
    chunks = [make_chunk(content="a", finish_reason="stop")]
    stream = TracedAsyncStream(MockAsyncStream(chunks), _start_span())

    await _collect(stream)
    await stream.close()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK
    assert "gen_ai.stream.partial" not in span.attributes


async def test_double_finalization_close_then_close(span_exporter):
    stream = TracedAsyncStream(MockAsyncStream([make_chunk(content="a")]), _start_span())
    await stream.close()
    await stream.close()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK


async def test_double_finalization_exit_then_close(span_exporter):
    chunks = [make_chunk(content="a")]
    stream = TracedAsyncStream(MockAsyncStream(chunks), _start_span())
    async with stream:
        pass
    await stream.close()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.OK


async def test_double_finalization_provider_error_then_close(span_exporter):
    stream = TracedAsyncStream(MockAsyncStream([], error_after=0), _start_span())
    try:
        await stream.__anext__()
    except ConnectionError:
        pass
    await stream.close()

    span = _attrs(span_exporter)
    assert span.status.status_code == StatusCode.ERROR


async def test_chunks_pass_through_unchanged(span_exporter):
    chunks = [make_chunk(content="a"), make_chunk(content="b")]
    stream = TracedAsyncStream(MockAsyncStream(chunks), _start_span())

    collected = await _collect(stream)

    assert collected == chunks
    for original, passed in zip(chunks, collected):
        assert original is passed
