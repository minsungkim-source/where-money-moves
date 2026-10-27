#!/usr/bin/env bash
# Manual production deploy: ./deploy.sh — Vercel builds site/ with vercel.json's buildCommand (python3 build.py).
# The local build only checks that nothing is broken. To refresh data, run the ETLs and commit data/processed first.
set -euo pipefail
cd "$(dirname "$0")"

python3 build.py

# Corporate TLS inspection: pass the roots this Mac already trusts to this one command (never disable checks)
if command -v security >/dev/null 2>&1; then
  CA="${TMPDIR:-/tmp}/wmm-corp-ca.pem"
  security find-certificate -a -p /Library/Keychains/System.keychain > "$CA"
  export NODE_EXTRA_CA_CERTS="$CA"
fi

npx -y vercel@61.1.0 deploy --prod --yes
