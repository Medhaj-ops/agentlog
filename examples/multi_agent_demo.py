"""
Multi-agent A2A demo — supervisor routes queries to one of 3 specialist agents.

Architecture:
  User input → Supervisor (decides which specialist) → Specialist → Answer

Specialists:
  - tech_agent: answers technology/programming questions
  - science_agent: answers science/physics/biology questions
  - history_agent: answers history/politics/geography questions

Requires:
  - OPENAI_API_KEY set in environment
  - agentlog collector running (docker compose up -d)
  - pip install -e ".[openai]" from sdk/

Run:
  python examples/multi_agent_demo.py "How does a CPU cache work?"
  python examples/multi_agent_demo.py "What caused the fall of Rome?"
  python examples/multi_agent_demo.py "How do black holes form?"
"""

import json
import os
import sys

import openai

import agentlog

agentlog.init()

client = openai.OpenAI()


@agentlog.agent(name="tech_agent")
def tech_agent(query: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a technology expert. Answer questions about programming, computers, software, and engineering. Be concise (2-3 sentences)."},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content


@agentlog.agent(name="science_agent")
def science_agent(query: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a science expert. Answer questions about physics, chemistry, biology, and natural sciences. Be concise (2-3 sentences)."},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content


@agentlog.agent(name="history_agent")
def history_agent(query: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a history expert. Answer questions about historical events, politics, geography, and civilizations. Be concise (2-3 sentences)."},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content


AGENTS = {
    "tech": tech_agent,
    "science": science_agent,
    "history": history_agent,
}


@agentlog.agent(name="supervisor")
def supervisor(user_input: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """You are a routing supervisor. Given a user question, decide which specialist should answer it.
Respond with ONLY one word — the agent name:
- "tech" for technology/programming/computers
- "science" for physics/chemistry/biology/nature
- "history" for historical events/politics/geography

Respond with just the word, nothing else."""},
            {"role": "user", "content": user_input},
        ],
    )
    route = response.choices[0].message.content.strip().lower()
    print(f"  [supervisor] routing to: {route}")

    agent_fn = AGENTS.get(route)
    if not agent_fn:
        agent_fn = AGENTS["tech"]
        print(f"  [supervisor] unknown route '{route}', defaulting to tech")

    result = agent_fn(user_input)
    return result


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        raise SystemExit(1)

    if len(sys.argv) < 2:
        print("Usage: python examples/multi_agent_demo.py \"your question here\"")
        raise SystemExit(1)

    query = sys.argv[1]
    print(f"\n  [query] {query}")
    answer = supervisor(query)
    print(f"\n  [answer] {answer}")
    print("\n✓ Trace emitted — check UI at localhost:3000")
