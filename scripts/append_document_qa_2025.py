#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from domains.document_qa.functions.index import DocumentIndex, DocumentPaths
from domains.document_qa.functions.storage import (
    connect,
    delete_document,
    init_schema,
    insert_parsed_document,
    refresh_term_statistics,
)


DEFAULT_SRC = ROOT / "kunshan/documents_2025_md_clean"
DEFAULT_INDEX = ROOT / "domains/document_qa/.document_qa/document_index.sqlite"
EXPECTED_PREFIX = "documents_2025_md_clean/"
OLD_PREFIX = "documents_mineru_md_clean/"


def backup_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)


def make_backups(index_path: Path) -> dict[str, str]:
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup_dir = index_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backups: dict[str, str] = {}
    sqlite_backup = backup_dir / f"{index_path.name}.bak.{stamp}"
    backup_sqlite(index_path, sqlite_backup)
    backups["sqlite"] = str(sqlite_backup)

    for path in [
        index_path.parent / "chunk_embeddings.faiss",
        index_path.parent / "chunk_embeddings.faiss.json",
    ]:
        if path.exists():
            target = backup_dir / f"{path.name}.bak.{stamp}"
            shutil.copy2(path, target)
            backups[path.name] = str(target)
    return backups


def existing_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "documents": conn.execute("select count(*) from documents").fetchone()[0],
        "chunks": conn.execute("select count(*) from chunks").fetchone()[0],
        "old_prefix_documents": conn.execute(
            "select count(*) from documents where path like ?",
            (OLD_PREFIX + "%",),
        ).fetchone()[0],
        "new_prefix_documents": conn.execute(
            "select count(*) from documents where path like ?",
            (EXPECTED_PREFIX + "%",),
        ).fetchone()[0],
    }


def plan_jobs(index: DocumentIndex, conn: sqlite3.Connection, src_root: Path) -> tuple[list[tuple[Path, str]], int]:
    existing = {
        row["path"]: float(row["file_mtime"] or 0.0)
        for row in conn.execute(
            "select path, file_mtime from documents where path like ?",
            (EXPECTED_PREFIX + "%",),
        ).fetchall()
    }
    jobs: list[tuple[Path, str]] = []
    unchanged = 0
    for path in sorted(src_root.rglob("*.md")):
        logical_path = index.paths.document_path_id(path)
        if not logical_path.startswith(EXPECTED_PREFIX):
            raise RuntimeError(f"refusing unexpected logical path: {logical_path}")
        old_mtime = existing.get(logical_path)
        if old_mtime is not None and abs(old_mtime - path.stat().st_mtime) <= 1e-6:
            unchanged += 1
            continue
        jobs.append((path, "added" if old_mtime is None else "updated"))
    return jobs, unchanged


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["action", "logical_path", "document_id", "chunks", "message"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append-only ingestion for Kunshan 2025 clean markdown into document_qa."
    )
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--report", type=Path, default=ROOT / "kunshan/documents_2025_md/logs/2025_document_qa_append_report.csv")
    parser.add_argument("--progress-every", type=int, default=500)
    args = parser.parse_args()

    src_root = args.src.resolve()
    index_path = args.index.resolve()
    if src_root.name != "documents_2025_md_clean":
        raise SystemExit(f"refusing source root with unexpected name: {src_root}")
    if not src_root.is_dir():
        raise SystemExit(f"source directory not found: {src_root}")
    if not index_path.exists():
        raise SystemExit(f"index not found: {index_path}")

    paths = DocumentPaths(
        repo_root=ROOT,
        corpus_root=src_root,
        index_path=index_path,
    )
    index = DocumentIndex(paths)

    with connect(index_path) as conn:
        init_schema(conn)
        before = existing_counts(conn)
        old_prefix_docs = before["old_prefix_documents"]
        if old_prefix_docs <= 0:
            raise SystemExit("safety check failed: existing old document prefix count is zero")
        jobs, unchanged = plan_jobs(index, conn, src_root)

    planned_added = sum(1 for _path, action in jobs if action == "added")
    planned_updated = sum(1 for _path, action in jobs if action == "updated")
    print(
        "plan",
        f"src={src_root}",
        f"index={index_path}",
        f"total_md={planned_added + planned_updated + unchanged}",
        f"added={planned_added}",
        f"updated={planned_updated}",
        f"unchanged={unchanged}",
        f"old_prefix_before={before['old_prefix_documents']}",
        f"new_prefix_before={before['new_prefix_documents']}",
        flush=True,
    )
    if args.dry_run:
        return 0

    backups: dict[str, str] = {}
    if not args.no_backup:
        backups = make_backups(index_path)
        print("backups", backups, flush=True)

    rows: list[dict[str, Any]] = []
    added = 0
    updated = 0
    chunks_upserted = 0
    started = time.time()
    with connect(index_path) as conn:
        init_schema(conn)
        for idx, (path, action) in enumerate(jobs, 1):
            doc, chunks = index._parse_document(path)
            logical_path = doc["path"]
            if not logical_path.startswith(EXPECTED_PREFIX):
                raise RuntimeError(f"refusing unexpected parsed path: {logical_path}")
            if action == "updated":
                delete_document(conn, doc["document_id"])
                updated += 1
            else:
                existing_old = conn.execute(
                    "select path from documents where document_id = ?",
                    (doc["document_id"],),
                ).fetchone()
                if existing_old and not existing_old["path"].startswith(EXPECTED_PREFIX):
                    raise RuntimeError(
                        f"refusing to overwrite non-2025 document_id={doc['document_id']} path={existing_old['path']}"
                    )
                added += 1
            insert_parsed_document(conn, doc, chunks)
            chunks_upserted += len(chunks)
            rows.append(
                {
                    "action": action,
                    "logical_path": logical_path,
                    "document_id": doc["document_id"],
                    "chunks": len(chunks),
                    "message": "",
                }
            )
            if args.progress_every > 0 and idx % args.progress_every == 0:
                conn.commit()
                elapsed = time.time() - started
                print(
                    f"progress processed={idx}/{len(jobs)} added={added} updated={updated} "
                    f"chunks={chunks_upserted} elapsed={elapsed:.1f}s",
                    flush=True,
                )
        if jobs:
            print("refresh_term_statistics start", flush=True)
            refresh_term_statistics(conn)
        after = existing_counts(conn)

    write_report(args.report, rows)
    print(
        "done",
        f"added={added}",
        f"updated={updated}",
        f"unchanged={unchanged}",
        f"chunks_upserted={chunks_upserted}",
        f"documents_before={before['documents']}",
        f"documents_after={after['documents']}",
        f"chunks_before={before['chunks']}",
        f"chunks_after={after['chunks']}",
        f"old_prefix_after={after['old_prefix_documents']}",
        f"new_prefix_after={after['new_prefix_documents']}",
        f"report={args.report}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
