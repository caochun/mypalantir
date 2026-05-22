from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .document import chunk_markdown
from .llm import DistillerLLM
from .prompts import FUNCTION_DISCOVERY_PROMPT

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 30000


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
    doc_content = _collect_doc_content(docs_dir)

    prompt = FUNCTION_DISCOVERY_PROMPT.format(
        current_schema=schema_str,
        current_links=links_str,
        doc_content=doc_content,
    )

    log.info("Function discovery prompt: %d chars", len(prompt))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

    functions = result.get("functions", [])
    log.info("Discovered %d functions", len(functions))

    return {"functions": functions}


def _links_to_str(links: list[dict]) -> str:
    if not links:
        return "(无关系定义)"
    lines = []
    for link in links:
        lines.append(f"- {link.get('name', '?')}: {link.get('source', '?')}.{link.get('source_key', '?')} -> {link.get('target', '?')}.{link.get('target_key', '?')} ({link.get('description', '')})")
    return "\n".join(lines)


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


def save_functions(result: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved %d functions to %s", len(result["functions"]), output_path)
