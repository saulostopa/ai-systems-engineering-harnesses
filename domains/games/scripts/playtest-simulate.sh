#!/usr/bin/env bash
# playtest-simulate.sh — simulated playtest of a feature (Lesson 10: the "E2E"
# of the game). Simulates flow variations and scores the design doc's acceptance criteria.
# Usage: playtest-simulate.sh <design-doc.md> [--verbose]
set -uo pipefail

DOC="${1:-}"
[ -f "$DOC" ] || { echo "Usage: playtest-simulate.sh <design-doc.md>"; exit 1; }

section() { printf '\n== %s ==\n' "$1"; }
ok()   { printf '  [ok]     %s\n' "$1"; }
fail() { printf '  [FAIL]   %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
FAILURES=0

section "Simulated scenarios (player variations)"

# Scenario 1: new player (never saw the mechanic)
grep -qi "persona" "$DOC" && ok "persona defined — new-player simulation possible" \
  || fail "no persona in the design doc — blind simulation"

# Scenario 2: complete loop (input -> rule -> feedback)
grep -qi "feedback" "$DOC" && ok "feedback described — closed loop" \
  || fail "no feedback described — mechanic without closure"

# Scenario 3: economy (if applicable)
if grep -qi "economia" "$DOC"; then
  NUMBERS=$(grep -oE '[0-9]{2,}' "$DOC" | wc -l)
  [ "$NUMBERS" -ge 3 ] && ok "economy with values ($NUMBERS numbers) — consistency can be simulated" \
    || fail "economy mentioned but without enough values (>=3)"
fi

# Scenario 4: acceptance criteria
grep -qiE "verificacao|aceit" "$DOC" && ok "acceptance criteria present — playtest has a target" \
  || fail "no acceptance criteria in the doc — playtest without a verdict"

section "Simulated playtest result"
printf '%s — %d failure(s)\n' "$([ "$FAILURES" -eq 0 ] && echo "PLAYTEST ACCEPTED" || echo "PLAYTEST REJECTED")" "$FAILURES"
exit "$FAILURES"