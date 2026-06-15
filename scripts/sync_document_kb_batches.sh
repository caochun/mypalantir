#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BATCH_SIZE="${1:-200}"
MAX_BATCHES="${2:-0}"
INCLUDE_SOFT="${INCLUDE_SOFT:-false}"
LOG_PATH="${LOG_PATH:-raw/logs/document_kb_batches.log}"
SLEEP_SECONDS="${SLEEP_SECONDS:-2}"

mkdir -p "$(dirname "$LOG_PATH")"

batch=0
while true; do
  if [ "$MAX_BATCHES" -gt 0 ] && [ "$batch" -ge "$MAX_BATCHES" ]; then
    echo "[$(date '+%F %T')] stopped max_batches=$MAX_BATCHES" | tee -a "$LOG_PATH"
    break
  fi

  output="$(
    set -a
    [ -f .env ] && . ./.env
    set +a
    DOCUMENT_QA_KB_BATCH_SIZE="$BATCH_SIZE" DOCUMENT_QA_KB_INCLUDE_SOFT="$INCLUDE_SOFT" uv run python - <<'PY'
import json
import os
from pathlib import Path
from domains.document_qa.functions.index import DocumentIndex, resolve_paths

idx = DocumentIndex(resolve_paths(Path("domains/document_qa")))
result = idx.build_document_kb(
    force=False,
    include_soft=os.getenv("DOCUMENT_QA_KB_INCLUDE_SOFT", "false").lower() == "true",
    limit=int(os.getenv("DOCUMENT_QA_KB_BATCH_SIZE", "200")),
)
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY
  )"
  batch=$((batch + 1))
  echo "[$(date '+%F %T')] batch=$batch $output" | tee -a "$LOG_PATH"

  pending="$(printf '%s\n' "$output" | uv run python -c 'import json,sys; print(json.load(sys.stdin).get("documents_pending", 0))')"
  if [ "$pending" -le 0 ]; then
    break
  fi
  sleep "$SLEEP_SECONDS"
done
