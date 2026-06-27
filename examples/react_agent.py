"""
3-hop ReAct agent demo — produces a multi-span trace in agentlog.

Requires:
  - OPENAI_API_KEY set in environment
  - agentlog collector running (docker compose up -d)
  - pip install -e ".[openai]" from sdk/

Run:
  python examples/react_agent.py
"""

import json
import os

import openai

import agentlog

agentlog.init()

client = openai.OpenAI()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search Wikipedia for a topic. Returns a short summary.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]

FAKE_SEARCH_RESULTS = {
    "Tokyo population": "Tokyo has a population of approximately 14 million in the city proper and 37 million in the greater metropolitan area.",
    "Tokyo area km2": "Tokyo covers 2,194 square kilometers in the metropolitan area.",
}


def fake_search(query: str) -> str:
    for key, val in FAKE_SEARCH_RESULTS.items():
        if key.lower() in query.lower():
            return val
    return f"No results found for: {query}"


def run_agent():
    from agentlog.tracer import get_tracer

    tracer = get_tracer()

    with tracer.start_as_current_span("react_agent"):
        messages = [
            {"role": "system", "content": "You are a research assistant. Use the search tool to find information, then synthesize an answer. Think step by step."},
            {"role": "user", "content": "What is the population density of Tokyo?"},
        ]

        for turn in range(3):
            with tracer.start_as_current_span(f"turn_{turn}"):
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )

                choice = response.choices[0]
                messages.append(choice.message.model_dump())

                if choice.finish_reason == "tool_calls":
                    for tc in choice.message.tool_calls:
                        args = json.loads(tc.function.arguments)
                        result = fake_search(args["query"])
                        print(f"  [tool] search({args['query']!r}) → {result[:60]}...")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })
                elif choice.finish_reason == "stop":
                    print(f"\n  [answer] {choice.message.content}")
                    break

    print("\n✓ Trace emitted — check collector logs (docker compose logs otel-collector)")


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        raise SystemExit(1)
    run_agent()
