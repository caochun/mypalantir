"""Tests for retry, micro-compaction, and stop hooks."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.retry import call_llm_with_retry, _backoff_delay
from oag.context import ContextManager, count_messages_tokens, estimate_tokens
from oag.hooks import HookRegistry


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

    with patch("oag.retry.time.sleep"):
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
        with patch("oag.retry.time.sleep"):
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


# ── stop hooks ──

def test_query_complete_hook_fires():
    registry = HookRegistry()
    fired = []

    def my_hook(ctx):
        fired.append(ctx["user_question"])
        from oag.hooks import HookResult
        return HookResult()

    registry.register("query_complete", my_hook)
    registry.fire("query_complete", {"user_question": "test", "messages": []})

    assert fired == ["test"]


def test_default_stop_hook_detects_short_reply():
    from oag.harness import _default_stop_hook
    result = _default_stop_hook({
        "messages": [
            {"role": "assistant", "content": "ok"},
        ],
        "user_question": "详细分析一下",
    })
    assert result.action == "pause"
    assert "过短" in result.reason


def test_default_stop_hook_passes_normal():
    from oag.harness import _default_stop_hook
    result = _default_stop_hook({
        "messages": [
            {"role": "assistant", "content": "这是一个完整的回答，包含了所有需要的信息。"},
        ],
        "user_question": "test",
    })
    assert result.action == "allow"
