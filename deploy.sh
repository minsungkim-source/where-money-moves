#!/usr/bin/env bash
# 수동 운영 배포: ./deploy.sh — Vercel이 vercel.json의 buildCommand(python3 build.py)로 site/를 굽는다.
# 로컬 빌드는 미리 깨지는지 보는 용도. 데이터 갱신은 먼저 etl/etl.py를 돌리고 data/processed를 커밋한다.
set -euo pipefail
cd "$(dirname "$0")"

python3 build.py

# 회사망 TLS 검사 대응: 맥이 이미 믿는 루트 인증서를 꺼내 이 명령에만 붙인다 (검사를 끄지 않는다)
if command -v security >/dev/null 2>&1; then
  CA="${TMPDIR:-/tmp}/wmm-corp-ca.pem"
  security find-certificate -a -p /Library/Keychains/System.keychain > "$CA"
  export NODE_EXTRA_CA_CERTS="$CA"
fi

npx -y vercel@61.1.0 deploy --prod --yes
