"""业务规则查询：损伤分级、事件等级、抢通技术、交通管制等。

数据来自 store（各规则表），按字段精确匹配。
"""
from __future__ import annotations

from oag.store import Store


def lookup_damage_grade(store: Store, facility_type: str = "",
                        damage_grade: str = "") -> dict | list[dict]:
    if not facility_type:
        return {"error": "需要参数: facility_type"}
    filters: dict[str, str] = {"facility_type": facility_type}
    if damage_grade:
        filters["damage_grade"] = damage_grade
    rows = store.query("DamageGradeStandard", filters)
    if not rows:
        return {"error": f"未找到匹配的损伤分级标准: {facility_type} {damage_grade}"}
    return rows


def lookup_event_level(store: Store, level: str = "") -> dict | list[dict]:
    filters: dict[str, str] = {}
    if level:
        filters["level"] = level
    rows = store.query("EventLevelStandard", filters)
    if not rows:
        return {"error": f"未找到匹配的事件分级标准: {level}"}
    return rows


def lookup_clearance_technique(store: Store, facility_type: str = "",
                               damage_type: str = "") -> dict | list[dict]:
    if not facility_type:
        return {"error": "需要参数: facility_type"}
    filters: dict[str, str] = {"facility_type": facility_type}
    if damage_type:
        filters["damage_type"] = damage_type
    rows = store.query("ClearanceTechniqueRule", filters)
    if not rows:
        return {"error": f"未找到匹配的抢通技术: {facility_type} {damage_type}"}
    return rows


def lookup_traffic_control(store: Store, damage_grade: str = "",
                           facility_type: str = "") -> dict | list[dict]:
    if not damage_grade:
        return {"error": "需要参数: damage_grade"}
    filters: dict[str, str] = {"damage_grade": damage_grade}
    if facility_type:
        filters["facility_type"] = facility_type
    rows = store.query("TrafficControlRule", filters)
    if not rows:
        return {"error": f"未找到匹配的交通管制规则: {damage_grade} {facility_type}"}
    return rows


def lookup_tunnel_importance(store: Store, road_grade: str = "",
                             aadt_range: str = "") -> dict | list[dict]:
    if not road_grade:
        return {"error": "需要参数: road_grade"}
    filters: dict[str, str] = {"road_grade": road_grade}
    if aadt_range:
        filters["aadt_range"] = aadt_range
    rows = store.query("TunnelImportanceLevel", filters)
    if not rows:
        return {"error": f"未找到匹配的隧道重要等级: {road_grade} {aadt_range}"}
    return rows


def lookup_tunnel_target(store: Store, difficulty: str = "",
                         importance_level: str = "") -> dict | list[dict]:
    if not difficulty or not importance_level:
        return {"error": "需要参数: difficulty, importance_level"}
    rows = store.query(
        "TunnelTargetMatrix",
        {"difficulty": difficulty, "importance_level": importance_level},
        limit=1,
    )
    if not rows:
        return {"error": f"未找到匹配的隧道抢通目标: {difficulty} {importance_level}"}
    return rows[0]


def lookup_bridge_type(store: Store, scenario: str = "",
                       obstacle_width_range: str = "") -> dict | list[dict]:
    filters: dict[str, str] = {}
    if scenario:
        filters["scenario"] = scenario
    if obstacle_width_range:
        filters["obstacle_width_range"] = obstacle_width_range
    rows = store.query("BridgeTypeSelection", filters)
    if not rows:
        return {"error": f"未找到匹配的便桥选型: {scenario} {obstacle_width_range}"}
    return rows


def lookup_response_level(store: Store, event_level: str = "") -> dict | list[dict]:
    if not event_level:
        return {"error": "需要参数: event_level"}
    rows = store.query(
        "ResponseLevelRule",
        {"event_level": event_level},
        limit=1,
    )
    if not rows:
        return {"error": f"未找到匹配的响应级别: {event_level}"}
    return rows[0]


def lookup_drone_class(store: Store, category: str = "") -> list[dict]:
    filters = {}
    if category:
        filters["category"] = category
    rows = store.query("DroneClassRule", filters)
    return rows if rows else {"error": f"未找到无人机分类: {category}"}

