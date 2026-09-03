import functools
import inspect

from .tracer import get_tracer


def agent(name: str):
    """Decorator that wraps a function in a named span.

    Usage:
        @agentlog.agent(name="supervisor")
        def my_agent(input):
            ...
    """
    def decorator(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                tracer = get_tracer()
                with tracer.start_as_current_span(name):
                    return await fn(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                tracer = get_tracer()
                with tracer.start_as_current_span(name):
                    return fn(*args, **kwargs)
            return sync_wrapper
    return decorator
