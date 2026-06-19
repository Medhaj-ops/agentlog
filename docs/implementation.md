# agentlog — Implementation Details

A granular, systems-level reference for how agentlog works internally.

---

## 1. The Problem (First Principles)

An LLM agent makes multiple API calls in a loop. Each call depends on the output of the previous one. When the final answer is wrong, you need to know:
- What did the model see at each step? (the prompt)
- What did it decide? (the response)
- Which step went wrong? (the tree structure)
- How long did each step take? (timing)

Print debugging doesn't scale past 2-3 steps. You need structured, queryable records of every decision point — captured automatically without modifying application code.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ YOUR PYTHON PROCESS                                              │
│                                                                   │
│  agentlog.init() ─────────────────────────────────────────────── │
│      │                                                            │
│      ├─► tracer.py: setup()                                      │
│      │     Creates: Resource → TracerProvider → BatchSpanProcessor│
│      │              → OTLPSpanExporter                           │
│      │     Registers TracerProvider as global                    │
│      │                                                            │
│      └─► instrument.py: patch_openai()                           │
│            Replaces Completions.create with _wrapped_create       │
│                                                                   │
│  When create() is called:                                        │
│    _wrapped_create() → start span → record attrs → call real     │
│    API → record response → end span                              │
│                                                                   │
│  Span lifecycle:                                                  │
│    span created (in-memory object)                               │
│        ↓                                                          │
│    span.end() called (when `with` block exits)                   │
│        ↓                                                          │
│    BatchSpanProcessor receives span, adds to buffer              │
│        ↓ (every 5s or 512 spans, whichever first)               │
│    OTLPSpanExporter.export(batch)                                │
│        ↓                                                          │
│    encode_spans() → protobuf serialization                       │
│        ↓                                                          │
│    gRPC client.Export() → TCP to collector:4317                   │
└──────────────────────────────────────────────────────────────────┘
                              │
                    OTLP/gRPC (protobuf over TCP)
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ OTEL COLLECTOR (container, port 4317)                            │
│                                                                   │
│  Pipeline: receivers → processors → exporters                    │
│                                                                   │
│  receivers:                                                       │
│    otlp (gRPC on 4317, HTTP on 4318)                            │
│      Accepts ExportTraceServiceRequest, deserializes protobuf    │
│                                                                   │
│  processors:                                                      │
│    batch (timeout: 1s, batch_size: 1024)                         │
│      Accumulates spans, flushes in bulk to exporters             │
│                                                                   │
│  exporters:                                                       │
│    clickhouse (TCP to clickhouse:9000)                           │
│      Translates spans → INSERT INTO spans (...) VALUES (...)     │
│      Auto-creates table schema on first write                    │
│    debug (stdout, verbosity: detailed)                           │
│      Prints every span as text for development visibility        │
└──────────────────────────────────────────────────────────────────┘
                              │
                    ClickHouse native protocol (TCP:9000)
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ CLICKHOUSE (container, ports 8123 HTTP / 9000 native)            │
│                                                                   │
│  Database: agentlog                                               │
│  Table: spans                                                     │
│                                                                   │
│  Schema (auto-created by collector):                             │
│    TraceId          String                                        │
│    SpanId           String                                        │
│    ParentSpanId     String                                        │
│    SpanName         LowCardinality(String)                       │
│    ServiceName      LowCardinality(String)                       │
│    Timestamp        DateTime64(9)                                │
│    Duration         Int64 (nanoseconds)                          │
│    StatusCode       LowCardinality(String)                       │
│    SpanAttributes   Map(LowCardinality(String), String)          │
│    ResourceAttributes Map(LowCardinality(String), String)        │
│                                                                   │
│  Storage: MergeTree engine, partitioned by date                  │
│  Retention: 180 days TTL                                         │
│  Compression: ZSTD(1) on all columns                            │
│  Indexing: Bloom filter on TraceId, attribute keys/values        │
│                                                                   │
│  Span attributes stored in Map column:                           │
│    SpanAttributes['gen_ai.request.model'] = 'gpt-4o-mini'       │
│    SpanAttributes['gen_ai.usage.input_tokens'] = '138'           │
│    SpanAttributes['gen_ai.prompt'] = '[{"role":"system",...}]'   │
│    SpanAttributes['gen_ai.completion'] = '{"role":"assistant"}'  │
│                                                                   │
│  Queryable via SQL over HTTP:                                    │
│    SELECT * FROM spans WHERE TraceId = 'abc123'                  │
│    WHERE SpanAttributes['gen_ai.request.model'] = 'gpt-4o'      │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                    HTTP (port 8123, SQL queries, JSON response)
                              │
