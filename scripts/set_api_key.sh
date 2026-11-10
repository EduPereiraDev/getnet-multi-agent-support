#!/usr/bin/env bash
# Stores ANTHROPIC_API_KEY in .env without echoing it or writing it to shell history.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
read -rsp "Paste ANTHROPIC_API_KEY and press Enter: " KEY
echo
grep -v '^ANTHROPIC_API_KEY=' .env > .env.tmp || true
printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" >> .env.tmp
mv .env.tmp .env
chmod 600 .env
unset KEY
echo "ok: key saved to .env (git- and docker-ignored)"
