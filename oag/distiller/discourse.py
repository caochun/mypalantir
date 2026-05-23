from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .document import Chunk, DocumentIndex, chunk_markdown
from .llm import DistillerLLM
from .prompts import DISCOURSE_CHUNK_PROMPT, DISCOURSE_DOC_PROMPT

log = logging.getLogger(__name__)

DISCOURSE_TYPES = ("definition", "rule", "procedure", "example", "background", "enumeration")
DOC_TYPES = ("regulation", "standard", "procedure", "guideline")

CHUNK_BATCH_SIZE = 30
CHUNK_PREVIEW_CHARS = 150
MIN_CHUNK_CHARS = 50


@dataclass
class ChunkDiscourse:
    doc: str
    section: str
    discourse_type: str
    topic: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class DocDiscourse:
    file: str
    doc_type: str
    core_topics: list[str] = field(default_factory=list)
    chapter_roles: list[dict] = field(default_factory=list)


@dataclass
class DiscourseAnalysis:
    documents: list[DocDiscourse] = field(default_factory=list)
    chunks: list[ChunkDiscourse] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "documents": [
                {"file": d.file, "doc_type": d.doc_type, "core_topics": d.core_topics, "chapter_roles": d.chapter_roles}
                for d in self.documents
            ],
            "chunks": [
                {"doc": c.doc, "section": c.section, "discourse_type": c.discourse_type, "topic": c.topic, "keywords": c.keywords}
                for c in self.chunks
            ],
        }

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        log.info("Saved discourse analysis to %s (%d docs, %d chunks)", path, len(self.documents), len(self.chunks))

    @classmethod
    def load(cls, path: Path) -> DiscourseAnalysis:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        analysis = cls()
        for d in data.get("documents", []):
            analysis.documents.append(DocDiscourse(
                file=d["file"], doc_type=d.get("doc_type", ""),
                core_topics=d.get("core_topics", []), chapter_roles=d.get("chapter_roles", []),
            ))
        for c in data.get("chunks", []):
            analysis.chunks.append(ChunkDiscourse(
                doc=c["doc"], section=c["section"],
                discourse_type=c.get("discourse_type", "background"),
                topic=c.get("topic", ""), keywords=c.get("keywords", []),
            ))
        return analysis


# --- NLP keyword extraction ---

STOPWORDS = set(
    "的 了 是 在 有 和 与 或 等 及 对 为 中 上 下 不 也 就 都 而 被 把 让 向 从 到 以 可 会 能 要 将 已 由 其 这 那 之 所 如 但 则 又 "
    "应当 可以 不得 按照 根据 依照 通过 进行 实施 规定 要求 条件 情况 活动 工作 管理 部门 单位 人员 信息 系统 设备 区域 范围 "
    "第一 第二 第三 第四 第五 第六 第七 第八 第九 第十 一 二 三 四 五 六 七 八 九 十 百 千 万 "
    "本 该 各 每 某 其他 以下 以上 之一 之间".split()
)


def extract_chunk_keywords(chunks: list[Chunk], top_k: int = 5) -> dict[tuple[str, str], list[str]]:
    import jieba
    from sklearn.feature_extraction.text import TfidfVectorizer

    def tokenize(text: str) -> str:
        return " ".join(w for w in jieba.cut(text) if len(w) > 1 and w not in STOPWORDS)

    corpus = [tokenize(c.content) for c in chunks]
    if not corpus:
        return {}

    vectorizer = TfidfVectorizer(max_features=5000)
    tfidf_matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()

    result = {}
    for i, chunk in enumerate(chunks):
        row = tfidf_matrix[i].toarray().flatten()
        top_indices = row.argsort()[-top_k:][::-1]
        keywords = [feature_names[j] for j in top_indices if row[j] > 0]
        result[(chunk.doc, chunk.section)] = keywords
    return result


# --- LLM analysis ---

def _analyze_doc_level(doc_name: str, summary: str, chapter_list: str, llm: DistillerLLM) -> DocDiscourse:
    prompt = DISCOURSE_DOC_PROMPT.format(filename=doc_name, summary=summary, chapter_list=chapter_list)
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)
    return DocDiscourse(
        file=doc_name,
        doc_type=result.get("doc_type", "guideline"),
        core_topics=result.get("core_topics", []),
        chapter_roles=result.get("chapter_roles", []),
    )


