from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .document import chunk_markdown
from .llm import DistillerLLM
from .prompts import RULE_EXTRACTION_PROMPT

log = logging.getLogger(__name__)

MAX_DOC_CHARS_PER_FUNCTION = 15000


def extract_rules(
    functions_path: Path,
    schema_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
) -> list[dict]:
    with open(functions_path) as f:
        func_data = yaml.safe_load(f)
    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    functions = func_data.get("functions", [])
    all_chunks = _load_all_chunks(docs_dir)

    enriched = []
    for i, func in enumerate(functions):
        name = func.get("name", "?")
        log.info("Phase 5-6 [%d/%d]: extracting rules for %s", i + 1, len(functions), name)

        func_def_str = yaml.dump(func, allow_unicode=True, default_flow_style=False)
        related_objects = _get_related_objects(func, schema)
        doc_content = _select_relevant_content(func, all_chunks)

        prompt = RULE_EXTRACTION_PROMPT.format(
            function_def=func_def_str,
            related_objects=related_objects,
            doc_content=doc_content,
        )

        log.info("  Prompt: %d chars", len(prompt))
        result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

        func["hint"] = result.get("hint", "")
        if result.get("summary_optimized"):
            func["summary"] = result["summary_optimized"]
        if result.get("description_optimized"):
            func["description"] = result["description_optimized"]

        enriched.append(func)
        log.info("  hint: %d chars", len(func.get("hint", "")))

    return enriched


def _load_all_chunks(docs_dir: Path) -> list:
    all_chunks = []
    for md_file in sorted(docs_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        all_chunks.extend(chunk_markdown(text, md_file.name))
    return all_chunks


def _get_related_objects(func: dict, schema: dict) -> str:
    obj_names = func.get("involves_objects", [])
    lines = []
    for name in obj_names:
        obj = schema.get(name, {})
        lines.append(f"### {name}")
        lines.append(f"  summary: {obj.get('summary', '')}")
        props = obj.get("properties", {})
        for pname, pdef in props.items():
            lines.append(f"  - {pname}: {pdef.get('type', 'str')} — {pdef.get('description', '')}")
        lines.append("")
    return "\n".join(lines) if lines else "(无关联对象)"


def _select_relevant_content(func: dict, all_chunks: list) -> str:
    source = func.get("source", "").lower()
    keywords = [func.get("name", ""), func.get("summary", "")]
    keywords.extend(func.get("involves_objects", []))

    scored_chunks = []
    for chunk in all_chunks:
        score = 0
        chunk_text_lower = chunk.content.lower()
        if source and any(part in chunk.doc.lower() for part in source.split(" > ")[0:1]):
            score += 1
        for kw in keywords:
            if kw and kw.lower() in chunk_text_lower:
                score += 1
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: (-x[0], x[1].level))

    selected: list[str] = []
    total = 0
    for _, chunk in scored_chunks:
        if total + chunk.char_count > MAX_DOC_CHARS_PER_FUNCTION:
            break
        selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content}\n")
        total += chunk.char_count

    return "\n".join(selected) if selected else "(无相关文档内容)"


def save_enriched_functions(functions: list[dict], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump({"functions": functions}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved %d enriched functions to %s", len(functions), output_path)
