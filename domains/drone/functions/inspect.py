"""inspect_facility: 对受损设施进行现场检查评估，确定损伤等级和通行建议。"""
from __future__ import annotations

from oag.store import Store

from ._helpers import get_event_detail, get_facility_info, next_id


# 灾害类型 → 各子项模拟损伤等级
_ROAD_DAMAGE = {
    "滑坡":   {"路基路面": "III", "路基防护": "II",  "路基支挡": "II"},
    "泥石流": {"路基路面": "III", "路基防护": "II",  "路基支挡": "II"},
    "崩塌":   {"路基路面": "II",  "路基防护": "III", "路基支挡": "II"},
    "地震":   {"路基路面": "III", "路基防护": "III", "路基支挡": "III"},
    "暴雨":   {"路基路面": "II",  "路基防护": "II",  "路基支挡": "I"},
    "洪水":   {"路基路面": "III", "路基防护": "II",  "路基支挡": "I"},
}

_BRIDGE_DAMAGE = {
    "地震":   {"桥涵整体稳定": "III", "桥涵承载力": "III", "桥涵通行能力": "III"},
    "洪水":   {"桥涵整体稳定": "II",  "桥涵承载力": "III", "桥涵通行能力": "II"},
    "暴雨":   {"桥涵整体稳定": "I",   "桥涵承载力": "II",  "桥涵通行能力": "II"},
    "滑坡":   {"桥涵整体稳定": "II",  "桥涵承载力": "II",  "桥涵通行能力": "I"},
    "崩塌":   {"桥涵整体稳定": "III", "桥涵承载力": "II",  "桥涵通行能力": "II"},
}

_TUNNEL_DAMAGE = {
    "地震":   {"隧道洞口边仰坡": "III", "隧道洞门": "III", "隧道衬砌": "III", "隧道路面": "II",  "隧道吊顶预埋件": "II"},
    "泥石流": {"隧道洞口边仰坡": "III", "隧道洞门": "II",  "隧道衬砌": "I",   "隧道路面": "II",  "隧道吊顶预埋件": "I"},
    "暴雨":   {"隧道洞口边仰坡": "II",  "隧道洞门": "I",   "隧道衬砌": "I",   "隧道路面": "II",  "隧道吊顶预埋件": "I"},
    "崩塌":   {"隧道洞口边仰坡": "III", "隧道洞门": "III", "隧道衬砌": "II",  "隧道路面": "I",   "隧道吊顶预埋件": "II"},
    "火灾":   {"隧道洞口边仰坡": "I",   "隧道洞门": "I",   "隧道衬砌": "III", "隧道路面": "III", "隧道吊顶预埋件": "III"},
}

_GRADE_ORDER = {"I": 1, "II": 2, "III": 3}
_GRADE_TO_ACCESS = {"I": "观察通行", "II": "限制通行", "III": "禁止通行"}


def _max_grade(grades: list[str]) -> str:
    best = "I"
    for g in grades:
        if _GRADE_ORDER.get(g, 0) > _GRADE_ORDER.get(best, 0):
            best = g
    return best


def _get_sub_damages(facility_type: str, disaster_type: str) -> dict[str, str]:
    """根据设施类型和灾害类型返回各子项模拟损伤等级。"""
    default_grade = "II"
    if facility_type == "路段":
        table = _ROAD_DAMAGE
        default = {"路基路面": default_grade, "路基防护": "I", "路基支挡": "I"}
    elif facility_type == "桥梁":
        table = _BRIDGE_DAMAGE
        default = {"桥涵整体稳定": default_grade, "桥涵承载力": "I", "桥涵通行能力": "I"}
    elif facility_type == "隧道":
        table = _TUNNEL_DAMAGE
        default = {"隧道洞口边仰坡": default_grade, "隧道洞门": "I", "隧道衬砌": "I",
                    "隧道路面": "I", "隧道吊顶预埋件": "I"}
    else:
        return {}
    return table.get(disaster_type, default)


def inspect_facility(store: Store, event_id: str = "",
                     facility_type: str = "",
                     facility_id: str = "") -> dict:
    """对设施进行检查评估，写入 FacilityInspection。"""
    event = get_event_detail(store, event_id)
    if not event:
        return {"error": f"事件 {event_id} 不存在"}

    info = get_facility_info(facility_type, facility_id)
    if not info or "error" in info:
        return {"error": f"{facility_type} {facility_id} 不存在"}

    disaster_type = event.get("disaster_type", "")
    sub_damages = _get_sub_damages(facility_type, disaster_type)
    if not sub_damages:
        return {"error": f"不支持的设施类型: {facility_type}"}

    overall = _max_grade(list(sub_damages.values()))
    access_rec = _GRADE_TO_ACCESS.get(overall, "观察通行")

    # 构造损伤概况文本
    damage_parts = [f"{k}:{v}" for k, v in sub_damages.items()]
    damage_summary = ", ".join(damage_parts)

    facility_name = info.get("name") or info.get("road_name", facility_id)
    inspection_id = next_id("INS")

    store.execute_write(
        "INSERT INTO facility_inspection "
        "(inspection_id, event_id, facility_type, facility_id, facility_name, "
        "damage_summary, overall_damage_grade, access_recommendation, inspection_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        [inspection_id, event_id, facility_type, facility_id, facility_name,
         damage_summary, overall, access_rec],
    )

    return {
        "inspection_id": inspection_id,
        "event_id": event_id,
        "facility_type": facility_type,
        "facility_id": facility_id,
        "facility_name": facility_name,
        "sub_damages": sub_damages,
        "overall_damage_grade": overall,
        "access_recommendation": access_rec,
    }
