import json
from opentelemetry.trace import StatusCode
from . import attributes as attr
from .tracer import get_tracer

_patched = False


def patch_litellm() -> None:
    global _patched
    if _patched:
        return

    import litellm

    _original_completion = litellm.completion

    def _wrapped_completion(*args, **kwargs):
        tracer = get_tracer()
        model = kwargs.get("model") or (args[0] if args else "unknown")
        messages = kwargs.get("messages") or (args[1] if len(args) > 1 else [])

        with tracer.start_as_current_span("litellm.completion") as span:
            span.set_attribute(attr.SYSTEM, _extract_provider(model))
            span.set_attribute(attr.REQUEST_MODEL, model)
            span.set_attribute(attr.PROMPT, json.dumps(messages, default=str))

            try:
                response = _original_completion(*args, **kwargs)
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

            if response.usage:
                span.set_attribute(attr.USAGE_INPUT_TOKENS, response.usage.prompt_tokens)
                span.set_attribute(attr.USAGE_OUTPUT_TOKENS, response.usage.completion_tokens)

            span.set_attribute(attr.RESPONSE_MODEL, response.model or model)

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

    litellm.completion = _wrapped_completion
    _patched = True


def _extract_provider(model: str) -> str:
    """Extract provider name from LiteLLM model string.

    LiteLLM uses prefixes: 'bedrock/anthropic.claude-v2', 'anthropic/claude-3',
    'openai/gpt-4o', 'gemini/gemini-pro', etc.
    """
    if "/" in model:
        return model.split("/")[0]
    return "openai"
