#!/bin/sh
# 빌드하고 미리보기용 복사본을 갱신한다 (미리보기 서버는 Documents를 못 읽어 스크래치에서 서빙한다)
set -e
cd "$(dirname "$0")"
../blindspot-th/etl/.venv/bin/python build.py
[ -n "$PREVIEW_DIR" ] && rsync -a --delete site/ "$PREVIEW_DIR/"
