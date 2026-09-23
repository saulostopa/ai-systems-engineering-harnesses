#!/usr/bin/env bash
# gatekeeper.sh — pre-commit: blocks commits without a feature in_progress.
# Rule (Lesson 07): one feature in_progress at a time; no "loose commits".
# Conscious bypass: touch .harness/skip-gatekeeper (expires in 5 min).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FLAG=".harness/skip-gatekeeper"
if [ -f "$FLAG" ]; then
  AGE=$(( $(date +%s) - $(stat -c %Y "$FLAG") ))
  if [ "$AGE" -lt 300 ]; then
    echo "[gatekeeper] temporary bypass active ($(( 300 - AGE ))s left)"
    exit 0
  fi
  rm -f "$FLAG"
fi

[ -f "feature_list.json" ] || { echo "[gatekeeper] BLOCKED: feature_list.json missing — run ./init.sh"; exit 1; }

ACTIVE=$(node -e "const f=require('./feature_list.json').features;const a=f.filter(x=>x.status==='in_progress');console.log(a.length)" 2>/dev/null || echo "?")

if [ "$ACTIVE" = "?" ]; then
  echo "[gatekeeper] WARNING: could not read feature_list.json (node missing?) — allowing, but validate manually"
  exit 0
fi

if [ "$ACTIVE" -eq 1 ]; then
  echo "[gatekeeper] OK: 1 feature in_progress"
  exit 0
elif [ "$ACTIVE" -gt 1 ]; then
  echo "[gatekeeper] BLOCKED: $ACTIVE features in_progress — keep ONE (Lesson 06/07)"
  exit 1
else
  echo "[gatekeeper] BLOCKED: no feature in_progress — declare the feature in feature_list.json before committing (Lesson 08)"
  exit 1
fi