def lookup_operator_license_rule(store: Store, drone_category: str = "", operation_type: str = "") -> list[dict]:
    filters = {}
    if drone_category:
        filters["drone_category"] = drone_category
    if operation_type:
        filters["operation_type"] = operation_type
    rows = store.query("OperatorLicenseRule", filters)
    return rows if rows else {"error": "未找到匹配的操控员资质规则"}

def lookup_operation_class(store: Store, operation_class: str = "") -> list[dict]:
    filters = {}
    if operation_class:
        filters["operation_class"] = operation_class
    rows = store.query("OperationClassRule", filters)
    return rows if rows else {"error": f"未找到运行分类: {operation_class}"}

def lookup_airspace_rule(store: Store, airspace_type: str = "") -> list[dict]:
    filters = {}
    if airspace_type:
        filters["airspace_type"] = airspace_type
    rows = store.query("AirspaceRule", filters)
    return rows if rows else {"error": f"未找到空域规则: {airspace_type}"}

def lookup_flight_approval_rule(store: Store, scenario: str = "") -> list[dict]:
    filters = {}
    if scenario:
        filters["scenario"] = scenario
    rows = store.query("FlightApprovalRule", filters)
    return rows if rows else {"error": f"未找到审批规则: {scenario}"}

def lookup_emergency_flight_rule(store: Store, emergency_type: str = "") -> list[dict]:
    filters = {}
    if emergency_type:
        filters["emergency_type"] = emergency_type
    rows = store.query("EmergencyFlightRule", filters)
    return rows if rows else {"error": f"未找到应急飞行规则: {emergency_type}"}

def lookup_preflight_check(store: Store, check_category: str = "", drone_category: str = "") -> list[dict]:
    filters = {}
    if check_category:
        filters["check_category"] = check_category
    rows = store.query("PreflightCheckRule", filters)
    if drone_category and isinstance(rows, list):
        rows = [r for r in rows if drone_category in (r.get("required_for_categories") or "")]
    return rows if rows else {"error": "未找到飞行前检查项"}

def lookup_maintenance_rule(store: Store, maintenance_type: str = "") -> list[dict]:
    filters = {}
    if maintenance_type:
        filters["maintenance_type"] = maintenance_type
    rows = store.query("DroneMaintenanceRule", filters)
    return rows if rows else {"error": f"未找到维护规则: {maintenance_type}"}

def lookup_payload_type(store: Store, payload_type: str = "", scenario: str = "") -> list[dict]:
    filters = {}
    if payload_type:
        filters["payload_type"] = payload_type
    rows = store.query("PayloadTypeRule", filters)
    if scenario and isinstance(rows, list):
        rows = [r for r in rows if scenario in (r.get("applicable_scenarios") or "")]
    return rows if rows else {"error": f"未找到载荷类型: {payload_type} {scenario}"}

def lookup_s3_regulation(store: Store, article_number: str = "", keyword: str = "") -> list[dict]:
    filters = {}
    if article_number:
        filters["article_number"] = article_number
    rows = store.query("S3Regulation", filters)
    if keyword and isinstance(rows, list):
        rows = [r for r in rows if keyword in (r.get("keywords") or "") or keyword in (r.get("content") or "")]
    elif keyword:
        all_rows = store.query("S3Regulation")
        rows = [r for r in all_rows if keyword in (r.get("keywords") or "") or keyword in (r.get("content") or "")]
    return rows if rows else {"error": f"未找到S3条文: {article_number} {keyword}"}

def lookup_s4_regulation(store: Store, section_number: str = "", keyword: str = "") -> list[dict]:
    filters = {}
    if section_number:
        filters["section_number"] = section_number
    rows = store.query("S4Regulation", filters)
    if keyword and isinstance(rows, list):
        rows = [r for r in rows if keyword in (r.get("keywords") or "") or keyword in (r.get("content") or "")]
    elif keyword:
        all_rows = store.query("S4Regulation")
        rows = [r for r in all_rows if keyword in (r.get("keywords") or "") or keyword in (r.get("content") or "")]
    return rows if rows else {"error": f"未找到S4条文: {section_number} {keyword}"}
