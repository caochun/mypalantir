from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .document import DocumentIndex, chunk_markdown
from .llm import DistillerLLM
from .prompts import ATTRIBUTE_ENRICHMENT_PROMPT, SCHEMA_CONSOLIDATION_PROMPT

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 24000


def enrich_attributes(
    concepts_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
) -> dict:
    with open(concepts_path) as f:
        concepts = yaml.safe_load(f)

    schema = _concepts_to_schema(concepts)
    md_files = sorted(docs_dir.glob("*.md"))

    for i, md_file in enumerate(md_files):
        log.info("Phase 2 [%d/%d]: processing %s", i + 1, len(md_files), md_file.name)
        text = md_file.read_text(encoding="utf-8")
        doc_content = _select_doc_content(text, md_file.name)

        current_schema_str = _schema_to_str(schema)
        prompt = ATTRIBUTE_ENRICHMENT_PROMPT.format(
            current_schema=current_schema_str,
            doc_content=doc_content,
        )

        log.info("  Prompt: %d chars", len(prompt))
        result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

        n_updates = _apply_updates(schema, result)
        log.info("  Applied %d property updates", n_updates)

    log.info("Phase 2: consolidation pass")
    schema = consolidate_schema(schema, llm)

    return schema


def _concepts_to_schema(concepts: dict) -> dict:
    schema = {}
    for obj in concepts.get("objects", []):
        schema[obj["name"]] = {
            "summary": obj.get("summary", ""),
            "source": obj.get("source", ""),
            "properties": {},
        }
    return schema


def _schema_to_str(schema: dict) -> str:
    lines = []
    for name, obj in schema.items():
        props = obj.get("properties", {})
        lines.append(f"### {name}")
        lines.append(f"  summary: {obj.get('summary', '')}")
        if props:
            for pname, pdef in props.items():
                req = " [required]" if pdef.get("required") else ""
                lines.append(f"  - {pname}: {pdef.get('type', 'str')}{req} — {pdef.get('description', '')}")
        else:
            lines.append("  (尚无属性)")
        lines.append("")
    return "\n".join(lines)


def _select_doc_content(text: str, filename: str) -> str:
    chunks = chunk_markdown(text, filename)
    selected: list[str] = []
    total = 0
    for chunk in chunks:
        if total + chunk.char_count > MAX_DOC_CHARS:
            remaining = MAX_DOC_CHARS - total
            if remaining > 200:
                selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content[:remaining]}...\n")
            break
        selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content}\n")
        total += chunk.char_count
    return "\n".join(selected)


def _apply_updates(schema: dict, result: dict) -> int:
    count = 0
    for update in result.get("updates", []):
        obj_name = update.get("object", "")
        if obj_name not in schema:
            log.warning("  Unknown object: %s, skipping", obj_name)
            continue
        props = schema[obj_name].setdefault("properties", {})
        for prop in update.get("new_properties", []):
            pname = prop.get("name", "")
            if not pname or pname in props:
                continue
            props[pname] = {
                "type": prop.get("type", "str"),
                "required": prop.get("required", False),
                "description": prop.get("description", ""),
            }
            count += 1

    for new_obj in result.get("new_objects", []):
        obj_name = new_obj.get("name", "")
        if not obj_name or obj_name in schema:
            continue
        props = {}
        for prop in new_obj.get("properties", []):
            pname = prop.get("name", "")
            if pname:
                props[pname] = {
                    "type": prop.get("type", "str"),
                    "required": prop.get("required", False),
                    "description": prop.get("description", ""),
                }
        schema[obj_name] = {
            "summary": new_obj.get("summary", ""),
            "source": new_obj.get("source", ""),
            "properties": props,
        }
        count += len(props)
        log.info("  New object discovered: %s (%d properties)", obj_name, len(props))

    return count


def consolidate_schema(schema: dict, llm: DistillerLLM) -> dict:
    schema_str = _schema_to_str(schema)
    prompt = SCHEMA_CONSOLIDATION_PROMPT.format(current_schema=schema_str)

    log.info("  Consolidation prompt: %d chars", len(prompt))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

    actions = result.get("actions", [])
    if not actions:
        log.info("  No consolidation needed")
        return schema

    merged_count = 0
    removed_count = 0
    prop_removed_count = 0

    for action in actions:
        action_type = action.get("type", "")

        if action_type == "merge":
            source = action.get("source", "")
            target = action.get("target", "")
            if source in schema and target in schema:
                source_props = schema[source].get("properties", {})
                target_props = schema[target].setdefault("properties", {})
                for pname, pdef in source_props.items():
                    if pname not in target_props:
                        target_props[pname] = pdef
                del schema[source]
                merged_count += 1
                log.info("  Merged %s -> %s (%s)", source, target, action.get("reason", ""))

        elif action_type == "remove":
            obj_name = action.get("object", "")
            if obj_name in schema:
                del schema[obj_name]
                removed_count += 1
                log.info("  Removed %s (%s)", obj_name, action.get("reason", ""))

        elif action_type == "remove_property":
            obj_name = action.get("object", "")
            prop_name = action.get("property", "")
            if obj_name in schema and prop_name in schema[obj_name].get("properties", {}):
                del schema[obj_name]["properties"][prop_name]
                prop_removed_count += 1

    log.info("  Consolidation: merged=%d, removed=%d, props_removed=%d", merged_count, removed_count, prop_removed_count)
    return schema


def save_schema(schema: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(schema, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved enriched schema to %s", output_path)
