from __future__ import annotations
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


def build_graph(store: Store, version_id: str = "") -> dict:
    units = store.query("TollUnit")
    stations = store.query("TollStation")
    rules = store.query("NoContiguityRule")

    store.execute_write("DELETE FROM contiguity")

    edges: list[dict] = []

    # E1: unit → unit
    for a in units:
        a_end_id = _str(a.get("end_org_id"))
        a_end_type = _int(a.get("end_org_type"))
        a_opposite = _str(a.get("opposite_id"))
        a_id = _str(a.get("toll_interval_id"))
        a_miles = _int(a.get("actual_length"))
        a_charge = _int(a.get("charge_length"))

        for b in units:
            b_id = _str(b.get("toll_interval_id"))
            if b_id == a_id:
                continue
            if a_opposite and b_id == a_opposite:
                continue
            b_start_id = _str(b.get("start_org_id"))
            b_start_type = _int(b.get("start_org_type"))

            if a_end_id and a_end_id == b_start_id and a_end_type == b_start_type:
                edges.append({
                    "en": a_id, "en_type": 0, "ex": b_id, "ex_type": 0,
                    "miles": a_miles, "charge_miles": a_charge,
                    "invalid": 0, "rule_id": None,
                })

    # E2: station → unit (station is start of unit)
    for u in units:
        if _int(u.get("start_org_type")) != 1:
            continue
        start_org_id = _str(u.get("start_org_id"))
        u_id = _str(u.get("toll_interval_id"))
        for s in stations:
            if _int(s.get("use_status")) != 2:
                continue
            if _str(s.get("station_id")) == start_org_id:
                edges.append({
                    "en": _str(s.get("station_id")), "en_type": 1,
                    "ex": u_id, "ex_type": 0,
                    "miles": 0, "charge_miles": 0, "invalid": 0, "rule_id": None,
                })

    # E3: unit → station (station is end of unit)
    for u in units:
        if _int(u.get("end_org_type")) != 1:
            continue
        end_org_id = _str(u.get("end_org_id"))
        u_id = _str(u.get("toll_interval_id"))
        miles = _int(u.get("actual_length"))
        charge = _int(u.get("charge_length"))
        for s in stations:
            if _str(s.get("station_id")) == end_org_id:
                edges.append({
                    "en": u_id, "en_type": 0,
                    "ex": _str(s.get("station_id")), "ex_type": 1,
                    "miles": miles, "charge_miles": charge,
                    "invalid": 0, "rule_id": None,
                })

    # E4: invalidate edges (contiguity_type=1)
    invalidated = 0
    for rule in rules:
        if _int(rule.get("contiguity_type")) != 1:
            continue
        en_id = _str(rule.get("en_road_node_id"))
        en_type = _int(rule.get("en_road_node_type"))
        ex_id = _str(rule.get("ex_road_node_id"))
        ex_type = _int(rule.get("ex_road_node_type"))
        for e in edges:
            if (e["en"] == en_id and e["en_type"] == en_type
                    and e["ex"] == ex_id and e["ex_type"] == ex_type):
                e["invalid"] = 1
                e["rule_id"] = "E4"
                invalidated += 1

    # E5: force-add edges (contiguity_type=2 or 3)
    for rule in rules:
        c_type = _int(rule.get("contiguity_type"))
        if c_type not in (2, 3):
            continue
        en_id = _str(rule.get("en_road_node_id"))
        en_type = _int(rule.get("en_road_node_type"))
        ex_id = _str(rule.get("ex_road_node_id"))
        ex_type = _int(rule.get("ex_road_node_type"))
        exists = any(
            e["en"] == en_id and e["en_type"] == en_type
            and e["ex"] == ex_id and e["ex_type"] == ex_type
            and not e["invalid"]
            for e in edges
        )
        if not exists:
            edges.append({
                "en": en_id, "en_type": en_type,
                "ex": ex_id, "ex_type": ex_type,
                "miles": 0, "charge_miles": 0, "invalid": 0, "rule_id": "E5",
            })

    # E6: deduplicate
    seen: set[str] = set()
    deduped: list[dict] = []
    for e in edges:
        key = f"{e['en']}|{e['en_type']}|{e['ex']}|{e['ex_type']}"
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    for e in deduped:
        store.execute_write(
            "INSERT INTO contiguity "
            "(en_road_node_id, en_road_node_type, ex_road_node_id, ex_road_node_type, "
            "miles, charge_miles, invalid, rule_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [e["en"], e["en_type"], e["ex"], e["ex_type"],
             e["miles"], e["charge_miles"], e["invalid"], e["rule_id"]],
        )

    return {"edges_created": len(deduped), "edges_invalidated": invalidated}
