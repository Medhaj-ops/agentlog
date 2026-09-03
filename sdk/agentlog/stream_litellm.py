import json

from opentelemetry.trace import StatusCode

from . import attributes as attr
from . import redact
from .accumulator import StreamAccumulator


class TracedLiteLLMStream:
    """Proxy wrapper around litellm's CustomStreamWrapper (sync iteration)."""

    def __init__(self, stream, span):
        self._stream = stream
        self._span = span
        self._accumulator = StreamAccumulator()
        self._finalized = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
            self._accumulator.ingest(chunk)
            return chunk
        except StopIteration:
            self._finalize_span_ok(partial=False)
            raise
        except Exception as exc:
            self._finalize_span_error(exc)
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._finalized:
            self._finalize_span_ok(partial=True)
        if hasattr(self._stream, "close"):
            self._stream.close()
        return False

    def close(self):
        if not self._finalized:
            self._finalize_span_ok(partial=True)
        if hasattr(self._stream, "close"):
            self._stream.close()

    def __del__(self):
        try:
            if not self._finalized:
                self._finalize_span_ok(partial=True)
        except Exception:  # noqa: BLE001, S110 — best-effort GC cleanup, must never raise
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def _finalize_span_ok(self, partial: bool):
        if self._finalized:
            return
        self._finalized = True
        self._set_accumulated_attributes()
        if partial:
            self._span.set_attribute("gen_ai.stream.partial", True)
        self._span.set_status(StatusCode.OK)
        self._span.end()

    def _finalize_span_error(self, exc: Exception):
        if self._finalized:
            return
        self._finalized = True
        self._set_accumulated_attributes()
        self._span.set_status(StatusCode.ERROR, str(exc))
        self._span.record_exception(exc)
        self._span.end()

    def _set_accumulated_attributes(self):
        self._span.set_attribute("gen_ai.stream", True)

        result = self._accumulator.finalize()

        if result["model"]:
            self._span.set_attribute(attr.RESPONSE_MODEL, result["model"])

        if result["finish_reason"]:
            self._span.set_attribute(attr.FINISH_REASON, result["finish_reason"])

        if result["usage"]:
            self._span.set_attribute(attr.USAGE_INPUT_TOKENS, result["usage"]["prompt_tokens"])
            self._span.set_attribute(attr.USAGE_OUTPUT_TOKENS, result["usage"]["completion_tokens"])

        self._span.set_attribute(
            attr.COMPLETION,
            redact.apply(json.dumps(result["completion"], default=str)),
        )


class TracedAsyncLiteLLMStream:
    """Proxy wrapper around litellm's CustomStreamWrapper (async iteration)."""

    def __init__(self, stream, span):
        self._stream = stream
        self._span = span
        self._accumulator = StreamAccumulator()
        self._finalized = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self._stream.__anext__()
            self._accumulator.ingest(chunk)
            return chunk
        except StopAsyncIteration:
            self._finalize_span_ok(partial=False)
            raise
        except Exception as exc:
            self._finalize_span_error(exc)
            raise

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._finalized:
            self._finalize_span_ok(partial=True)
        if hasattr(self._stream, "close"):
            await self._stream.close()
        return False

    async def close(self):
        if not self._finalized:
            self._finalize_span_ok(partial=True)
        if hasattr(self._stream, "close"):
            await self._stream.close()

    def __del__(self):
        try:
            if not self._finalized:
                self._finalize_span_ok(partial=True)
        except Exception:  # noqa: BLE001, S110 — best-effort GC cleanup, must never raise
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def _finalize_span_ok(self, partial: bool):
        if self._finalized:
            return
        self._finalized = True
        self._set_accumulated_attributes()
        if partial:
            self._span.set_attribute("gen_ai.stream.partial", True)
        self._span.set_status(StatusCode.OK)
        self._span.end()

    def _finalize_span_error(self, exc: Exception):
        if self._finalized:
            return
        self._finalized = True
        self._set_accumulated_attributes()
        self._span.set_status(StatusCode.ERROR, str(exc))
        self._span.record_exception(exc)
        self._span.end()

    def _set_accumulated_attributes(self):
        self._span.set_attribute("gen_ai.stream", True)

        result = self._accumulator.finalize()

        if result["model"]:
            self._span.set_attribute(attr.RESPONSE_MODEL, result["model"])

        if result["finish_reason"]:
            self._span.set_attribute(attr.FINISH_REASON, result["finish_reason"])

        if result["usage"]:
            self._span.set_attribute(attr.USAGE_INPUT_TOKENS, result["usage"]["prompt_tokens"])
            self._span.set_attribute(attr.USAGE_OUTPUT_TOKENS, result["usage"]["completion_tokens"])

        self._span.set_attribute(
            attr.COMPLETION,
            redact.apply(json.dumps(result["completion"], default=str)),
        )
