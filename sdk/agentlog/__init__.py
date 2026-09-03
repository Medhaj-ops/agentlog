"""agentlog — OpenTelemetry-native observability for multi-agent LLM systems."""

__version__ = "0.1.0a1"

from .decorator import agent as agent
from .propagation import extract_context as extract_context
from .propagation import inject_context as inject_context


def init(endpoint: str = "localhost:4317", redact=None) -> None:
    from . import redact as redact_module
    from .instrument import patch_openai, patch_openai_async
    from .tracer import setup

    if redact is not None:
        redact_module.configure(redact)

    setup(endpoint)
    patch_openai()
    patch_openai_async()

    try:
        from .instrument_litellm import patch_litellm, patch_litellm_async
        patch_litellm()
        patch_litellm_async()
    except ImportError:
        pass
