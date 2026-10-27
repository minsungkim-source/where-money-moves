#!/bin/sh
# Build, then refresh the preview copy (the preview server cannot read ~/Documents, so it serves a copy)
set -e
cd "$(dirname "$0")"
../blindspot-th/etl/.venv/bin/python build.py
[ -n "$PREVIEW_DIR" ] && rsync -a --delete site/ "$PREVIEW_DIR/"
