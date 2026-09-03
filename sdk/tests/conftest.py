import pytest

# The OTel API installs the global tracer provider at most once per process
# (set-once semantics), so we install a single InMemorySpanExporter lazily
# and just clear it between tests rather than swapping providers per-test.
_exporter = None


def _shared_exporter():
    global _exporter
    if _exporter is None:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        _exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
        trace.set_tracer_provider(provider)
    return _exporter


@pytest.fixture
def span_exporter():
    """In-memory span exporter for asserting on span attributes/status."""
    exporter = _shared_exporter()
    exporter.clear()
    yield exporter
    exporter.clear()


class MockToolCallFunction:
    """Mock of ChoiceDeltaToolCallFunction."""

    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class MockToolCallDelta:
    """Mock of openai.types.chat.chat_completion_chunk.ChoiceDeltaToolCall."""

    def __init__(self, index, id=None, type=None, function=None):
        self.index = index
        self.id = id
        self.type = type
        self.function = function


class MockDelta:
    """Mock of openai.types.chat.chat_completion_chunk.ChoiceDelta."""

    def __init__(self, content=None, role=None, tool_calls=None):
        self.content = content
        self.role = role
        self.tool_calls = tool_calls


class MockChoice:
    """Mock of openai.types.chat.chat_completion_chunk.Choice."""

    def __init__(self, delta=None, finish_reason=None, index=0):
        self.delta = delta or MockDelta()
        self.finish_reason = finish_reason
        self.index = index


class MockUsage:
    """Mock of CompletionUsage."""

    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class MockChunk:
    """Mock of openai.types.chat.ChatCompletionChunk."""

    def __init__(self, choices=None, model=None, usage=None):
        self.choices = choices if choices is not None else []
        self.model = model
        self.usage = usage


def make_tool_call_delta(index, id=None, type=None, name=None, arguments=None):
    """Factory for creating mock tool call deltas."""
    function = None
    if name is not None or arguments is not None:
        function = MockToolCallFunction(name=name, arguments=arguments)
    return MockToolCallDelta(index=index, id=id, type=type, function=function)


def make_chunk(content=None, role=None, finish_reason=None, tool_calls=None, model=None, usage=None, empty_choices=False):
    """Factory for creating mock streaming chunks.

    Provider-agnostic — used for both OpenAI and LiteLLM accumulator tests,
    since both expose the same `choices[0].delta` / `chunk.usage` shape.
    """
    mock_usage = MockUsage(*usage) if usage else None

    if empty_choices:
        return MockChunk(choices=[], model=model, usage=mock_usage)

    delta = MockDelta(content=content, role=role, tool_calls=tool_calls)
    choice = MockChoice(delta=delta, finish_reason=finish_reason)
    return MockChunk(choices=[choice], model=model, usage=mock_usage)


class MockStream:
    """Mock sync stream that yields pre-defined chunks, with optional mid-stream error."""

    def __init__(self, chunks, error_after=None):
        self._chunks = chunks
        self._error_after = error_after
        self._index = 0
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._error_after is not None and self._index >= self._error_after:
            raise ConnectionError("mock stream error")
        if self._index >= len(self._chunks):
            raise StopIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def close(self):
        self._closed = True

    @property
    def response(self):
        return None


class MockAsyncStream:
    """Async version of MockStream."""

    def __init__(self, chunks, error_after=None):
        self._chunks = chunks
        self._error_after = error_after
        self._index = 0
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._error_after is not None and self._index >= self._error_after:
            raise ConnectionError("mock stream error")
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
        return False

    async def close(self):
        self._closed = True

    @property
    def response(self):
        return None
