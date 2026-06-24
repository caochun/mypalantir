#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="kunshan/documents_2025_md/logs/mineru_2025_queue.log"
mkdir -p "$(dirname "$LOG")"

export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="${PYTHONPATH:-agent}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export MINERU_DEVICE_MODE="${MINERU_DEVICE_MODE:-cuda}"

ts() {
  date '+%F %T'
}

log() {
  printf '[%s] %s\n' "$(ts)" "$*"
}

wait_for_current_2025_07_small4() {
  while pgrep -f 'python3 scripts/run_mineru_2025_pdf.py --groups 2025_07 --max-pages 8 --batch-docs 4' >/dev/null; do
    log "waiting for active 2025_07 <=8-page small4 runner"
    sleep 60
  done
}

stop_orphan_api() {
  pkill -f 'uv run mineru --api-url http://127.0.0.1:51017' 2>/dev/null || true
  pkill -f 'mineru-api --host 127.0.0.1 --port 51017' 2>/dev/null || true
  sleep 5
}

run_stage() {
  local group="$1"
  local label="$2"
  shift 2

  log "stage start group=${group} label=${label} args=$*"
  stop_orphan_api
  rm -rf .mineru_2025_work
  mkdir -p .mineru_2025_work

  python3 scripts/run_mineru_2025_pdf.py \
    --groups "$group" \
    "$@" \
    --formula false \
    --table true \
    >> "$LOG" 2>&1

  log "stage done group=${group} label=${label}"
}

run_group() {
  local group="$1"

  run_stage "$group" le8 \
    --max-pages 8 \
    --batch-docs 24 \
    --batch-pages 96 \
    --timeout 1500 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 20 \
    --batch-prefix "${group}_le8"

  run_stage "$group" p9_32 \
    --min-pages 9 \
    --max-pages 32 \
    --batch-docs 12 \
    --batch-pages 192 \
    --timeout 1800 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 10 \
    --batch-prefix "${group}_p9_32"

  run_stage "$group" p33_128 \
    --min-pages 33 \
    --max-pages 128 \
    --batch-docs 4 \
    --batch-pages 256 \
    --timeout 2400 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 5 \
    --batch-prefix "${group}_p33_128"

  run_stage "$group" p129_plus \
    --min-pages 129 \
    --batch-docs 1 \
    --batch-pages 512 \
    --timeout 3600 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 1 \
    --batch-prefix "${group}_p129_plus"
}

main() {
  log "queue start"
  wait_for_current_2025_07_small4

  run_stage 2025_07 p9_32 \
    --min-pages 9 \
    --max-pages 32 \
    --batch-docs 12 \
    --batch-pages 192 \
    --timeout 1800 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 10 \
    --batch-prefix 2025_07_p9_32

  run_stage 2025_07 p33_128 \
    --min-pages 33 \
    --max-pages 128 \
    --batch-docs 4 \
    --batch-pages 256 \
    --timeout 2400 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 5 \
    --batch-prefix 2025_07_p33_128

  run_stage 2025_07 p129_plus \
    --min-pages 129 \
    --batch-docs 1 \
    --batch-pages 512 \
    --timeout 3600 \
    --api-concurrency 1 \
    --processing-window-size 128 \
    --pdf-render-threads 8 \
    --api-port 51017 \
    --api-restart-every-batches 1 \
    --batch-prefix 2025_07_p129_plus

  for group in 2025_07-1 2025_08 2025_09 2025_10; do
    run_group "$group"
  done

  stop_orphan_api
  log "queue done"
}

main "$@"
