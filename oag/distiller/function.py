from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .attribute import _schema_to_str
from .discourse import filter_chunks_by_type, load_discourse
from .document import chunk_markdown
from .few_shot import load_functions_few_shot
from .llm import DistillerLLM
from .prompts import FUNCTION_DESIGN_PROMPT
from .workflow import load_workflow, workflow_to_str

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 80000


def design_functions(
    schema_path: Path,
    links_path: Path,
    docs_dir: Path,
    llm: DistillerLLM,
    domains_dir: Path | None = None,
) -> dict:
    if domains_dir is None:
        domains_dir = docs_dir.parent

    with open(schema_path) as f:
        schema = yaml.safe_load(f)
    with open(links_path) as f:
        links_data = yaml.safe_load(f)

    state_dir = schema_path.parent

    workflow = load_workflow(state_dir / "phase1_workflow.yaml")
    workflow_str = workflow_to_str(workflow) if workflow else "(无工作流分析)"

    few_shot = load_functions_few_shot(domains_dir)

    schema_str = _schema_to_str(schema)
    links_str = _links_to_str(links_data.get("links", []))

    discourse = load_discourse(state_dir)
    doc_content = _select_content(docs_dir, discourse)

    prompt = FUNCTION_DESIGN_PROMPT.format(
        workflow_analysis=workflow_str,
        current_schema=schema_str,
        current_links=links_str,
        few_shot_functions=few_shot,
        doc_content=doc_content,
    )

    log.info("Phase 5: function design prompt: %d chars", len(prompt))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

    functions = result.get("functions", [])

    valid_functions = []
    seen_names: set[str] = set()
    for func in functions:
        name = func.get("name", "")
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        valid_functions.append(func)

    biz = sum(1 for f in valid_functions if f.get("function_type") == "business")
    lookup = sum(1 for f in valid_functions if f.get("function_type") == "lookup")
    get = sum(1 for f in valid_functions if f.get("function_type") == "get")
    log.info("Phase 5: %d functions (business=%d, lookup=%d, get=%d)", len(valid_functions), biz, lookup, get)

    return {"functions": valid_functions}


def _links_to_str(links: list[dict]) -> str:
    if not links:
        return "(无关系定义)"
    lines = []
    for link in links:
        lines.append(
            f"- {link.get('name', '?')}: {link.get('source', '?')}.{link.get('source_key', '?')} "
            f"-> {link.get('target', '?')}.{link.get('target_key', '?')} "
            f"({link.get('description', '')})"
        )
    return "\n".join(lines)


def _select_content(docs_dir: Path, discourse=None) -> str:
    all_chunks = []
    for md_file in sorted(docs_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        all_chunks.extend(chunk_markdown(text, md_file.name))

    if discourse:
        all_chunks = filter_chunks_by_type(
            all_chunks, discourse, ["procedure", "rule", "definition", "enumeration"]
        )

    selected: list[str] = []
    total = 0
    for chunk in all_chunks:
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
