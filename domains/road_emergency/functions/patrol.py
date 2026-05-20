from __future__ import annotations
from oag.store import Store
from . import interfaces as iface
from ._helpers import next_id


def schedule_patrol(store: Store, route_segment_ids: str = "", drone_id: str = "",
                    operator_id: str = "", frequency: str = "每周") -> dict:
    if not route_segment_ids or not drone_id or not operator_id:
        return {"error": "需要 route_segment_ids, drone_id, operator_id"}

    drone = iface.get_drone(drone_id)
    if "error" in drone:
        return drone

    operator = iface.get_drone_operator(operator_id)
    if "error" in operator:
        return operator

    schedule_id = next_id("PS")
    store.execute_write(
        "INSERT INTO patrol_schedule (schedule_id, drone_id, operator_id, route_segment_ids, "
        "frequency, next_patrol_time, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [schedule_id, drone_id, operator_id, route_segment_ids, frequency,
         "待安排", "活跃"]
    )

    return {
        "schedule_id": schedule_id,
        "drone_id": drone_id,
        "drone_name": drone.get("name", ""),
        "operator_id": operator_id,
        "operator_name": operator.get("name", ""),
        "route_segment_ids": route_segment_ids,
        "frequency": frequency,
        "status": "活跃",
    }
