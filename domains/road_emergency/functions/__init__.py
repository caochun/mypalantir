from __future__ import annotations

from oag.registry import FunctionRegistry
from oag.schema import Ontology
from oag.store import Store

from . import interfaces as iface
from .assess import assess_event_level
from .control import set_traffic_control
from .detour import generate_detour
from .dispatch import dispatch_resources
from .evaluate import evaluate_traffic
from .inspect import inspect_facility
from .lookups import (
    lookup_bridge_type,
    lookup_clearance_technique,
    lookup_damage_grade,
    lookup_event_level,
    lookup_response_level,
    lookup_traffic_control,
    lookup_tunnel_importance,
    lookup_tunnel_target,
    # Drone lookup functions
    lookup_drone_class,
    lookup_operator_license_rule,
    lookup_operation_class,
    lookup_airspace_rule,
    lookup_flight_approval_rule,
    lookup_emergency_flight_rule,
    lookup_preflight_check,
    lookup_maintenance_rule,
    lookup_payload_type,
    lookup_s3_regulation,
    lookup_s4_regulation,
)
from .plan import generate_clearance_plans
from .score import score_plans
from .recon import plan_recon_mission, dispatch_drone, collect_recon_data
from .compliance import check_compliance, request_flight_approval, check_airspace_conflict
from .patrol import schedule_patrol
from .maintenance import log_maintenance
from .warning import trigger_defense_response, intensify_patrol
from .report import generate_event_report
from .airspace_coord import coordinate_airspace

# 只装载业务规则表 + 事件样例。公路基础设施走 mock 接口，不入库
FIELD_MAPPINGS: dict[str, dict[str, str]] = {}

DATA_FILES = {
    "DamageGradeStandard": "damage_grade_standard.json",
    "EventLevelStandard": "event_level_standard.json",
    "ClearanceTechniqueRule": "clearance_technique_rule.json",
    "TrafficControlRule": "traffic_control_rule.json",
    "TunnelImportanceLevel": "tunnel_importance_level.json",
    "TunnelDifficultyMatrix": "tunnel_difficulty_matrix.json",
    "TunnelTargetMatrix": "tunnel_target_matrix.json",
    "BridgeTypeSelection": "bridge_type_selection.json",
    "ResponseLevelRule": "response_level_rule.json",
    "DisasterEvent": "disaster_event.json",
    "AccidentEvent": "accident_event.json",
    # Drone rule data
    "DroneClassRule": "drone_class_rule.json",
    "OperatorLicenseRule": "operator_license_rule.json",
    "OperationClassRule": "operation_class_rule.json",
    "AirspaceRule": "airspace_rule.json",
    "FlightApprovalRule": "flight_approval_rule.json",
    "EmergencyFlightRule": "emergency_flight_rule.json",
    "PreflightCheckRule": "preflight_check_rule.json",
    "DroneMaintenanceRule": "drone_maintenance_rule.json",
    "PayloadTypeRule": "payload_type_rule.json",
    "S3Regulation": "s3_regulation.json",
    "S4Regulation": "s4_regulation.json",
    "DefenseResponseLevelRule": "defense_response_level_rule.json",
    "WeatherWarning": "weather_warning.json",
    # 实体数据
    "RoadSegment": "road_segment.json",
    "Bridge": "bridge.json",
    "Tunnel": "tunnel.json",
    "EmergencyDepot": "emergency_depot.json",
    "RescueTeam": "rescue_team.json",
    "EquipmentStock": "equipment_stock.json",
    "MaterialStock": "material_stock.json",
    "Drone": "drone.json",
    "DroneOperator": "drone_operator.json",
    "DroneBase": "drone_base.json",
    "AirspaceZone": "airspace_zone.json",
}


