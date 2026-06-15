#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p raw/logs/mineru_batches raw/mineru_batch_work

runner_log="raw/logs/mineru_batch_runner.log"
failed_log="raw/logs/mineru_failed_batches.txt"
skip_log="raw/logs/mineru_skipped_pdfs.txt"

printf '[%s] resume runner md_count=%s\n' \
  "$(date '+%F %T')" \
  "$(find documents_mineru -type f -name '*.md' | wc -l)" >> "$runner_log"

for batch in raw/mineru_batches/pdf_*; do
  batch_name="$(basename "$batch")"
  work_dir="raw/mineru_batch_work/$batch_name"
  batch_log="raw/logs/mineru_batches/$batch_name.log"

  rm -rf "$work_dir"
  mkdir -p "$work_dir"

  while IFS= read -r pdf; do
    file_name="$(basename "$pdf")"
    stem="${file_name%.*}"
    if [ -f "$skip_log" ] && grep -Fxq "$file_name" "$skip_log"; then
      continue
    fi
    if [ ! -f "documents_mineru/$stem/auto/$stem.md" ]; then
      ln "$pdf" "$work_dir/$file_name"
    fi
  done < "$batch"

  pending="$(find "$work_dir" -type f -iname '*.pdf' | wc -l)"
  printf '[%s] %s pending=%s\n' "$(date '+%F %T')" "$batch_name" "$pending" >> "$runner_log"

  if [ "$pending" -eq 0 ]; then
    continue
  fi

  CUDA_VISIBLE_DEVICES=0 MINERU_DEVICE_MODE=cuda PYTHONUNBUFFERED=1 \
    uv run mineru \
      -p "$work_dir" \
      -o documents_mineru \
      -b pipeline \
      -m auto \
      -l ch > "$batch_log" 2>&1

  rc=$?
  md_count="$(find documents_mineru -type f -name '*.md' | wc -l)"
  printf '[%s] %s rc=%s md_count=%s\n' "$(date '+%F %T')" "$batch_name" "$rc" "$md_count" >> "$runner_log"

  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$batch_name" >> "$failed_log"
  fi
done

printf '[%s] done md_count=%s\n' \
  "$(date '+%F %T')" \
  "$(find documents_mineru -type f -name '*.md' | wc -l)" >> "$runner_log"
