"""new_feeder: 变电站新出线评估。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_request


def new_feeder(store: Store, request_id: str = "", max_radius_m: int = 15000) -> dict:
    req = get_request(store, request_id)
    if not req:
        return {"error": f"申请 {request_id} 不存在"}

    capacity = int(req.get("capacity_kva") or 0)
    lng, lat = float(req["lng"]), float(req["lat"])
    max_r = int(max_radius_m)

    substations = iface.get_substations_in_range(lng, lat, max_r)
    all_trans = iface.all_transformers()

    candidates = []
    for s in substations:
        sub_trans = [t for t in all_trans if t["transformer_id"] and t.get("substation_id") == s["substation_id"]]
        for t in sub_trans:
            spare = int(t.get("spare_interval_count") or 0)
            load = float(t.get("load_rate") or 0)
            openable = int(t.get("openable_capacity") or 0)
            if spare > 0 and load < 0.8 and openable > capacity:
                candidates.append({
                    "substation_id": s["substation_id"],
                    "substation_name": s.get("name"),
                    "transformer_id": t["transformer_id"],
                    "distance_m": s["distance_m"],
                    "spare_interval_count": spare,
                    "load_rate": load,
                    "openable_capacity": openable,
                })

    candidates.sort(key=lambda x: (x["distance_m"], x["load_rate"]))
    best = candidates[0] if candidates else None

    if best:
        msg = (f"变电站新出线：从 {best['substation_name']}({best['substation_id']}) "
               f"的主变 {best['transformer_id']} 新出线，距离 {best['distance_m']}m，"
               f"主变负载率 {best['load_rate']}, 可开放容量 {best['openable_capacity']}kVA")
        store.execute_write(
            "INSERT INTO new_feeder_suggestion "
            "(request_id, substation_id, transformer_id, distance_m, "
            "load_rate, openable_capacity, spare_interval_count, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [request_id, best["substation_id"], best["transformer_id"],
             best["distance_m"], best["load_rate"], best["openable_capacity"],
             best["spare_interval_count"], msg],
        )
    else:
        msg = f"{max_r}m 范围内未找到满足空余间隔+主变达标的变电站，判定无可用方案"
        store.execute_write(
            "INSERT INTO no_solution_verdict (request_id, searched_radius_m, reason) "
            "VALUES (?, ?, ?)",
            [request_id, max_r, msg],
        )

    return {
        "request_id": request_id,
        "max_radius_m": max_r,
        "found_substations": len(substations),
        "qualified_candidates": len(candidates),
        "best": best,
        "feasible": best is not None,
    }
