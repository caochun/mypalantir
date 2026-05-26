from __future__ import annotations

import json
import operator
from typing import Any, Callable

from .schema import Ontology, RuleCondition, RuleDef
from .store import Store

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


def _coerce(value: Any, target: Any) -> Any:
    if target is None:
        return value
    try:
        return type(target)(value)
    except (TypeError, ValueError):
        return value


def _evaluate_condition(condition: RuleCondition, record: dict) -> bool:
    field_value = record.get(condition.field)
    if field_value is None:
        return False

    op = condition.operator

    if op in OPERATORS:
        return OPERATORS[op](_coerce(field_value, condition.value), condition.value)

    if op == "in":
        if isinstance(condition.value, list):
            return field_value in condition.value
        return False

    if op == "between":
        if isinstance(condition.value, list) and len(condition.value) == 2:
            lo, hi = condition.value
            v = _coerce(field_value, lo)
            return lo <= v <= hi
        return False

    if op == "like":
        if isinstance(field_value, str) and isinstance(condition.value, str):
            pattern = condition.value.lower()
            target = field_value.lower()
            if pattern.startswith("%") and pattern.endswith("%"):
                return pattern[1:-1] in target
            if pattern.startswith("%"):
                return target.endswith(pattern[1:])
            if pattern.endswith("%"):
                return target.startswith(pattern[:-1])
            return pattern in target
        return False

    return operator.eq(field_value, condition.value)


def _compile_rule(rule_def: RuleDef) -> Callable[[dict], Any]:
    conditions = rule_def.conditions

    def apply(record: dict) -> Any:
        for cond in conditions:
            if _evaluate_condition(cond, record):
                return cond.result
        return None

    return apply


class RuleEngine:
    def __init__(self, ontology: Ontology, store: Store):
        self.ontology = ontology
        self.store = store
        self._compiled: dict[str, Callable[[dict], Any]] = {}
        self._compile_all()

    def _compile_all(self):
        for name, rule_def in self.ontology.rules.items():
            self._compiled[name] = _compile_rule(rule_def)

    def apply(self, rule_name: str, object_type: str, object_id: Any) -> dict:
        rule_fn = self._compiled.get(rule_name)
        if not rule_fn:
            return {"error": f"未知规则: {rule_name}"}

        record = self.store.query_by_id(object_type, object_id)
        if not record:
            return {"error": f"未找到对象: {object_type}#{object_id}"}

        result = rule_fn(record)
        rule_def = self.ontology.rules[rule_name]
        return {
            "rule": rule_name,
            "object_type": object_type,
            "object_id": object_id,
            "result": result,
            "result_field": rule_def.result_field,
            "rule_type": rule_def.rule_type,
        }

    def apply_batch(self, rule_name: str, object_type: str,
                    filters: dict | None = None) -> list[dict]:
        rule_fn = self._compiled.get(rule_name)
        if not rule_fn:
            return [{"error": f"未知规则: {rule_name}"}]

        records = self.store.query(object_type, filters)
        rule_def = self.ontology.rules[rule_name]
        id_col = self.ontology.get_id_column(object_type)

        results = []
        for record in records:
            obj_id = record.get(id_col, record.get("_id"))
            result = rule_fn(record)
            results.append({
                "object_id": obj_id,
                "result": result,
                "result_field": rule_def.result_field,
            })
        return results

    def apply_to_record(self, rule_name: str, record: dict) -> Any:
        rule_fn = self._compiled.get(rule_name)
        if not rule_fn:
            return None
        return rule_fn(record)

    def list_rules(self) -> list[tuple[str, RuleDef]]:
        return list(self.ontology.rules.items())

    def get_rules_for_object(self, object_type: str) -> dict[str, RuleDef]:
        return self.ontology.get_rules_for_object(object_type)

    def build_tools(self) -> list[dict]:
        if not self.ontology.rules:
            return []

        rule_names = list(self.ontology.rules.keys())
        applicable_types = set()
        for rule_def in self.ontology.rules.values():
            applicable_types.update(rule_def.applies_to)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "apply_rule",
                    "description": "对指定对象应用业务规则，返回确定性结果（无需LLM推理）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rule_name": {
                                "type": "string",
                                "description": "规则名称",
                                "enum": rule_names,
                            },
                            "object_type": {
                                "type": "string",
                                "description": "对象类型",
                                "enum": sorted(applicable_types),
                            },
                            "object_id": {
                                "type": "string",
                                "description": "对象ID",
                            },
                        },
                        "required": ["rule_name", "object_type", "object_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "apply_rule_batch",
                    "description": "批量应用规则到多个对象",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rule_name": {
                                "type": "string",
                                "enum": rule_names,
                            },
                            "object_type": {
                                "type": "string",
                                "enum": sorted(applicable_types),
                            },
                            "filters": {
                                "type": "object",
                                "description": "过滤条件（同 query）",
                            },
                        },
                        "required": ["rule_name", "object_type"],
                    },
                },
            },
        ]
        return tools

    def execute_tool(self, name: str, args: dict) -> str:
        if name == "apply_rule":
            result = self.apply(
                args["rule_name"], args["object_type"], args["object_id"],
            )
            return json.dumps(result, ensure_ascii=False, default=str)

        if name == "apply_rule_batch":
            results = self.apply_batch(
                args["rule_name"], args["object_type"], args.get("filters"),
            )
            return json.dumps(results, ensure_ascii=False, default=str)

        return json.dumps({"error": f"未知规则工具: {name}"}, ensure_ascii=False)
