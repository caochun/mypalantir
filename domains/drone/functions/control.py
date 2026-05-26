"""set_traffic_control: 对受损设施设置交通管制措施。"""
from __future__ import annotations

from oag.store import Store

from ._helpers import get_facility_info, next_id

# 管制类型默认参数
_CONTROL_DEFAULTS = {
    "半幅通行":  {"speed_limit_kmh": 40, "weight_limit_t": 30},
    "单车道":    {"speed_limit_kmh": 30, "weight_limit_t": 20},
    "限速限载":  {"speed_limit_kmh": 20, "weight_limit_t": 15},
    "分时控制":  {"speed_limit_kmh": 30, "weight_limit_t": 20},
    "封闭":      {"speed_limit_kmh": 0,  "weight_limit_t": 0},
}


def set_traffic_control(store: Store, event_id: str = "",
                        facility_id: str = "",
                        control_type: str = "") -> dict:
    if not event_id or not facility_id or not control_type:
        return {"error": "需要参数: event_id, facility_id, control_type"}

    # 尝试查找设施信息
    facility_name = facility_id
    for ftype in ("路段", "桥梁", "隧道"):
        info = get_facility_info(ftype, facility_id)
        if info and "error" not in info:
            facility_name = info.get("name") or info.get("road_name", facility_id)
            break

    defaults = _CONTROL_DEFAULTS.get(control_type, {"speed_limit_kmh": 0, "weight_limit_t": 0})
    control_id = next_id("CTL")

    message = f"对 {facility_name} 实施{control_type}管制"
    if defaults["speed_limit_kmh"] > 0:
        message += f"，限速{defaults['speed_limit_kmh']}km/h"
    if defaults["weight_limit_t"] > 0:
        message += f"，限重{defaults['weight_limit_t']}t"

    store.execute_write(
        "INSERT INTO traffic_control "
        "(control_id, event_id, facility_id, facility_name, control_type, "
        "speed_limit_kmh, weight_limit_t, status, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        [control_id, event_id, facility_id, facility_name, control_type,
         defaults["speed_limit_kmh"], defaults["weight_limit_t"], message],
    )

    return {
        "control_id": control_id,
        "event_id": event_id,
        "facility_id": facility_id,
        "facility_name": facility_name,
        "control_type": control_type,
        "speed_limit_kmh": defaults["speed_limit_kmh"],
        "weight_limit_t": defaults["weight_limit_t"],
        "status": "active",
        "message": message,
    }
