from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .discourse import filter_chunks_by_type, load_discourse
from .document import DocumentIndex
from .few_shot import load_workflow_few_shot
from .llm import DistillerLLM
from .prompts import WORKFLOW_ANALYSIS_PROMPT

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 120000


def analyze_workflow(
    index: DocumentIndex,
    llm: DistillerLLM,
    docs_dir: Path,
    domains_dir: Path | None = None,
) -> dict:
    if domains_dir is None:
        domains_dir = docs_dir.parent

    few_shot = load_workflow_few_shot(domains_dir)

    doc_summaries = "\n".join(
        f"- **{d.file}**: {d.summary} ({d.chunk_count} 个分块)"
        for d in index.documents
    )

    state_dir = docs_dir / ".distill" if (docs_dir / ".distill").exists() else docs_dir
    discourse = load_discourse(state_dir)
    doc_content = _select_content(index, discourse)

    prompt = WORKFLOW_ANALYSIS_PROMPT.format(
        few_shot_workflow=few_shot,
        doc_summaries=doc_summaries,
        doc_content=doc_content,
    )

    log.info("Workflow analysis prompt: %d chars", len(prompt))

    result = llm.chat_json(
        [{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    workflows = result.get("workflows", [])
    rule_tables = result.get("rule_tables", [])
    entities = result.get("entities", [])
    log.info(
        "Workflow analysis: %d workflows, %d rule tables, %d entities",
        len(workflows), len(rule_tables), len(entities),
    )

    return result


def _select_content(index: DocumentIndex, discourse=None) -> str:
    doc_names = list(dict.fromkeys(c.doc for c in index.chunks))
    per_doc_budget = MAX_CONTENT_CHARS // max(len(doc_names), 1)

    selected: list[str] = []
    for doc_name in doc_names:
        doc_chunks = [c for c in index.chunks if c.doc == doc_name]
        if discourse:
            doc_chunks = filter_chunks_by_type(
                doc_chunks, discourse, ["procedure", "rule", "definition", "enumeration"]
            )
        doc_total = 0
        for chunk in doc_chunks:
            if doc_total + chunk.char_count > per_doc_budget:
                remaining = per_doc_budget - doc_total
                if remaining > 200:
                    selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content[:remaining]}...\n")
                break
            selected.append(f"### [{chunk.doc}] {chunk.section}\n{chunk.content}\n")
            doc_total += chunk.char_count

    return "\n".join(selected)


def save_workflow(result: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved workflow analysis to %s", output_path)


def load_workflow(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def workflow_to_str(workflow: dict) -> str:
    """Format workflow analysis for inclusion in prompts."""
    lines = []
    lines.append(f"领域范围: {workflow.get('domain_scope', '?')}")
    lines.append("")

    for wf in workflow.get("workflows", []):
        lines.append(f"### 工作流: {wf.get('name', '?')}")
        lines.append(f"触发: {wf.get('trigger', '?')}")
        for step in wf.get("steps", []):
            lines.append(f"  {step.get('name', '?')}")
            if step.get("queries_entities"):
                lines.append(f"    查询实体: {step['queries_entities']}")
            if step.get("consults_rules"):
                lines.append(f"    查规则: {step['consults_rules']}")
            if step.get("produces_record"):
                lines.append(f"    产出记录: {step['produces_record']}")
            if step.get("decision"):
                lines.append(f"    决策: {step['decision']}")
        lines.append("")

    if workflow.get("rule_tables"):
        lines.append("### 识别的规则表")
        for rt in workflow["rule_tables"]:
            dims = rt.get("dimensions", [])
            lines.append(f"- {rt.get('name', '?')}: {' + '.join(dims)} → {rt.get('result', '?')} ({rt.get('source', '')})")
        lines.append("")

    if workflow.get("entities"):
        lines.append("### 识别的实体")
        for ent in workflow["entities"]:
            lines.append(f"- {ent.get('name', '?')}: {ent.get('description', '')}")

    return "\n".join(lines)
