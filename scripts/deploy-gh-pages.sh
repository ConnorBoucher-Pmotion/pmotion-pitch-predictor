#!/usr/bin/env bash
# Build frontend and push to gh-pages (qf-lab style), preserving history when possible.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FE="$ROOT/frontend"
API_URL="${VITE_API_BASE_URL:-}"
BASE="${VITE_BASE:-/pmotion-pitch-predictor/}"

cd "$FE"
npm ci
VITE_BASE="$BASE" VITE_API_BASE_URL="$API_URL" npm run build
touch dist/.nojekyll

WORK=$(mktemp -d)
git clone --depth 1 --branch gh-pages "$1" "$WORK" 2>/dev/null || {
  git clone --depth 1 "$1" "$WORK"
  cd "$WORK"
  git checkout --orphan gh-pages
  git rm -rf . >/dev/null 2>&1 || true
}
rm -rf "$WORK"/*
cp -R "$FE/dist"/. "$WORK"/
cd "$WORK"
git add -A
git -c user.email="connor@pmotiontech.com" -c user.name="Connor Boucher" \
  commit -m "Deploy frontend to GitHub Pages" || echo "No changes"
git push -u origin gh-pages
echo "Pushed gh-pages → $1"
