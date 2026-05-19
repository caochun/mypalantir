from __future__ import annotations
import math
from oag.store import Store


def _int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(str(v))
    except (ValueError, TypeError):
        return 0


def _str(v) -> str | None:
    return str(v) if v is not None else None


def validate_path(store: Store, path_id: int = 0) -> dict:
    if not path_id:
        return {"error": "需要参数: path_id"}

    path_id = int(path_id)
    rows = store.execute_sql(
        "SELECT * FROM minimum_fee_path WHERE _id = ?", [path_id]
    )
    if not rows:
        return {"error": f"路径 {path_id} 不存在"}

    path = rows[0]
    intervals_str = path.get("toll_intervals") or ""
    mfee_str = path.get("chargefee_group") or ""
    efee_str = path.get("chargefee95_group") or ""
    total_fee = _int(path.get("total_fee"))
    total_fee95 = _int(path.get("total_fee95"))
    vehicle_type = _int(path.get("vehicle_type"))

    intervals = [s.strip() for s in intervals_str.split(",") if s.strip()]
    mfees = [_int(s.strip()) for s in mfee_str.split(",") if s.strip()]
    efees = [_int(s.strip()) for s in efee_str.split(",") if s.strip()]

    errors: list[dict] = []

    def add_error(rule: str, msg: str):
        errors.append({"path_id": path_id, "rule_id": rule, "message": msg})

    # V1: adjacent toll units must be connected in contiguity graph
    for i in range(len(intervals) - 1):
        a, b = intervals[i], intervals[i + 1]
        connected = store.execute_sql(
            "SELECT COUNT(*) as cnt FROM contiguity "
            "WHERE en_road_node_id = ? AND en_road_node_type = 0 "
            "AND ex_road_node_id = ? AND ex_road_node_type = 0 "
            "AND invalid = 0",
            [a, b],
        )
        if not connected or _int(connected[0].get("cnt")) == 0:
            add_error("V1", f"收费单元 {a} → {b} 在路网中不相邻")

    # V2: MTC total fee formula check
    sum_mfee = sum(mfees)
    expected_fee = int(math.floor(sum_mfee / 100 + 0.5) * 100)
    if total_fee != expected_fee:
        add_error("V2", f"MTC总费额不一致: 记录={total_fee}, 计算={expected_fee}")

    # V3: ETC total fee formula check
    sum_efee = sum(efees)
    expected_95 = int(min(sum_efee, math.floor(sum_mfee / 100) * 100 * 0.95))
    expected_95 = int(math.floor(expected_95 / 100 + 0.5) * 100)
    if total_fee95 != expected_95:
        add_error("V3", f"ETC总费额不一致: 记录={total_fee95}, 计算={expected_95}")

    # V4: sequence lengths must be consistent
    if len(intervals) != len(mfees) or len(intervals) != len(efees):
        add_error(
            "V4",
            f"序列长度不一致: intervals={len(intervals)}, "
            f"mfees={len(mfees)}, efees={len(efees)}",
        )

    # V5: units sharing the same gantry must be contiguous in the sequence
    unit_rows = {}
    for uid in intervals:
        rows = store.execute_sql(
            "SELECT gantry_id FROM toll_unit WHERE toll_interval_id = ?", [uid]
        )
        if rows:
            unit_rows[uid] = _str(rows[0].get("gantry_id"))

    gantry_positions: dict[str, list[int]] = {}
    for i, uid in enumerate(intervals):
        gid = unit_rows.get(uid)
        if gid:
            gantry_positions.setdefault(gid, []).append(i)

    for gid, positions in gantry_positions.items():
        if len(positions) > 1:
            for j in range(1, len(positions)):
                if positions[j] - positions[j - 1] != 1:
                    add_error(
                        "V5",
                        f"门架 {gid} 的收费单元在路径中不连续 "
                        f"(位置: {positions})",
                    )
                    break

    # write errors to validation_error table
    store.execute_write(
        "DELETE FROM validation_error WHERE path_id = ?", [path_id]
    )
    for e in errors:
        store.execute_write(
            "INSERT INTO validation_error (path_id, rule_id, message) "
            "VALUES (?, ?, ?)",
            [e["path_id"], e["rule_id"], e["message"]],
        )

    return {
        "path_id": path_id,
        "errors": errors,
        "passed": len(errors) == 0,
    }