def register(registry: FunctionRegistry, store: Store, ontology: Ontology):
    iface.bind_store(store)
    # 接口包装函数(mock)
    interface_fns = [
        ("get_event",                   lambda event_id="": iface.get_event(event_id)),
        ("get_road_segment",            lambda segment_id="": iface.get_road_segment(segment_id)),
        ("get_bridge_status",           lambda bridge_id="": iface.get_bridge_status(bridge_id)),
        ("get_tunnel_status",           lambda tunnel_id="": iface.get_tunnel_status(tunnel_id)),
        ("get_affected_facilities",     iface.get_affected_facilities),
        ("get_depots_in_range",         iface.get_depots_in_range),
        ("get_rescue_teams_in_range",   iface.get_rescue_teams_in_range),
        ("get_equipment_by_depot",      iface.get_equipment_by_depot),
        ("get_material_by_depot",       iface.get_material_by_depot),
        # mock-only 列表函数（生产对接真接口后移除）
        ("list_all_road_segment",       iface.list_all_road_segment),
        ("list_all_bridge",             iface.list_all_bridge),
        ("list_all_tunnel",             iface.list_all_tunnel),
        ("list_all_emergency_depot",    iface.list_all_emergency_depot),
        ("list_all_rescue_team",        iface.list_all_rescue_team),
        ("list_all_equipment_stock",    iface.list_all_equipment_stock),
        ("list_all_material_stock",     iface.list_all_material_stock),
        # Drone interface functions
        ("get_drone",                   lambda drone_id="": iface.get_drone(drone_id)),
        ("get_drone_operator",          lambda operator_id="": iface.get_drone_operator(operator_id)),
        ("get_drone_base",              lambda base_id="": iface.get_drone_base(base_id)),
        ("get_airspace_zone",           lambda zone_id="": iface.get_airspace_zone(zone_id)),
        ("get_drones_in_range",         iface.get_drones_in_range),
        ("get_operators_available",     iface.get_operators_available),
        # Drone UI-only list functions
        ("list_all_drone",              iface.list_all_drone),
        ("list_all_drone_operator",     iface.list_all_drone_operator),
        ("list_all_drone_base",         iface.list_all_drone_base),
        ("list_all_airspace_zone",      iface.list_all_airspace_zone),
        # Weather warning interface functions
        ("get_weather_warning",         iface.get_weather_warning),
        ("list_all_weather_warning",    iface.list_all_weather_warning),
    ]
    for name, fn in interface_fns:
        registry.register(name, fn, ontology.functions.get(name))

    # 业务规则查询(走 store)
    lookup_fns = [
        ("lookup_damage_grade",         lookup_damage_grade),
        ("lookup_event_level",          lookup_event_level),
        ("lookup_clearance_technique",  lookup_clearance_technique),
        ("lookup_traffic_control",      lookup_traffic_control),
        ("lookup_tunnel_importance",    lookup_tunnel_importance),
        ("lookup_tunnel_target",        lookup_tunnel_target),
        ("lookup_bridge_type",          lookup_bridge_type),
        ("lookup_response_level",       lookup_response_level),
        # Drone lookup functions
        ("lookup_drone_class",          lookup_drone_class),
        ("lookup_operator_license_rule", lookup_operator_license_rule),
        ("lookup_operation_class",      lookup_operation_class),
        ("lookup_airspace_rule",        lookup_airspace_rule),
        ("lookup_flight_approval_rule", lookup_flight_approval_rule),
        ("lookup_emergency_flight_rule", lookup_emergency_flight_rule),
        ("lookup_preflight_check",      lookup_preflight_check),
        ("lookup_maintenance_rule",     lookup_maintenance_rule),
        ("lookup_payload_type",         lookup_payload_type),
        ("lookup_s3_regulation",        lookup_s3_regulation),
        ("lookup_s4_regulation",        lookup_s4_regulation),
    ]
    for name, fn in lookup_fns:
        registry.register(
            name,
            lambda s=store, f=fn, **kw: f(s, **kw),
            ontology.functions.get(name),
        )

    # 业务编排函数(注入 store)
    business_fns = [
        ("inspect_facility",            inspect_facility),
        ("assess_event_level",          assess_event_level),
        ("generate_clearance_plans",    generate_clearance_plans),
        ("score_plans",                 score_plans),
        ("dispatch_resources",          dispatch_resources),
        ("set_traffic_control",         set_traffic_control),
        ("evaluate_traffic",            evaluate_traffic),
        ("generate_detour",             generate_detour),
        # Drone business functions
        ("plan_recon_mission",          plan_recon_mission),
        ("dispatch_drone",              dispatch_drone),
        ("collect_recon_data",          collect_recon_data),
        ("check_compliance",            check_compliance),
        ("request_flight_approval",     request_flight_approval),
        ("check_airspace_conflict",     check_airspace_conflict),
        ("schedule_patrol",             schedule_patrol),
        ("log_maintenance",             log_maintenance),
        # Warning, report, airspace coordination
        ("trigger_defense_response",    trigger_defense_response),
        ("intensify_patrol",            intensify_patrol),
        ("generate_event_report",       generate_event_report),
        ("coordinate_airspace",         coordinate_airspace),
    ]
    for name, fn in business_fns:
        registry.register(
            name,
            lambda s=store, f=fn, **kw: f(s, **kw),
            ontology.functions.get(name),
        )
