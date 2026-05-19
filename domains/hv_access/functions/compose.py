"""compose_plans: 按重要等级+负荷性质组合电源拓扑，生成 AccessPlan 候选。"""
from __future__ import annotations

from itertools import combinations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_point_topology, get_request, parse_csv
from .lookups import lookup_source_requirement

# 7 种 operation_mode（spec 第四章）
DUAL_MODES = ["双电源-同时供电", "双电源-互为备用", "双电源-一主一备"]
LOOP_MODES = ["双回路-同时供电", "双回路-互为备用", "双回路-一主一备"]
MULTI_MODE = "多电源-同时供电互为备用"
SINGLE_MODE = "单电源供电"

MAX_SINGLE = 5
MAX_DUAL_PAIRS = 10
MAX_LOOP_PAIRS = 10
MAX_MULTI_TRIPLES = 5


def compose_plans(store: Store, request_id: str = "",
                  qualified_point_ids: str = "") -> dict:
    req = get_request(store, request_id)
    if not req:
        return {"error": f"申请 {request_id} 不存在"}

    requirement = lookup_source_requirement(
        store,
        load_class=req.get("load_class") or "",
        importance_level=req.get("importance_level") or "",
    )
    if "error" in requirement:
        return {"error": f"查不到电源结构要求: {requirement['error']}"}

    structure = requirement.get("source_structure_type") or "单电源"
    pids = parse_csv(qualified_point_ids)
    if not pids:
        return {"error": "需要参数: qualified_point_ids"}

    # 拉拓扑。distance_m 按本次申请受电点重算(不污染 iface 缓存)
    req_lng, req_lat = float(req["lng"]), float(req["lat"])
    topos = []
    for pid in pids:
        t = get_point_topology(pid)
        if t:
            ap = t["access_point"]
            d = iface._haversine_m(req_lng, req_lat, float(ap["lng"]), float(ap["lat"]))
            ap_with_d = {**ap, "distance_m": d}
            topos.append({**t, "access_point": ap_with_d})
    if not topos:
        return {"error": "qualified_point_ids 中无有效电源点"}

    # 清空已有 candidate（重新生成）
    store.execute_write(
        "DELETE FROM access_plan WHERE request_id = ? AND status = 'candidate'",
        [request_id],
    )

    plans: list[dict] = []
    if structure == "单电源":
        plans.extend(_compose_single(topos))
    elif structure == "双电源":
        plans.extend(_compose_dual(topos))
    elif structure == "双回路":
        plans.extend(_compose_loop(topos))
    elif structure == "多电源":
        plans.extend(_compose_multi(topos))
    else:
        plans.extend(_compose_single(topos))

    for p in plans:
        store.execute_write(
            "INSERT INTO access_plan "
            "(request_id, operation_mode, structure_type, access_point_ids, "
            "source_feeder_ids, source_substation_ids, total_distance_m, "
            "min_openable_capacity, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate')",
            [request_id, p["operation_mode"], p["structure_type"],
             p["access_point_ids"], p["source_feeder_ids"],
             p["source_substation_ids"], p["total_distance_m"],
             p["min_openable_capacity"]],
        )

    return {
        "request_id": request_id,
        "required_structure": structure,
        "candidate_count": len(plans),
        "by_mode": _count_by(plans, "operation_mode"),
        "plans_summary": [
            {"operation_mode": p["operation_mode"], "points": p["access_point_ids"],
             "total_distance_m": p["total_distance_m"]}
            for p in plans
        ],
    }


# ---------- 组合策略 ----------

def _compose_single(topos: list[dict]) -> list[dict]:
    sorted_t = sorted(topos, key=lambda x: x["access_point"].get("distance_m") or 0)
    return [_make_plan([t], SINGLE_MODE, "单电源") for t in sorted_t[:MAX_SINGLE]]


def _compose_dual(topos: list[dict]) -> list[dict]:
    """双电源：跨站 或 同站不同电源进线两段母线。"""
    pairs = []
    for a, b in combinations(topos, 2):
        if a["feeder"]["feeder_id"] == b["feeder"]["feeder_id"]:
            continue  # 同馈线不算
        cross_sub = a["substation"]["substation_id"] != b["substation"]["substation_id"]
        cross_feedline = (
            not cross_sub
            and a["busbar"]["feed_line_id"] != b["busbar"]["feed_line_id"]
        )
        if cross_sub or cross_feedline:
            pairs.append((a, b))

    pairs.sort(key=lambda pr: (pr[0]["access_point"]["distance_m"]
                                + pr[1]["access_point"]["distance_m"]))
    out = []
    for pair in pairs[:MAX_DUAL_PAIRS]:
        for mode in DUAL_MODES:
            out.append(_make_plan(list(pair), mode, "双电源"))
    return out


def _compose_loop(topos: list[dict]) -> list[dict]:
    """双回路：同变电站不同母线即可。"""
    pairs = []
    for a, b in combinations(topos, 2):
        if a["feeder"]["feeder_id"] == b["feeder"]["feeder_id"]:
            continue
        same_sub = a["substation"]["substation_id"] == b["substation"]["substation_id"]
        diff_busbar = a["busbar"]["busbar_id"] != b["busbar"]["busbar_id"]
        if same_sub and diff_busbar:
            pairs.append((a, b))

    pairs.sort(key=lambda pr: (pr[0]["access_point"]["distance_m"]
                                + pr[1]["access_point"]["distance_m"]))
    out = []
    for pair in pairs[:MAX_LOOP_PAIRS]:
        for mode in LOOP_MODES:
            out.append(_make_plan(list(pair), mode, "双回路"))
    return out


def _compose_multi(topos: list[dict]) -> list[dict]:
    """多电源(特级)：至少 3 路，2 路跨站，1 路应急。"""
    triples = []
    for a, b, c in combinations(topos, 3):
        subs = {a["substation"]["substation_id"], b["substation"]["substation_id"],
                c["substation"]["substation_id"]}
        feeders = {a["feeder"]["feeder_id"], b["feeder"]["feeder_id"], c["feeder"]["feeder_id"]}
        if len(feeders) < 3:
            continue
        if len(subs) >= 2:
            triples.append((a, b, c))

    triples.sort(key=lambda tr: sum(t["access_point"]["distance_m"] for t in tr))
    out = []
    for tr in triples[:MAX_MULTI_TRIPLES]:
        out.append(_make_plan(list(tr), MULTI_MODE, "多电源"))
    return out


def _make_plan(topos: list[dict], operation_mode: str, structure_type: str) -> dict:
    pids = [t["access_point"]["point_id"] for t in topos]
    fids = [t["feeder"]["feeder_id"] for t in topos]
    sids = [t["substation"]["substation_id"] for t in topos]
    total_d = sum(t["access_point"].get("distance_m") or 0 for t in topos)
    min_cap = min(int(t["feeder"].get("openable_capacity") or 0) for t in topos)
    return {
        "operation_mode": operation_mode,
        "structure_type": structure_type,
        "access_point_ids": ",".join(pids),
        "source_feeder_ids": ",".join(fids),
        "source_substation_ids": ",".join(sids),
        "total_distance_m": int(total_d),
        "min_openable_capacity": int(min_cap),
    }


def _count_by(plans: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in plans:
        k = p.get(key)
        if k:
            out[k] = out.get(k, 0) + 1
    return out
