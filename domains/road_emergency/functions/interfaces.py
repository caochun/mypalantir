"""公路基础设施接口的 mock 实现。

生产环境每个 get_xxx 函数应替换为对真实接口的 HTTP/RPC 调用。
本文件用本地 JSON 模拟，仅用于开发与冒烟测试。
当 Store 实例可用时，优先从 Store 读取（与 mutate 写入一致）。
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oag.store import Store

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_store: Store | None = None


def bind_store(store: Store):
    global _store
    _store = store


def _query_all(object_type: str) -> list[dict]:
    if _store:
        return _store.query(object_type)
    return _load_json(_type_to_file(object_type))


def _type_to_file(object_type: str) -> str:
    from oag.schema import Ontology
    result = []
    for i, ch in enumerate(object_type):
        if ch.isupper() and i > 0:
            result.append("_")
        result.append(ch.lower())
    return "".join(result) + ".json"


@lru_cache(maxsize=None)
def _load_json(filename: str) -> list[dict]:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def _load(filename: str) -> list[dict]:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6371.0
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lng2 - lng1)
    a = math.sin(dl / 2) ** 2 + math.cos(rl1) * math.cos(rl2) * math.sin(dn / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 2)


def get_event(event_id: str = "") -> dict:
    """查询突发事件详情。"""
    for e in _query_all("DisasterEvent"):
        if e.get("event_id") == event_id:
            return {"event_type": "DisasterEvent", **e}
    for e in _query_all("AccidentEvent"):
        if e.get("event_id") == event_id:
            return {"event_type": "AccidentEvent", **e}
    return {"error": f"未找到事件: {event_id}"}


def get_road_segment(segment_id: str = "") -> dict:
    """查询路段信息。"""
    for r in all_road_segments():
        if r.get("segment_id") == segment_id:
            return r
    return {"error": f"路段 {segment_id} 不存在"}


def get_bridge_status(bridge_id: str = "") -> dict:
    """查询桥梁信息。"""
    for b in all_bridges():
        if b.get("bridge_id") == bridge_id:
            return b
    return {"error": f"桥梁 {bridge_id} 不存在"}


def get_tunnel_status(tunnel_id: str = "") -> dict:
    """查询隧道信息。"""
    for t in all_tunnels():
        if t.get("tunnel_id") == tunnel_id:
            return t
    return {"error": f"隧道 {tunnel_id} 不存在"}


def get_affected_facilities(event_id: str = "",
                            radius_km: float = 5) -> dict:
    """根据事件位置，搜索半径内的路段、桥梁、隧道。"""
    radius_km = float(radius_km)
    event = get_event(event_id)
    if "error" in event:
        return event
    elng, elat = float(event["lng"]), float(event["lat"])

    segments = []
    for s in all_road_segments():
        d = _haversine_km(elng, elat, s["lng"], s["lat"])
        if d <= radius_km:
            segments.append({**s, "distance_km": d})

    bridges = []
    for b in all_bridges():
        d = _haversine_km(elng, elat, b["lng"], b["lat"])
        if d <= radius_km:
            bridges.append({**b, "distance_km": d})

    tunnels = []
    for t in all_tunnels():
        d = _haversine_km(elng, elat, t["lng"], t["lat"])
        if d <= radius_km:
            tunnels.append({**t, "distance_km": d})

    segments.sort(key=lambda x: x["distance_km"])
    bridges.sort(key=lambda x: x["distance_km"])
    tunnels.sort(key=lambda x: x["distance_km"])

    return {
        "event_id": event_id,
        "radius_km": radius_km,
        "segments": segments,
        "bridges": bridges,
        "tunnels": tunnels,
    }


def get_depots_in_range(lng: float = 0, lat: float = 0,
                        radius_km: float = 100) -> list[dict]:
    """空间查询：以(lng,lat)为中心搜索储备点。"""
    lng, lat, radius_km = float(lng), float(lat), float(radius_km)
    out = []
    for d in all_depots():
        dist = _haversine_km(lng, lat, d["lng"], d["lat"])
        if dist <= radius_km:
            out.append({**d, "distance_km": dist})
    out.sort(key=lambda x: x["distance_km"])
    return out


def get_rescue_teams_in_range(lng: float = 0, lat: float = 0,
                              radius_km: float = 100) -> list[dict]:
    """空间查询：以(lng,lat)为中心搜索可用应急队伍。"""
    lng, lat, radius_km = float(lng), float(lat), float(radius_km)
    out = []
    for t in all_teams():
        if not t.get("available", 1):
            continue
        dist = _haversine_km(lng, lat, t["lng"], t["lat"])
        if dist <= radius_km:
            out.append({**t, "distance_km": dist})
    out.sort(key=lambda x: x["distance_km"])
    return out


def get_equipment_by_depot(depot_id: str = "",
                           category: str = "") -> list[dict]:
    """查询某储备点的装备库存，可按大类过滤。"""
    out = [e for e in all_equipment() if e.get("depot_id") == depot_id]
    if category:
        out = [e for e in out if e.get("category") == category]
    return out


def get_material_by_depot(depot_id: str = "",
                          disaster_type: str = "") -> list[dict]:
    """查询某储备点的物资库存，可按灾害类型过滤。"""
    out = [m for m in all_material() if m.get("depot_id") == depot_id]
    if disaster_type:
        out = [m for m in out
               if disaster_type in (m.get("applicable_disasters") or "")]
    return out


# ---------- 内部辅助：供其它业务函数复用，避免重复加载 ----------

def all_road_segments() -> list[dict]:
    return _query_all("RoadSegment")


def all_bridges() -> list[dict]:
    return _query_all("Bridge")


def all_tunnels() -> list[dict]:
    return _query_all("Tunnel")


def all_depots() -> list[dict]:
    return _query_all("EmergencyDepot")


def all_teams() -> list[dict]:
    return _query_all("RescueTeam")


def all_equipment() -> list[dict]:
    return _query_all("EquipmentStock")


def all_material() -> list[dict]:
    return _query_all("MaterialStock")


# ---------- 列表接口（仅 mock 期用；UI 数据面板/LLM 概览可用）
# 注：生产环境真接口不提供"全表扫"，对接时这些函数应替换为 raise 或删除

def list_all_road_segment() -> list[dict]:
    return all_road_segments()


def list_all_bridge() -> list[dict]:
    return all_bridges()


def list_all_tunnel() -> list[dict]:
    return all_tunnels()


def list_all_emergency_depot() -> list[dict]:
    return all_depots()


def list_all_rescue_team() -> list[dict]:
    return all_teams()


def list_all_equipment_stock() -> list[dict]:
    return all_equipment()


def list_all_material_stock() -> list[dict]:
    return all_material()


# ===== Drone interface functions =====

def all_drones() -> list[dict]:
    return _query_all("Drone")

def all_drone_operators() -> list[dict]:
    return _query_all("DroneOperator")

def all_drone_bases() -> list[dict]:
    return _query_all("DroneBase")

def all_airspace_zones() -> list[dict]:
    return _query_all("AirspaceZone")

def get_drone(drone_id: str = "") -> dict:
    for d in all_drones():
        if d.get("drone_id") == drone_id:
            return d
    return {"error": f"未找到无人机: {drone_id}"}

def get_drone_operator(operator_id: str = "") -> dict:
    for op in all_drone_operators():
        if op.get("operator_id") == operator_id:
            return op
    return {"error": f"未找到操控员: {operator_id}"}

def get_drone_base(base_id: str = "") -> dict:
    for b in all_drone_bases():
        if b.get("base_id") == base_id:
            return b
    return {"error": f"未找到基地: {base_id}"}

def get_airspace_zone(zone_id: str = "") -> dict:
    for z in all_airspace_zones():
        if z.get("zone_id") == zone_id:
            return z
    return {"error": f"未找到空域: {zone_id}"}

def get_drones_in_range(lng: float = 0, lat: float = 0, radius_km: float = 50) -> list[dict]:
    out = []
    for d in all_drones():
        if d.get("status") != "可用":
            continue
        base = get_drone_base(d.get("base_id", ""))
        if "error" in base:
            continue
        dist = _haversine_km(lng, lat, base["lng"], base["lat"])
        if dist <= radius_km:
            out.append({**d, "base_lng": base["lng"], "base_lat": base["lat"], "distance_km": round(dist, 2)})
    out.sort(key=lambda x: x["distance_km"])
    return out

def get_operators_available(license_type: str = "") -> list[dict]:
    out = []
    for op in all_drone_operators():
        if op.get("available") != 1:
            continue
        if license_type and op.get("license_type") != license_type:
            continue
        out.append(op)
    return out

# UI-only list functions for drones
def list_all_drone() -> list[dict]:
    return all_drones()

def list_all_drone_operator() -> list[dict]:
    return all_drone_operators()

def list_all_drone_base() -> list[dict]:
    return all_drone_bases()

def list_all_airspace_zone() -> list[dict]:
    return all_airspace_zones()


# ===== Weather warning interface =====

def all_weather_warnings() -> list[dict]:
    return _query_all("WeatherWarning")

def get_weather_warning(warning_id: str = "") -> dict:
    if not warning_id:
        active = [w for w in all_weather_warnings() if w.get("status") == "生效中"]
        return active if active else {"message": "当前无生效预警"}
    for w in all_weather_warnings():
        if w.get("warning_id") == warning_id:
            return w
    return {"error": f"未找到预警: {warning_id}"}

def list_all_weather_warning() -> list[dict]:
    return all_weather_warnings()
