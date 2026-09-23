#!/usr/bin/env bash
# log-event.sh — records harness friction/event (Lesson 11).
# Usage: ./scripts/log-event.sh <category> <message>
# E.g.: ./scripts/log-event.sh friction "agent stalled 3x on the same step"
set -uo pipefail

CAT="${1:-event}"
MSG="${2:-}"

mkdir -p .harness/logs
LOG=".harness/logs/$(date +%Y-%m).md"

[ -f "$LOG" ] || printf '# Harness log — %s\n\n' "$(date +%Y-%m)" > "$LOG"

printf -- '- %s `%s`: %s\n' "$(date -Iseconds)" "$CAT" "$MSG" >> "$LOG"
echo "[log-event] logged to $LOG"
