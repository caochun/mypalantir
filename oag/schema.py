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
    description: str = ""
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
    depends_on: list[str] = []
    hint: str = ""
    params: dict[str, FunctionParam] = {}


class Ontology(BaseModel):
    name: str
    description: str = ""
    objects: dict[str, ObjectTypeDef] = {}
    links: dict[str, LinkDef] = {}
    functions: dict[str, FunctionDef] = {}

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
