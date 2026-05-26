from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class PropertyDef(BaseModel):
    type: str = "str"
    required: bool = False
    description: str = ""
    default: Any = None


class ObjectTypeDef(BaseModel):
    kind: str = "entity"  # entity / rule_table / lookup_table / config
    description: str = ""
    summary: str = ""
    properties: dict[str, PropertyDef] = {}


class LinkDef(BaseModel):
    source: str
    target: str
    join: dict[str, str]
    description: str = ""


class FunctionParam(BaseModel):
    type: str = "str"
    description: str = ""
    default: Any = None


class FunctionDef(BaseModel):
    description: str = ""
    summary: str = ""
    group: str = ""
    depends_on: list[str] = []
    hint: str = ""
    params: dict[str, FunctionParam] = {}
    function_type: str = ""  # business / lookup / get
    writes_to: list[str] = []
    involves_objects: list[str] = []


class RuleCondition(BaseModel):
    field: str
    operator: str = "eq"  # eq / ne / gt / gte / lt / lte / in / between / like
    value: Any = None
    result: Any = None


class RuleDef(BaseModel):
    description: str = ""
    rule_type: str = ""  # classification / judgment / qualification / threshold
    applies_to: list[str] = []
    conditions: list[RuleCondition] = []
    result_field: str = ""
    source: str = ""


class WorkflowStep(BaseModel):
    name: str
    function: str = ""
    description: str = ""
    next: str | dict[str, str] = ""


class WorkflowDef(BaseModel):
    description: str = ""
    trigger: str = ""
    steps: list[WorkflowStep] = []
    involves_objects: list[str] = []


class Ontology(BaseModel):
    name: str
    description: str = ""
    objects: dict[str, ObjectTypeDef] = {}
    links: dict[str, LinkDef] = {}
    functions: dict[str, FunctionDef] = {}
    rules: dict[str, RuleDef] = {}
    workflows: dict[str, WorkflowDef] = {}

    @classmethod
    def load(cls, path: str | Path) -> Ontology:
        with open(path) as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)

    def get_id_column(self, object_type: str) -> str | None:
        obj = self.objects.get(object_type)
        if not obj:
            return None
        for name, prop in obj.properties.items():
            if prop.required:
                return name
        return None

    def table_name(self, object_type: str) -> str:
        result = []
        for i, ch in enumerate(object_type):
            if ch.isupper() and i > 0:
                result.append("_")
            result.append(ch.lower())
        return "".join(result)

    def get_entity_objects(self) -> dict[str, ObjectTypeDef]:
        return {k: v for k, v in self.objects.items() if v.kind == "entity"}

    def get_rule_tables(self) -> dict[str, ObjectTypeDef]:
        return {k: v for k, v in self.objects.items() if v.kind == "rule_table"}

    def get_lookup_tables(self) -> dict[str, ObjectTypeDef]:
        return {k: v for k, v in self.objects.items() if v.kind == "lookup_table"}

    def get_rules_for_object(self, object_type: str) -> dict[str, RuleDef]:
        return {
            k: v for k, v in self.rules.items()
            if object_type in v.applies_to
        }

    def get_workflow_by_trigger(self, trigger: str) -> WorkflowDef | None:
        for wf in self.workflows.values():
            if trigger in wf.trigger:
                return wf
        return None
