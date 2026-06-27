from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import api
from oag.runtime.events import TextEvent
from oag.ontology.registry import FunctionRegistry
from oag.ontology.schema import FunctionDef, Ontology


class FakeSessions:
    def __init__(self):
        self.saved: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict]:
        return [dict(item) for item in self.saved.get(session_id, [])]

    def save(self, session_id: str, messages: list[dict]):
        self.saved[session_id] = [dict(item) for item in messages]


class FakeAgent:
    def __init__(self):
        self.sessions = FakeSessions()
        self.harness = SimpleNamespace(build_system_prompt=lambda: "system prompt")
        self.chat_stream_called = False
        self.run_loop_called = False

    def chat_stream(self, message: str, session_id: str = "default"):
        self.chat_stream_called = True
        raise AssertionError("fast path should not call Agent.chat_stream")

    def _run_loop(self, state):
        self.run_loop_called = True
        tool_result = json.loads(state.messages[-1]["content"])
        answer = tool_result["answer_md"] + "\n\n最终回答由 agent 生成。"
        state.messages.append({"role": "assistant", "content": answer})
        yield TextEvent(content=answer)

    def _save_stream_snapshot(self, session_id: str, messages: list[dict], streamed_content: str):
        snapshot = [dict(message) for message in messages]
        if streamed_content:
            snapshot.append({"role": "assistant", "content": streamed_content})
        self.sessions.save(session_id, snapshot)

    def chat(self, message: str, session_id: str = "default") -> str:
        self.chat_stream_called = True
        return ""

    def has_pending(self, session_id: str) -> bool:
        return False

    def list_sessions(self) -> list[dict]:
        return []

    def get_history(self, session_id: str) -> list[dict]:
        return [
            {"role": item["role"], "content": item.get("content", "")}
            for item in self.sessions.get(session_id)
            if item["role"] in {"user", "assistant"} and item.get("content")
        ]

    def get_context_usage(self, session_id: str) -> dict:
        return {}


class FakeRepository:
    def query(self, *args, **kwargs):
        return []


def test_substation_long_event_chain_stream_uses_fast_path(monkeypatch):
    fake_agent = FakeAgent()
    monkeypatch.setattr(api, "_make_agent", lambda *args, **kwargs: fake_agent)

    ontology = Ontology(
        name="substation",
        description="substation test",
        functions={
            "assess_substation_event_chain": FunctionDef(
                description="assess",
                params={},
            ),
        },
    )
    registry = FunctionRegistry()
    calls = []

    def assess_substation_event_chain(**kwargs):
        calls.append(kwargs)
        return {
            "answer_md": "## 事件链研判结论\n\n- 事件性质：需核查",
            "event_summary": {"event_count": 3},
            "structured_conclusion": {
                "event_description": "测试事件链",
                "event_type": "测试类型",
                "event_nature": "需核查",
                "risk_level": "一般",
                "reason": "测试依据",
            },
        }

    registry.register("assess_substation_event_chain", assess_substation_event_chain)
    app = api.create_app(ontology, FakeRepository(), registry, {}, domain_dir=None)
    client = TestClient(app)

    event_line = (
        "2026-01-20 16:11:05.442 至 2026-01-20 16:12:16.605，"
        "站点：山阳换流站，设备：系统监视，事件类型：二次设备-测量系统异常，"
        "二级摘要：测试信号出现后消失，告警等级：3。"
    )
    message = "请总结这一段事件链发生了什么，并判断是否异常。\n" + "\n".join(
        f"{i + 1}. {event_line}" for i in range(8)
    )

    response = client.get(
        "/agent/chat/stream",
        params={"session_id": "s1", "message": message},
    )

    assert response.status_code == 200
    assert fake_agent.chat_stream_called is False
    assert fake_agent.run_loop_called is True
    assert len(calls) == 1
    assert calls[0]["event_text"] == message
    assert "事件链研判结论" in response.text
    assert "最终回答由 agent 生成" in response.text
    history = fake_agent.get_history("s1")
    assert history[0]["role"] == "user"
    assert history[0]["content"] != message
    assert "原始输入约" in history[0]["content"]
    assert history[1]["role"] == "assistant"
    assert "最终回答由 agent 生成" in history[1]["content"]

    saved_messages = fake_agent.sessions.get("s1")
    tool_messages = [item for item in saved_messages if item.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "测试事件链" in tool_messages[0]["content"]


def test_substation_single_event_stream_uses_fast_path(monkeypatch):
    fake_agent = FakeAgent()
    monkeypatch.setattr(api, "_make_agent", lambda *args, **kwargs: fake_agent)

    ontology = Ontology(
        name="substation",
        description="substation test",
        functions={
            "assess_substation_event_chain": FunctionDef(
                description="assess",
                params={},
            ),
        },
    )
    registry = FunctionRegistry()
    calls = []

    def assess_substation_event_chain(**kwargs):
        calls.append(kwargs)
        return {
            "answer_md": "## 单事件研判\n\n- 事件性质：正常",
            "event_summary": {"event_count": 1},
            "structured_conclusion": {
                "event_description": "单条测试事件",
                "event_type": "测试类型",
                "event_nature": "正常",
                "risk_level": "低",
                "reason": "测试依据",
            },
        }

    registry.register("assess_substation_event_chain", assess_substation_event_chain)
    app = api.create_app(ontology, FakeRepository(), registry, {}, domain_dir=None)
    client = TestClient(app)

    message = (
        "请判断是否异常。"
        "2026-01-20 16:11:05.442 至 2026-01-20 16:12:16.605，"
        "站点：山阳换流站，设备：系统监视，事件类型：二次设备-测量系统异常，"
        "二级摘要：测试信号出现后消失，告警等级：3。"
    )

    response = client.get(
        "/agent/chat/stream",
        params={"session_id": "single", "message": message},
    )

    assert response.status_code == 200
    assert fake_agent.chat_stream_called is False
    assert fake_agent.run_loop_called is True
    assert len(calls) == 1
    assert calls[0]["event_text"] == message
    history = fake_agent.get_history("single")
    assert "一个或多个换流站事件文本" in history[0]["content"]
