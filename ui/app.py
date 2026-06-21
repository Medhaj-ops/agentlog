from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import httpx
import json
import os
from datetime import datetime

app = FastAPI()

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DB", "agentlog")


async def query_clickhouse(sql: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CLICKHOUSE_URL,
            content=sql,
            params={"default_format": "JSONEachRow", "database": CLICKHOUSE_DB},
        )
        resp.raise_for_status()
        if not resp.text.strip():
            return []
        return [json.loads(line) for line in resp.text.strip().split("\n")]


@app.get("/", response_class=HTMLResponse)
async def trace_list(request: Request):
    model_filter = request.query_params.get("model", "").strip()
    min_tokens = request.query_params.get("min_tokens", "").strip()
    max_tokens = request.query_params.get("max_tokens", "").strip()
    finish_reason_filter = request.query_params.get("finish_reason", "").strip()
    span_name_filter = request.query_params.get("span_name", "").strip()
    status_filter = request.query_params.get("status", "").strip()

    having_clauses = []
    where_clauses = []

    if model_filter:
        where_clauses.append(f"SpanAttributes['gen_ai.request.model'] = '{_sql_escape(model_filter)}'")
    if finish_reason_filter:
        where_clauses.append(f"SpanAttributes['gen_ai.response.finish_reason'] = '{_sql_escape(finish_reason_filter)}'")
    if span_name_filter:
        where_clauses.append(f"SpanName LIKE '%{_sql_escape(span_name_filter)}%'")
    if status_filter == "error":
        where_clauses.append("StatusCode = 'STATUS_CODE_ERROR'")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    if min_tokens:
        having_clauses.append(f"total_input_tokens + total_output_tokens >= {int(min_tokens)}")
    if max_tokens:
        having_clauses.append(f"total_input_tokens + total_output_tokens <= {int(max_tokens)}")

    having_sql = f"HAVING {' AND '.join(having_clauses)}" if having_clauses else ""

    traces = await query_clickhouse(f"""
        SELECT
            TraceId as trace_id,
            min(Timestamp) as start_time,
            max(Timestamp) as end_time,
            count() as span_count,
            maxIf(SpanAttributes['gen_ai.request.model'], SpanAttributes['gen_ai.request.model'] != '') as model,
            sum(toInt64OrZero(SpanAttributes['gen_ai.usage.input_tokens'])) as total_input_tokens,
            sum(toInt64OrZero(SpanAttributes['gen_ai.usage.output_tokens'])) as total_output_tokens
        FROM spans
        {where_sql}
        GROUP BY TraceId
        {having_sql}
        ORDER BY start_time DESC
        LIMIT 50
    """)

    rows = ""
    for t in traces:
        model = t.get("model") or "—"
        input_tok = int(t.get("total_input_tokens", 0))
        output_tok = int(t.get("total_output_tokens", 0))
        tokens_str = f"{input_tok}→{output_tok}" if input_tok else "—"

        duration_ms = "—"
        try:
            start = datetime.fromisoformat(t["start_time"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(t["end_time"].replace("Z", "+00:00"))
            duration_ms = f"{(end - start).total_seconds() * 1000:.0f}ms"
        except (ValueError, KeyError, TypeError):
            pass

        rows += f"""
        <tr>
            <td><input type="checkbox" name="trace" value="{t['trace_id']}" class="compare-check"></td>
            <td><a href="/trace/{t['trace_id']}">{t['trace_id'][:16]}...</a></td>
            <td>{t.get('start_time', '—')}</td>
            <td>{model}</td>
            <td>{tokens_str}</td>
            <td>{t.get('span_count', 0)}</td>
            <td>{duration_ms}</td>
        </tr>
        """

    return PAGE_TEMPLATE.format(
        title="Traces",
        content=f"""
        <h1>Traces</h1>
        <form class="search-bar" method="get" action="/">
            <input type="text" name="model" placeholder="Model (e.g. gpt-4o-mini)" value="{_escape(model_filter)}">
            <input type="text" name="finish_reason" placeholder="Finish reason (stop, tool_calls)" value="{_escape(finish_reason_filter)}">
            <input type="text" name="span_name" placeholder="Span name contains..." value="{_escape(span_name_filter)}">
            <input type="number" name="min_tokens" placeholder="Min tokens" value="{_escape(min_tokens)}">
            <input type="number" name="max_tokens" placeholder="Max tokens" value="{_escape(max_tokens)}">
            <select name="status">
                <option value="">Any status</option>
                <option value="error" {"selected" if status_filter == "error" else ""}>Errors only</option>
            </select>
            <button type="submit">Search</button>
            <a href="/" class="clear-btn">Clear</a>
        </form>
        <div class="compare-bar" id="compare-bar" style="display:none;">
            <span id="compare-count">0</span> selected
            <button onclick="compareTraces()">Compare</button>
        </div>
        <table>
            <thead>
                <tr>
                    <th></th>
                    <th>Trace ID</th>
                    <th>Time</th>
                    <th>Model</th>
                    <th>Tokens (in→out)</th>
                    <th>Spans</th>
                    <th>Duration</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <script>
            const checks = document.querySelectorAll('.compare-check');
            const bar = document.getElementById('compare-bar');
            const countEl = document.getElementById('compare-count');
            checks.forEach(cb => cb.addEventListener('change', () => {{
                const selected = document.querySelectorAll('.compare-check:checked');
                countEl.textContent = selected.length;
                bar.style.display = selected.length >= 2 ? 'flex' : 'none';
            }}));
            function compareTraces() {{
                const selected = document.querySelectorAll('.compare-check:checked');
                const ids = Array.from(selected).map(cb => cb.value);
                window.location.href = '/compare?traces=' + ids.join(',');
            }}
        </script>
        """
    )


@app.get("/compare", response_class=HTMLResponse)
async def compare_traces(request: Request):
    trace_ids_raw = request.query_params.get("traces", "")
    trace_ids = [t.strip() for t in trace_ids_raw.split(",") if t.strip()]

    if len(trace_ids) < 2:
        return PAGE_TEMPLATE.format(title="Compare", content="<h1>Select at least 2 traces to compare</h1><p><a href='/'>← Back</a></p>")

    columns_html = ""
    for trace_id in trace_ids:
        spans = await query_clickhouse(f"""
            SELECT
                SpanId as span_id,
                ParentSpanId as parent_span_id,
                SpanName as name,
                Timestamp as start_time,
                Duration as duration_ns,
                SpanAttributes as attributes,
                StatusCode as status_code
            FROM spans
            WHERE TraceId = '{_sql_escape(trace_id)}'
            ORDER BY Timestamp ASC
        """)

        if spans:
            tree_html = build_span_tree(spans)
        else:
            tree_html = "<p>No spans found</p>"

        columns_html += f"""
        <div class="compare-column">
            <div class="compare-column-header"><code>{trace_id[:12]}...</code></div>
            <div class="trace-tree">{tree_html}</div>
        </div>
        """

    return COMPARE_TEMPLATE.format(
        title="Compare Traces",
        columns=columns_html,
        count=len(trace_ids),
    )


@app.get("/trace/{trace_id}", response_class=HTMLResponse)
async def trace_detail(trace_id: str):
    spans = await query_clickhouse(f"""
        SELECT
            SpanId as span_id,
            ParentSpanId as parent_span_id,
            SpanName as name,
            Timestamp as start_time,
            Duration as duration_ns,
            SpanAttributes as attributes,
            StatusCode as status_code
        FROM spans
        WHERE TraceId = '{trace_id}'
        ORDER BY Timestamp ASC
    """)

    if not spans:
        return PAGE_TEMPLATE.format(title="Not Found", content="<h1>Trace not found</h1>")

    tree_html = build_span_tree(spans)

    return PAGE_TEMPLATE.format(
        title=f"Trace {trace_id[:16]}",
        content=f"""
        <h1>Trace <code>{trace_id[:16]}...</code></h1>
        <p><a href="/">← Back to traces</a></p>
        <div class="trace-tree">{tree_html}</div>
        """
    )


def build_span_tree(spans: list[dict]) -> str:
    children_map: dict[str, list[dict]] = {}
    roots = []

    for span in spans:
        parent = span.get("parent_span_id", "")
        if not parent:
            roots.append(span)
        else:
            children_map.setdefault(parent, []).append(span)

    def render_span(span: dict, depth: int = 0) -> str:
        raw = span.get("attributes", {})
        attrs = raw if isinstance(raw, dict) else {}
        if isinstance(raw, str):
            try:
                attrs = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                attrs = {}

        model = attrs.get("gen_ai.request.model", "")
        input_tokens = attrs.get("gen_ai.usage.input_tokens", "")
        output_tokens = attrs.get("gen_ai.usage.output_tokens", "")
        finish_reason = attrs.get("gen_ai.response.finish_reason", "")

        duration_ms = "—"
        try:
            ns = int(span.get("duration_ns", 0))
            duration_ms = f"{ns / 1_000_000:.0f}ms"
        except (ValueError, TypeError):
            pass

        meta_parts = []
        if model:
            meta_parts.append(model)
        if input_tokens:
            meta_parts.append(f"{input_tokens}→{output_tokens} tokens")
        if finish_reason:
            meta_parts.append(finish_reason)
        meta_parts.append(duration_ms)
        meta = " · ".join(meta_parts)

        prompt_html = ""
        completion_html = ""

        prompt_raw = attrs.get("gen_ai.prompt", "")
        if prompt_raw:
            try:
                messages = json.loads(prompt_raw)
                prompt_html = '<details><summary>Prompt</summary><div class="messages">'
                for msg in messages:
                    role = msg.get("role", "?")
                    content = msg.get("content") or ""
                    if isinstance(content, str):
                        content = content[:2000]
                    prompt_html += f'<div class="msg"><span class="role">{role}</span> {_escape(str(content))}</div>'
                prompt_html += "</div></details>"
            except (json.JSONDecodeError, TypeError):
                pass

        completion_raw = attrs.get("gen_ai.completion", "")
        if completion_raw:
            try:
                completion = json.loads(completion_raw)
                role = completion.get("role", "assistant")
                content = completion.get("content") or ""
                tool_calls = completion.get("tool_calls", [])

                completion_html = '<details><summary>Completion</summary><div class="messages">'
                if content:
                    completion_html += f'<div class="msg"><span class="role">{role}</span> {_escape(str(content)[:2000])}</div>'
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    completion_html += f'<div class="msg"><span class="role">tool_call</span> {_escape(fn.get("name", ""))}({_escape(fn.get("arguments", "")[:500])})</div>'
                completion_html += "</div></details>"
            except (json.JSONDecodeError, TypeError):
                pass

        status_class = "error" if span.get("status_code") == "STATUS_CODE_ERROR" else ""

        child_spans = children_map.get(span.get("span_id", ""), [])
        children_html = "".join(render_span(c, depth + 1) for c in child_spans)

        return f"""
        <div class="span {status_class}" style="margin-left: {depth * 24}px">
            <div class="span-header">
                <strong>{_escape(span.get('name', '?'))}</strong>
                <span class="meta">{meta}</span>
            </div>
            {prompt_html}
            {completion_html}
            {children_html}
        </div>
        """

    return "".join(render_span(r) for r in roots)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sql_escape(text: str) -> str:
    return text.replace("'", "''").replace("\\", "\\\\").replace("%", "\\%")


PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title} — agentlog</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #e6edf3; padding: 24px; }}
        h1 {{ margin-bottom: 16px; font-size: 1.4rem; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        code {{ background: #161b22; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #21262d; }}
        th {{ color: #8b949e; font-weight: 500; font-size: 0.85rem; text-transform: uppercase; }}
        tr:hover {{ background: #161b22; }}
        .search-bar {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; align-items: center; }}
        .search-bar input, .search-bar select {{ background: #161b22; border: 1px solid #21262d; color: #e6edf3; padding: 8px 12px; border-radius: 6px; font-size: 0.85rem; }}
        .search-bar input::placeholder {{ color: #484f58; }}
        .search-bar button {{ background: #238636; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }}
        .search-bar button:hover {{ background: #2ea043; }}
        .clear-btn {{ color: #8b949e; font-size: 0.85rem; padding: 8px; }}
        .compare-bar {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 10px 14px; background: #1c2128; border: 1px solid #30363d; border-radius: 6px; }}
        .compare-bar button {{ background: #1f6feb; color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }}
        .compare-bar button:hover {{ background: #388bfd; }}
        .trace-tree {{ margin-top: 16px; }}
        .span {{ border: 1px solid #21262d; border-radius: 6px; padding: 12px; margin-bottom: 8px; background: #161b22; }}
        .span.error {{ border-color: #f85149; }}
        .span-header {{ display: flex; justify-content: space-between; align-items: center; }}
        .meta {{ color: #8b949e; font-size: 0.8rem; }}
        details {{ margin-top: 8px; }}
        summary {{ cursor: pointer; color: #58a6ff; font-size: 0.85rem; }}
        .messages {{ margin-top: 8px; font-size: 0.8rem; }}
        .msg {{ padding: 6px 8px; margin-bottom: 4px; background: #0d1117; border-radius: 4px; white-space: pre-wrap; word-break: break-word; }}
        .role {{ font-weight: 600; color: #7ee787; }}
    </style>
</head>
<body>{content}</body>
</html>"""


COMPARE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title} — agentlog</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #e6edf3; padding: 24px; }}
        h1 {{ margin-bottom: 16px; font-size: 1.4rem; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        code {{ background: #161b22; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
        .compare-grid {{ display: grid; grid-template-columns: repeat({count}, 1fr); gap: 16px; overflow-x: auto; }}
        .compare-column {{ min-width: 350px; }}
        .compare-column-header {{ font-weight: 600; margin-bottom: 8px; padding: 8px; background: #1c2128; border-radius: 6px; text-align: center; }}
        .trace-tree {{ margin-top: 8px; }}
        .span {{ border: 1px solid #21262d; border-radius: 6px; padding: 10px; margin-bottom: 6px; background: #161b22; }}
        .span.error {{ border-color: #f85149; }}
        .span-header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }}
        .meta {{ color: #8b949e; font-size: 0.75rem; }}
        details {{ margin-top: 6px; }}
        summary {{ cursor: pointer; color: #58a6ff; font-size: 0.8rem; }}
        .messages {{ margin-top: 6px; font-size: 0.75rem; }}
        .msg {{ padding: 4px 6px; margin-bottom: 3px; background: #0d1117; border-radius: 4px; white-space: pre-wrap; word-break: break-word; }}
        .role {{ font-weight: 600; color: #7ee787; }}
    </style>
</head>
<body>
    <h1>Compare Traces</h1>
    <p><a href="/">← Back to traces</a></p>
    <div class="compare-grid">{columns}</div>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
