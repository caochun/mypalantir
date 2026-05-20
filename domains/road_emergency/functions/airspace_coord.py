from __future__ import annotations

from oag.store import Store

from ._helpers import next_id, get_event_detail


def coordinate_airspace(store: Store, event_id: str = "",
                        participating_departments: str = "交通,公安,消防") -> dict:
    if not event_id:
        return {"error": "需要 event_id"}

    evt = get_event_detail(store, event_id)
    if not evt:
        return {"error": f"未找到事件: {event_id}"}

    level = evt.get("event_level", "IV")

    if level not in ("I", "II"):
        return {
            "event_id": event_id,
            "event_level": level,
            "message": f"事件等级{level}级，无需多部门空域协调(仅I/II级需要)",
        }

    depts = [d.strip() for d in participating_departments.split(",") if d.strip()]

    altitude_plan = []
    for dept in depts:
        if dept == "交通":
            altitude_plan.append(f"{dept}: <120m (侦测无人机)")
        elif dept in ("公安", "消防"):
            altitude_plan.append(f"{dept}: 120-300m (中继/监控无人机)")
        elif dept in ("军方", "救援直升机"):
            altitude_plan.append(f"{dept}: >300m (直升机)")
        else:
            altitude_plan.append(f"{dept}: 待协调")

    coord_id = next_id("AC")
    altitude_str = "; ".join(altitude_plan)

    store.execute_write(
        "INSERT INTO airspace_coordination (coordination_id, event_id, "
        "participating_departments, altitude_assignments, time_slots, "
        "coordination_authority, status, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [coord_id, event_id, participating_departments, altitude_str,
         "全时段", "空中交通管理机构", "已协调",
         f"事件{event_id}({level}级)多部门空域协调方案已制定"]
    )

    return {
        "coordination_id": coord_id,
        "event_id": event_id,
        "event_level": level,
        "departments": depts,
        "altitude_assignments": altitude_plan,
        "authority": "空中交通管理机构",
        "status": "已协调",
    }
