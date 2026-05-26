"""assess_event_level: 根据检查记录综合评估事件等级，更新 DisasterEvent/AccidentEvent。"""
from __future__ import annotations

from oag.store import Store

from ._helpers import get_event_detail


def assess_event_level(store: Store, event_id: str = "") -> dict:
    event = get_event_detail(store, event_id)
    if not event:
        return {"error": f"事件 {event_id} 不存在"}

    inspections = store.query("FacilityInspection", {"event_id": event_id})
    if not inspections:
        return {"error": f"事件 {event_id} 无检查记录，请先调用 inspect_facility"}

    grade_iii_count = sum(1 for i in inspections if i.get("overall_damage_grade") == "III")
    grade_ii_count = sum(1 for i in inspections if i.get("overall_damage_grade") == "II")
    grade_i_count = sum(1 for i in inspections if i.get("overall_damage_grade") == "I")

    # 评估逻辑（规范 5.2.1）
    # I级: 国家干线阻断24h+ 或 多设施严重损伤
    # II级: 国家干线阻断12h+ 或 省级干线24h+ 或 多设施中等损伤
    # III级: 国家干线6h+ 或 省级12h+ 或 单设施严重损伤
    # IV级: 其他
    if grade_iii_count >= 3 or (grade_iii_count >= 2 and grade_ii_count >= 2):
        event_level = "I"
        response_level = "一级"
    elif grade_iii_count >= 2 or (grade_iii_count >= 1 and grade_ii_count >= 2):
        event_level = "II"
        response_level = "二级"
    elif grade_iii_count == 1 or grade_ii_count >= 2:
        event_level = "III"
        response_level = "三级"
    elif grade_ii_count == 1:
        event_level = "III"
        response_level = "三级"
    else:
        event_level = "IV"
        response_level = "四级"

    table = "disaster_event" if event.get("event_type") == "DisasterEvent" else "accident_event"
    store.execute_write(
        f"UPDATE {table} SET event_level=?, response_level=? WHERE event_id=?",
        [event_level, response_level, event_id],
    )

    return {
        "event_id": event_id,
        "total_inspections": len(inspections),
        "grade_iii_count": grade_iii_count,
        "grade_ii_count": grade_ii_count,
        "grade_i_count": grade_i_count,
        "event_level": event_level,
        "response_level": response_level,
    }
