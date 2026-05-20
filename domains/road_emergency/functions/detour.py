"""generate_detour: 当设施短期内无法抢通时，生成绕行方案。"""
from __future__ import annotations

from oag.store import Store

from . import interfaces as iface
from ._helpers import get_event_detail, next_id


def generate_detour(store: Store, event_id: str = "",
                    facility_id: str = "") -> dict:
    event = get_event_detail(store, event_id)
    if not event:
        return {"error": f"事件 {event_id} 不存在"}

    elng, elat = float(event.get("lng", 0)), float(event.get("lat", 0))
    location_desc = event.get("location_desc", "")

    # 搜索附近路段作为绕行候选
    nearby_segments = []
    for seg in iface.all_road_segments():
        dist = iface._haversine_km(elng, elat, seg["lng"], seg["lat"])
        if 1 < dist <= 50:  # 排除事发路段本身(太近的)，取50km内
            nearby_segments.append({**seg, "distance_km": dist})
    nearby_segments.sort(key=lambda x: x["distance_km"])

    detour_id = next_id("DTR")

    if nearby_segments:
        alt = nearby_segments[0]
        detour_route = alt.get("road_name", "备用路线")
        length_km = round(alt.get("length_km", 20) + alt["distance_km"], 1)
        estimated_delay = int(length_km / 40 * 60)  # 40km/h 换算分钟
        road_condition = f"{alt.get('road_grade', '公路')}，{alt.get('lane_count', 2)}车道"
        start_point = location_desc or f"事件点({elng},{elat})"
        end_point = f"{detour_route} {alt.get('start_stake', '')}"
    else:
        detour_route = "S301(备用省道)"
        length_km = 35.0
        estimated_delay = 50
        road_condition = "二级公路，双车道"
        start_point = location_desc or f"事件点({elng},{elat})"
        end_point = "S301 与主线交汇处"

    message = (
        f"因 {location_desc} 路段受阻，建议绕行 {detour_route}，"
        f"绕行距离约 {length_km}km，预计增加耗时 {estimated_delay} 分钟。"
    )

    store.execute_write(
        "INSERT INTO detour_plan "
        "(detour_id, event_id, detour_route_name, start_point, end_point, "
        "length_km, road_condition, estimated_delay_min, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [detour_id, event_id, detour_route, start_point, end_point,
         length_km, road_condition, estimated_delay, message],
    )

    return {
        "detour_id": detour_id,
        "event_id": event_id,
        "detour_route_name": detour_route,
        "start_point": start_point,
        "end_point": end_point,
        "length_km": length_km,
        "road_condition": road_condition,
        "estimated_delay_min": estimated_delay,
        "message": message,
    }
