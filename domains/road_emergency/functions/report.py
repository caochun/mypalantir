from __future__ import annotations

from oag.store import Store

from ._helpers import next_id, get_event_detail


def generate_event_report(store: Store, event_id: str = "",
                          report_type: str = "首报") -> dict:
    if not event_id:
        return {"error": "需要 event_id"}

    evt = get_event_detail(store, event_id)
    if not evt:
        return {"error": f"未找到事件: {event_id}"}

    data_sources = []

    if report_type == "首报":
        recon_data = store.query("ReconData", {"event_id": event_id})
        if recon_data:
            findings = recon_data[0].get("key_findings", "")
            indicators = recon_data[0].get("damage_indicators", "")
            data_sources.append("ReconData(无人机侦测)")
        else:
            findings = evt.get("location_desc", "")
            indicators = ""

        evt_type_label = "自然灾害" if evt.get("event_type") == "DisasterEvent" else "交通事故"
        evt_sub_type = evt.get("disaster_type", "") or evt.get("accident_type", "")
        event_summary = (
            f"事件编号{event_id}，{evt_type_label}"
            f"({evt_sub_type})，"
            f"发生时间{evt.get('event_time','')}，"
            f"位置: {evt.get('location_desc','')}"
        )
        damage_scope = findings if findings else "待侦测确认"
        trend = f"基于无人机侦测数据: {indicators}" if indicators else "待进一步侦测"
        measures = "已启动应急响应，已派遣无人机侦测" if recon_data else "已启动应急响应"
        next_plan = "开展设施现场检查(inspect_facility)获取详细损伤评估"

    elif report_type == "续报":
        data_sources.append("FacilityInspection(设施检查)")
        inspections = store.query("FacilityInspection", {"event_id": event_id})
        plans = store.query("ClearancePlan", {"event_id": event_id})

        damage_details = []
        for insp in inspections:
            damage_details.append(
                f"{insp.get('facility_name','')}: "
                f"{insp.get('overall_damage_grade','')}级-"
                f"{insp.get('access_recommendation','')}"
            )

        event_summary = (
            f"事件{event_id}续报，已完成{len(inspections)}个设施检查"
        )
        damage_scope = "; ".join(damage_details) if damage_details else "检查进行中"
        trend = f"已生成{len(plans)}个抢通方案" if plans else "方案制定中"
        measures = f"已完成设施检查{len(inspections)}个，抢通方案{len(plans)}个"
        next_plan = "实施抢通方案，开展资源调度"
        if plans:
            data_sources.append("ClearancePlan(抢通方案)")

    else:  # 终报
        data_sources.append("TrafficEvaluation(通行评估)")
        evals = store.query("TrafficEvaluation", {"event_id": event_id})
        controls = store.query("TrafficControl", {"event_id": event_id})

        event_summary = f"事件{event_id}终报"
        damage_scope = "详见续报"
        opened = sum(1 for e in evals if e.get("eval_result") == "开放应急通行")
        trend = f"已开放应急通行{opened}处" if evals else "评估进行中"
        measures = f"通行评估{len(evals)}个，交通管制{len(controls)}个"
        next_plan = "转入恢复重建阶段"

    report_id = next_id("RPT")
    store.execute_write(
        "INSERT INTO event_report (report_id, event_id, report_type, event_summary, "
        "damage_scope, casualty_info, trend_analysis, measures_taken, next_plan, "
        "data_sources, report_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [report_id, event_id, report_type, event_summary, damage_scope,
         "暂无人员伤亡报告", trend, measures, next_plan,
         ",".join(data_sources), "now"]
    )

    return {
        "report_id": report_id,
        "event_id": event_id,
        "report_type": report_type,
        "event_summary": event_summary,
        "damage_scope": damage_scope,
        "trend_analysis": trend,
        "measures_taken": measures,
        "next_plan": next_plan,
        "data_sources": data_sources,
    }
