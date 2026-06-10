# agentlog

OpenTelemetry-native observability for multi-agent LLM systems.

**Status:** v0.1 in progress (June 2026). Not yet usable.

## What it does

When LLM agents fail in production — wrong cost, wrong answer, weird latency — there's no good way to debug them. Generic APM (Datadog) doesn't understand LLMs; LLM-specific tools (LangSmith, Langfuse) lock you into proprietary formats.

agentlog is the open-source, OpenTelemetry-native answer:
- **SDK** (Python) that auto-instruments OpenAI and Anthropic clients with `gen_ai.*` semantic conventions
- **OTel collector** with a custom processor that prices every LLM call
- **ClickHouse** storage for high-volume span queries
- **Web UI** to browse traces as trees and inspect every prompt, response, tool call

Works alongside any existing OTel-compatible backend (Datadog, Honeycomb, Grafana Tempo).

## Roadmap

- v0.1 — Python SDK (OpenAI), collector + ClickHouse + cost enrichment, minimal UI, 3-hop ReAct demo
- v0.2 — Anthropic SDK, regression eval CLI, distribution gate (1 non-friend star or stranger comment)
- v0.3 — Deterministic replay, Next.js UI polish
- v0.4 — Go and TypeScript SDKs, A2A trace propagation across services

## Quickstart (dev)

```bash
docker compose up -d                              # ClickHouse + OTel collector
curl http://localhost:13133/                      # collector health
curl 'http://localhost:8123/?query=SELECT%201'    # ClickHouse health
```

SDK and example app come next.

## License

Apache 2.0
