"""filter_sources: 对候选电源点套用 7 条硬约束。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_point_topology, get_request, parse_csv


def filter_sources(store: Store, request_id: str = "", point_ids: str = "",
                   per_path_capacity_kva: int = 0) -> dict:
    req = get_request(store, request_id)
    if not req:
        return {"error": f"申请 {request_id} 不存在"}

    capacity = int(per_path_capacity_kva) if per_path_capacity_kva else int(req.get("capacity_kva") or 0)
    pids = parse_csv(point_ids)
    if not pids:
        return {"error": "需要参数: point_ids"}

    qualified: list[dict] = []
    rejected: list[dict] = []

    for pid in pids:
        topo = get_point_topology(pid)
        if not topo:
            rejected.append({"point_id": pid, "reasons": ["F0: 电源点不存在"]})
            continue

        f = topo["feeder"]; t = topo["transformer"]; ap = topo["access_point"]
        reasons: list[str] = []

        # F1
        if float(f.get("max_load_rate") or 0) >= 0.8:
            reasons.append(f"F1: 馈线最大负载率 {f.get('max_load_rate')} ≥ 0.8")
        # F2
        if int(f.get("openable_capacity") or 0) <= capacity:
            reasons.append(f"F2: 馈线可开放容量 {f.get('openable_capacity')} 不足 {capacity}kVA")
        # F3 (only for 环网柜/开关站)
        if ap.get("device_type") in ("环网柜", "开关站"):
            if int(ap.get("spare_interval_count") or 0) < 2:
                reasons.append(f"F3: {ap['device_type']}备用间隔 {ap.get('spare_interval_count')} < 2")
        # F4
        if int(f.get("connected_user_count") or 0) > 50:
            reasons.append(f"F4: 馈线已接入用户 {f.get('connected_user_count')} > 50")
        # F5
        if float(f.get("loss_rate") or 0) > 0.07:
            reasons.append(f"F5: 馈线线损率 {f.get('loss_rate')} > 0.07")
        # F6/F7 主变
        if t:
            if int(t.get("openable_capacity") or 0) <= capacity:
                reasons.append(f"F6: 主变可开放容量 {t.get('openable_capacity')} 不足 {capacity}kVA")
            if float(t.get("load_rate") or 0) >= 0.8:
                reasons.append(f"F7: 主变负载率 {t.get('load_rate')} ≥ 0.8")
        else:
            reasons.append("F6/F7: 主变信息缺失")

        item = {
            "point_id": pid,
            "feeder_id": f["feeder_id"],
            "substation_id": f["substation_id"],
            "busbar_id": f["busbar_id"],
            "transformer_id": t["transformer_id"] if t else None,
            "device_type": ap.get("device_type"),
            "distance_m": ap.get("distance_m"),
        }
        if reasons:
            rejected.append({**item, "reasons": reasons})
        else:
            qualified.append(item)

    return {
        "request_id": request_id,
        "per_path_capacity_kva": capacity,
        "qualified_count": len(qualified),
        "rejected_count": len(rejected),
        "qualified": qualified,
        "qualified_point_ids": ",".join(x["point_id"] for x in qualified),
        "rejected": rejected,
    }