┌──────────────────────────────────────────────────────────────────┐
│ WEB UI (FastAPI, port 3000)                                      │
│                                                                   │
│  app.py — single file, no framework dependencies beyond FastAPI  │
│                                                                   │
│  Routes:                                                          │
│    GET /                                                          │
│      → Trace list page                                           │
│      → SQL: SELECT TraceId, min(Timestamp), count(), ...         │
│             FROM spans GROUP BY TraceId ORDER BY start_time DESC │
│      → Supports query params for behavioral search:              │
│        ?model=gpt-4o-mini                                        │
│        ?finish_reason=tool_calls                                 │
│        ?min_tokens=100&max_tokens=500                            │
│        ?span_name=chat.completions                               │
│        ?status=error                                             │
│                                                                   │
│    GET /trace/{trace_id}                                         │
│      → Trace detail page                                         │
│      → SQL: SELECT * FROM spans WHERE TraceId = X               │
│             ORDER BY Timestamp ASC                                │
│      → Builds parent-child tree from ParentSpanId relationships  │
│      → Renders nested spans with expandable prompt/completion    │
│                                                                   │
│  Tree reconstruction algorithm:                                   │
│    1. Query all spans for a trace_id                             │
│    2. Separate into roots (ParentSpanId = '') and children       │
│    3. Build children_map: {span_id → [child spans]}             │
│    4. Recursively render: root → its children → their children   │
│    5. Indent each level by 24px                                  │
│                                                                   │
│  Communication with ClickHouse:                                  │
│    POST http://clickhouse:8123                                   │
│    Body: raw SQL                                                  │
│    Params: default_format=JSONEachRow, database=agentlog         │
│    Response: one JSON object per line (newline-delimited)        │
└──────────────────────────────────────────────────────────────────┘

---

## 3. The Monkey-Patch Mechanism

### Why it works

Python classes are mutable objects. Methods are just attributes on the class.
When you call `instance.create(...)`, Python looks up `create` on the class
(not the instance) at call time. So replacing the method on the class affects
all instances — past and future.

### What happens step by step

```python
from openai.resources.chat.completions import Completions

# 1. Save original
_original_create = Completions.create

# 2. Define wrapper
def _wrapped_create(self, *args, **kwargs):
    # ... tracing logic ...
    response = _original_create(self, *args, **kwargs)  # call real method
    # ... record response ...
    return response

# 3. Replace on class
Completions.create = _wrapped_create
```

After step 3, any OpenAI client anywhere in the process calls `_wrapped_create`.
The user's code is unchanged. The response they get back is unchanged.
The only side effect is a span being emitted.

### Why imports are inside functions

```python
def patch_openai():
    from openai.resources.chat.completions import Completions  # HERE
```

If `openai` isn't installed, `import agentlog` still works. The import only
fails when you call `agentlog.init()`. This makes agentlog safe to list as a
dependency even in environments where openai might not be present.

---

## 4. OpenTelemetry Concepts Mapped to Code

| Concept | What it is | Where in our code |
|---------|-----------|-------------------|
| **Span** | A unit of work with start/end time, attributes, parent link | Created in `instrument.py` via `tracer.start_as_current_span()` |
| **Trace** | A tree of spans sharing one trace_id | Emerges automatically from parent-child nesting |
| **Tracer** | A span factory — creates spans, assigns IDs, links parents | Retrieved via `get_tracer()` in `tracer.py` |
| **TracerProvider** | Holds config (resource, processors) and creates tracers | Created in `tracer.py:setup()` |
| **Resource** | Metadata about the emitting process (service.name) | `Resource.create({"service.name": "agentlog"})` |
| **SpanProcessor** | Sits between span.end() and export — buffers | `BatchSpanProcessor(exporter)` |
| **Exporter** | Serializes and sends spans over the network | `OTLPSpanExporter(endpoint, insecure=True)` |
| **Context propagation** | How parent-child links work across call boundaries | Automatic via `start_as_current_span` (uses Python context vars) |

