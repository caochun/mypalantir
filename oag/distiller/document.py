from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .llm import DistillerLLM
from .prompts import DOC_SUMMARY_PROMPT

log = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    doc: str
    section: str
    content: str
    level: int = 1

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass
class DocInfo:
    file: str
    summary: str = ""
    chunk_count: int = 0


@dataclass
class DocumentIndex:
    documents: list[DocInfo] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "documents": [
                {"file": d.file, "summary": d.summary, "chunks": d.chunk_count}
                for d in self.documents
            ],
            "chunks": [
                {"doc": c.doc, "section": c.section, "level": c.level, "chars": c.char_count}
                for c in self.chunks
            ],
        }

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        log.info("Saved document index to %s", path)

    @classmethod
    def load(cls, path: Path) -> DocumentIndex:
        with open(path) as f:
            data = yaml.safe_load(f)
        idx = cls()
        for d in data.get("documents", []):
            idx.documents.append(DocInfo(file=d["file"], summary=d.get("summary", ""), chunk_count=d.get("chunks", 0)))
        return idx


def chunk_markdown(text: str, filename: str) -> list[Chunk]:
    headings: list[tuple[int, str, int]] = []
    for m in HEADING_RE.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        headings.append((level, title, m.start()))

    if not headings:
        return [Chunk(doc=filename, section="(全文)", content=text.strip(), level=0)]

    chunks = []
    for i, (level, title, start) in enumerate(headings):
        end = headings[i + 1][2] if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()
        if not content:
            continue

        section_path = _build_section_path(headings[:i + 1], level)
        chunks.append(Chunk(doc=filename, section=section_path, content=content, level=level))

    return chunks


def _build_section_path(headings_so_far: list[tuple[int, str, int]], current_level: int) -> str:
    ancestors: list[str] = []
    for lvl, title, _ in headings_so_far[:-1]:
        if lvl < current_level:
            while len(ancestors) >= lvl:
                if ancestors:
                    ancestors.pop()
            ancestors.append(title)
    current_title = headings_so_far[-1][1]
    if ancestors:
        return " > ".join(ancestors + [current_title])
    return current_title


def prepare_documents(docs_dir: Path, llm: DistillerLLM) -> DocumentIndex:
    md_files = sorted(docs_dir.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files found in {docs_dir}")

    log.info("Found %d markdown files in %s", len(md_files), docs_dir)
    index = DocumentIndex()

    for md_file in md_files:
        filename = md_file.name
        text = md_file.read_text(encoding="utf-8")
        log.info("Processing %s (%d chars)", filename, len(text))

        chunks = chunk_markdown(text, filename)
        index.chunks.extend(chunks)

        summary = _generate_summary(llm, filename, text)

        index.documents.append(DocInfo(
            file=filename,
            summary=summary,
            chunk_count=len(chunks),
        ))
        log.info("  %s: %d chunks, summary: %s", filename, len(chunks), summary)

    return index


def _generate_summary(llm: DistillerLLM, filename: str, text: str) -> str:
    max_chars = 8000
    truncated = text[:max_chars] if len(text) > max_chars else text
    prompt = DOC_SUMMARY_PROMPT.format(filename=filename, content=truncated)
    return llm.chat([{"role": "user", "content": prompt}], temperature=0.1).strip()
