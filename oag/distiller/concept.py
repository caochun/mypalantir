from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .discourse import filter_chunks_by_type, load_discourse
from .document import DocumentIndex
from .few_shot import load_objects_few_shot
from .llm import DistillerLLM
from .prompts import CONCEPT_DISCOVERY_PROMPT
from .workflow import load_workflow, workflow_to_str

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 120000


def discover_concepts(
    index: DocumentIndex,
    llm: DistillerLLM,
    docs_dir: Path,
    domains_dir: Path | None = None,
) -> dict:
    if domains_dir is None:
        domains_dir = docs_dir.parent

    state_dir = docs_dir / ".distill" if (docs_dir / ".distill").exists() else docs_dir

    workflow = load_workflow(state_dir / "phase1_workflow.yaml")
    workflow_str = workflow_to_str(workflow) if workflow else "(无工作流分析，请直接从文档中发现对象)"

    few_shot = load_objects_few_shot(domains_dir)

    doc_summaries = "\n".join(
        f"- **{d.file}**: {d.summary} ({d.chunk_count} 个分块)"
        for d in index.documents
    )

    discourse = load_discourse(state_dir)
    doc_content = _select_content(index, discourse)

    prompt = CONCEPT_DISCOVERY_PROMPT.format(
        workflow_analysis=workflow_str,
        few_shot_objects=few_shot,
        doc_summaries=doc_summaries,
        doc_content=doc_content,
    )

    log.info("Concept discovery prompt: %d chars", len(prompt))

    result = llm.chat_json(
        [{"role": "user", "content": prompt}],
        temperature=0.1,
        reasoning=True,
    )

    objects = result.get("objects", [])
    maybe_attrs = result.get("maybe_attributes", [])
    log.info("Discovered %d objects, %d maybe-attributes", len(objects), len(maybe_attrs))

    return result


def _select_content(index: DocumentIndex, discourse=None) -> str:
    doc_names = list(dict.fromkeys(c.doc for c in index.chunks))
    per_doc_budget = MAX_CONTENT_CHARS // max(len(doc_names), 1)

    selected: list[str] = []
    for doc_name in doc_names:
        doc_chunks = [c for c in index.chunks if c.doc == doc_name]
        if discourse:
            doc_chunks = filter_chunks_by_type(doc_chunks, discourse, ["definition", "enumeration", "rule"])
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


def save_concepts(result: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Saved concepts to %s", output_path)
