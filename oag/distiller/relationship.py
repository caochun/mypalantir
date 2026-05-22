from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .document import chunk_markdown
from .llm import DistillerLLM
from .prompts import RELATIONSHIP_DISCOVERY_PROMPT

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 20000


def discover_relationships(
    schema_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
) -> dict:
    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    schema_str = _schema_to_str(schema)
    valid_objects = set(schema.keys())
    md_files = sorted(docs_dir.glob("*.md"))

    all_links: dict[str, dict] = {}
    all_missing: list[dict] = []

    for i, md_file in enumerate(md_files):
        log.info("Phase 3 [%d/%d]: discovering relationships from %s", i + 1, len(md_files), md_file.name)
        text = md_file.read_text(encoding="utf-8")
        doc_content = _select_doc_content(text, md_file.name)

        existing_links_str = _links_summary(list(all_links.values())) if all_links else "(尚未发现关系)"

        prompt = RELATIONSHIP_DISCOVERY_PROMPT.format(
            current_schema=schema_str,
            doc_content=f"### 已发现的关系\n{existing_links_str}\n\n### 文档内容\n{doc_content}",
        )

        log.info("  Prompt: %d chars", len(prompt))
        result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

        links = result.get("links", [])
        missing = result.get("missing_properties", [])

        added = 0
        for link in links:
            src = link.get("source", "")
            tgt = link.get("target", "")
            name = link.get("name", "")
            if src not in valid_objects or tgt not in valid_objects or not name:
                continue
            if name not in all_links:
                all_links[name] = link
                added += 1

        all_missing.extend(missing)
        log.info("  Found %d links (%d new), %d missing properties", len(links), added, len(missing))

    if all_missing:
        _apply_missing_properties(schema, all_missing)

    log.info("Total: %d unique links, %d missing properties applied", len(all_links), len(all_missing))

    return {
        "schema": schema,
        "links": list(all_links.values()),
        "missing_properties_applied": len(all_missing),
    }


def _select_doc_content(text: str, filename: str) -> str:
    chunks = chunk_markdown(text, filename)
    selected: list[str] = []
    total = 0
    for chunk in chunks:
        if total + chunk.char_count > MAX_DOC_CHARS:
            break
        selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content}\n")
        total += chunk.char_count
    return "\n".join(selected)


def _links_summary(links: list[dict]) -> str:
    lines = []
    for link in links:
        lines.append(f"- {link.get('name', '?')}: {link.get('source', '?')}.{link.get('source_key', '?')} -> {link.get('target', '?')}.{link.get('target_key', '?')}")
    return "\n".join(lines)


def _apply_missing_properties(schema: dict, missing: list[dict]):
    seen = set()
    for mp in missing:
        obj_name = mp.get("object", "")
        prop_name = mp.get("property", "")
        key = f"{obj_name}.{prop_name}"
        if not obj_name or not prop_name or obj_name not in schema or key in seen:
            continue
        seen.add(key)
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
