from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .document import chunk_markdown
from .llm import DistillerLLM
from .prompts import RELATIONSHIP_DISCOVERY_PROMPT

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 30000


def discover_relationships(
    schema_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
) -> dict:
    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    schema_str = _schema_to_str(schema)
    doc_content = _collect_doc_content(docs_dir)

    prompt = RELATIONSHIP_DISCOVERY_PROMPT.format(
        current_schema=schema_str,
        doc_content=doc_content,
    )

    log.info("Relationship discovery prompt: %d chars", len(prompt))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

    links = result.get("links", [])
    missing = result.get("missing_properties", [])
    log.info("Discovered %d links, %d missing properties", len(links), len(missing))

    valid_objects = set(schema.keys())
    validated_links = []
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        if src not in valid_objects:
            log.warning("  Skipping link %s: unknown source %s", link.get("name", "?"), src)
            continue
        if tgt not in valid_objects:
            log.warning("  Skipping link %s: unknown target %s", link.get("name", "?"), tgt)
            continue
        validated_links.append(link)

    if missing:
        _apply_missing_properties(schema, missing)

    return {
        "schema": schema,
        "links": validated_links,
        "missing_properties_applied": len(missing),
    }


def _collect_doc_content(docs_dir: Path) -> str:
    md_files = sorted(docs_dir.glob("*.md"))
    per_doc_budget = MAX_CONTENT_CHARS // len(md_files) if md_files else MAX_CONTENT_CHARS

    selected: list[str] = []
    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        chunks = chunk_markdown(text, md_file.name)
        doc_total = 0
        for chunk in chunks:
            if chunk.level <= 2:
                if doc_total + chunk.char_count > per_doc_budget:
                    break
                selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content}\n")
                doc_total += chunk.char_count

    return "\n".join(selected)


def _apply_missing_properties(schema: dict, missing: list[dict]):
    for mp in missing:
        obj_name = mp.get("object", "")
        prop_name = mp.get("property", "")
        if not obj_name or not prop_name or obj_name not in schema:
            continue
        props = schema[obj_name].setdefault("properties", {})
        if prop_name not in props:
            props[prop_name] = {
                "type": mp.get("type", "str"),
                "required": False,
                "description": mp.get("description", ""),
            }
            log.info("  Added missing property %s.%s (for relationship)", obj_name, prop_name)


def save_relationships(result: dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    links_path = output_dir / "phase3_links.yaml"
    with open(links_path, "w") as f:
        yaml.dump({"links": result["links"]}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved %d links to %s", len(result["links"]), links_path)

    schema_path = output_dir / "phase3_schema.yaml"
    with open(schema_path, "w") as f:
        yaml.dump(result["schema"], f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved updated schema to %s", schema_path)
