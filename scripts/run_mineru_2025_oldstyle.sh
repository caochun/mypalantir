#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET_CATEGORIES=("$@")

DOMAIN_ROOT="${DOMAIN_ROOT:-domains/substation}"
RAW_ROOT="${RAW_ROOT:-$DOMAIN_ROOT/raw}"
OUT_ROOT="${OUT_ROOT:-$DOMAIN_ROOT/docs_md}"
BATCH_DOCS="${BATCH_DOCS:-20}"
FORMULA="${FORMULA:-false}"
TABLE="${TABLE:-true}"
DRY_RUN="${DRY_RUN:-false}"
WORK_ROOT="${WORK_ROOT:-$OUT_ROOT/mineru_oldstyle_work}"
BATCH_DIR="$WORK_ROOT/batches"
WORK_DIR="$WORK_ROOT/work"
RAW_OUT="$WORK_ROOT/output"
LOG_DIR="$OUT_ROOT/logs/oldstyle_batches"
RUNNER_LOG="$OUT_ROOT/logs/mineru_oldstyle_runner.log"

mkdir -p "$BATCH_DIR" "$WORK_DIR" "$RAW_OUT" "$LOG_DIR" "$(dirname "$RUNNER_LOG")"
rm -rf "$BATCH_DIR" "$WORK_DIR" "$RAW_OUT"
mkdir -p "$BATCH_DIR" "$WORK_DIR" "$RAW_OUT"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export MINERU_DEVICE_MODE="${MINERU_DEVICE_MODE:-cuda}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="${PYTHONPATH:-.}"

printf '[%s] substation oldstyle start raw_root=%s categories=%s batch_docs=%s table=%s formula=%s dry_run=%s\n' \
  "$(date '+%F %T')" "$RAW_ROOT" "${TARGET_CATEGORIES[*]:-ALL}" "$BATCH_DOCS" "$TABLE" "$FORMULA" "$DRY_RUN" >> "$RUNNER_LOG"

python3 - "$BATCH_DIR" "$BATCH_DOCS" "$RAW_ROOT" "$OUT_ROOT" "$DRY_RUN" "${TARGET_CATEGORIES[@]}" <<'PY'
from __future__ import annotations

import csv
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
batch_docs = int(sys.argv[2])
raw_root = Path(sys.argv[3])
out_root = Path(sys.argv[4])
dry_run = sys.argv[5].lower() == "true"
categories = set(sys.argv[6:])

root = Path.cwd()
status_path = out_root / "status.csv"
manifest_path = out_root / "manifest.csv"
md_root = out_root / "md"

from scripts.run_mineru_substation_pdf import doc_id_for, page_count, write_headers

done: set[str] = set()
if status_path.exists():
    with status_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") in {"ok", "failed_bad_pdf"}:
                done.add(row.get("source_path", ""))

jobs: list[dict[str, str]] = []
sources = sorted(raw_root.rglob("*.pdf"), key=lambda p: str(p.relative_to(raw_root)))
for index, source in enumerate(sources, 1):
    source_rel = source.relative_to(raw_root).as_posix()
    parts = source.relative_to(raw_root).parts
    category = parts[0] if len(parts) > 1 else "uncategorized"
    if categories and category not in categories:
        continue
    doc_id = doc_id_for(index, source_rel)
    if source_rel in done:
        continue
    if (md_root / category / f"{doc_id}.md").exists():
        continue
    jobs.append(
        {
            "doc_id": doc_id,
            "category": category,
            "source_path": str(source),
            "source_rel": source_rel,
            "original_name": source.name,
            "input_name": f"{doc_id}.pdf",
            "pages": str(page_count(source)),
            "size_bytes": str(source.stat().st_size),
        }
    )

