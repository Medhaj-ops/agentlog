import pytest
from opentelemetry.trace import StatusCode

from .conftest import MockStream, MockUsage, make_chunk

pytest.importorskip("openai")
pytest.importorskip("litellm")


class _MockMessage:
    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


class _MockNonStreamChoice:
    def __init__(self, message, finish_reason):
        self.message = message
        self.finish_reason = finish_reason


class _MockCompletionResponse:
    def __init__(self, model, choices, usage):
        self.model = model
        self.choices = choices
        self.usage = usage


def test_openai_stream_true_returns_traced_stream(span_exporter, monkeypatch):
    from agentlog import instrument
    from agentlog.stream import TracedStream
    from openai.resources.chat.completions import Completions

    chunks = [make_chunk(role="assistant", content="hi", finish_reason="stop", model="gpt-4o")]

    def fake_create(self, *args, **kwargs):
        return MockStream(chunks)

    monkeypatch.setattr(Completions, "create", fake_create)
    monkeypatch.setattr(instrument, "_patched", False)
    instrument.patch_openai()

    response = Completions.create(
        object(), model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    assert isinstance(response, TracedStream)

    list(response)  # drain the stream to trigger finalization

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream"] is True
    assert span.attributes["gen_ai.request.model"] == "gpt-4o"
    assert span.attributes["gen_ai.response.finish_reason"] == "stop"


def test_litellm_stream_true_returns_traced_stream(span_exporter, monkeypatch):
    import litellm as litellm_module
    from agentlog import instrument_litellm
    from agentlog.stream_litellm import TracedLiteLLMStream

    chunks = [make_chunk(role="assistant", content="hi", finish_reason="stop", model="gpt-4o")]

    def fake_completion(*args, **kwargs):
        return MockStream(chunks)

    monkeypatch.setattr(litellm_module, "completion", fake_completion)
    monkeypatch.setattr(instrument_litellm, "_patched", False)
    instrument_litellm.patch_litellm()

    response = litellm_module.completion(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    assert isinstance(response, TracedLiteLLMStream)

    list(response)

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["gen_ai.stream"] is True
    assert span.attributes["gen_ai.request.model"] == "gpt-4o"


def test_non_streaming_unchanged(span_exporter, monkeypatch):
    """Regression test: non-streaming behavior must be untouched by the streaming branch."""
    from agentlog import instrument
    from openai.resources.chat.completions import Completions

    mock_response = _MockCompletionResponse(
        model="gpt-4o",
        choices=[_MockNonStreamChoice(_MockMessage(role="assistant", content="hi"), finish_reason="stop")],
        usage=MockUsage(prompt_tokens=10, completion_tokens=5),
    )

    def fake_create(self, *args, **kwargs):
        return mock_response

    monkeypatch.setattr(Completions, "create", fake_create)
    monkeypatch.setattr(instrument, "_patched", False)
    instrument.patch_openai()

    response = Completions.create(
        object(), model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
    )

    assert response is mock_response  # returned unchanged, not wrapped in a proxy

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.UNSET
    assert "gen_ai.stream" not in span.attributes
    assert span.attributes["gen_ai.usage.input_tokens"] == 10
    assert span.attributes["gen_ai.usage.output_tokens"] == 5
    assert span.attributes["gen_ai.response.finish_reason"] == "stop"
