from __future__ import annotations

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def assemble_ontology(state_dir: Path, domain_name: str = "") -> dict:
    schema_path = state_dir / "phase3_schema.yaml"
    links_path = state_dir / "phase3_links.yaml"
    functions_path = state_dir / "phase5_functions.yaml"

    if not domain_name:
        domain_name = state_dir.parent.name

    with open(schema_path) as f:
        schema = yaml.safe_load(f)
    with open(links_path) as f:
        links_data = yaml.safe_load(f)
    with open(functions_path) as f:
        func_data = yaml.safe_load(f)

    ontology = {
        "name": domain_name,
        "description": _generate_description(schema),
        "objects": _build_objects(schema),
        "links": _build_links(links_data.get("links", [])),
        "functions": _build_functions(func_data.get("functions", [])),
    }

    obj_count = len(ontology["objects"])
    link_count = len(ontology["links"])
    func_count = len(ontology["functions"])
    prop_count = sum(len(o.get("properties", {})) for o in ontology["objects"].values())
    log.info("Assembled ontology: %d objects (%d properties), %d links, %d functions",
             obj_count, prop_count, link_count, func_count)

    return ontology


def _generate_description(schema: dict) -> str:
    obj_names = list(schema.keys())[:5]
    return f"领域本体，包含 {len(schema)} 个对象类型（{', '.join(obj_names)} 等）"


def _build_objects(schema: dict) -> dict:
    objects = {}
    for name, obj in schema.items():
        props = {}
        for pname, pdef in obj.get("properties", {}).items():
            props[pname] = {
                "type": pdef.get("type", "str"),
                "description": pdef.get("description", ""),
            }
            if pdef.get("required"):
                props[pname]["required"] = True

        objects[name] = {
            "summary": obj.get("summary", ""),
            "description": obj.get("summary", ""),
            "properties": props,
        }
    return objects


def _build_links(links: list[dict]) -> dict:
    result = {}
    for link in links:
        name = link.get("name", "")
        if not name:
            continue
        result[name] = {
            "source": link.get("source", ""),
            "target": link.get("target", ""),
            "join": {
                "source_key": link.get("source_key", ""),
                "target_key": link.get("target_key", ""),
            },
            "description": link.get("description", ""),
        }
    return result


def _build_functions(functions: list[dict]) -> dict:
    result = {}
    for func in functions:
        name = func.get("name", "")
        if not name:
            continue

        params = {}
        for p in func.get("params", []):
            pname = p.get("name", "")
            if pname:
                param_def = {
                    "type": p.get("type", "str"),
                    "description": p.get("description", ""),
                }
                if p.get("default") is not None:
                    param_def["default"] = p["default"]
                params[pname] = param_def

        result[name] = {
            "summary": func.get("summary", ""),
            "group": func.get("group", ""),
            "description": func.get("description", ""),
            "depends_on": func.get("depends_on", []),
            "hint": func.get("hint", ""),
            "params": params,
        }
    return result


def save_ontology(ontology: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(ontology, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved ontology to %s", output_path)
