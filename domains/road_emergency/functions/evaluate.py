"""evaluate_traffic: 抢通完成后通行评估，决定开放通行或继续抢通。"""
from __future__ import annotations

from oag.store import Store

from ._helpers import next_id


def evaluate_traffic(store: Store, event_id: str = "",
                     plan_id: str = "") -> dict:
    if not event_id or not plan_id:
        return {"error": "需要参数: event_id, plan_id"}

    plans = store.query("ClearancePlan", {"plan_id": plan_id}, limit=1)
    if not plans:
        return {"error": f"方案 {plan_id} 不存在"}
    plan = plans[0]

    total_score = float(plan.get("total_score") or 0)
    facility_id = plan.get("facility_id", "")

    eval_id = next_id("EVL")

    if total_score > 50:
        eval_result = "开放应急通行"
        restrictions = "限速30km/h，限重20t，单车道通行"
        message = (
            f"方案 {plan_id} 综合评分 {total_score}，"
            f"设施 {facility_id} 抢通效果达标，可开放应急通行。"
            f"通行限制: {restrictions}"
        )
    else:
        eval_result = "继续抢通"
        restrictions = "禁止通行"
        message = (
            f"方案 {plan_id} 综合评分 {total_score}，"
            f"设施 {facility_id} 抢通效果未达标，需继续抢通或采用替代方案。"
        )

    store.execute_write(
        "INSERT INTO traffic_evaluation "
        "(eval_id, event_id, plan_id, facility_id, eval_result, "
        "restrictions, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [eval_id, event_id, plan_id, facility_id,
         eval_result, restrictions, message],
    )

    return {
        "eval_id": eval_id,
        "event_id": event_id,
        "plan_id": plan_id,
        "facility_id": facility_id,
        "eval_result": eval_result,
        "restrictions": restrictions,
        "message": message,
    }
