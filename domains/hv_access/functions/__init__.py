from __future__ import annotations

from oag.registry import FunctionRegistry
from oag.schema import Ontology
from oag.store import Store

from . import interfaces as iface
from .compose import compose_plans
from .filter import filter_sources
from .finalize import finalize_plans
from .lookups import lookup_importance_level, lookup_source_requirement
from .new_feeder import new_feeder
from .score import score_plans
from .search import search_sources
from .transfer import transfer_load

# 只装载业务规则表 + 申请样例。电网对象走 mock 接口，不入库
FIELD_MAPPINGS: dict[str, dict[str, str]] = {}

DATA_FILES = {
    "ImportanceLevelMap": "importance_level_map.json",
    "SourceRequirement":  "source_requirement.json",
    "AccessRequest":      "access_request.json",
    "ExpandRequest":      "expand_request.json",
}


def register(registry: FunctionRegistry, store: Store, ontology: Ontology):
    # 接口包装函数(mock)
    interface_fns = [
        ("get_request",                 lambda request_id="": iface.get_request(request_id)),
        ("get_access_points_in_range",  iface.get_access_points_in_range),
        ("get_feeder_status",           iface.get_feeder_status),
        ("get_transformer_status",      iface.get_transformer_status),
        ("get_busbar_info",             iface.get_busbar_info),
        ("get_tie_switches",            iface.get_tie_switches),
        ("get_substations_in_range",    iface.get_substations_in_range),
        # mock-only 列表函数（生产对接真接口后移除）
        ("list_all_substation",         iface.list_all_substation),
        ("list_all_main_transformer",   iface.list_all_main_transformer),
        ("list_all_busbar",             iface.list_all_busbar),
        ("list_all_feeder",             iface.list_all_feeder),
        ("list_all_access_point",       iface.list_all_access_point),
        ("list_all_tie_switch",         iface.list_all_tie_switch),
    ]
    for name, fn in interface_fns:
        registry.register(name, fn, ontology.functions.get(name))

    # 业务规则查询(走 store)
    registry.register(
        "lookup_importance_level",
        lambda s=store, **kw: lookup_importance_level(s, **kw),
        ontology.functions.get("lookup_importance_level"),
    )
    registry.register(
        "lookup_source_requirement",
        lambda s=store, **kw: lookup_source_requirement(s, **kw),
        ontology.functions.get("lookup_source_requirement"),
    )

    # 业务编排函数(注入 store)
    business_fns = [
        ("search_sources",  search_sources),
        ("filter_sources",  filter_sources),
        ("transfer_load",   transfer_load),
        ("new_feeder",      new_feeder),
        ("compose_plans",   compose_plans),
        ("score_plans",     score_plans),
        ("finalize_plans",  finalize_plans),
    ]
    for name, fn in business_fns:
        registry.register(
            name,
            lambda s=store, f=fn, **kw: f(s, **kw),
            ontology.functions.get(name),
        )
