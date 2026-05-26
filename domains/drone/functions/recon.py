from __future__ import annotations
from oag.store import Store
from . import interfaces as iface
from ._helpers import get_event_detail, next_id, parse_csv

DISASTER_PAYLOAD_MAP = {
    "滑坡": "光学相机,红外相机",
    "地震": "光学相机,激光雷达",
    "泥石流": "光学相机,红外相机",
    "崩塌": "光学相机,激光雷达",
    "暴雨": "光学相机,视频摄像机",
    "洪水": "光学相机,红外相机",
    "冰雪": "红外相机,多光谱",
    "火灾": "红外相机,视频摄像机",
}

def plan_recon_mission(store: Store, event_id: str = "",
                       drone_id: str = "") -> dict:
    if not event_id:
        return {"error": "需要 event_id"}
    evt = get_event_detail(store, event_id)
    if not evt:
        return {"error": f"未找到事件: {event_id}"}

    if evt.get("event_type") == "AccidentEvent":
        return {"error": "交通事故事件不需要无人机侦测", "event_id": event_id}

    disaster_type = evt.get("disaster_type", "")
    payload_types = DISASTER_PAYLOAD_MAP.get(disaster_type, "光学相机,视频摄像机")
    required_payloads = parse_csv(payload_types)
    mission_type = "灾情宏观侦测"

    lng, lat = evt.get("lng", 0), evt.get("lat", 0)

    if drone_id:
        selected_drone = iface.get_drone(drone_id)
        if "error" in selected_drone:
            return selected_drone
        if selected_drone.get("status") != "可用":
            return {"error": f"无人机 {drone_id} 状态为{selected_drone.get('status')}，不可用"}
    else:
        drones = iface.get_drones_in_range(lng, lat, 80)
        if not drones:
            return {"error": "范围内无可用无人机", "event_id": event_id}
        selected_drone = None
        for d in drones:
            drone_payloads = parse_csv(d.get("payload_types", ""))
            if all(p in drone_payloads for p in required_payloads):
                selected_drone = d
                break
        if not selected_drone:
            available_info = [f"{d['drone_id']}({d.get('name','')},载荷:{d.get('payload_types','')})" for d in drones[:3]]
            return {"error": f"范围内无人机均不满足载荷要求({payload_types})，可用: {'; '.join(available_info)}", "event_id": event_id}

    operators = iface.get_operators_available()
    if not operators:
        return {"error": "无可用操控员", "event_id": event_id}
    selected_operator = operators[0]

    affected = evt.get("affected_segment_ids", "")
    mission_id = next_id("RCN")

    store.execute_write(
        "INSERT INTO recon_mission (mission_id, event_id, mission_type, drone_id, operator_id, "
        "target_facility_ids, planned_area_desc, payload_types, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [mission_id, event_id, mission_type, selected_drone["drone_id"],
         selected_operator["operator_id"], affected,
         evt.get("location_desc", ""), payload_types, "计划中"]
    )

    return {
        "mission_id": mission_id,
        "event_id": event_id,
        "mission_type": mission_type,
        "drone": {"id": selected_drone["drone_id"], "name": selected_drone.get("name",""), "model": selected_drone.get("model",""), "distance_km": selected_drone.get("distance_km",0)},
        "operator": {"id": selected_operator["operator_id"], "name": selected_operator.get("name","")},
        "payload_types": payload_types,
        "status": "计划中",
    }


def dispatch_drone(store: Store, mission_id: str = "") -> dict:
    if not mission_id:
        return {"error": "需要 mission_id"}

    missions = store.query("ReconMission", {"mission_id": mission_id}, limit=1)
    if not missions:
        return {"error": f"未找到任务: {mission_id}"}
    mission = missions[0]

    # Check compliance
    checks = store.query("ComplianceCheck", {"mission_id": mission_id}, limit=1)
    if not checks or checks[0].get("overall_result") != "通过":
        return {"error": "合规检查未通过，不可派遣", "mission_id": mission_id}

    # Check flight approval
    approvals = store.query("FlightApproval", {"mission_id": mission_id}, limit=1)
    if not approvals or approvals[0].get("approval_status") != "已批准":
        return {"error": "飞行审批未通过，不可派遣", "mission_id": mission_id}

    # Update mission status
    store.execute_write(
        "UPDATE recon_mission SET status = ? WHERE mission_id = ?",
        ["执行中", mission_id]
    )

    return {
        "mission_id": mission_id,
        "drone_id": mission.get("drone_id"),
        "operator_id": mission.get("operator_id"),
        "status": "执行中",
        "message": f"无人机 {mission.get('drone_id')} 已派遣执行侦测任务"
    }


def collect_recon_data(store: Store, mission_id: str = "") -> dict:
    if not mission_id:
        return {"error": "需要 mission_id"}

    missions = store.query("ReconMission", {"mission_id": mission_id}, limit=1)
    if not missions:
        return {"error": f"未找到任务: {mission_id}"}
    mission = missions[0]

    event_id = mission.get("event_id", "")
    payload_types = mission.get("payload_types", "")
    facility_ids = parse_csv(mission.get("target_facility_ids", ""))

    # Determine data type from payload
    if "激光雷达" in payload_types:
        data_type = "点云"
    elif "红外相机" in payload_types:
        data_type = "红外热图"
    elif "气体检测仪" in payload_types:
        data_type = "气体浓度"
    else:
        data_type = "影像"

    # Mock findings based on event disaster type
    evt = get_event_detail(store, event_id) if event_id else None
    disaster = evt.get("disaster_type", "未知") if evt else "未知"

    findings_map = {
        "滑坡": "发现滑坡体约200m长，覆盖双向车道，滑坡后缘仍有裂缝发育",
        "地震": "桥梁主梁有明显横向位移约15cm，桥墩可见裂缝",
        "泥石流": "隧道洞口被泥石流堆积物掩埋约3m高，洞口上方边坡仍有不稳定迹象",
        "崩塌": "崩塌体方量约500立方米，含大块岩石，路基完全阻断",
        "洪水": "路基缺口约30m，水深约2m，流速较快",
    }

    key_findings = findings_map.get(disaster, f"发现{disaster}相关损伤迹象")
    damage_indicators = f'{{"disaster_type":"{disaster}","severity":"中-重","affected_length_m":200,"blockage":true}}'

    data_id = next_id("RD")
    facility_id = facility_ids[0] if facility_ids else ""

    store.execute_write(
        "INSERT INTO recon_data (data_id, mission_id, event_id, facility_id, data_type, "
        "coverage_area_desc, key_findings, damage_indicators, recommended_actions) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [data_id, mission_id, event_id, facility_id, data_type,
         mission.get("planned_area_desc", ""), key_findings, damage_indicators,
         "建议开展设施现场检查(inspect_facility)获取详细损伤评估"]
    )

    # Update mission status
    store.execute_write(
        "UPDATE recon_mission SET status = ? WHERE mission_id = ?",
        ["完成", mission_id]
    )

    return {
        "data_id": data_id,
        "mission_id": mission_id,
        "event_id": event_id,
        "data_type": data_type,
        "key_findings": key_findings,
        "damage_indicators": damage_indicators,
        "recommended_actions": "建议开展设施现场检查(inspect_facility)获取详细损伤评估",
    }
