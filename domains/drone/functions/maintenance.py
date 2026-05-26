from __future__ import annotations
from oag.store import Store
from . import interfaces as iface
from ._helpers import next_id


def log_maintenance(store: Store, drone_id: str = "", maintenance_type: str = "",
                    work_items: str = "") -> dict:
    if not drone_id or not maintenance_type:
        return {"error": "需要 drone_id 和 maintenance_type"}

    drone = iface.get_drone(drone_id)
    if "error" in drone:
        return drone

    # Determine next maintenance from rules
    rules = store.query("DroneMaintenanceRule", {"maintenance_type": maintenance_type})
    next_due = "按规则计算"
    if rules:
        next_due = rules[0].get("interval_desc", "按规则计算")

    log_id = next_id("ML")
    store.execute_write(
        "INSERT INTO drone_maintenance_log (log_id, drone_id, maintenance_type, work_items, "
        "flight_hours_at_maintenance, result, next_maintenance_due) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [log_id, drone_id, maintenance_type, work_items or f"{maintenance_type}维护",
         0, "通过", next_due]
    )

    return {
        "log_id": log_id,
        "drone_id": drone_id,
        "drone_name": drone.get("name", ""),
        "maintenance_type": maintenance_type,
        "result": "通过",
        "next_maintenance_due": next_due,
    }
