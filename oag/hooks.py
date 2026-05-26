from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

HOOK_EVENTS = [
    "pre_tool_call",
    "post_tool_call",
    "pre_function",
    "post_function",
    "plan_generated",
    "session_start",
    "session_end",
    "compact_triggered",
]

HookHandler = Callable[[dict], "HookResult"]


@dataclass
class HookResult:
    action: str = "allow"  # allow / block / pause
    reason: str = ""
    data: dict = field(default_factory=dict)


class HookRegistry:
    def __init__(self):
        self._hooks: dict[str, list[HookHandler]] = {}

    def register(self, event: str, handler: HookHandler):
        if event not in HOOK_EVENTS:
            raise ValueError(f"Unknown hook event: {event}. Must be one of {HOOK_EVENTS}")
        self._hooks.setdefault(event, []).append(handler)

    def unregister(self, event: str, handler: HookHandler):
        handlers = self._hooks.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def fire(self, event: str, context: dict) -> HookResult:
        merged_data: dict = {}
        for handler in self._hooks.get(event, []):
            try:
                result = handler(context)
                if result.action == "block":
                    return result
                if result.action == "pause":
                    return result
                if result.data:
                    for k, v in result.data.items():
                        if k in merged_data and isinstance(merged_data[k], list) and isinstance(v, list):
                            merged_data[k].extend(v)
                        else:
                            merged_data[k] = v
            except Exception as e:
                logger.warning(f"Hook handler error on {event}: {e}")
        return HookResult(action="allow", data=merged_data)

    def has_handlers(self, event: str) -> bool:
        return bool(self._hooks.get(event))


class AuditLog:
    def __init__(self):
        self._entries: list[dict] = []

    def record(self, entry: dict):
        entry["timestamp"] = datetime.now().isoformat()
        self._entries.append(entry)

    def get_entries(self, limit: int | None = None) -> list[dict]:
        if limit:
            return self._entries[-limit:]
        return list(self._entries)

    def clear(self):
        self._entries.clear()


def write_confirmation_hook(context: dict) -> HookResult:
    tool_meta = context.get("tool_meta")
    if tool_meta and tool_meta.requires_confirmation:
        return HookResult(
            action="pause",
            reason=f"函数 {context['tool_name']} 将修改数据，请确认执行",
        )
    return HookResult(action="allow")


def audit_log_hook(context: dict) -> HookResult:
    audit_log = context.get("audit_log")
    if audit_log:
        audit_log.record({
            "event": context.get("hook_event", "unknown"),
            "tool": context.get("tool_name", ""),
            "args": context.get("args", {}),
            "session_id": context.get("session_id", ""),
            "result_preview": str(context.get("result", ""))[:200],
        })
    return HookResult(action="allow")


def business_review_hook(context: dict) -> HookResult:
    tool_meta = context.get("tool_meta")
    if not tool_meta or tool_meta.category != "action":
        return HookResult(action="allow")

    result = context.get("result", "")
    tool_name = context.get("tool_name", "")
    issues = []

    try:
        data = json.loads(result) if isinstance(result, str) else result
    except (json.JSONDecodeError, TypeError):
        return HookResult(action="allow")

    if isinstance(data, dict) and "error" in data:
        issues.append(f"函数 {tool_name} 执行出错: {data['error']}")

    if isinstance(data, dict):
        if data.get("event_level") and data.get("grade_iii_count", 0) == 0 and data.get("grade_ii_count", 0) == 0:
            if data.get("event_level") in ("I", "II"):
                issues.append(f"事件等级为{data['event_level']}但无II/III级损伤设施，请检查评估逻辑")
        if data.get("total_score") is not None and data.get("total_score") == 0:
            issues.append("方案评分为0，可能评分逻辑异常")
        if data.get("overall_result") == "不通过":
            issues.append(f"合规检查不通过: {data.get('issues', '')}")

    if issues:
        return HookResult(action="allow", data={"review_notes": issues})

    return HookResult(action="allow")
