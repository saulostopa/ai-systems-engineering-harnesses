#!/usr/bin/env bash
# artifacts.sh — renders the delivery artifacts of a feature (Lessons 09, 11).
#
# The split this script exists to enforce: an agent AUTHORS the diagram source
# (only it knows what was built), and the harness VERIFIES and renders it. No
# script can infer a diagram from a diff — but no human should be trusted to
# remember to validate one either.
#
# Usage: ./scripts/artifacts.sh <plan-id> [--type workflow|sequence|…] [--kind diagram|report|quiz|all]
#   e.g. ./scripts/artifacts.sh feature/OEM-123
#
# diagram  reads docs/artifacts/<slug>.json      → writes <slug>.html   (archify)
# report   checks docs/artifacts/<slug>-report.html
# quiz     checks docs/artifacts/<slug>-quiz.html
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ID="${1:-}"
TYPE="workflow"
KIND="all"
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="${2:?--type needs a value}"; shift 2 ;;
    --kind) KIND="${2:?--kind needs a value}"; shift 2 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -n "$ID" ] || { echo "usage: ./scripts/artifacts.sh <plan-id> [--type TYPE]"; exit 2; }

# Same rule as the execution plans: the id keeps the branch name, the file
# flattens the slash.
SLUG="$(printf '%s' "$ID" | tr '/' '-')"
SRC="docs/artifacts/${SLUG}.json"
OUT="docs/artifacts/${SLUG}.html"

say()  { printf '[artifacts] %s\n' "$1"; }
fail() { printf '[artifacts] FAIL: %s\n' "$1" >&2; exit 1; }
FAILURES=0
bad()  { printf '[artifacts] FAIL: %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }

# Bytes on disk are not evidence that a browser will show anything. An
# unterminated HTML comment silently swallows every section after it — the file
# looks delivered and renders an empty shell. Check what survives outside
# comments, which is the only thing a reader gets.
check_html() {
  local label="$1" file="$2" needle="$3" minimum="$4"
  [ -f "$file" ] || { bad "$label missing: $file"; return; }
  python3 - "$file" "$needle" "$minimum" "$label" <<'PYEOF'
import re, sys
path, needle, minimum, label = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
html = open(path, encoding="utf-8").read()
if html.count("<!--") != html.count("-->"):
    print(f"[artifacts] FAIL: {label} has unbalanced HTML comments — content is swallowed")
    sys.exit(1)
visible = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
found = visible.count(needle)
if found < minimum:
    print(f"[artifacts] FAIL: {label} shows {found} of {needle!r} outside comments (need {minimum})")
    sys.exit(1)
print(f"[artifacts] OK — {label}: {found} x {needle!r} visible")
PYEOF
  [ $? -eq 0 ] || FAILURES=$((FAILURES + 1))
}

if [ "$KIND" = "report" ] || [ "$KIND" = "quiz" ] || [ "$KIND" = "all" ]; then
  [ "$KIND" = "quiz" ]   || check_html "report" "docs/artifacts/${SLUG}-report.html" '<section class="card"' 3
  [ "$KIND" = "report" ] || check_html "quiz"   "docs/artifacts/${SLUG}-quiz.html"   'quiz-opt' 9
  [ "$KIND" = "all" ] || { [ "$FAILURES" -eq 0 ] && exit 0 || exit 1; }
fi
[ "$KIND" = "diagram" ] || [ "$KIND" = "all" ] || exit "$FAILURES"

# The archify skill is an optional pack, so its absence is a clear instruction,
# never a silent skip that lets an unverified artifact through.
ARCHIFY=""
for c in .agents/skills/archify/bin/archify.mjs .claude/skills/archify/bin/archify.mjs; do
  [ -f "$c" ] && { ARCHIFY="$c"; break; }
done
if [ -z "$ARCHIFY" ]; then
  fail "archify skill not installed — run: npx skills add tt-a1i/archify --agent opencode --copy"
fi
command -v node >/dev/null 2>&1 || fail "node not found — archify needs it"

if [ ! -f "$SRC" ]; then
  mkdir -p docs/artifacts
  say "no source at $SRC"
  say "The agent writes it: a typed $TYPE JSON describing what was built."
  say "Start from an example:  node $ARCHIFY examples"
  exit 1
fi

say "rendering $SRC → $OUT (type: $TYPE, quality: showcase)"
# showcase, not standard: the whole point of this skill is that the diagram is
# verified before it is delivered. A lower bar would make the artifact a
# decoration again.
if node "$ARCHIFY" deliver "$TYPE" "$SRC" "$OUT" --quality showcase >/dev/null 2>&1; then
  say "OK — $OUT passed validation at showcase quality"

  # Brand last, on purpose. Archify has no theming field in its schema, but the
  # delivered HTML exposes its palette as CSS custom properties — so the tokens
  # are overridable without touching the geometry the composition validator
  # just approved. Appending after delivery also means a theme bug can never
  # be mistaken for a diagram bug.
  THEME="$(dirname "${BASH_SOURCE[0]}")/archify-theme.css"
  if [ -f "$THEME" ]; then
    { printf '\n<style data-theme="eleanor">\n'; cat "$THEME"; printf '\n</style>\n'; } >> "$OUT"
    say "applied the Eleanor palette"
    # The artifact must still pass its own checks after being restyled.
    if node "$ARCHIFY" check "$OUT" >/dev/null 2>&1; then
      say "OK — still passes archify check with the brand applied"
    else
      bad "the artifact stopped passing archify check after theming"
    fi
  fi
  exit "$FAILURES"
fi

printf '\n[artifacts] validation failed — the diagnosis below is actionable:\n\n'
node "$ARCHIFY" validate "$TYPE" "$SRC" --quality showcase 2>&1 | tail -40
exit 1
