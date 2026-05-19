"""score_plans: 三维加权评分 距离40%+容量30%+可靠性30%。"""
from __future__ import annotations

from oag.store import Store

# 电源数维度（占可靠性 50%）
SOURCE_SCORES = {
    "多电源": 100,
    "双电源": 100,
    "双回路": 90,
    "单电源": 80,
}

# 运行方式维度（占可靠性 50%）
# 关键词匹配 operation_mode
OPERATION_SCORES = [
    ("互为备用", 100),
    ("同时供电", 90),
    ("一主一备", 80),
    ("一路主供", 70),
    ("单电源",   80),  # 单电源也算 80
]


def _op_score(operation_mode: str) -> int:
    for kw, s in OPERATION_SCORES:
        if kw in operation_mode:
            return s
    return 70


def score_plans(store: Store, request_id: str = "") -> dict:
    plans = store.query(
        "AccessPlan",
        {"request_id": request_id, "status": "candidate"},
    )
    if not plans:
        return {"error": f"申请 {request_id} 无候选方案，先调用 compose_plans"}

    # 距离：本批方案中 min 得 100，max 得 0，线性
    dists = [int(p.get("total_distance_m") or 0) for p in plans]
    d_min, d_max = min(dists), max(dists)
    # 容量：min_openable_capacity 越大得分越高
    caps = [int(p.get("min_openable_capacity") or 0) for p in plans]
    c_min, c_max = min(caps), max(caps)

    def _norm(v: int, lo: int, hi: int, invert: bool = False) -> float:
        if hi == lo:
            return 100.0
        score = (v - lo) / (hi - lo) * 100
        return round(100 - score if invert else score, 2)

    updated = 0
    for p in plans:
        d_score = _norm(int(p.get("total_distance_m") or 0), d_min, d_max, invert=True)
        c_score = _norm(int(p.get("min_openable_capacity") or 0), c_min, c_max, invert=False)
        src_score = SOURCE_SCORES.get(p.get("structure_type") or "单电源", 80)
        op_score = _op_score(p.get("operation_mode") or "")
        reliability = round(src_score * 0.5 + op_score * 0.5, 2)
        total = round(d_score * 0.4 + c_score * 0.3 + reliability * 0.3, 2)
        store.execute_write(
            "UPDATE access_plan SET distance_score=?, capacity_score=?, "
            "reliability_score=?, total_score=? WHERE _id=?",
            [d_score, c_score, reliability, total, p["_id"]],
        )
        updated += 1

    top = store.query(
        "AccessPlan",
        {"request_id": request_id, "status": "candidate"},
        order_by="-total_score", limit=5,
    )
    return {
        "request_id": request_id,
        "scored_count": updated,
        "distance_range_m": [d_min, d_max],
        "capacity_range_kva": [c_min, c_max],
        "top5_preview": [
            {"operation_mode": p["operation_mode"],
             "total_score": p["total_score"],
             "points": p["access_point_ids"]}
            for p in top
        ],
    }
