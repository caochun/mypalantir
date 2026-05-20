from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import next_id, parse_csv, get_event_detail


def trigger_defense_response(store: Store, warning_id: str = "") -> dict:
    if not warning_id:
        return {"error": "需要 warning_id"}

    warning = iface.get_weather_warning(warning_id)
    if "error" in warning:
        return warning

    level = warning.get("warning_level", "")
    level_map = {"红色": "一级", "橙色": "二级", "黄色": "三级", "蓝色": "四级"}
    response_level = level_map.get(level, "四级")

    rules = store.query("DefenseResponseLevelRule", {"warning_level": level}, limit=1)
    measures = rules[0].get("measures", "") if rules else "启动防御响应"
    preposition = rules[0].get("preposition_required", 0) if rules else 0

    affected_segments = parse_csv(warning.get("affected_segment_ids", ""))
    prepositioned_drones = []

    if preposition and affected_segments:
        lng = warning.get("lng", 103.5)
        lat = warning.get("lat", 30.7)
        drones = iface.get_drones_in_range(lng=103.5, lat=30.7, radius_km=80)
        for d in drones[:2]:
            prepositioned_drones.append(d["drone_id"])

    response_id = next_id("DR")
    store.execute_write(
        "INSERT INTO defense_response (response_id, warning_id, response_level, "
        "measures_taken, drone_prepositioned, patrol_intensified, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [response_id, warning_id, response_level, measures,
         ",".join(prepositioned_drones), len(affected_segments), "进行中"]
    )

    return {
        "response_id": response_id,
        "warning_id": warning_id,
        "warning_level": level,
        "response_level": response_level,
        "measures": measures,
        "prepositioned_drones": prepositioned_drones,
        "affected_segments": affected_segments,
        "status": "进行中",
    }


def intensify_patrol(store: Store, warning_id: str = "") -> dict:
    if not warning_id:
        return {"error": "需要 warning_id"}

    warning = iface.get_weather_warning(warning_id)
    if "error" in warning:
        return warning

    affected_segments = parse_csv(warning.get("affected_segment_ids", ""))
    if not affected_segments:
        return {"warning_id": warning_id, "message": "无受影响路段"}

    level = warning.get("warning_level", "")
    rules = store.query("DefenseResponseLevelRule", {"warning_level": level}, limit=1)
    new_freq = rules[0].get("patrol_frequency", "每日") if rules else "每日"

    updated = 0
    for seg_id in affected_segments:
        schedules = store.query("PatrolSchedule", {"status": "活跃"})
        for s in schedules:
            if seg_id in (s.get("route_segment_ids") or ""):
                store.execute_write(
                    "UPDATE patrol_schedule SET frequency = ? WHERE schedule_id = ?",
                    [new_freq, s["schedule_id"]]
                )
                updated += 1

    if updated == 0:
        drones = iface.get_drones_in_range(lng=103.5, lat=30.7, radius_km=80)
        operators = iface.get_operators_available()
        if drones and operators:
            schedule_id = next_id("PS")
            store.execute_write(
                "INSERT INTO patrol_schedule (schedule_id, drone_id, operator_id, "
                "route_segment_ids, frequency, next_patrol_time, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [schedule_id, drones[0]["drone_id"], operators[0]["operator_id"],
                 ",".join(affected_segments), new_freq, "立即", "活跃"]
            )
            updated = 1

    return {
        "warning_id": warning_id,
        "warning_level": level,
        "new_frequency": new_freq,
        "affected_segments": affected_segments,
        "schedules_updated": updated,
    }
