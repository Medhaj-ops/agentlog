# agentlog

OpenTelemetry-native observability for multi-agent LLM systems.

## Install

```bash
pip install agentlog[openai]     # for OpenAI
pip install agentlog[litellm]    # for LiteLLM (covers Bedrock, Anthropic, Gemini)
```

## Quick Start

```python
import agentlog
agentlog.init()  # patches LLM clients, exports spans to collector at localhost:4317

import openai
client = openai.OpenAI()
response = client.chat.completions.create(model="gpt-4o", messages=[...])
# ^ this call is now automatically traced
```

## Multi-Agent Tracing

```python
@agentlog.agent(name="supervisor")
def supervisor(input):
    # all LLM calls here are grouped under "supervisor"
    ...

@agentlog.agent(name="researcher")
def researcher(query):
    # all LLM calls here are grouped under "researcher"
    ...
```

## What Gets Captured

Every LLM call emits a span with:
- Full prompt (messages array)
- Full response (content + tool calls)
- Model name (requested and resolved)
- Token counts (input + output)
- Finish reason
- Timing and parent-child relationships

## Infrastructure

The SDK sends spans to an OpenTelemetry Collector. Deploy the full stack (collector + ClickHouse + trace viewer UI) via the Helm chart:

```bash
helm install agentlog oci://ghcr.io/medhaj-ops/agentlog/chart
```

Or run locally with Docker Compose:

```bash
git clone https://github.com/Medhaj-ops/agentlog && cd agentlog
docker compose up -d
```

## Links

- [GitHub](https://github.com/Medhaj-ops/agentlog)
- [Documentation](https://github.com/Medhaj-ops/agentlog/tree/main/docs)

## License

Apache 2.0
