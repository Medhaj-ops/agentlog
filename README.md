# agentlog

OpenTelemetry-native observability for multi-agent LLM systems.

**Status:** v0.1 alpha — SDK, trace viewer, Helm chart working. Active development.

## What it does

When LLM agents fail in production — wrong answer, weird latency, infinite tool loops — there's no good way to debug them. Generic APM tools don't understand LLM calls; LLM-specific tools (LangSmith, Langfuse) lock you into proprietary formats.

agentlog captures **full traces** of multi-agent LLM execution: every prompt, every response, every tool call, arranged in a parent-child tree that shows you exactly what happened and why.

## Architecture

```
Your Python app (SDK patches LLM clients)
    ↓ OTLP/gRPC (port 4317)
OTel Collector (batches, routes, auto-scales via HPA)
    ↓ TCP (port 9000)
ClickHouse (stores spans, persistent volume, TTL retention)
    ↑ HTTP queries (port 8123)
Web UI (trace list + span tree + multi-trace compare)
    ↑ OAuth2 Proxy (optional authentication)
```

## What gets captured

Every LLM call (`openai.chat.completions.create` / `litellm.completion`) emits a span with:
- Full messages array (prompt) and full response (completion)
- Model requested and model resolved
- Token counts (input + output)
- Finish reason (stop, tool_calls, length)
- Timing (start/end timestamps, duration)
- Parent-child relationships (automatic from code nesting)

## Quickstart (local dev)

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Install SDK
python3 -m venv .venv && source .venv/bin/activate
pip install -e "sdk[openai]"

# 3. Run the demo
export OPENAI_API_KEY="sk-..."
python examples/multi_agent_demo.py "How does a CPU cache work?"

# 4. View traces
pip install fastapi uvicorn httpx
python ui/app.py
# Open http://localhost:3000
```

## Deploy to Kubernetes

```bash
helm install agentlog ./chart
```

With authentication and ingress:

```bash
helm install agentlog ./chart \
  --set ui.ingress.enabled=true \
  --set ui.ingress.host=agentlog.yourdomain.com \
  --set ui.auth.enabled=true \
  --set ui.auth.provider=github \
  --set ui.auth.clientId=YOUR_ID \
  --set ui.auth.clientSecret=YOUR_SECRET
```

See [docs/deployment.md](docs/deployment.md) for full guide.

## SDK Usage

```python
import agentlog
agentlog.init()  # patches OpenAI + LiteLLM, exports to collector

# use OpenAI normally — every call is automatically traced
client = openai.OpenAI()
response = client.chat.completions.create(model="gpt-4o", messages=[...])
```

For multi-agent systems, use the `@agentlog.agent` decorator:

```python
@agentlog.agent(name="supervisor")
def supervisor(user_input):
    response = client.chat.completions.create(...)
    result = researcher(response)       # sub-agent call
    return synthesize(result)

@agentlog.agent(name="researcher")
def researcher(query):
    return client.chat.completions.create(...)
```

Trace in UI:
```
supervisor
├── chat.completions.create (routing)
├── researcher
│   └── chat.completions.create (research)
└── chat.completions.create (synthesis)
```

## Web UI Features

- **Trace list** — recent traces with model, token counts, span count, duration
- **Behavioral search** — filter by model, finish_reason, span name, token range, error status
- **Trace detail** — nested span tree with expandable prompts and completions
- **Multi-trace compare** — select N traces, view side-by-side with draggable dividers

## Project Structure

```
sdk/agentlog/
  __init__.py               # Public API: init(), @agent decorator
  instrument.py             # Patches OpenAI Completions.create
  instrument_litellm.py     # Patches litellm.completion
  decorator.py              # @agentlog.agent(name="X") decorator
  tracer.py                 # TracerProvider + OTLP exporter setup
  attributes.py             # gen_ai.* attribute name constants

collector/
  config.yaml               # OTel Collector pipeline config

db/migrations/
  001_init.sql              # ClickHouse schema (indexes, TTL, partitioning)

ui/
  app.py                    # FastAPI trace viewer
  Dockerfile                # Container image

chart/                      # Helm chart for Kubernetes deployment
  Chart.yaml
  values.yaml               # All configurable options
  templates/                # K8s manifests (StatefulSet, Deployments, HPA, OAuth, Ingress)

examples/
  react_agent.py            # Single agent with tool loop
  multi_agent_demo.py       # Supervisor + 3 specialist agents

docs/
  sdk-quickstart.md         # Instrument your agents in 3 steps
  deployment.md             # Deploy to Kubernetes
  configuration.md          # Helm values reference
  implementation.md         # Technical deep-dive
```

## Roadmap

- [x] v0.1 — Python SDK (OpenAI + LiteLLM), `@agent` decorator, collector + ClickHouse, trace viewer UI, behavioral search, multi-trace compare, Helm chart, OAuth auth, HPA autoscaling
- [ ] v0.2 — Cross-process trace propagation (HTTP middleware + traceparent)
- [ ] v0.3 — `gen_ai.*` schema spec + upstream OTel SIG proposal
- [ ] v0.4 — Anthropic SDK patcher, async/streaming support
- [ ] v0.5 — Regression detection (golden traces, automated diff, CI integration)

## License

Apache 2.0
