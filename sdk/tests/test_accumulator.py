from agentlog.accumulator import StreamAccumulator

from .conftest import make_chunk, make_tool_call_delta


def _run(chunks):
    acc = StreamAccumulator()
    for chunk in chunks:
        acc.ingest(chunk)
    return acc.finalize()


def test_simple_content_concatenation():
    result = _run([
        make_chunk(content="Hello"),
        make_chunk(content=" there"),
        make_chunk(content="!"),
    ])
    assert result["completion"]["content"] == "Hello there!"


def test_role_from_first_non_null():
    result = _run([
        make_chunk(role="assistant", content=""),
        make_chunk(role="user", content="hi"),  # should be ignored
    ])
    assert result["completion"]["role"] == "assistant"


def test_model_from_first_non_null():
    acc = StreamAccumulator()
    acc.ingest(make_chunk(content="a", model="gpt-4o"))
    acc.ingest(make_chunk(content="b", model="gpt-4o-mini"))
    result = acc.finalize()
    assert result["model"] == "gpt-4o"


def test_finish_reason_from_last_non_null():
    result = _run([
        make_chunk(content="a", finish_reason=None),
        make_chunk(content="b", finish_reason=None),
        make_chunk(content="", finish_reason="stop"),
    ])
    assert result["finish_reason"] == "stop"


def test_single_tool_call_assembly():
    result = _run([
        make_chunk(tool_calls=[make_tool_call_delta(0, id="call_1", type="function", name="get_weather", arguments="")]),
        make_chunk(tool_calls=[make_tool_call_delta(0, arguments='{"cit')]),
        make_chunk(tool_calls=[make_tool_call_delta(0, arguments='y":"NY"}')]),
    ])
    tool_calls = result["completion"]["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call_1"
    assert tool_calls[0]["type"] == "function"
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == '{"city":"NY"}'


def test_parallel_tool_calls():
    result = _run([
        make_chunk(tool_calls=[
            make_tool_call_delta(0, id="call_1", type="function", name="get_weather", arguments=""),
            make_tool_call_delta(1, id="call_2", type="function", name="get_time", arguments=""),
        ]),
        make_chunk(tool_calls=[make_tool_call_delta(0, arguments='{"city":"NY"}')]),
        make_chunk(tool_calls=[make_tool_call_delta(1, arguments='{"tz":"EST"}')]),
    ])
    tool_calls = result["completion"]["tool_calls"]
    assert len(tool_calls) == 2
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == '{"city":"NY"}'
    assert tool_calls[1]["function"]["name"] == "get_time"
    assert tool_calls[1]["function"]["arguments"] == '{"tz":"EST"}'


def test_out_of_order_tool_call_chunks():
    result = _run([
        make_chunk(tool_calls=[make_tool_call_delta(1, id="call_2", type="function", name="get_time", arguments="")]),
        make_chunk(tool_calls=[make_tool_call_delta(0, id="call_1", type="function", name="get_weather", arguments="")]),
        make_chunk(tool_calls=[make_tool_call_delta(1, arguments='{"tz":"EST"}')]),
        make_chunk(tool_calls=[make_tool_call_delta(0, arguments='{"city":"NY"}')]),
    ])
    tool_calls = result["completion"]["tool_calls"]
    # Grouped and sorted by index, not arrival order.
    assert [tc["id"] for tc in tool_calls] == ["call_1", "call_2"]
    assert tool_calls[0]["function"]["arguments"] == '{"city":"NY"}'
    assert tool_calls[1]["function"]["arguments"] == '{"tz":"EST"}'


def test_sticky_field_conflict_first_wins():
    result = _run([
        make_chunk(tool_calls=[make_tool_call_delta(0, id="call_1", type="function", name="get_weather", arguments="")]),
        # Duplicate id on a later chunk for the same index should be ignored.
        make_chunk(tool_calls=[make_tool_call_delta(0, id="call_2", arguments="{}")]),
    ])
    tool_calls = result["completion"]["tool_calls"]
    assert tool_calls[0]["id"] == "call_1"


def test_empty_choices_chunk_no_crash():
    result = _run([
        make_chunk(content="hi"),
        make_chunk(empty_choices=True, usage=(10, 5)),
    ])
    assert result["completion"]["content"] == "hi"
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_usage_present():
    result = _run([
        make_chunk(content="hi", finish_reason="stop", usage=(10, 5)),
    ])
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_usage_absent():
    result = _run([
        make_chunk(content="hi", finish_reason="stop"),
    ])
    assert result["usage"] is None


def test_content_with_none_deltas_skipped():
    result = _run([
        make_chunk(role="assistant", content=None),
        make_chunk(content="hello"),
        make_chunk(content=None, finish_reason="stop"),
    ])
    assert result["completion"]["content"] == "hello"


def test_single_chunk_stream():
    result = _run([
        make_chunk(role="assistant", content="hi", finish_reason="stop", model="gpt-4o"),
    ])
    assert result["completion"] == {"role": "assistant", "content": "hi"}
    assert result["finish_reason"] == "stop"
    assert result["model"] == "gpt-4o"


def test_empty_stream_sensible_defaults():
    result = _run([])
    assert result["completion"] == {"role": "assistant", "content": None}
    assert result["finish_reason"] is None
    assert result["model"] is None
    assert result["usage"] is None
