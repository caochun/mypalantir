"""电网一张图接口的 mock 实现。

生产环境每个 get_xxx 函数应替换为对真实接口的 HTTP/RPC 调用。
本文件用本地 JSON 模拟，仅用于开发与冒烟测试。
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=None)
def _load(filename: str) -> list[dict]:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> int:
    R = 6371000.0
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lng2 - lng1)
    a = math.sin(dl / 2) ** 2 + math.cos(rl1) * math.cos(rl2) * math.sin(dn / 2) ** 2
    return int(2 * R * math.asin(math.sqrt(a)))


def get_request(request_id: str = "") -> dict:
    """查询接入申请详情（实际由营销系统接口提供，这里直接读 store）"""
    # 这个函数对接 store —— request 是业务对象，已入库
    # 但为了一致性，也走 mock JSON 兜底
    for r in _load("access_request.json"):
        if r.get("request_id") == request_id:
            return r
    return {"error": f"申请 {request_id} 不存在"}


def get_access_points_in_range(lng: float = 0, lat: float = 0,
                                radius_m: int = 0, device_types: str = "") -> list[dict]:
    """范围内电源点。可选按设备类型过滤。返回值附加 distance_m。"""
    lng, lat, radius_m = float(lng), float(lat), int(radius_m)
    type_filter = {t.strip() for t in device_types.split(",") if t.strip()} if device_types else None

    out = []
    for ap in _load("access_point.json"):
        d = _haversine_m(lng, lat, ap["lng"], ap["lat"])
        if d > radius_m:
            continue
        if type_filter and ap.get("device_type") not in type_filter:
            continue
        out.append({**ap, "distance_m": d})
    out.sort(key=lambda x: x["distance_m"])
    return out


def get_feeder_status(feeder_id: str = "") -> dict:
    for f in _load("feeder.json"):
        if f.get("feeder_id") == feeder_id:
            return f
    return {"error": f"馈线 {feeder_id} 不存在"}


def get_transformer_status(transformer_id: str = "") -> dict:
    for t in _load("main_transformer.json"):
        if t.get("transformer_id") == transformer_id:
            return t
    return {"error": f"主变 {transformer_id} 不存在"}


def get_busbar_info(busbar_id: str = "") -> dict:
    for b in _load("busbar.json"):
        if b.get("busbar_id") == busbar_id:
            return b
    return {"error": f"母线 {busbar_id} 不存在"}


def get_tie_switches(scope: str = "", source_id: str = "") -> list[dict]:
    out = []
    for s in _load("tie_switch.json"):
        if scope and s.get("scope") != scope:
            continue
        if source_id and s.get("source_id") != source_id:
            continue
        out.append(s)
    return out


def get_substations_in_range(lng: float = 0, lat: float = 0, radius_m: int = 0) -> list[dict]:
    lng, lat, radius_m = float(lng), float(lat), int(radius_m)
    out = []
    for s in _load("substation.json"):
        d = _haversine_m(lng, lat, s["lng"], s["lat"])
        if d > radius_m:
            continue
        out.append({**s, "distance_m": d})
    out.sort(key=lambda x: x["distance_m"])
    return out


# ---------- 内部辅助：供其它业务函数复用，避免重复加载 ----------

def all_substations() -> list[dict]:
    return _load("substation.json")


def all_transformers() -> list[dict]:
    return _load("main_transformer.json")


def all_busbars() -> list[dict]:
    return _load("busbar.json")


def all_feeders() -> list[dict]:
    return _load("feeder.json")


def all_access_points() -> list[dict]:
    return _load("access_point.json")


def all_tie_switches() -> list[dict]:
    return _load("tie_switch.json")


# ---------- 列表接口（仅 mock 期用；UI 数据面板/LLM 概览可用）
# 注：生产环境真接口不提供"全表扫"，对接时这些函数应替换为 raise 或删除

def list_all_substation() -> list[dict]:
    return all_substations()


def list_all_main_transformer() -> list[dict]:
    return all_transformers()


def list_all_busbar() -> list[dict]:
    return all_busbars()


def list_all_feeder() -> list[dict]:
    return all_feeders()


def list_all_access_point() -> list[dict]:
    return all_access_points()


def list_all_tie_switch() -> list[dict]:
    return all_tie_switches()
