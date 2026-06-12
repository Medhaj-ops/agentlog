import json
from opentelemetry.trace import StatusCode
from . import attributes as attr
from .tracer import get_tracer

_patched = False


def patch_openai() -> None:
    global _patched
    if _patched:
        return

    from openai.resources.chat.completions import Completions

    _original_create = Completions.create

    def _wrapped_create(self, *args, **kwargs):
        tracer = get_tracer()
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        with tracer.start_as_current_span("chat.completions.create") as span:
            span.set_attribute(attr.SYSTEM, "openai")
            span.set_attribute(attr.REQUEST_MODEL, model)
            span.set_attribute(attr.PROMPT, json.dumps(messages, default=str))

            try:
                response = _original_create(self, *args, **kwargs)
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

            if response.usage:
                span.set_attribute(attr.USAGE_INPUT_TOKENS, response.usage.prompt_tokens)
                span.set_attribute(attr.USAGE_OUTPUT_TOKENS, response.usage.completion_tokens)

            span.set_attribute(attr.RESPONSE_MODEL, response.model)

            choice = response.choices[0] if response.choices else None
            if choice:
                span.set_attribute(attr.FINISH_REASON, choice.finish_reason or "")
                message = choice.message
                completion = {
                    "role": message.role,
                    "content": message.content,
                }
                if message.tool_calls:
                    completion["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ]
                span.set_attribute(attr.COMPLETION, json.dumps(completion, default=str))

            return response

    Completions.create = _wrapped_create
    _patched = True
