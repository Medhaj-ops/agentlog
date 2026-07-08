# SDK Quickstart

Instrument your LLM agents in 3 steps.

## 1. Install

```bash
pip install agentlog[openai]      # if using OpenAI
pip install agentlog[litellm]     # if using LiteLLM (Bedrock, Anthropic, Gemini, etc.)
pip install agentlog[openai,litellm]  # both
```

## 2. Initialize

Add two lines at the top of your entry point:

```python
import agentlog
agentlog.init()
```

This does two things:
- Patches your LLM client (`openai.chat.completions.create` / `litellm.completion`) to emit spans automatically
- Sets up the OTLP exporter to send spans to the collector at `localhost:4317`

To point at a remote collector:

```python
agentlog.init(endpoint="agentlog-collector.monitoring:4317")
```

## 3. (Optional) Name your agents

Without the decorator, you get flat LLM call spans. With it, you get a tree showing which agent made which calls:

```python
@agentlog.agent(name="supervisor")
def supervisor(user_input):
    response = client.chat.completions.create(...)  # child of "supervisor"
    result = researcher(response)
    return result

@agentlog.agent(name="researcher")
def researcher(query):
    response = client.chat.completions.create(...)  # child of "researcher"
    return response
```

The decorator works with any framework (LangGraph, CrewAI, ADK, custom). It just wraps the function in a named span.

## What gets captured automatically

Every LLM call emits a span containing:

| Field | Example |
|-------|---------|
| Model | `gpt-4o-mini` |
| Full prompt | `[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]` |
| Full response | `{"role": "assistant", "content": "...", "tool_calls": [...]}` |
| Input tokens | `138` |
| Output tokens | `18` |
| Finish reason | `stop` or `tool_calls` |
| Duration | `2816ms` |
| Parent span | Which agent or step triggered this call |

## Async support

The `@agentlog.agent` decorator works with both sync and async functions:

```python
@agentlog.agent(name="async_agent")
async def my_agent(input):
    response = await async_client.chat.completions.create(...)
    return response
```

## Verifying it works

After running your instrumented code:

```bash
# If using Docker Compose locally:
docker compose logs otel-collector | tail -20

# If using the UI:
# Open localhost:3000
```

You should see spans with `gen_ai.request.model`, `gen_ai.prompt`, etc.

## Common patterns

### Multiple agents calling each other

```python
@agentlog.agent(name="supervisor")
def supervisor(input):
    plan = client.chat.completions.create(...)      # routing call
    result = researcher(plan)                        # calls sub-agent
    final = client.chat.completions.create(...)     # synthesis call
    return final

@agentlog.agent(name="researcher")
def researcher(query):
    return client.chat.completions.create(...)
```

Trace tree:
```
supervisor
├── chat.completions.create (routing)
├── researcher
│   └── chat.completions.create (research)
└── chat.completions.create (synthesis)
```

### LangGraph nodes

```python
@agentlog.agent(name="planner")
def planner_node(state):
    response = client.chat.completions.create(...)
    return {"plan": response.choices[0].message.content}

@agentlog.agent(name="executor")
def executor_node(state):
    response = client.chat.completions.create(...)
    return {"result": response.choices[0].message.content}
```

### CrewAI tasks

```python
@agentlog.agent(name="research_agent")
def research_task(task_input):
    # CrewAI calls this internally
    ...
```
