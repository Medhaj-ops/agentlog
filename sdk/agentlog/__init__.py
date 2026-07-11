"""agentlog — OpenTelemetry-native observability for multi-agent LLM systems."""

__version__ = "0.1.0a1"

from .decorator import agent
from .propagation import inject_context, extract_context


def init(endpoint: str = "localhost:4317") -> None:
    from .tracer import setup
    from .instrument import patch_openai, patch_openai_async

    setup(endpoint)
    patch_openai()
    patch_openai_async()

    try:
        from .instrument_litellm import patch_litellm, patch_litellm_async
        patch_litellm()
        patch_litellm_async()
    except ImportError:
        pass
