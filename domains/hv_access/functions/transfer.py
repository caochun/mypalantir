"""负荷划接评估。按 scope 拆为两个独立函数(transfer_feeder_load / transfer_transformer_load)，
让 LLM 凭工具名直接选对，不再需要 scope 字符串字段。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface


def _record_issue(store: Store, request_id: str, source_id: str,
                  target_id: str | None, message: str):
    store.execute_write(
        "INSERT INTO plan_issue (plan_id, request_id, issue_type, source_id, target_id, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [None, request_id, "load_transfer", source_id, target_id, message],
    )


def transfer_feeder_load(store: Store, request_id: str = "",
                          source_feeder_id: str = "",
                          transfer_capacity_kva: int = 0) -> dict:
    if not source_feeder_id:
        return {"error": "需要参数: source_feeder_id"}

    transfer_kva = int(transfer_capacity_kva) if transfer_capacity_kva else 0
    switches = iface.get_feeder_tie_switches(source_feeder_id)
    if not switches:
        return {
            "scope": "feeder", "source_feeder_id": source_feeder_id,
            "candidates": [], "best": None,
            "message": f"未找到 {source_feeder_id} 的可用联络开关",
        }

    candidates = []
    for sw in switches:
        target = iface.get_feeder_status(sw["target_feeder_id"])
        if "error" in target:
            continue
        cur_rate = float(target.get("max_load_rate") or 0)
        openable = int(target.get("openable_capacity") or 0)
        new_rate = cur_rate + (transfer_kva / max(openable + transfer_kva, 1)) * (1 - cur_rate)
        feasible = new_rate <= 0.8 and openable >= transfer_kva
        candidates.append({
            "target_feeder_id": sw["target_feeder_id"],
            "current_load_rate": cur_rate,
            "openable_capacity": openable,
            "estimated_new_load_rate": round(new_rate, 3),
            "feasible": feasible,
            "switch_id": sw["switch_id"],
        })

    feasible_list = [c for c in candidates if c["feasible"]]
    best = min(feasible_list, key=lambda x: x["estimated_new_load_rate"]) if feasible_list else None

    if request_id:
        if best:
            msg = (f"通过联络开关 {best['switch_id']} 将馈线 {source_feeder_id} "
                   f"的 {transfer_kva}kVA 转移至 {best['target_feeder_id']} "
                   f"(预计新负载率 {best['estimated_new_load_rate']})")
            _record_issue(store, request_id, source_feeder_id, best["target_feeder_id"], msg)
        else:
            msg = f"馈线 {source_feeder_id} 周边无满足割接条件的馈线"
            _record_issue(store, request_id, source_feeder_id, None, msg)

    return {
        "scope": "feeder",
        "source_feeder_id": source_feeder_id,
        "transfer_capacity_kva": transfer_kva,
        "candidates": candidates,
        "best": best,
        "feasible": best is not None,
    }


def transfer_transformer_load(store: Store, request_id: str = "",
                               source_transformer_id: str = "",
                               transfer_capacity_kva: int = 0) -> dict:
    if not source_transformer_id:
        return {"error": "需要参数: source_transformer_id"}

    transfer_kva = int(transfer_capacity_kva) if transfer_capacity_kva else 0
    switches = iface.get_transformer_tie_switches(source_transformer_id)
    if not switches:
        return {
            "scope": "transformer", "source_transformer_id": source_transformer_id,
            "candidates": [], "best": None,
            "message": f"未找到 {source_transformer_id} 的可用联络开关",
        }

    candidates = []
    for sw in switches:
        target = iface.get_transformer_status(sw["target_transformer_id"])
        if "error" in target:
            continue
        cur_rate = float(target.get("load_rate") or 0)
        rated = int(target.get("rated_capacity") or 1)
        openable = int(target.get("openable_capacity") or 0)
        new_rate = cur_rate + transfer_kva / rated
        feasible = new_rate <= 0.8 and openable >= transfer_kva
        candidates.append({
            "target_transformer_id": sw["target_transformer_id"],
            "current_load_rate": cur_rate,
            "openable_capacity": openable,
            "estimated_new_load_rate": round(new_rate, 3),
            "feasible": feasible,
            "switch_id": sw["switch_id"],
        })

    feasible_list = [c for c in candidates if c["feasible"]]
    best = min(feasible_list, key=lambda x: x["estimated_new_load_rate"]) if feasible_list else None

    if request_id:
        if best:
            msg = (f"通过联络开关 {best['switch_id']} 将主变 {source_transformer_id} "
                   f"的 {transfer_kva}kVA 转移至 {best['target_transformer_id']} "
                   f"(预计新负载率 {best['estimated_new_load_rate']})")
            _record_issue(store, request_id, source_transformer_id, best["target_transformer_id"], msg)
        else:
            msg = f"主变 {source_transformer_id} 站内无满足割接条件的主变"
            _record_issue(store, request_id, source_transformer_id, None, msg)

    return {
        "scope": "transformer",
        "source_transformer_id": source_transformer_id,
        "transfer_capacity_kva": transfer_kva,
        "candidates": candidates,
        "best": best,
        "feasible": best is not None,
    }
