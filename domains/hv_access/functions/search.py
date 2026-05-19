"""search_sources: 受电点周围扩散搜索电源点，凑齐 N 条不同馈线。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_request

RADIUS_STEPS = [200, 500, 800, 1000]


def search_sources(store: Store, request_id: str = "",
                   min_distinct_feeders: int = 5,
                   device_types: str = "") -> dict:
    req = get_request(store, request_id)
    if not req:
        return {"error": f"申请 {request_id} 不存在"}

    lng, lat = float(req["lng"]), float(req["lat"])
    min_n = int(min_distinct_feeders)

    found: list[dict] = []
    seen_pids: set[str] = set()
    radius_used = 0
    for r in RADIUS_STEPS:
        radius_used = r
        points = iface.get_access_points_in_range(lng, lat, r, device_types)
        for p in points:
            if p["point_id"] not in seen_pids:
                seen_pids.add(p["point_id"])
                found.append(p)
        distinct_feeders = {p["feeder_id"] for p in found}
        if len(distinct_feeders) >= min_n:
            break

    distinct_feeders = sorted({p["feeder_id"] for p in found})
    return {
        "request_id": request_id,
        "radius_used_m": radius_used,
        "found_points": len(found),
        "distinct_feeders": distinct_feeders,
        "distinct_feeder_count": len(distinct_feeders),
        "satisfied": len(distinct_feeders) >= min_n,
        "point_ids": ",".join(p["point_id"] for p in found),
        "points": found,
    }
