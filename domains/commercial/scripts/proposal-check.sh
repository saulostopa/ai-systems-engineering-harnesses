#!/usr/bin/env bash
# proposal-check.sh — validates the proposal against the briefing (commercial).
# Usage: proposal-check.sh <proposal.md> <briefing.md>
# Briefing requirements marked with "- [REQ]" are compared by keywords.
set -uo pipefail

PROPOSTA="${1:-}"
BRIEFING="${2:-}"
[ -f "$PROPOSTA" ] && [ -f "$BRIEFING" ] || { echo "Usage: proposal-check.sh <proposal.md> <briefing.md>"; exit 1; }

FAILURES=0
ok()   { printf '  [ok]     %s\n' "$1"; }
fail() { printf '  [FAIL]   %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
section() { printf '\n== %s ==\n' "$1"; }

# Words that do not count as answer evidence (stopwords + request verbs)
STOPWORDS='^(para|com|que|este|esta|nossa|assinatura|incluir|propor|pela|pelo|rede|das|dos|uma|uma)$'

section "Briefing requirements (item by item)"
TOTAL_REQ=0
while IFS= read -r req; do
  TOTAL_REQ=$((TOTAL_REQ + 1))
  term=$(echo "$req" | sed -E 's/^- \[REQ\] *//' | cut -c1-60)
  KEYWORDS=$(echo "$req" | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z]{4,}' | grep -vE "$STOPWORDS" || true)
  HITS=0
  for kw in $KEYWORDS; do
    grep -qi "$kw" "$PROPOSTA" && HITS=$((HITS + 1))
  done
  TOTAL_KW=$(echo "$KEYWORDS" | wc -w | tr -d ' ')
  if [ "${TOTAL_KW:-0}" -ge 2 ] && [ "${HITS:-0}" -ge 2 ]; then
    ok "requirement met: $term..."
  else
    fail "requirement WITHOUT a clear answer: $term... (keywords: ${HITS:-0}/${TOTAL_KW:-0})"
  fi
done < <(grep -E "^- \[REQ\]" "$BRIEFING" || true)
if [ "${TOTAL_REQ:-0}" -eq 0 ]; then
  echo "  (no requirements marked - [REQ] in the briefing)"
  FAILURES=$((FAILURES + 1))
fi

section "Numbers with source"
# A number is safe if the line has FONTE, or the previous/next line does.
SOLTOS=$(awk '
  { lines[NR] = $0 }
  END {
    bad = 0
    for (i = 1; i <= NR; i++) {
      if (lines[i] ~ /[0-9]/ && lines[i] !~ /FONTE:/) {
        before = (i > 1 && lines[i-1] ~ /FONTE:/) ? 1 : 0
        after  = (i < NR && lines[i+1] ~ /FONTE:/) ? 1 : 0
        if (before == 0 && after == 0) bad++
      }
    }
    print bad
  }' "$PROPOSTA")
FONTES=$(grep -c "FONTE:" "$PROPOSTA" || true)
ok "sources cited: $FONTES"
if [ "${SOLTOS:-0}" -gt 0 ]; then
  fail "$SOLTOS numeric line(s) without FONTE"
else
  ok "no loose numbers"
fi

section "Cross review"
if grep -qi "revisor\|revisad" "$PROPOSTA"; then
  ok "review recorded in the document"
else
  fail "no cross-review record — ask an independent reviewer"
fi

section "Result"
printf '%s — %d failure(s)\n' "$([ "$FAILURES" -eq 0 ] && echo "PROPOSAL APPROVED FOR SUBMISSION" || echo "PROPOSAL BLOCKED")" "$FAILURES"
exit "$FAILURES"