from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .document import chunk_markdown
from .llm import DistillerLLM
from .prompts import FUNCTION_DISCOVERY_PROMPT

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 60000


def discover_functions(
    schema_path: Path,
    links_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
) -> dict:
    with open(schema_path) as f:
        schema = yaml.safe_load(f)
    with open(links_path) as f:
        links_data = yaml.safe_load(f)

    schema_str = _schema_to_str(schema)
    links_str = _links_to_str(links_data.get("links", []))
    md_files = sorted(docs_dir.glob("*.md"))

    all_functions: dict[str, dict] = {}

    for i, md_file in enumerate(md_files):
        log.info("Phase 4 [%d/%d]: discovering functions from %s", i + 1, len(md_files), md_file.name)
        text = md_file.read_text(encoding="utf-8")
        doc_content = _select_doc_content(text, md_file.name)

        existing_str = _functions_summary(list(all_functions.values())) if all_functions else "(尚未发现函数)"

        prompt = FUNCTION_DISCOVERY_PROMPT.format(
            current_schema=schema_str,
            current_links=f"### 已发现的函数\n{existing_str}\n\n### 关系\n{links_str}",
            doc_content=doc_content,
        )

        log.info("  Prompt: %d chars", len(prompt))
        result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

        functions = result.get("functions", [])
        added = 0
        for func in functions:
            name = func.get("name", "")
            if name and name not in all_functions:
                all_functions[name] = func
                added += 1

        log.info("  Found %d functions (%d new)", len(functions), added)

    log.info("Total: %d unique functions", len(all_functions))
    return {"functions": list(all_functions.values())}


def _links_to_str(links: list[dict]) -> str:
    if not links:
        return "(无关系定义)"
    lines = []
    for link in links:
        lines.append(f"- {link.get('name', '?')}: {link.get('source', '?')}.{link.get('source_key', '?')} -> {link.get('target', '?')}.{link.get('target_key', '?')} ({link.get('description', '')})")
    return "\n".join(lines)


def _functions_summary(functions: list[dict]) -> str:
    lines = []
    for func in functions:
        deps = func.get("depends_on", [])
        dep_str = f" (depends_on: {deps})" if deps else ""
        lines.append(f"- {func.get('name', '?')}: {func.get('summary', '')}{dep_str}")
    return "\n".join(lines)


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


def save_functions(result: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved %d functions to %s", len(result["functions"]), output_path)
