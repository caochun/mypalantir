from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

RULE_SUFFIXES = ("Rule", "Standard", "Matrix", "Level", "Selection")
SKIP_OBJECTS = {"DroneSystem", "StandardizedBridge"}


def generate_template_functions(schema_path: Path, existing_functions_path: Path) -> list[dict]:
    with open(schema_path) as f:
        schema = yaml.safe_load(f)
    with open(existing_functions_path) as f:
        existing = yaml.safe_load(f)

    existing_names = {f["name"] for f in existing.get("functions", [])}
    generated = []

    for obj_name, obj in schema.items():
        if obj_name in SKIP_OBJECTS:
            continue

        is_rule = any(obj_name.endswith(s) for s in RULE_SUFFIXES)
        props = obj.get("properties", {})
        summary = obj.get("summary", "")

        if is_rule:
            func = _make_lookup_function(obj_name, summary, props)
        else:
            func = _make_get_function(obj_name, summary, props)

        if func["name"] not in existing_names:
            generated.append(func)

    log.info("Generated %d template functions (lookup + get)", len(generated))
    return generated


def _to_snake(name: str) -> str:
    s = re.sub(r"([A-Z])", r"_\1", name).lstrip("_").lower()
    return s


def _make_lookup_function(obj_name: str, summary: str, props: dict) -> dict:
    snake = _to_snake(obj_name)
    required_props = [p for p, d in props.items() if d.get("required")]
    first_key = required_props[0] if required_props else (list(props.keys())[0] if props else "key")

    params = [{
        "name": first_key,
        "type": props.get(first_key, {}).get("type", "str"),
        "description": props.get(first_key, {}).get("description", f"{obj_name} 的查询键"),
        "default": None,
    }]

    return {
        "name": f"lookup_{snake}",
        "summary": f"查询{summary.split('，')[0]}",
        "group": "规则查询",
        "description": f"根据条件查询 {obj_name} 中的记录",
        "depends_on": [],
        "params": params,
        "involves_objects": [obj_name],
        "source": "自动生成",
    }


def _make_get_function(obj_name: str, summary: str, props: dict) -> dict:
    snake = _to_snake(obj_name)
    id_field = None
    for p, d in props.items():
        if d.get("required"):
            id_field = p
            break
    if not id_field:
        for p in props:
            if p.endswith("_id") or p == "name":
                id_field = p
                break
    if not id_field:
        id_field = f"{snake}_id"

    params = [{
        "name": id_field,
        "type": props.get(id_field, {}).get("type", "str"),
        "description": props.get(id_field, {}).get("description", f"{obj_name} 的唯一标识"),
        "default": None,
    }]

    return {
        "name": f"get_{snake}",
        "summary": f"获取{summary.split('，')[0]}的详细信息",
        "group": "数据获取",
        "description": f"根据标识查询 {obj_name} 的完整记录",
        "depends_on": [],
        "params": params,
        "involves_objects": [obj_name],
        "source": "自动生成",
    }


def save_all_functions(existing_functions: list[dict], template_functions: list[dict], output_path: Path):
    all_funcs = existing_functions + template_functions
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump({"functions": all_funcs}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved %d total functions (%d existing + %d template) to %s",
             len(all_funcs), len(existing_functions), len(template_functions), output_path)
