#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET_GROUPS=("$@")
if [ "${#TARGET_GROUPS[@]}" -eq 0 ]; then
  TARGET_GROUPS=(2025_10)
fi

BATCH_DOCS="${BATCH_DOCS:-40}"
WORK_ROOT="${WORK_ROOT:-.mineru_2025_work}"
BATCH_DIR="$WORK_ROOT/oldstyle_batches"
WORK_DIR="$WORK_ROOT/oldstyle_work"
RAW_OUT="$WORK_ROOT/oldstyle_output"
LOG_DIR="kunshan/documents_2025_md/logs/oldstyle_batches"
RUNNER_LOG="kunshan/documents_2025_md/logs/mineru_oldstyle_runner.log"

mkdir -p "$BATCH_DIR" "$WORK_DIR" "$RAW_OUT" "$LOG_DIR" "$(dirname "$RUNNER_LOG")"
rm -rf "$BATCH_DIR" "$WORK_DIR" "$RAW_OUT"
mkdir -p "$BATCH_DIR" "$WORK_DIR" "$RAW_OUT"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export MINERU_DEVICE_MODE="${MINERU_DEVICE_MODE:-cuda}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="${PYTHONPATH:-.}"

printf '[%s] oldstyle start groups=%s batch_docs=%s table=true formula=false\n' \
  "$(date '+%F %T')" "${TARGET_GROUPS[*]}" "$BATCH_DOCS" >> "$RUNNER_LOG"

python3 - "$BATCH_DIR" "$BATCH_DOCS" "${TARGET_GROUPS[@]}" <<'PY'
from __future__ import annotations

import csv
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
batch_docs = int(sys.argv[2])
groups = set(sys.argv[3:])

root = Path.cwd()
manifest_path = root / "raw/2025/manifest.csv"
status_path = root / "kunshan/documents_2025_md/status.csv"
md_root = root / "kunshan/documents_2025_md/md"

done: set[str] = set()
if status_path.exists():
    with status_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") in {"ok", "failed_bad_pdf"}:
                done.add(row.get("source_path", ""))

jobs: list[dict[str, str]] = []
with manifest_path.open("r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        group = row.get("group", "")
        short_path = row.get("short_path", "")
        if group not in groups or not short_path.lower().endswith(".pdf"):
            continue
        if short_path in done:
            continue
        source = root / "raw/2025" / short_path
        if not source.exists():
            continue
        if (md_root / group / f"{source.stem}.md").exists():
            continue
        jobs.append(
            {
                "group": group,
                "short_path": short_path,
                "original_path": row.get("original_path", ""),
                "source_path": str(source),
                "stem": source.stem,
                "size_bytes": str(source.stat().st_size),
            }
        )

for index in range(0, len(jobs), batch_docs):
    batch = jobs[index : index + batch_docs]
    path = out_dir / f"oldstyle_{index // batch_docs + 1:06d}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["group", "short_path", "original_path", "source_path", "stem", "size_bytes"],
        )
        writer.writeheader()
        writer.writerows(batch)

print(len(jobs), (len(jobs) + batch_docs - 1) // batch_docs)
PY

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
        dst = work_dir / src.name
        try:
            os.link(src, dst)
        except OSError:
            dst.symlink_to(src)
PY

  pending="$(find "$batch_work" -type f -iname '*.pdf' -o -type l -iname '*.pdf' | wc -l)"
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
    --formula false \
    --table true \
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

from scripts.run_mineru_2025_pdf import PdfJob, collect_output, write_headers, write_manifest

batch_csv = Path(sys.argv[1])
batch_out = Path(sys.argv[2])
batch_name = sys.argv[3]
rc = int(sys.argv[4])
seconds = float(sys.argv[5])

write_headers()
with batch_csv.open("r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        source_path = Path(row["source_path"])
        job = PdfJob(
            group=row["group"],
            short_path=row["short_path"],
            original_path=row["original_path"],
            source_path=source_path,
            stem=row["stem"],
            pages=0,
            size_bytes=int(row["size_bytes"] or 0),
        )
        collect_output(job, batch_name, batch_out, seconds, "failed", f"mineru rc={rc}")

write_manifest([])
PY

  printf '[%s] %s rc=%s seconds=%s\n' "$(date '+%F %T')" "$batch_name" "$rc" "$seconds" >> "$RUNNER_LOG"
  rm -rf "$batch_work"
done

printf '[%s] oldstyle done groups=%s\n' "$(date '+%F %T')" "${TARGET_GROUPS[*]}" >> "$RUNNER_LOG"
