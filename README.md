# agentlog

[![PyPI](https://img.shields.io/pypi/v/agentlog-ai)](https://pypi.org/project/agentlog-ai/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/agentlog-ai)](https://pypi.org/project/agentlog-ai/)

**OpenTelemetry-native observability for multi-agent LLM systems.**

Automatically captures full traces of LLM agent execution — every prompt, response, tool call, and routing decision — arranged as a parent-child tree. Framework-agnostic. Works with OpenAI, Anthropic, Bedrock, Gemini (via LiteLLM). Deploys to Kubernetes via Helm.

---

## Why

When an LLM agent gives a wrong answer, you need to know: what did it see, what did it decide, and which step broke? Generic APM tools don't understand LLM calls. LLM-specific tools (LangSmith, Langfuse) lock you into proprietary formats.

agentlog is open-source, built on OpenTelemetry, and stores data in your own infrastructure.

## Install

```bash
pip install agentlog-ai[openai]      # OpenAI
pip install agentlog-ai[litellm]     # Bedrock, Anthropic, Gemini, 100+ providers
```

## Quick Start

```python
import agentlog
agentlog.init()

# Every LLM call is now automatically traced — zero code changes below this line
client = openai.OpenAI()
response = client.chat.completions.create(model="gpt-4o", messages=[...])
```

## Multi-Agent Tracing

Group LLM calls under named agents with one decorator:

```python
@agentlog.agent(name="supervisor")
def supervisor(user_input):
    plan = client.chat.completions.create(...)
    result = researcher(plan)
    return client.chat.completions.create(...)

@agentlog.agent(name="researcher")
def researcher(query):
    return client.chat.completions.create(...)
```

Produces a trace tree:

```
supervisor                              4200ms
├── chat.completions.create             "route decision"
├── researcher                          1800ms
│   └── chat.completions.create         "research query"
└── chat.completions.create             "synthesize answer"
```

## Cross-Process Tracing

For agents deployed as separate services (A2A, microservices):

```python
# Outgoing (supervisor)
headers = agentlog.inject_context()
httpx.post("http://agent-b:8002/", headers=headers, json=payload)

# Incoming (agent B)
agentlog.extract_context(request.headers)
```

One unified trace across processes — linked via the W3C `traceparent` header.

## Content Redaction

Strip sensitive data before storage:

```python
agentlog.init(redact="standard")  # API keys, SSNs, emails, credit cards

# Or custom patterns:
agentlog.init(redact=[
    r"sk-[a-zA-Z0-9_-]{20,}",
    (r"patient\s+\w+", "[PATIENT]"),
])
```

Redaction happens after the API call (model sees full data) but before storage (traces are clean).

## Architecture

```
SDK (patches OpenAI / LiteLLM)
    │ OTLP/gRPC
    ▼
OTel Collector (batch + memory limiter, HPA auto-scaling)
    │ TCP
    ▼
ClickHouse (columnar storage, bloom indexes, 30-day TTL, persistent volumes)
    ▲ HTTP/SQL
    │
Web UI (trace list, behavioral search, span tree, multi-trace compare)
    │
OAuth2 Proxy (GitHub/Google authentication)
```

## What Gets Captured

| Attribute | Example |
|-----------|---------|
| Full prompt | `[{"role": "system", ...}, {"role": "user", ...}]` |
| Full response | `{"role": "assistant", "content": "...", "tool_calls": [...]}` |
| Model | `gpt-4o-mini-2024-07-18` |
| Tokens | `138 in → 18 out` |
| Finish reason | `stop`, `tool_calls`, `length` |
| Duration | `2816ms` |
| Agent hierarchy | `supervisor → researcher → LLM call` |

## Deploy to Kubernetes

```bash
helm install agentlog ./chart
```

Production deployment with auth:

```bash
helm install agentlog ./chart \
  --namespace monitoring --create-namespace \
  --set clickhouse.storage=50Gi \
  --set clickhouse.retention=30 \
  --set ui.ingress.enabled=true \
  --set ui.ingress.host=agentlog.yourdomain.com \
  --set ui.auth.enabled=true \
  --set ui.auth.provider=github \
  --set ui.auth.clientId=YOUR_ID \
  --set ui.auth.clientSecret=YOUR_SECRET
```

Features:
- **ClickHouse StatefulSet** with persistent volumes and data retention TTL
- **Collector HPA** auto-scales under load (1-5 replicas)
- **OAuth2 Proxy** for UI authentication (GitHub/Google)
- **Ingress** with optional TLS

See [docs/deployment.md](docs/deployment.md) for full guide.

## Web UI

- **Trace list** — recent traces with model, token counts, duration
- **Behavioral search** — filter by model, finish_reason, span name, token range, error status
- **Trace detail** — nested span tree with expandable prompts and completions at each node
- **Multi-trace compare** — select N traces, view side-by-side with draggable column dividers

## Local Development

```bash
git clone https://github.com/Medhaj-ops/agentlog && cd agentlog
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -e "sdk[openai]" && pip install fastapi uvicorn httpx
export OPENAI_API_KEY="sk-..."
python examples/multi_agent_demo.py "How does a CPU cache work?"
python ui/app.py  # open localhost:3000
```

## Project Structure

```
sdk/agentlog/
  __init__.py               # Public API: init(), @agent, inject/extract_context
  instrument.py             # Patches OpenAI (sync + async)
  instrument_litellm.py     # Patches LiteLLM (sync + async)
  decorator.py              # @agentlog.agent(name="X")
  propagation.py            # Cross-process trace context (traceparent)
  redact.py                 # Content redaction engine
  tracer.py                 # OTel TracerProvider + OTLP exporter
  attributes.py             # gen_ai.* semantic convention constants

collector/config.yaml       # OTel Collector pipeline (OTLP → batch → ClickHouse)
db/migrations/001_init.sql  # ClickHouse schema (indexes, partitioning, TTL)

ui/
  app.py                    # FastAPI trace viewer (search, detail, compare)
  Dockerfile                # Container image

chart/                      # Helm chart for Kubernetes
  values.yaml               # All configurable options
  templates/                # StatefulSet, Deployments, HPA, OAuth, Ingress, Services

examples/
  react_agent.py            # Single agent with tool-calling loop
  multi_agent_demo.py       # Supervisor + 3 specialist agents
  cross_process_demo.py     # Two HTTP agents sharing one trace

docs/
  sdk-quickstart.md         # 3-step instrumentation guide
  deployment.md             # Kubernetes deployment guide
  configuration.md          # Helm values reference
  implementation.md         # Technical deep-dive
```

## Supported Providers

| Provider | Via | Sync | Async |
|----------|-----|------|-------|
| OpenAI | `openai` SDK | Yes | Yes |
| Anthropic (Claude) | LiteLLM | Yes | Yes |
| AWS Bedrock | LiteLLM | Yes | Yes |
| Google Gemini | LiteLLM | Yes | Yes |
| Azure OpenAI | LiteLLM | Yes | Yes |
| 100+ others | LiteLLM | Yes | Yes |

## Documentation

- [SDK Quickstart](docs/sdk-quickstart.md) — instrument your agents in 3 steps
- [Deployment Guide](docs/deployment.md) — deploy to Kubernetes with Helm
- [Configuration Reference](docs/configuration.md) — all Helm values explained
- [Implementation Details](docs/implementation.md) — architecture deep-dive

## Roadmap

- [x] Python SDK — auto-instrumentation for OpenAI + LiteLLM (sync + async)
- [x] `@agentlog.agent` decorator — framework-agnostic agent grouping
- [x] Cross-process trace propagation — W3C traceparent over HTTP
- [x] Content redaction — configurable regex patterns for sensitive data
- [x] Trace viewer UI — search, detail view, multi-trace compare
- [x] Helm chart — production K8s deployment with HPA, OAuth, persistent storage
- [x] PyPI package — `pip install agentlog-ai`
- [ ] OTel GenAI SIG contribution — propose agent span conventions upstream
- [ ] Regression detection — golden traces, automated diff, CI integration
- [ ] Streaming support — accumulate stream chunks into complete spans

## License

Apache 2.0
