"""跨多个业务函数共享的工具：拓扑遍历、距离、CSV 解析等。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> int:
    return iface._haversine_m(lng1, lat1, lng2, lat2)


def parse_csv(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def get_request(store: Store, request_id: str) -> dict | None:
    """从 AccessRequest 或 ExpandRequest 中查找请求记录。

    返回 dict 多一个 request_type 字段标识来源对象类型。
    """
    rows = store.query("AccessRequest", {"request_id": request_id}, limit=1)
    if rows:
        return {"request_type": "AccessRequest", **rows[0]}
    rows = store.query("ExpandRequest", {"request_id": request_id}, limit=1)
    if rows:
        return {"request_type": "ExpandRequest", **rows[0]}
    return None


def get_point_topology(point_id: str) -> dict | None:
    """从电源点反向遍历到变电站，返回完整拓扑字典。"""
    ap = next((p for p in iface.all_access_points() if p["point_id"] == point_id), None)
    if not ap:
        return None
    feeder = next((f for f in iface.all_feeders() if f["feeder_id"] == ap["feeder_id"]), None)
    if not feeder:
        return None
    busbar = next((b for b in iface.all_busbars() if b["busbar_id"] == feeder["busbar_id"]), None)
    transformer = next(
        (t for t in iface.all_transformers() if t["transformer_id"] == busbar["transformer_id"]),
        None,
    ) if busbar else None
    substation = next(
        (s for s in iface.all_substations() if s["substation_id"] == feeder["substation_id"]),
        None,
    )
    return {
        "access_point": ap,
        "feeder": feeder,
        "busbar": busbar,
        "transformer": transformer,
        "substation": substation,
    }
