# agentlog

OpenTelemetry-native observability for multi-agent LLM systems.

**Status:** v0.1 alpha — SDK and trace viewer working. Active development.

## What it does

When LLM agents fail in production — wrong answer, weird latency, infinite tool loops — there's no good way to debug them. Generic APM tools don't understand LLM calls; LLM-specific tools (LangSmith, Langfuse) lock you into proprietary formats.

agentlog captures **full traces** of multi-agent LLM execution: every prompt, every response, every tool call, arranged in a parent-child tree that shows you exactly what happened and why.

## Architecture

```
Your Python app (SDK patches OpenAI client)
    ↓ OTLP/gRPC (port 4317)
OTel Collector (batches, routes)
    ↓ TCP (port 9000)
ClickHouse (stores spans as rows)
    ↑ HTTP queries (port 8123)
Web UI (trace list + span tree viewer)
```

## What gets captured

Every `chat.completions.create()` call emits a span with:
- Full messages array (prompt) and full response (completion)
- Model requested and model resolved
- Token counts (input + output)
- Finish reason (stop, tool_calls, length)
- Timing (start/end timestamps, duration)
- Parent-child relationships (automatic from code nesting)

## Quickstart

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Install SDK
python3 -m venv .venv && source .venv/bin/activate
pip install -e "sdk[openai]"

# 3. Run the demo
export OPENAI_API_KEY="sk-..."
python examples/react_agent.py

# 4. View traces
# Option A: collector debug output
docker compose logs otel-collector

# Option B: web UI (requires pip install fastapi uvicorn httpx)
python ui/app.py
# Open http://localhost:3000
```

## SDK Usage

```python
import agentlog
agentlog.init()  # one line — patches OpenAI, sets up export to collector

# use OpenAI normally — every call is automatically traced
client = openai.OpenAI()
response = client.chat.completions.create(model="gpt-4o", messages=[...])
```

For multi-agent systems, wrap agent logic in named spans:

```python
from agentlog.tracer import get_tracer
tracer = get_tracer()

with tracer.start_as_current_span("supervisor"):
    # LLM calls here are children of "supervisor"
    with tracer.start_as_current_span("research_agent"):
        # LLM calls here are children of "research_agent"
        client.chat.completions.create(...)
```

## Web UI

The trace viewer shows:
- **Trace list** — recent traces with model, token counts, span count, duration
- **Behavioral search** — filter by model, finish_reason, span name, token range, error status
- **Trace detail** — nested span tree with expandable prompts and completions at each node

## Project Structure

```
sdk/
  agentlog/__init__.py      # Public API: agentlog.init()
  agentlog/instrument.py    # Monkey-patches OpenAI Completions.create
  agentlog/tracer.py        # Configures TracerProvider + OTLP exporter
  agentlog/attributes.py    # gen_ai.* attribute name constants

collector/
  config.yaml               # OTel Collector pipeline: OTLP → batch → ClickHouse + debug

ui/
  app.py                    # FastAPI trace viewer (queries ClickHouse, renders HTML)
  Dockerfile                # Container image for the UI

examples/
  react_agent.py            # 3-hop ReAct agent demo producing multi-span traces

docker-compose.yml          # ClickHouse + OTel Collector + UI
```

## Roadmap

- [x] v0.1 — Python SDK (OpenAI sync), collector + ClickHouse, trace viewer UI, behavioral search
- [ ] v0.2 — Trace diff view (side-by-side comparison of two traces)
- [ ] v0.3 — `gen_ai.*` schema spec + upstream OTel SIG proposal
- [ ] v0.4 — Anthropic SDK support, async/streaming, cross-process trace propagation
- [ ] v0.5 — Regression detection (saved inputs + expected outputs, CI integration)

## License

Apache 2.0
