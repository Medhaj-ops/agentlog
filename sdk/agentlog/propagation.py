from opentelemetry import context
from opentelemetry.propagate import extract, inject


def inject_context() -> dict:
    """Inject current trace context into a dict of HTTP headers.

    Call this before making an outgoing HTTP request to another agent.
    Pass the returned dict as headers on that request.

    Returns:
        dict with 'traceparent' header (and optionally 'tracestate')
    """
    headers = {}
    inject(headers)
    return headers


def extract_context(headers: dict) -> None:
    """Extract trace context from incoming HTTP request headers.

    Call this at the start of an incoming request handler, before
    any spans are created. Sets the extracted context as the active
    context so subsequent spans become children of the caller's span.

    Args:
        headers: the HTTP request headers (dict-like)
    """
    ctx = extract(headers)
    context.attach(ctx)
