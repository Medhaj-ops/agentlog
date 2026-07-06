-- agentlog schema: explicit span storage for LLM agent traces
-- This replaces the auto-created schema from the OTel collector exporter
-- with one optimized for our query patterns.

CREATE DATABASE IF NOT EXISTS agentlog;

CREATE TABLE IF NOT EXISTS agentlog.spans (
    -- === Identity: who is this span and who is its parent? ===
    TraceId          String,
    SpanId           String,
    ParentSpanId     String,
    TraceState       String,

    -- === What happened? ===
    SpanName         LowCardinality(String),
    SpanKind         LowCardinality(String),
    ServiceName      LowCardinality(String),

    -- === When did it happen? ===
    Timestamp        DateTime64(9) CODEC(Delta, ZSTD(1)),
    Duration         Int64 CODEC(ZSTD(1)),

    -- === Did it succeed? ===
    StatusCode       LowCardinality(String),
    StatusMessage    String,

    -- === Instrumentation info ===
    ScopeName        String,
    ScopeVersion     String,

    -- === Attributes (the main payload) ===
    -- All span attributes (gen_ai.prompt, gen_ai.request.model, etc.)
    -- stored as a Map — queryable with SpanAttributes['key']
    SpanAttributes   Map(LowCardinality(String), String) CODEC(ZSTD(1)),

    -- Resource attributes (service.name, telemetry.sdk.version, etc.)
    ResourceAttributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),

    -- === Events (exceptions, logs attached to the span) ===
    Events Nested(
        Timestamp    DateTime64(9),
        Name         LowCardinality(String),
        Attributes   Map(LowCardinality(String), String)
    ) CODEC(ZSTD(1)),

    -- === Links (references to other spans/traces) ===
    Links Nested(
        TraceId      String,
        SpanId       String,
        TraceState   String,
        Attributes   Map(LowCardinality(String), String)
    ) CODEC(ZSTD(1)),

    -- === Index for fast trace lookups ===
    INDEX idx_trace_id TraceId TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_span_name SpanName TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_duration Duration TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
PARTITION BY toDate(Timestamp)
ORDER BY (ServiceName, SpanName, toUnixTimestamp(Timestamp), TraceId)
TTL toDateTime(Timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