def _analyze_chunk_batch(batch: list[tuple[int, Chunk, list[str]]], llm: DistillerLLM) -> list[ChunkDiscourse]:
    items = []
    for idx, chunk, keywords in batch:
        preview = chunk.content[:CHUNK_PREVIEW_CHARS]
        kw_str = ", ".join(keywords) if keywords else "(无)"
        items.append(f"片段 {idx}:\n  来源: [{chunk.doc}] {chunk.section}\n  关键词: {kw_str}\n  内容: {preview}")

    prompt = DISCOURSE_CHUNK_PROMPT.format(chunks_text="\n---\n".join(items), count=len(batch))
    result = llm.chat_json([{"role": "user", "content": prompt}], temperature=0.1)

    results = []
    chunk_results = result.get("chunks", [])
    for item in chunk_results:
        idx = item.get("index", -1)
        match = next(((c, kw) for i, c, kw in batch if i == idx), None)
        if match is None:
            continue
        chunk, keywords = match
        dtype = item.get("discourse_type", "background")
        if dtype not in DISCOURSE_TYPES:
            dtype = "background"
        results.append(ChunkDiscourse(
            doc=chunk.doc, section=chunk.section,
            discourse_type=dtype, topic=item.get("topic", ""),
            keywords=keywords,
        ))
    return results


# --- Main orchestrator ---

def analyze_discourse(index: DocumentIndex, docs_dir: Path, llm: DistillerLLM) -> DiscourseAnalysis:
    analysis = DiscourseAnalysis()

    all_chunks: list[Chunk] = []
    for md_file in sorted(docs_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        all_chunks.extend(chunk_markdown(text, md_file.name))

    log.info("Extracting keywords for %d chunks via TF-IDF", len(all_chunks))
    keywords_map = extract_chunk_keywords(all_chunks)

    # Document-level analysis
    for doc_info in index.documents:
        doc_chunks = [c for c in all_chunks if c.doc == doc_info.file]
        top_sections = list(dict.fromkeys(c.section.split(" > ")[0] for c in doc_chunks if c.level <= 2))
        chapter_list = "\n".join(f"- {s}" for s in top_sections[:30])

        log.info("Doc-level discourse analysis: %s", doc_info.file)
        doc_discourse = _analyze_doc_level(doc_info.file, doc_info.summary, chapter_list, llm)
        analysis.documents.append(doc_discourse)

    # Chunk-level analysis (batched, skip short chunks)
    meaningful_chunks = [(i, c, keywords_map.get((c.doc, c.section), [])) for i, c in enumerate(all_chunks) if c.char_count >= MIN_CHUNK_CHARS]
    log.info("Meaningful chunks for LLM annotation: %d / %d total", len(meaningful_chunks), len(all_chunks))
    for batch_start in range(0, len(meaningful_chunks), CHUNK_BATCH_SIZE):
        batch = meaningful_chunks[batch_start:batch_start + CHUNK_BATCH_SIZE]
        log.info("Chunk-level discourse analysis: batch %d-%d / %d", batch_start, batch_start + len(batch), len(meaningful_chunks))
        chunk_results = _analyze_chunk_batch(batch, llm)
        analysis.chunks.extend(chunk_results)

    # Fill in any chunks that weren't returned by LLM
    annotated_keys = {(c.doc, c.section) for c in analysis.chunks}
    for chunk in all_chunks:
        if (chunk.doc, chunk.section) not in annotated_keys:
            analysis.chunks.append(ChunkDiscourse(
                doc=chunk.doc, section=chunk.section,
                discourse_type="background", topic="",
                keywords=keywords_map.get((chunk.doc, chunk.section), []),
            ))

    return analysis


# --- Utilities for later phases ---

def load_discourse(state_dir: Path) -> DiscourseAnalysis | None:
    path = state_dir / "discourse_analysis.yaml"
    if not path.exists():
        return None
    return DiscourseAnalysis.load(path)


def filter_chunks_by_type(chunks: list[Chunk], discourse: DiscourseAnalysis, preferred_types: list[str]) -> list[Chunk]:
    type_map = {(c.doc, c.section): c.discourse_type for c in discourse.chunks}
    preferred = []
    rest = []
    for chunk in chunks:
        if type_map.get((chunk.doc, chunk.section)) in preferred_types:
            preferred.append(chunk)
        else:
            rest.append(chunk)
    return preferred + rest
