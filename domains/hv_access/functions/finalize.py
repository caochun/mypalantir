"""finalize_plans: 按 operation_mode 去重，每种保留最高分1套，总数≤10。"""
from __future__ import annotations

from oag.store import Store


def finalize_plans(store: Store, request_id: str = "") -> dict:
    plans = store.query(
        "AccessPlan",
        {"request_id": request_id, "status": "candidate"},
        order_by="-total_score",
    )
    if not plans:
        return {"error": f"申请 {request_id} 无候选方案"}

    # 每种 operation_mode 取最高分 1 套
    kept: list[dict] = []
    seen_modes: set[str] = set()
    for p in plans:
        mode = p.get("operation_mode") or ""
        if mode in seen_modes:
            continue
        seen_modes.add(mode)
        kept.append(p)

    # 总数限制 10
    if len(kept) > 10:
        kept = kept[:10]

    kept_ids = {p["_id"] for p in kept}
    final_count = 0
    dropped_count = 0
    for p in plans:
        new_status = "final" if p["_id"] in kept_ids else "dropped"
        store.execute_write(
            "UPDATE access_plan SET status=? WHERE _id=?",
            [new_status, p["_id"]],
        )
        if new_status == "final":
            final_count += 1
        else:
            dropped_count += 1

    return {
        "request_id": request_id,
        "final_count": final_count,
        "dropped_count": dropped_count,
        "final_plans": [
            {"operation_mode": p["operation_mode"],
             "structure_type": p["structure_type"],
             "points": p["access_point_ids"],
             "feeders": p["source_feeder_ids"],
             "total_score": p["total_score"],
             "distance_m": p["total_distance_m"]}
            for p in kept
        ],
    }
