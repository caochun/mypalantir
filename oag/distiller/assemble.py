from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .few_shot import load_summary_few_shot
from .llm import DistillerLLM
from .prompts import SUMMARY_OPTIMIZATION_PROMPT

log = logging.getLogger(__name__)


def assemble_ontology(
    state_dir: Path,
    llm: DistillerLLM,
    domain_name: str = "",
    domains_dir: Path | None = None,
) -> dict:
    schema_path = state_dir / "phase4_schema.yaml"
    links_path = state_dir / "phase4_links.yaml"
    functions_path = state_dir / "phase6_functions.yaml"

    if not domain_name:
        domain_name = state_dir.parent.name

    with open(schema_path) as f:
        schema = yaml.safe_load(f)
    with open(links_path) as f:
        links_data = yaml.safe_load(f)
    with open(functions_path) as f:
        func_data = yaml.safe_load(f)

    functions = func_data.get("functions", [])

    log.info("Phase 7: optimizing summaries")
    schema, functions = _optimize_summaries(schema, functions, llm, domains_dir)

    warnings = _quality_check(schema, functions)
    for w in warnings:
        log.warning("  Quality: %s", w)

    ontology = {
        "name": domain_name,
        "description": _generate_description(schema),
        "objects": _build_objects(schema),
        "links": _build_links(links_data.get("links", [])),
        "functions": _build_functions(functions),
    }

    obj_count = len(ontology["objects"])
    link_count = len(ontology["links"])
    func_count = len(ontology["functions"])
    prop_count = sum(len(o.get("properties", {})) for o in ontology["objects"].values())
    log.info("Assembled ontology: %d objects (%d properties), %d links, %d functions",
             obj_count, prop_count, link_count, func_count)

    return ontology


def _optimize_summaries(schema: dict, functions: list[dict], llm: DistillerLLM, domains_dir: Path | None) -> tuple[dict, list[dict]]:
    items_lines = []

    items_lines.append("## 对象")
    for name, obj in schema.items():
        cat = obj.get("category", "")
        items_lines.append(f"- **{name}** [{cat}]: summary=\"{obj.get('summary', '')}\"")

    items_lines.append("\n## 函数")
    for func in functions:
        ft = func.get("function_type", "")
        items_lines.append(f"- **{func.get('name', '')}** [{ft}]: summary=\"{func.get('summary', '')}\"")

    few_shot = ""
    if domains_dir:
        few_shot = load_summary_few_shot(domains_dir)

    prompt = SUMMARY_OPTIMIZATION_PROMPT.format(
        items="\n".join(items_lines),
        few_shot_summaries=few_shot,
    )

    log.info("  Summary optimization prompt: %d chars", len(prompt))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

    optimized = {item["name"]: item for item in result.get("optimized", []) if item.get("name")}

    for name, obj in schema.items():
        if name in optimized:
            opt = optimized[name]
            if opt.get("summary"):
                obj["summary"] = opt["summary"]
            if opt.get("description"):
                obj["description"] = opt["description"]

    for func in functions:
        fname = func.get("name", "")
        if fname in optimized:
            opt = optimized[fname]
            if opt.get("summary"):
                func["summary"] = opt["summary"]
            if opt.get("description"):
                func["description"] = opt["description"]

    log.info("  Optimized %d summaries", len(optimized))
    return schema, functions


def _quality_check(schema: dict, functions: list[dict]) -> list[str]:
    warnings = []

    rule_objects = {name for name, obj in schema.items() if obj.get("category") == "rule"}
    process_objects = {name for name, obj in schema.items() if obj.get("category") == "process"}

    lookup_targets = set()
    writes_targets = set()
    for func in functions:
        if func.get("function_type") == "lookup":
            for obj in func.get("involves_objects", []):
                if obj in rule_objects:
                    lookup_targets.add(obj)
        for wt in func.get("writes_to", []):
            writes_targets.add(wt)

    for name in rule_objects:
        if name not in lookup_targets:
            warnings.append(f"B类对象 {name} 没有对应的 lookup 函数")

    for name in process_objects:
        if name not in writes_targets:
            warnings.append(f"C类对象 {name} 没有被任何函数 writes_to")

    for func in functions:
        if func.get("function_type") == "business" and not func.get("hint"):
            warnings.append(f"业务函数 {func.get('name')} 的 hint 为空")

    return warnings


def _generate_description(schema: dict) -> str:
    categories = {"entity": 0, "rule": 0, "process": 0}
    for obj in schema.values():
        cat = obj.get("category", "entity")
        categories[cat] = categories.get(cat, 0) + 1

    return (
        f"领域本体，包含 {len(schema)} 个对象类型"
        f"（{categories['entity']} 实体、{categories['rule']} 规则、{categories['process']} 过程）"
    )


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
            "description": obj.get("description", obj.get("summary", "")),
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

        func_entry = {
            "summary": func.get("summary", ""),
            "group": func.get("group", ""),
            "description": func.get("description", ""),
            "depends_on": func.get("depends_on", []),
            "hint": func.get("hint", ""),
            "params": params,
        }

        if func.get("writes_to"):
            func_entry["writes_to"] = func["writes_to"]

        result[name] = func_entry
    return result


def save_ontology(ontology: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(ontology, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved ontology to %s", output_path)
