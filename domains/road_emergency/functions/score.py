"""score_plans: 三维加权评分 时效40%+安全30%+经济30%。"""
from __future__ import annotations

from oag.store import Store

from ._helpers import parse_csv


def score_plans(store: Store, event_id: str = "") -> dict:
    plans = store.query(
        "ClearancePlan",
        {"event_id": event_id, "status": "candidate"},
    )
    if not plans:
        return {"error": f"事件 {event_id} 无候选方案，先调用 generate_clearance_plans"}

    # 时效性：工期归一化
    durations = [float(p.get("estimated_duration_hours") or 24) for p in plans]
    d_min, d_max = min(durations), max(durations)

    def _norm(v: float, lo: float, hi: float, invert: bool = False) -> float:
        if hi == lo:
            return 100.0
        score = (v - lo) / (hi - lo) * 100
        return round(100 - score if invert else score, 2)

    updated = 0
    for p in plans:
        duration = float(p.get("estimated_duration_hours") or 24)
        timeliness_score = _norm(duration, d_min, d_max, invert=True)

        # 安全性：基础 70，技术含"监测"或"支撑"加 30
        tech_name = p.get("technique_name") or ""
        tech_desc = p.get("technique_desc") or ""
        safety_score = 70.0
        if "监测" in tech_name or "监测" in tech_desc or "支撑" in tech_name or "支撑" in tech_desc:
            safety_score = 100.0

        # 经济性：所需装备数量越少分越高
        equip_count = len(parse_csv(p.get("required_equipment") or ""))
        material_count = len(parse_csv(p.get("required_material") or ""))
        total_items = equip_count + material_count
        economy_score = round(max(100 - total_items * 10, 20), 2)

        total_score = round(
            timeliness_score * 0.4 + safety_score * 0.3 + economy_score * 0.3, 2
        )

        store.execute_write(
            "UPDATE clearance_plan SET timeliness_score=?, safety_score=?, "
            "economy_score=?, total_score=? WHERE _id=?",
            [timeliness_score, safety_score, economy_score, total_score, p["_id"]],
        )
        updated += 1

    # 返回排名
    top = store.query(
        "ClearancePlan",
        {"event_id": event_id, "status": "candidate"},
        order_by="-total_score", limit=5,
    )
    return {
        "event_id": event_id,
        "scored_count": updated,
        "duration_range_hours": [d_min, d_max],
        "top5_preview": [
            {"plan_id": p.get("plan_id"),
             "facility_id": p.get("facility_id"),
             "technique_name": p.get("technique_name"),
             "total_score": p.get("total_score"),
             "timeliness": p.get("timeliness_score"),
             "safety": p.get("safety_score"),
             "economy": p.get("economy_score")}
            for p in top
        ],
    }
