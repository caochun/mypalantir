from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .discourse import filter_chunks_by_type, load_discourse
from .document import DocumentIndex, chunk_markdown
from .few_shot import load_links_few_shot
from .llm import DistillerLLM
from .prompts import RELATIONSHIP_DISCOVERY_PROMPT
from .workflow import load_workflow, workflow_to_str

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 80000


def discover_relationships(
    schema_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
    domains_dir: Path | None = None,
) -> dict:
    if domains_dir is None:
        domains_dir = docs_dir.parent

    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    state_dir = schema_path.parent

    workflow = load_workflow(state_dir / "phase1_workflow.yaml")
    workflow_str = workflow_to_str(workflow) if workflow else "(无工作流分析)"

    few_shot = load_links_few_shot(domains_dir)

    schema_str = _schema_to_str(schema)
    valid_objects = set(schema.keys())

    discourse = load_discourse(state_dir)
    doc_content = _select_content(docs_dir, discourse)

    prompt = RELATIONSHIP_DISCOVERY_PROMPT.format(
        workflow_analysis=workflow_str,
        current_schema=schema_str,
        few_shot_links=few_shot,
        doc_content=doc_content,
    )

    log.info("Phase 4: relationship discovery prompt: %d chars", len(prompt))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1, reasoning=True)

    links = result.get("links", [])
    missing = result.get("missing_properties", [])

    valid_links = []
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        name = link.get("name", "")
        if not name or src not in valid_objects or tgt not in valid_objects:
            log.warning("  Skipping invalid link %s: %s -> %s", name, src, tgt)
            continue
        valid_links.append(link)

    if missing:
        _apply_missing_properties(schema, missing, valid_objects)

    log.info("Phase 4: %d valid links, %d missing properties", len(valid_links), len(missing))

    return {
        "schema": schema,
        "links": valid_links,
        "missing_properties_applied": len(missing),
    }


def _select_content(docs_dir: Path, discourse=None) -> str:
    all_chunks = []
    for md_file in sorted(docs_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        all_chunks.extend(chunk_markdown(text, md_file.name))

    if discourse:
        all_chunks = filter_chunks_by_type(
            all_chunks, discourse, ["procedure", "rule", "definition"]
        )

    selected: list[str] = []
    total = 0
    for chunk in all_chunks:
        if total + chunk.char_count > MAX_DOC_CHARS:
            break
        selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content}\n")
        total += chunk.char_count

    return "\n".join(selected)


def _apply_missing_properties(schema: dict, missing: list[dict], valid_objects: set[str]):
    seen = set()
    for mp in missing:
        obj_name = mp.get("object", "")
        prop_name = mp.get("property", "")
        key = f"{obj_name}.{prop_name}"
        if not obj_name or not prop_name or obj_name not in valid_objects or key in seen:
            continue
        seen.add(key)
        props = schema[obj_name].setdefault("properties", {})
        if prop_name not in props:
            props[prop_name] = {
                "type": mp.get("type", "str"),
                "required": False,
                "description": mp.get("description", ""),
            }
            log.info("  Added missing property %s.%s (for relationship: %s)", obj_name, prop_name, mp.get("reason", ""))


def save_relationships(result: dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    links_path = output_dir / "phase4_links.yaml"
    with open(links_path, "w") as f:
        yaml.dump({"links": result["links"]}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved %d links to %s", len(result["links"]), links_path)

    schema_path = output_dir / "phase4_schema.yaml"
    with open(schema_path, "w") as f:
        yaml.dump(result["schema"], f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved updated schema to %s", schema_path)
