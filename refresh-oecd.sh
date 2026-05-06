#!/bin/bash
# refresh-oecd.sh — runs daily on Mac (where OECD API is accessible)
# Fetches fresh CLI data, commits, and pushes to GitHub
# GitHub Actions then auto-deploys to Cloudflare Pages

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$REPO_DIR/market-insight/scripts/fetch-oecd-cli.py"
OUTPUT="$REPO_DIR/market-insight/public/data/oecd-cli.json"
LOG="$REPO_DIR/refresh-oecd.log"

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"

cd "$REPO_DIR"

# Fetch fresh data
python3 "$SCRIPT" "$OUTPUT" >> "$LOG" 2>&1

# Commit and push if changed
git add "$OUTPUT"
if git diff --staged --quiet; then
  echo "No changes to commit" >> "$LOG"
else
  git commit -m "chore: update OECD CLI data $(date -u +%Y-%m-%d) [skip ci]" >> "$LOG" 2>&1
  git push >> "$LOG" 2>&1
  echo "Pushed to GitHub — Cloudflare deploy triggered" >> "$LOG"
fi

echo "Done" >> "$LOG"
