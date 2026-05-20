"""跨多个业务函数共享的工具：事件查询、设施信息、ID 生成等。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface


def parse_csv(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def get_event_detail(store: Store, event_id: str) -> dict | None:
    rows = store.query("DisasterEvent", {"event_id": event_id}, limit=1)
    if rows:
        return {"event_type": "DisasterEvent", **rows[0]}
    rows = store.query("AccidentEvent", {"event_id": event_id}, limit=1)
    if rows:
        return {"event_type": "AccidentEvent", **rows[0]}
    return None


def get_facility_info(facility_type: str, facility_id: str) -> dict | None:
    if facility_type == "路段":
        return iface.get_road_segment(segment_id=facility_id)
    elif facility_type == "桥梁":
        return iface.get_bridge_status(bridge_id=facility_id)
    elif facility_type == "隧道":
        return iface.get_tunnel_status(tunnel_id=facility_id)
    return None


_counters: dict[str, int] = {}


def next_id(prefix: str) -> str:
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}{_counters[prefix]:03d}"
