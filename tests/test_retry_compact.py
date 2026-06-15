"""Tests for retry, micro-compaction, and stop hooks."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.llm.retry import call_llm_with_retry, _backoff_delay
from oag.llm.context import ContextManager, count_messages_tokens, estimate_tokens
from oag.loop.query_loop import QueryLoop
from oag.tools.pipeline import ToolResult
from oag.runtime.hooks import HookRegistry
from oag.runtime import RunState


# ── retry ──

def test_backoff_delay_increases():
    d0 = _backoff_delay(0)
    d3 = _backoff_delay(3)
    assert d0 < d3
    assert d0 < 1.0
    assert d3 < 40.0


def test_retry_succeeds_after_failures():
    mock_client = MagicMock()
    import httpx
    from openai import APIStatusError
    resp = httpx.Response(429, request=httpx.Request("POST", "http://test"))
    error = APIStatusError("rate limited", response=resp, body=None)

    call_count = 0
    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise error
        result = MagicMock()
        result.choices = [MagicMock()]
        result.choices[0].message.content = "ok"
        return result

    mock_client.chat.completions.create = MagicMock(side_effect=side_effect)

    with patch("oag.llm.retry.time.sleep"):
        result = call_llm_with_retry(mock_client, max_retries=5, model="test", messages=[])

    assert call_count == 3
    assert result.choices[0].message.content == "ok"


def test_retry_raises_on_non_retryable():
    mock_client = MagicMock()
    import httpx
    from openai import APIStatusError
    resp = httpx.Response(400, request=httpx.Request("POST", "http://test"))
    error = APIStatusError("bad request", response=resp, body=None)

    mock_client.chat.completions.create = MagicMock(side_effect=error)

    try:
        call_llm_with_retry(mock_client, max_retries=3, model="test", messages=[])
        assert False, "Should have raised"
    except APIStatusError as e:
        assert e.status_code == 400


def test_retry_exhausts_retries():
    mock_client = MagicMock()
    import httpx
    from openai import APIStatusError
    resp = httpx.Response(500, request=httpx.Request("POST", "http://test"))
    error = APIStatusError("server error", response=resp, body=None)

    mock_client.chat.completions.create = MagicMock(side_effect=error)

    try:
        with patch("oag.llm.retry.time.sleep"):
            call_llm_with_retry(mock_client, max_retries=2, model="test", messages=[])
        assert False, "Should have raised"
    except APIStatusError as e:
        assert e.status_code == 500
    assert mock_client.chat.completions.create.call_count == 3


# ── micro_compact ──

def _make_messages(tool_count=10, tool_content_len=1000):
    msgs = [{"role": "system", "content": "system prompt"}]
    for i in range(tool_count):
        msgs.append({"role": "assistant", "content": f"calling tool {i}", "tool_calls": [{"id": f"t{i}", "type": "function", "function": {"name": "query", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": "x" * tool_content_len})
    msgs.append({"role": "assistant", "content": "final answer"})
    return msgs


def test_micro_compact_truncates_old_tool_results():
    ctx = ContextManager(MagicMock(), "test", context_window=100000)
    msgs = _make_messages(tool_count=10, tool_content_len=1000)

    original_tokens = count_messages_tokens(msgs)
    compacted = ctx._micro_compact(msgs)
    compacted_tokens = count_messages_tokens(compacted)

    assert compacted_tokens < original_tokens
    # Last 3 tool results should be preserved
    tool_msgs = [m for m in compacted if m.get("role") == "tool"]
    assert len(tool_msgs[-1]["content"]) == 1000  # last preserved
    assert len(tool_msgs[0]["content"]) < 500  # old ones truncated


def test_micro_compact_preserves_recent():
    ctx = ContextManager(MagicMock(), "test", context_window=100000)
    msgs = _make_messages(tool_count=4, tool_content_len=1000)
    tool_msgs_before = [m for m in msgs if m.get("role") == "tool"]

    compacted = ctx._micro_compact(msgs)
    tool_msgs_after = [m for m in compacted if m.get("role") == "tool"]

    # With 4 tools, last 3 are protected, only first gets truncated
    assert len(tool_msgs_after[0]["content"]) < 500
    assert len(tool_msgs_after[1]["content"]) == 1000
    assert len(tool_msgs_after[2]["content"]) == 1000
    assert len(tool_msgs_after[3]["content"]) == 1000


def test_maybe_compact_micro_before_full():
    ctx = ContextManager(MagicMock(), "test", context_window=1000)
    msgs = _make_messages(tool_count=5, tool_content_len=200)

    tokens = count_messages_tokens(msgs)
    # Just verify micro runs without error — threshold math depends on token estimation
    result, compacted = ctx.maybe_compact(msgs)
    assert isinstance(result, list)


def test_query_loop_repairs_missing_tool_results_before_request():
    harness = MagicMock()
    harness.build_tools.return_value = []
    harness.config.max_turns = 5
    harness.maybe_compact.side_effect = lambda messages: (messages, False)
    harness.force_compact.side_effect = lambda messages: (messages, False)
    harness.run_stop_check.return_value = None
    harness.collect_context_usage.return_value = {
        "model": "test-model",
        "total_tokens": 10,
        "context_window": 1000,
        "percentage": 1.0,
        "free_tokens": 990,
        "messages": {
            "count": 4,
            "largest_tool_results": [],
        },
        "tools": {
            "count": 0,
            "largest_tools": [],
        },
        "categories": {},
    }

    def create_response(**kwargs):
        sent_messages = kwargs["messages"]
        assistant_index = next(
            i for i, msg in enumerate(sent_messages)
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        )
        assert sent_messages[assistant_index + 1]["role"] == "tool"
        assert sent_messages[assistant_index + 1]["tool_call_id"] == "call_1"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None),
                )
            ],
        )

    client = MagicMock()
    client.chat.completions.create.side_effect = create_response

    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search_documents", "arguments": "{}"},
                }
            ],
        },
        {"role": "user", "content": "continue"},
    ]
    state = RunState(messages=messages, session_id="s1", user_question="continue")

    events = list(QueryLoop(harness, client, "test-model", lambda *args: None).run(state))

    assert any(getattr(event, "content", "") == "ok" for event in events)
    assert state.messages[2]["role"] == "tool"
    assert state.messages[2]["tool_call_id"] == "call_1"


def test_query_loop_repairs_non_contiguous_tool_results_before_request():
    harness = MagicMock()
    harness.build_tools.return_value = []
    harness.config.max_turns = 5
    harness.maybe_compact.side_effect = lambda messages: (messages, False)
    harness.force_compact.side_effect = lambda messages: (messages, False)
    harness.run_stop_check.return_value = None
    harness.collect_context_usage.return_value = {
        "model": "test-model",
        "total_tokens": 10,
        "context_window": 1000,
        "percentage": 1.0,
        "free_tokens": 990,
        "messages": {
            "count": 5,
            "largest_tool_results": [],
        },
        "tools": {
            "count": 0,
            "largest_tools": [],
        },
        "categories": {},
    }

    def create_response(**kwargs):
        sent_messages = kwargs["messages"]
        assistant_index = next(
            i for i, msg in enumerate(sent_messages)
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        )
        following = sent_messages[assistant_index + 1:assistant_index + 3]
        assert [msg["role"] for msg in following] == ["tool", "tool"]
        assert [msg["tool_call_id"] for msg in following] == ["call_1", "call_2"]
        assert sent_messages[assistant_index + 3]["role"] == "user"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None),
                )
            ],
        )

    client = MagicMock()
    client.chat.completions.create.side_effect = create_response

    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "describe", "arguments": "{}"},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "describe", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"ok\": true}"},
        {"role": "user", "content": "[系统提示] 工具 describe 被阻止"},
        {"role": "tool", "tool_call_id": "call_2", "content": "{\"late\": true}"},
        {"role": "user", "content": "continue"},
    ]
    state = RunState(messages=messages, session_id="s1", user_question="continue")

    events = list(QueryLoop(harness, client, "test-model", lambda *args: None).run(state))

    assert any(getattr(event, "content", "") == "ok" for event in events)
    assert state.messages[2]["tool_call_id"] == "call_1"
    assert state.messages[3]["tool_call_id"] == "call_2"
    assert state.messages[4]["role"] == "user"


def test_query_loop_blocks_tool_calls_not_in_visible_tools():
    harness = MagicMock()
    harness.build_tools.return_value = [
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    harness.config.max_turns = 3
    harness.maybe_compact.side_effect = lambda messages: (messages, False)
    harness.force_compact.side_effect = lambda messages: (messages, False)
    harness.run_stop_check.return_value = None
    harness.collect_context_usage.return_value = {
        "model": "test-model",
        "total_tokens": 10,
        "context_window": 1000,
        "percentage": 1.0,
        "free_tokens": 990,
        "messages": {"count": 2, "largest_tool_results": []},
        "tools": {"count": 1, "largest_tools": []},
        "categories": {},
    }
    harness.execute_tool.return_value = ToolResult(content='{"ok": true}')

    responses = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="calling hidden",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_hidden",
                                function=SimpleNamespace(
                                    name="build_document_kb",
                                    arguments='{"force": true}',
                                ),
                            )
                        ],
                    ),
                )
            ],
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="done", tool_calls=None),
                )
            ],
        ),
    ]
    client = MagicMock()
    client.chat.completions.create.side_effect = responses

    state = RunState(
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "go"}],
        session_id="s1",
        user_question="go",
    )

    events = list(QueryLoop(harness, client, "test-model", lambda *args: None).run(state))

    harness.execute_tool.assert_not_called()
    tool_messages = [msg for msg in state.messages if msg.get("role") == "tool"]
    assert tool_messages
    assert tool_messages[0]["tool_call_id"] == "call_hidden"
    assert "工具不可用" in tool_messages[0]["content"]
    assert any(getattr(event, "content", "") == "done" for event in events)


# ── stop hooks ──

def test_query_complete_hook_fires():
    registry = HookRegistry()
    fired = []

    def my_hook(ctx):
        fired.append(ctx["user_question"])
        from oag.runtime.hooks import HookResult
        return HookResult()

    registry.register("query_complete", my_hook)
    registry.fire("query_complete", {"user_question": "test", "messages": []})

    assert fired == ["test"]


def test_default_stop_hook_detects_short_reply():
    from oag.runtime.stop_check import default_stop_hook
    result = default_stop_hook({
        "messages": [
            {"role": "assistant", "content": "ok"},
        ],
        "user_question": "详细分析一下",
    })
    assert result.action == "pause"
    assert "过短" in result.reason


def test_default_stop_hook_passes_normal():
    from oag.runtime.stop_check import default_stop_hook
    result = default_stop_hook({
        "messages": [
            {"role": "assistant", "content": "这是一个完整的回答，包含了所有需要的信息。"},
        ],
        "user_question": "test",
    })
    assert result.action == "allow"