if not dry_run and jobs:
    write_headers()
    out_root.mkdir(parents=True, exist_ok=True)
    existing_manifest_ids: set[str] = set()
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8", newline="") as f:
            existing_manifest_ids = {row.get("doc_id", "") for row in csv.DictReader(f)}
    with manifest_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not existing_manifest_ids and manifest_path.stat().st_size == 0:
            writer.writerow(["doc_id", "category", "source_path", "original_name", "pages", "size_bytes", "md_path", "assets_dir"])
        for row in jobs:
            if row["doc_id"] in existing_manifest_ids:
                continue
            writer.writerow(
                [
                    row["doc_id"],
                    row["category"],
                    row["source_rel"],
                    row["original_name"],
                    row["pages"],
                    row["size_bytes"],
                    f"md/{row['category']}/{row['doc_id']}.md",
                    f"assets/{row['category']}/{row['doc_id']}",
                ]
            )

for index in range(0, len(jobs), batch_docs):
    batch = jobs[index : index + batch_docs]
    path = out_dir / f"oldstyle_{index // batch_docs + 1:06d}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["doc_id", "category", "source_path", "source_rel", "original_name", "input_name", "pages", "size_bytes"],
        )
        writer.writeheader()
        writer.writerows(batch)

total_pages = sum(max(int(row["pages"]), 0) for row in jobs)
print(len(jobs), (len(jobs) + batch_docs - 1) // batch_docs, total_pages)
PY

if [ "$DRY_RUN" = "true" ]; then
  printf '[%s] substation oldstyle dry_run done\n' "$(date '+%F %T')" >> "$RUNNER_LOG"
  exit 0
fi

shopt -s nullglob
for batch_csv in "$BATCH_DIR"/oldstyle_*.csv; do
  batch_name="$(basename "$batch_csv" .csv)"
  batch_work="$WORK_DIR/$batch_name"
  batch_out="$RAW_OUT/$batch_name"
  batch_log="$LOG_DIR/$batch_name.log"

  rm -rf "$batch_work" "$batch_out"
  mkdir -p "$batch_work" "$batch_out"

  python3 - "$batch_csv" "$batch_work" <<'PY'
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

batch_csv = Path(sys.argv[1])
work_dir = Path(sys.argv[2])

with batch_csv.open("r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        src = Path(row["source_path"])
        dst = work_dir / row["input_name"]
        try:
            os.link(src, dst)
        except OSError:
            dst.symlink_to(src)
PY

  pending="$(find "$batch_work" \( -type f -o -type l \) -iname '*.pdf' | wc -l)"
  printf '[%s] %s pending=%s\n' "$(date '+%F %T')" "$batch_name" "$pending" >> "$RUNNER_LOG"
  if [ "$pending" -eq 0 ]; then
    continue
  fi

  started="$(date +%s)"
  set +e
  uv run mineru \
    -p "$batch_work" \
    -o "$batch_out" \
    -b pipeline \
    -m auto \
    -l ch \
    --formula "$FORMULA" \
    --table "$TABLE" \
    > "$batch_log" 2>&1
  rc=$?
  set -e
  finished="$(date +%s)"
  seconds="$((finished - started))"

  python3 - "$batch_csv" "$batch_out" "$batch_name" "$rc" "$seconds" <<'PY'
from __future__ import annotations

import csv
import sys
from pathlib import Path

from scripts.run_mineru_substation_pdf import PdfJob, collect_output, write_headers

batch_csv = Path(sys.argv[1])
batch_out = Path(sys.argv[2])
batch_name = sys.argv[3]
rc = int(sys.argv[4])
seconds = float(sys.argv[5])

write_headers()
with batch_csv.open("r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        job = PdfJob(
            doc_id=row["doc_id"],
            category=row["category"],
            source_path=Path(row["source_path"]),
            source_rel=row["source_rel"],
            original_name=row["original_name"],
            input_name=row["input_name"],
            pages=int(row["pages"] or 0),
            size_bytes=int(row["size_bytes"] or 0),
        )
        collect_output(job, batch_name, batch_out, seconds, "failed", f"mineru rc={rc}")
PY

  printf '[%s] %s rc=%s seconds=%s\n' "$(date '+%F %T')" "$batch_name" "$rc" "$seconds" >> "$RUNNER_LOG"
  rm -rf "$batch_work"
done

printf '[%s] substation oldstyle done categories=%s\n' "$(date '+%F %T')" "${TARGET_CATEGORIES[*]:-ALL}" >> "$RUNNER_LOG"
