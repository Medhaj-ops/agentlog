class StreamAccumulator:
    """Provider-agnostic accumulation of streaming chunks into a completion dict.

    Faithfully reconstructs what the non-streaming response shape would have
    been, without validating or second-guessing what the provider sent.
    """

    def __init__(self):
        self.content_parts: list[str] = []
        self.role: str | None = None
        self.model: str | None = None
        self.finish_reason: str | None = None
        self.tool_calls: dict[int, dict] = {}
        self.usage: dict | None = None

    def ingest(self, chunk) -> None:
        """Process one streaming chunk. Call for every chunk in order."""

        if self.model is None and getattr(chunk, "model", None) is not None:
            self.model = chunk.model

        if getattr(chunk, "usage", None) is not None:
            self.usage = {
                "prompt_tokens": chunk.usage.prompt_tokens,
                "completion_tokens": chunk.usage.completion_tokens,
            }

        if not chunk.choices:
            return

        choice = chunk.choices[0]

        if choice.finish_reason is not None:
            self.finish_reason = choice.finish_reason

        delta = choice.delta

        if self.role is None and getattr(delta, "role", None) is not None:
            self.role = delta.role

        if getattr(delta, "content", None) is not None:
            self.content_parts.append(delta.content)

        tool_call_deltas = getattr(delta, "tool_calls", None)
        if tool_call_deltas:
            for tc in tool_call_deltas:
                idx = tc.index
                if idx not in self.tool_calls:
                    self.tool_calls[idx] = {
                        "id": getattr(tc, "id", None),
                        "type": getattr(tc, "type", None),
                        "function": {
                            "name": getattr(tc.function, "name", None) if getattr(tc, "function", None) else None,
                            "arguments": "",
                        },
                    }
                existing = self.tool_calls[idx]

                if existing["id"] is None and getattr(tc, "id", None) is not None:
                    existing["id"] = tc.id
                if existing["type"] is None and getattr(tc, "type", None) is not None:
                    existing["type"] = tc.type
                function = getattr(tc, "function", None)
                if function is not None:
                    if existing["function"]["name"] is None and getattr(function, "name", None) is not None:
                        existing["function"]["name"] = function.name
                    if getattr(function, "arguments", None) is not None:
                        existing["function"]["arguments"] += function.arguments

    def finalize(self) -> dict:
        """Produce the final accumulated state. Call once after stream ends.

        Returns a dict with keys:
            completion: dict (same shape as non-streaming completion)
            finish_reason: str or None
            model: str or None
            usage: dict or None (with prompt_tokens, completion_tokens)
        """
        content = "".join(self.content_parts) if self.content_parts else None

        completion = {
            "role": self.role or "assistant",
            "content": content,
        }

        if self.tool_calls:
            completion["tool_calls"] = [self.tool_calls[idx] for idx in sorted(self.tool_calls.keys())]

        return {
            "completion": completion,
            "finish_reason": self.finish_reason,
            "model": self.model,
            "usage": self.usage,
        }
