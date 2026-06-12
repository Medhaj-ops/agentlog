"""agentlog — OpenTelemetry-native observability for multi-agent LLM systems."""

__version__ = "0.1.0a0"


def init(endpoint: str = "localhost:4317") -> None:
    from .tracer import setup
    from .instrument import patch_openai

    setup(endpoint)
    patch_openai()
