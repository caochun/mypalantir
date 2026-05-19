"""业务规则查询：行业→重要等级，(负荷,等级)→电源结构要求。

数据来自 store(importance_level_map / source_requirement 表)，
match_scope 优先级: exact > subtree(前缀匹配) > default
"""
from __future__ import annotations

from oag.store import Store


def lookup_importance_level(store: Store, industry_code: str = "",
                             applicant_type: str = "任意") -> dict:
    if not industry_code:
        return {"error": "需要参数: industry_code"}

    rows = store.query("ImportanceLevelMap")

    # 1. exact match
    for r in rows:
        if r.get("match_scope") == "exact" and r.get("industry_code") == industry_code:
            if r.get("applicant_type") in ("任意", applicant_type):
                return _result(r, "exact")

    # 2. subtree match: 给定编码以表内某条 subtree 编码为前缀
    best_match = None
    best_len = -1
    for r in rows:
        if r.get("match_scope") != "subtree":
            continue
        code = r.get("industry_code") or ""
        if industry_code.startswith(code) and len(code) > best_len:
            if r.get("applicant_type") in ("任意", applicant_type):
                best_match = r
                best_len = len(code)
    if best_match:
        return _result(best_match, "subtree")

    # 3. default fallback
    for r in rows:
        if r.get("match_scope") == "default":
            return _result(r, "default")

    return {"error": f"未匹配到行业 {industry_code} 的重要性等级"}


def _result(row: dict, matched_by: str) -> dict:
    return {
        "industry_code": row.get("industry_code"),
        "industry_name": row.get("industry_name"),
        "importance_level": row.get("importance_level"),
        "industry_category": row.get("industry_category"),
        "standard_ref": row.get("standard_ref"),
        "matched_by": matched_by,
    }


def lookup_source_requirement(store: Store, load_class: str = "",
                               importance_level: str = "") -> dict:
    if not load_class or not importance_level:
        return {"error": "需要参数: load_class, importance_level"}

    rows = store.query(
        "SourceRequirement",
        {"load_class": load_class, "importance_level": importance_level},
        limit=1,
    )
    if rows:
        return rows[0]

    # fallback to DEFAULT
    rows = store.query(
        "SourceRequirement",
        {"load_class": load_class, "importance_level": "DEFAULT"},
        limit=1,
    )
    if rows:
        return {**rows[0], "matched_by": "DEFAULT"}

    return {"error": f"未匹配到({load_class},{importance_level})的电源结构要求"}