### How parent-child linking works (no manual IDs)

OTel uses Python's `contextvars` module. When you enter `start_as_current_span("X")`:
1. A new span X is created
2. X is stored in a context variable as the "current span"
3. Any span created inside that `with` block reads the context variable
   and uses X's span_id as its parent_span_id
4. When the `with` block exits, the previous span is restored as current

This is why nested `with` blocks produce a tree:
```python
with tracer.start_as_current_span("A"):       # A is current
    with tracer.start_as_current_span("B"):   # B's parent = A
        with tracer.start_as_current_span("C"):  # C's parent = B
```
Result: A → B → C

---

## 5. Data Flow: From API Call to UI Pixel

### Step 1: User calls OpenAI

```python
response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
```

### Step 2: _wrapped_create intercepts

```
→ Creates span with name "chat.completions.create"
→ Sets attributes: model, messages (as JSON string)
→ Calls _original_create (real OpenAI API)
→ Sets attributes: response, tokens, finish_reason
→ Span ends (with block exit records end timestamp)
```

### Step 3: BatchSpanProcessor receives the ended span

```
→ Adds to internal buffer (list in memory)
→ Timer thread checks every 5 seconds
→ When buffer has 512 spans OR 5s elapsed:
    → Calls exporter.export(batch_of_spans)
```

### Step 4: OTLPSpanExporter serializes and sends

```
→ encode_spans(batch) converts ReadableSpan objects to protobuf:
    ExportTraceServiceRequest {
        ResourceSpans {
            resource: { attributes: [service.name = "agentlog"] }
            ScopeSpans {
                scope: { name: "agentlog" }
                spans: [
                    Span {
                        trace_id: bytes(16)
                        span_id: bytes(8)
                        parent_span_id: bytes(8)
                        name: "chat.completions.create"
                        start_time_unix_nano: 1718180459093508118
                        end_time_unix_nano: 1718180461909421132
                        attributes: [
                            KeyValue { key: "gen_ai.system", value: "openai" }
                            KeyValue { key: "gen_ai.request.model", value: "gpt-4o-mini" }
                            ...
                        ]
                    }
                ]
            }
        }
    }
→ gRPC client.Export(request) sends serialized bytes over TCP
```

### Step 5: Collector receives, processes, exports

```
→ OTLP receiver deserializes protobuf
→ Batch processor accumulates (1s timeout / 1024 batch)
→ ClickHouse exporter: INSERT INTO spans (...) VALUES (...)
→ Debug exporter: prints to stdout
```

### Step 6: ClickHouse stores as a row

```
One span = one row:
  TraceId = '64889f1d594a5e0bf7f9186bc7f1ca5e'
  SpanId = '30cf7b69b495affe'
  ParentSpanId = '0f2651612f798e18'
  SpanName = 'chat.completions.create'
  Timestamp = 2026-06-12 07:30:59.093508118
  Duration = 2815913014  (nanoseconds)
  SpanAttributes = {'gen_ai.system': 'openai', 'gen_ai.request.model': 'gpt-4o-mini', ...}
```

### Step 7: UI queries and renders

```
→ User opens localhost:3000
→ FastAPI handler sends SQL to ClickHouse over HTTP
→ ClickHouse returns JSON rows
→ Python builds tree from ParentSpanId relationships
→ Renders nested HTML divs with expandable details
→ User clicks a span, sees the full prompt and response
```

---

## 6. The Collector Pipeline

Defined in `collector/config.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }
      http: { endpoint: 0.0.0.0:4318 }

processors:
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  clickhouse:
    endpoint: tcp://clickhouse:9000
    database: agentlog
    traces_table_name: spans
    create_schema: true
  debug:
    verbosity: detailed

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse, debug]
```

The pipeline reads left to right:
- **Receivers** accept data in various formats (OTLP over gRPC or HTTP)
- **Processors** transform/batch data in transit
- **Exporters** write data to backends

Data flows: receiver → processor → exporter (all exporters receive same data).
The collector is a standalone binary — it doesn't know or care what language
produced the spans.

---

## 7. ClickHouse: Why This Database

