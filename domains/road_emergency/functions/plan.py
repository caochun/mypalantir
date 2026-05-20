"""generate_clearance_plans: 为需要抢通的设施生成候选方案。"""
from __future__ import annotations

from oag.store import Store

from ._helpers import get_event_detail, next_id

# 灾害类型 → 灾损类型的映射(简化)
_DISASTER_TO_DAMAGE = {
    "路段": {
        "滑坡": "滑坡阻塞", "泥石流": "泥石流", "崩塌": "崩塌落石",
        "地震": "沉陷开裂", "暴雨": "水毁", "洪水": "水毁",
        "冰雪": "冰雪", "火灾": "坍塌",
    },
    "桥梁": {
        "地震": "桥涵垮塌", "洪水": "桥涵受损可通车", "暴雨": "桥涵受损可通车",
        "滑坡": "桥涵受损可通车", "崩塌": "桥涵垮塌",
    },
    "隧道": {
        "地震": "衬砌受损", "泥石流": "洞口掩埋", "崩塌": "洞口掩埋",
        "暴雨": "涌水突泥", "火灾": "衬砌受损",
    },
}

# 设施类型 → ClearanceTechniqueRule 的 facility_type 值
_FACILITY_TYPE_MAP = {
    "路段": "路基路面",
    "桥梁": "桥涵",
    "隧道": "隧道",
}


def generate_clearance_plans(store: Store, event_id: str = "") -> dict:
    event = get_event_detail(store, event_id)
    if not event:
        return {"error": f"事件 {event_id} 不存在"}

    inspections = store.query("FacilityInspection", {"event_id": event_id})
    if not inspections:
        return {"error": f"事件 {event_id} 无检查记录"}

    # 筛选需要抢通的设施(损伤等级 II 或 III)
    needs_clearance = [
        i for i in inspections
        if i.get("overall_damage_grade") in ("II", "III")
    ]
    if not needs_clearance:
        return {"event_id": event_id, "message": "无需抢通的设施", "plan_count": 0}

    disaster_type = event.get("disaster_type", "")

    # 清空已有候选
    store.execute_write(
        "DELETE FROM clearance_plan WHERE event_id = ? AND status = 'candidate'",
        [event_id],
    )

    plans_created = 0
    plans_summary: list[dict] = []

    for insp in needs_clearance:
        ftype = insp.get("facility_type", "")
        fid = insp.get("facility_id", "")
        fname = insp.get("facility_name", "")

        # 确定灾损类型
        type_map = _DISASTER_TO_DAMAGE.get(ftype, {})
        damage_type = type_map.get(disaster_type, disaster_type)

        # 查抢通技术规则
        rule_ftype = _FACILITY_TYPE_MAP.get(ftype, ftype)
        techniques = store.query(
            "ClearanceTechniqueRule",
            {"facility_type": rule_ftype, "damage_type": damage_type},
        )
        # 若精确匹配无结果，放宽到只按设施类型查
        if not techniques:
            techniques = store.query(
                "ClearanceTechniqueRule",
                {"facility_type": rule_ftype},
            )

        for tech in techniques:
            plan_id = next_id("PLN")
            duration = tech.get("estimated_duration_hours", 24)
            # 若规则表没有工期字段，模拟一个
            if not duration:
                duration = 24 if insp.get("overall_damage_grade") == "III" else 12

            store.execute_write(
                "INSERT INTO clearance_plan "
                "(plan_id, event_id, plan_level, facility_id, facility_name, "
                "damage_type, technique_name, technique_desc, "
                "estimated_duration_hours, required_equipment, required_material, "
                "status) "
                "VALUES (?, ?, '设施', ?, ?, ?, ?, ?, ?, ?, ?, 'candidate')",
                [plan_id, event_id, fid, fname,
                 damage_type,
                 tech.get("technique_name", ""),
                 tech.get("technique_desc", ""),
                 duration,
                 tech.get("required_equipment", ""),
                 tech.get("required_material", "")],
            )
            plans_created += 1
            plans_summary.append({
                "plan_id": plan_id,
                "facility_id": fid,
                "facility_name": fname,
                "damage_type": damage_type,
                "technique_name": tech.get("technique_name", ""),
            })

    return {
        "event_id": event_id,
        "plan_count": plans_created,
        "plans_summary": plans_summary,
    }
