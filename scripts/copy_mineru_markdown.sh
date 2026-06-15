#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SRC_DIR="${1:-documents_mineru}"
DST_DIR="${2:-documents_mineru_md}"

if [ ! -d "$SRC_DIR" ]; then
  echo "source directory not found: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "$DST_DIR"

copied=0
skipped=0

while IFS= read -r -d '' src; do
  file_name="$(basename "$src")"
  dst="$DST_DIR/$file_name"
  if [ -e "$dst" ]; then
    skipped=$((skipped + 1))
    continue
  fi
  cp -p "$src" "$dst"
  copied=$((copied + 1))
done < <(find "$SRC_DIR" -type f -name '*.md' -print0)

echo "copied=$copied skipped=$skipped dst=$DST_DIR"
