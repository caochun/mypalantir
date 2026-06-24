#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from domains.document_qa.functions.embeddings import embedding_text, pack_vector
from domains.document_qa.functions.index import DocumentIndex, resolve_paths
from domains.document_qa.functions.storage import connect, init_schema
from domains.document_qa.functions.text_processing import stable_id


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build missing document_qa embeddings with progress logs.")
    parser.add_argument("--domain-dir", type=Path, default=ROOT / "domains/document_qa")
    parser.add_argument("--prefix", default="documents_2025_md_clean/%")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--commit-every-batches", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    index = DocumentIndex(resolve_paths(args.domain_dir))
    config = index.embedding_config
    if not config.enabled:
        raise SystemExit("DOCUMENT_QA_EMBEDDINGS is not enabled")

    with connect(index.paths.index_path) as conn:
        init_schema(conn)
        rows = conn.execute(
            """
            select c.chunk_id, c.heading, c.content, d.title, d.path, d.category, d.agency, d.doc_type
            from chunks c join documents d using (document_id)
            left join chunk_embeddings e on e.chunk_id = c.chunk_id and e.model = ?
            where d.path like ? and e.chunk_id is null
            order by d.path, c.ordinal
            """,
            (config.model, args.prefix),
        ).fetchall()

    if args.limit > 0:
        rows = rows[: args.limit]

    print(
        "plan",
        f"provider={config.provider}",
        f"model={config.model}",
        f"batch_size={config.batch_size}",
        f"max_chars={config.max_chars}",
        f"missing_chunks={len(rows)}",
        f"prefix={args.prefix}",
        f"index={index.paths.index_path}",
        flush=True,
    )
    if args.dry_run or not rows:
        return 0

    embedded = 0
    dimensions = 0
    started = time.time()
    with connect(index.paths.index_path) as conn:
        init_schema(conn)
        for batch_index, start in enumerate(range(0, len(rows), config.batch_size), 1):
            batch = rows[start : start + config.batch_size]
            texts = [embedding_text(dict(row), config.max_chars) for row in batch]
            vectors = index._embed_texts(texts)
            for row, text, vector in zip(batch, texts, vectors, strict=True):
                dimensions = len(vector)
                conn.execute(
                    """
                    insert or replace into chunk_embeddings
                    (chunk_id, model, dim, embedding, text_hash)
                    values (?, ?, ?, ?, ?)
                    """,
                    (row["chunk_id"], config.model, dimensions, pack_vector(vector), stable_id(text)),
                )
                embedded += 1
            if args.commit_every_batches > 0 and batch_index % args.commit_every_batches == 0:
                conn.commit()
                elapsed = time.time() - started
                rate = embedded / elapsed if elapsed > 0 else 0.0
                print(
                    f"progress batches={batch_index} embedded={embedded}/{len(rows)} "
                    f"rate={rate:.2f}/s elapsed={elapsed:.1f}s",
                    flush=True,
                )

    elapsed = time.time() - started
    print(
        "embedding_done",
        f"embedded={embedded}",
        f"dimensions={dimensions}",
        f"elapsed={elapsed:.1f}s",
        f"rate={embedded / elapsed if elapsed > 0 else 0.0:.2f}/s",
        flush=True,
    )
    print("faiss_rebuild start", flush=True)
    result = index.rebuild_vector_index(ensure_index=False)
    print(f"faiss_done {result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
