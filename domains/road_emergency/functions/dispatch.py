"""dispatch_resources: 为方案调度资源(队伍+装备+物资)。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_event_detail, next_id, parse_csv


def dispatch_resources(store: Store, event_id: str = "",
                       plan_id: str = "") -> dict:
    event = get_event_detail(store, event_id)
    if not event:
        return {"error": f"事件 {event_id} 不存在"}

    plans = store.query("ClearancePlan", {"plan_id": plan_id}, limit=1)
    if not plans:
        return {"error": f"方案 {plan_id} 不存在"}
    plan = plans[0]

    elng, elat = float(event.get("lng", 0)), float(event.get("lat", 0))

    # 搜索附近储备点
    depots = iface.get_depots_in_range(lng=elng, lat=elat, radius_km=100)
    if not depots:
        return {"error": "100km 范围内无可用储备点"}

    # 搜索附近应急队伍
    teams = iface.get_rescue_teams_in_range(lng=elng, lat=elat, radius_km=100)

    dispatches: list[dict] = []

    # 调度应急队伍
    if teams:
        team = teams[0]  # 最近的
        dispatch_id = next_id("DSP")
        dist = team.get("distance_km", 0)
        arrival = round(dist / 60, 2)  # 假设 60 km/h
        store.execute_write(
            "INSERT INTO resource_dispatch "
            "(dispatch_id, event_id, plan_id, resource_type, resource_name, "
            "quantity, source_depot_id, source_name, distance_km, "
            "estimated_arrival_hours, status) "
            "VALUES (?, ?, ?, '队伍', ?, ?, '', ?, ?, ?, 'pending')",
            [dispatch_id, event_id, plan_id,
             team.get("name", ""),
             team.get("capacity_person", 0),
             team.get("name", ""),
             dist, arrival],
        )
        dispatches.append({
            "dispatch_id": dispatch_id,
            "resource_type": "队伍",
            "resource_name": team.get("name", ""),
            "quantity": team.get("capacity_person", 0),
            "distance_km": dist,
            "estimated_arrival_hours": arrival,
        })

    # 调度装备
    required_equipment = parse_csv(plan.get("required_equipment") or "")
    for equip_name in required_equipment:
        dispatched = False
        for depot in depots:
            stocks = iface.get_equipment_by_depot(depot_id=depot["depot_id"])
            for stock in stocks:
                if equip_name in (stock.get("name") or ""):
                    dispatch_id = next_id("DSP")
                    dist = depot.get("distance_km", 0)
                    arrival = round(dist / 40, 2)  # 装备运输 40 km/h
                    store.execute_write(
                        "INSERT INTO resource_dispatch "
                        "(dispatch_id, event_id, plan_id, resource_type, resource_name, "
                        "quantity, source_depot_id, source_name, distance_km, "
                        "estimated_arrival_hours, status) "
                        "VALUES (?, ?, ?, '装备', ?, ?, ?, ?, ?, ?, 'pending')",
                        [dispatch_id, event_id, plan_id,
                         stock.get("name", equip_name),
                         stock.get("quantity", 1),
                         depot["depot_id"],
                         depot.get("name", ""),
                         dist, arrival],
                    )
                    dispatches.append({
                        "dispatch_id": dispatch_id,
                        "resource_type": "装备",
                        "resource_name": stock.get("name", equip_name),
                        "quantity": stock.get("quantity", 1),
                        "source_depot": depot.get("name", ""),
                        "distance_km": dist,
                        "estimated_arrival_hours": arrival,
                    })
                    dispatched = True
                    break
            if dispatched:
                break

    # 调度物资
    required_material = parse_csv(plan.get("required_material") or "")
    for mat_name in required_material:
        dispatched = False
        for depot in depots:
            stocks = iface.get_material_by_depot(depot_id=depot["depot_id"])
            for stock in stocks:
                if mat_name in (stock.get("name") or ""):
                    dispatch_id = next_id("DSP")
                    dist = depot.get("distance_km", 0)
                    arrival = round(dist / 40, 2)
                    store.execute_write(
                        "INSERT INTO resource_dispatch "
                        "(dispatch_id, event_id, plan_id, resource_type, resource_name, "
                        "quantity, source_depot_id, source_name, distance_km, "
                        "estimated_arrival_hours, status) "
                        "VALUES (?, ?, ?, '物资', ?, ?, ?, ?, ?, ?, 'pending')",
                        [dispatch_id, event_id, plan_id,
                         stock.get("name", mat_name),
                         stock.get("quantity", 1),
                         depot["depot_id"],
                         depot.get("name", ""),
                         dist, arrival],
                    )
                    dispatches.append({
                        "dispatch_id": dispatch_id,
                        "resource_type": "物资",
                        "resource_name": stock.get("name", mat_name),
                        "quantity": stock.get("quantity", 1),
                        "source_depot": depot.get("name", ""),
                        "distance_km": dist,
                        "estimated_arrival_hours": arrival,
                    })
                    dispatched = True
                    break
            if dispatched:
                break

    return {
        "event_id": event_id,
        "plan_id": plan_id,
        "dispatch_count": len(dispatches),
        "dispatches": dispatches,
    }