| Requirement | Why ClickHouse |
|-------------|---------------|
| High write throughput | Column-oriented, append-only MergeTree engine handles millions of inserts/sec |
| Fast analytical queries | Columnar storage means scanning one column (e.g., TraceId) doesn't touch others |
| Map column type | SpanAttributes stored as Map — queryable without schema changes for new attributes |
| SQL interface | UI can query directly over HTTP with standard SQL — no custom API needed |
| Compression | ZSTD(1) compresses repetitive string data (model names, attribute keys) extremely well |
| Time-series friendly | Partitioned by date, TTL for automatic retention, bloom filters for fast lookups |

---

## 8. Behavioral Search: How Filters Become SQL

When user submits: `?model=gpt-4o-mini&finish_reason=tool_calls&min_tokens=100`

The code builds:

```sql
SELECT
    TraceId as trace_id,
    min(Timestamp) as start_time,
    count() as span_count,
    sum(toInt64OrZero(SpanAttributes['gen_ai.usage.input_tokens'])) as total_input_tokens,
    sum(toInt64OrZero(SpanAttributes['gen_ai.usage.output_tokens'])) as total_output_tokens
FROM spans
WHERE SpanAttributes['gen_ai.request.model'] = 'gpt-4o-mini'
  AND SpanAttributes['gen_ai.response.finish_reason'] = 'tool_calls'
GROUP BY TraceId
HAVING total_input_tokens + total_output_tokens >= 100
ORDER BY start_time DESC
LIMIT 50
```

- WHERE filters individual spans (pre-aggregation)
- HAVING filters traces after aggregation (e.g., total token count)
- GROUP BY TraceId collapses spans into traces
- Map access syntax: `SpanAttributes['key_name']`

---

## 9. Multi-Agent Traces (Current Limitation)

Currently, each process generates independent traces. For a supervisor + k8s-agent setup:

```
Process 1 (supervisor):  Trace A — spans for supervisor LLM calls
Process 2 (k8s-agent):   Trace B — spans for k8s-agent LLM calls
```

Both appear in the same UI (same ClickHouse), but are separate trees.

**To unify them (future work):**

The supervisor must inject a `traceparent` HTTP header into the A2A call:
```
traceparent: 00-{trace_id}-{span_id}-01
```

The receiving agent extracts it and uses that trace_id + parent_span_id for its spans.
Result: one unified tree across processes.

This requires:
1. Outgoing middleware on supervisor HTTP calls (inject header)
2. Incoming middleware on agent HTTP handlers (extract and set context)
3. Both processes reporting to the same collector

---

## 10. Span Attributes Schema

All attributes follow the emerging `gen_ai.*` OpenTelemetry semantic conventions:

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `gen_ai.system` | string | yes | Provider identifier ("openai") |
| `gen_ai.request.model` | string | yes | Model requested by user |
| `gen_ai.response.model` | string | yes | Model that actually served (pinned version) |
| `gen_ai.usage.input_tokens` | int | yes | Tokens consumed by prompt |
| `gen_ai.usage.output_tokens` | int | yes | Tokens generated in response |
| `gen_ai.prompt` | string | yes | Full messages array as JSON |
| `gen_ai.completion` | string | yes | Full response (content + tool_calls) as JSON |
| `gen_ai.response.finish_reason` | string | yes | Why generation stopped (stop/tool_calls/length) |

These are stored as string values in ClickHouse's Map column. Numeric values
(tokens) are stored as strings in the Map and converted with `toInt64OrZero()`
in queries.

---

## 11. Docker Compose Networking

```
docker-compose.yml creates:
  Network: agentlog_default (bridge)
  Containers:
    agentlog-clickhouse (clickhouse:8123, clickhouse:9000)
    agentlog-collector  (collector:4317, collector:4318)
    agentlog-ui         (ui:3000)
```

- Containers reach each other by service name (DNS on the bridge network)
- Collector config uses `tcp://clickhouse:9000` — resolves inside the network
- UI uses `http://clickhouse:8123` — same mechanism
- Ports mapped to host: 8123, 4317, 4318, 3000, 13133
- SDK (running outside Docker) connects to `localhost:4317` (host-mapped port)

Health check on ClickHouse (`wget --spider http://localhost:8123/ping`) ensures
the collector doesn't start until ClickHouse is ready to accept connections.
`depends_on: condition: service_healthy` enforces this ordering.
