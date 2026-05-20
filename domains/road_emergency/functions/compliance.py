from __future__ import annotations
from oag.store import Store
from . import interfaces as iface
from ._helpers import get_event_detail, next_id, parse_csv


def check_compliance(store: Store, mission_id: str = "") -> dict:
    if not mission_id:
        return {"error": "需要 mission_id"}

    missions = store.query("ReconMission", {"mission_id": mission_id}, limit=1)
    if not missions:
        return {"error": f"未找到任务: {mission_id}"}
    mission = missions[0]

    drone = iface.get_drone(mission.get("drone_id", ""))
    operator = iface.get_drone_operator(mission.get("operator_id", ""))
    issues = []

    # 1. Drone compliance
    drone_ok = "通过"
    if "error" in drone:
        drone_ok = "不通过"
        issues.append(f"无人机 {mission.get('drone_id')} 不存在")
    else:
        category = drone.get("category", "")
        class_rules = store.query("DroneClassRule", {"category": category}, limit=1)
        if class_rules:
            rule = class_rules[0]
            if rule.get("registration_required") and not drone.get("registration_code"):
                drone_ok = "不通过"
                issues.append(f"{category}无人机需要实名登记但未登记")
            if rule.get("airworthiness_required") and not drone.get("airworthiness_cert"):
                drone_ok = "不通过"
                issues.append(f"{category}无人机需要适航证但未取得")
        if drone.get("status") != "可用":
            drone_ok = "不通过"
            issues.append(f"无人机状态为{drone.get('status')}，不可派遣")

    # 2. Operator compliance
    operator_ok = "通过"
    if "error" in operator:
        operator_ok = "不通过"
        issues.append(f"操控员 {mission.get('operator_id')} 不存在")
    else:
        category = drone.get("category", "") if "error" not in drone else ""
        license_rules = store.query("OperatorLicenseRule", {"drone_category": category})
        if license_rules:
            required = license_rules[0].get("required_license", "")
            actual = operator.get("license_type", "")
            license_rank = {"无需执照": 0, "安全操控合格证": 1, "操控员执照": 2}
            if license_rank.get(actual, 0) < license_rank.get(required, 0):
                operator_ok = "不通过"
                issues.append(f"操控员执照类型 {actual} 不满足要求 {required}")

    # 3. Airspace compliance
    airspace_ok = "通过"
    zones = iface.all_airspace_zones()
    for z in zones:
        if z.get("zone_type") == "禁飞区":
            airspace_ok = "通过"  # simplified: assume not in prohibited zone

    # 4. Payload compliance
    payload_ok = "通过"
    required_payloads = parse_csv(mission.get("payload_types", ""))
    if "error" not in drone:
        available_payloads = parse_csv(drone.get("payload_types", ""))
        for p in required_payloads:
            if p not in available_payloads:
                payload_ok = "不通过"
                issues.append(f"无人机不支持载荷: {p}")
                break

    overall = "通过" if all(x == "通过" for x in [drone_ok, operator_ok, airspace_ok, payload_ok]) else "不通过"

    check_id = next_id("CHK")
    store.execute_write(
        "INSERT INTO compliance_check (check_id, mission_id, drone_compliance, operator_compliance, "
        "airspace_compliance, payload_compliance, overall_result, issues) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [check_id, mission_id, drone_ok, operator_ok, airspace_ok, payload_ok,
         overall, ", ".join(issues) if issues else "无"]
    )

    return {
        "check_id": check_id,
        "mission_id": mission_id,
        "drone_compliance": drone_ok,
        "operator_compliance": operator_ok,
        "airspace_compliance": airspace_ok,
        "payload_compliance": payload_ok,
        "overall_result": overall,
        "issues": issues if issues else ["无"],
    }


def request_flight_approval(store: Store, mission_id: str = "") -> dict:
    if not mission_id:
        return {"error": "需要 mission_id"}

    missions = store.query("ReconMission", {"mission_id": mission_id}, limit=1)
    if not missions:
        return {"error": f"未找到任务: {mission_id}"}
    mission = missions[0]

    event_id = mission.get("event_id", "")
    is_emergency = False
    if event_id:
        evt = get_event_detail(store, event_id)
        if evt:
            is_emergency = True

    if is_emergency:
        approval_type = "应急快速"
        rules = store.query("EmergencyFlightRule", {"emergency_type": "抢险救灾"}, limit=1)
        authority = "空中交通管理机构(应急快速通道)"
        advance_desc = "提前30分钟申请，10分钟内批复"
    else:
        approval_type = "常规"
        rules = store.query("FlightApprovalRule", {"scenario": "常规飞行"}, limit=1)
        authority = "空中交通管理机构"
        advance_desc = "提前1日申请"

    approval_id = next_id("FA")
    store.execute_write(
        "INSERT INTO flight_approval (approval_id, mission_id, airspace_zone_id, approval_type, "
        "submit_time, planned_takeoff_time, approval_status, approval_authority, conditions) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [approval_id, mission_id, "", approval_type,
         "now", "ASAP" if is_emergency else "按计划",
         "已批准", authority,
         f"{'应急抢险任务快速审批(S3第29条)' if is_emergency else '常规审批'}: {advance_desc}"]
    )

    # Update mission status
    store.execute_write(
        "UPDATE recon_mission SET status = ? WHERE mission_id = ?",
        ["审批中", mission_id]
    )

    return {
        "approval_id": approval_id,
        "mission_id": mission_id,
        "approval_type": approval_type,
        "approval_status": "已批准",
        "authority": authority,
        "message": f"飞行审批{'(应急快速通道)' if is_emergency else ''}已批准",
    }


def check_airspace_conflict(store: Store, mission_id: str = "") -> dict:
    if not mission_id:
        return {"error": "需要 mission_id"}

    missions = store.query("ReconMission", {"mission_id": mission_id}, limit=1)
    if not missions:
        return {"error": f"未找到任务: {mission_id}"}
    mission = missions[0]

    event_id = mission.get("event_id", "")
    evt = get_event_detail(store, event_id) if event_id else None
    lng = evt.get("lng", 0) if evt else 0
    lat = evt.get("lat", 0) if evt else 0

    conflicts = []
    for zone in iface.all_airspace_zones():
        zone_type = zone.get("zone_type", "")
        # Simple proximity check (mock: check if zone center is within 20km)
        zone_lng = zone.get("lng", zone.get("center_lng", 0))
        zone_lat = zone.get("lat", zone.get("center_lat", 0))

        if zone_type == "禁飞区":
            conflict_id = next_id("AC")
            conflicts.append({
                "conflict_id": conflict_id,
                "zone_id": zone["zone_id"],
                "zone_name": zone.get("name", ""),
                "conflict_type": "禁飞区",
                "resolution": "需调整航线避开禁飞区"
            })
            store.execute_write(
                "INSERT INTO airspace_conflict (conflict_id, mission_id, conflicting_zone_id, "
                "conflict_type, resolution) VALUES (?, ?, ?, ?, ?)",
                [conflict_id, mission_id, zone["zone_id"], "禁飞区", "需调整航线避开禁飞区"]
            )

    if not conflicts:
        return {"mission_id": mission_id, "conflicts": [], "message": "无空域冲突"}

    return {
        "mission_id": mission_id,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }
