"""transfer_load: 负荷划接评估。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_request


def transfer_load(store: Store, request_id: str = "", scope: str = "",
                  source_id: str = "", transfer_capacity_kva: int = 0) -> dict:
    if scope not in ("feeder", "transformer"):
        return {"error": "scope 必须是 feeder 或 transformer"}
    if not source_id:
        return {"error": "需要参数: source_id"}

    req = get_request(store, request_id) if request_id else None
    transfer_kva = int(transfer_capacity_kva) if transfer_capacity_kva else 0

    switches = iface.get_tie_switches(scope, source_id)
    if not switches:
        return {
            "scope": scope, "source_id": source_id,
            "candidates": [], "best": None,
            "message": f"未找到 {source_id} 的可用联络开关",
        }

    candidates = []
    if scope == "feeder":
        for sw in switches:
            target = iface.get_feeder_status(sw["target_id"])
            if "error" in target:
                continue
            cur_rate = float(target.get("max_load_rate") or 0)
            openable = int(target.get("openable_capacity") or 0)
            # 粗略：转移容量按额定容量估算时 cur_rate + transfer_kva/openable 假设线性
            # 实际应有 feeder 额定容量字段，这里用 openable 作为剩余裕度的代理
            new_rate_estimate = cur_rate + (transfer_kva / max(openable + transfer_kva, 1)) * (1 - cur_rate)
            ok = new_rate_estimate <= 0.8 and openable >= transfer_kva
            candidates.append({
                "target_id": sw["target_id"],
                "current_load_rate": cur_rate,
                "openable_capacity": openable,
                "estimated_new_load_rate": round(new_rate_estimate, 3),
                "feasible": ok,
                "switch_id": sw["switch_id"],
            })
    else:  # transformer
        for sw in switches:
            target = iface.get_transformer_status(sw["target_id"])
            if "error" in target:
                continue
            cur_rate = float(target.get("load_rate") or 0)
            rated = int(target.get("rated_capacity") or 1)
            openable = int(target.get("openable_capacity") or 0)
            new_rate_estimate = cur_rate + transfer_kva / rated
            ok = new_rate_estimate <= 0.8 and openable >= transfer_kva
            candidates.append({
                "target_id": sw["target_id"],
                "current_load_rate": cur_rate,
                "openable_capacity": openable,
                "estimated_new_load_rate": round(new_rate_estimate, 3),
                "feasible": ok,
                "switch_id": sw["switch_id"],
            })

    feasible = [c for c in candidates if c["feasible"]]
    best = min(feasible, key=lambda x: x["estimated_new_load_rate"]) if feasible else None

    # 落 PlanIssue
    if request_id:
        if best:
            msg = (f"通过联络开关 {best['switch_id']} 将 {source_id} 的 {transfer_kva}kVA "
                   f"转移至 {best['target_id']} (预计新负载率 {best['estimated_new_load_rate']})")
        else:
            msg = f"{source_id} 周边无满足割接条件的{'馈线' if scope == 'feeder' else '主变'}"
        store.execute_write(
            "INSERT INTO plan_issue (plan_id, request_id, issue_type, source_id, target_id, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [None, request_id, "load_transfer", source_id,
             best["target_id"] if best else None, msg],
        )

    return {
        "scope": scope,
        "source_id": source_id,
        "transfer_capacity_kva": transfer_kva,
        "candidates": candidates,
        "best": best,
        "feasible": best is not None,
    }
