#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-offline_bundle}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to prepare the tiktoken cache." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

echo "Prewarming tiktoken encoding cache..."
CACHE_DIR="$(
  python3 - <<'PY'
import tiktoken
import tiktoken.load as load

tiktoken.get_encoding("o200k_base")
cache_dir = getattr(load, "CACHE_DIR", None) or getattr(load, "DEFAULT_CACHE_DIR", None)
if not cache_dir:
    raise SystemExit("tiktoken cache directory not found")
print(cache_dir)
PY
)"

if [[ ! -d "$CACHE_DIR" ]]; then
  echo "tiktoken cache directory does not exist: $CACHE_DIR" >&2
  exit 1
fi

DEST_DIR="$OUT_DIR/tiktoken-cache"
mkdir -p "$DEST_DIR"

echo "Copying tiktoken cache from: $CACHE_DIR"
cp -a "$CACHE_DIR"/. "$DEST_DIR"/

cat <<EOF
Offline bundle prepared.
- tiktoken cache: $DEST_DIR

To use in the offline environment:
  export TIKTOKEN_CACHE_DIR="$DEST_DIR"
EOF
