"""
Cross-process tracing demo — two agents as separate HTTP servers sharing one trace.

This simulates a distributed agent system:
  - Supervisor (port 5000) receives user query, delegates to specialist
  - Specialist (port 5001) answers the query

Both share one trace_id via the traceparent header.

Requires:
  - OPENAI_API_KEY set in environment
  - agentlog collector running (docker compose up -d)
  - pip install -e ".[openai]" from sdk/
  - pip install fastapi uvicorn httpx

Run (3 terminals):
  Terminal 1: python examples/cross_process_demo.py specialist
  Terminal 2: python examples/cross_process_demo.py supervisor
  Terminal 3: curl -X POST http://localhost:5000/ -H "Content-Type: application/json" -d '{"query": "How does DNS work?"}'
"""

import json
import os
import sys

import agentlog

agentlog.init()

import openai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import uvicorn

client = openai.OpenAI()


def run_specialist():
    """Specialist agent — answers queries. Runs on port 5001."""
    app = FastAPI()

    @app.post("/")
    async def handle(request: Request):
        # EXTRACT: read traceparent from incoming headers
        # This connects this process's spans to the supervisor's trace
        agentlog.extract_context(dict(request.headers))

        @agentlog.agent(name="specialist")
        def answer(query: str) -> str:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Answer concisely in 2-3 sentences."},
                    {"role": "user", "content": query},
                ],
            )
            return response.choices[0].message.content

        body = await request.json()
        result = answer(body["query"])
        return JSONResponse({"answer": result})

    print("Specialist agent running on port 5001")
    uvicorn.run(app, host="0.0.0.0", port=5001)


def run_supervisor():
    """Supervisor agent — routes to specialist. Runs on port 5000."""
    app = FastAPI()

    @app.post("/")
    async def handle(request: Request):
        body = await request.json()
        query = body["query"]

        @agentlog.agent(name="supervisor")
        def process(q: str) -> str:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Rephrase this question for a specialist. Respond with just the rephrased question."},
                    {"role": "user", "content": q},
                ],
            )
            rephrased = response.choices[0].message.content

            # INJECT: pass trace context to the specialist via HTTP headers
            headers = agentlog.inject_context()
            headers["Content-Type"] = "application/json"

            resp = httpx.post(
                "http://localhost:5001/",
                headers=headers,
                json={"query": rephrased},
            )
            return resp.json()["answer"]

        result = process(query)
        return JSONResponse({"answer": result})

    print("Supervisor agent running on port 5000")
    uvicorn.run(app, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        raise SystemExit(1)

    if len(sys.argv) < 2 or sys.argv[1] not in ("supervisor", "specialist"):
        print("Usage:")
        print("  Terminal 1: python examples/cross_process_demo.py specialist")
        print("  Terminal 2: python examples/cross_process_demo.py supervisor")
        print('  Terminal 3: curl -X POST http://localhost:5000/ -H "Content-Type: application/json" -d \'{"query": "How does DNS work?"}\'')
        raise SystemExit(1)

    if sys.argv[1] == "specialist":
        run_specialist()
    else:
        run_supervisor()
