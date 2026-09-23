#!/usr/bin/env bash
# validate-enterprise-harness.sh — health check of the orchestrator package.
#
# Like the basic harness's own health check, this runs in two situations:
# from the package source tree (before anything is installed) and from an
# installed orchestrator. The difference matters: the source tree has no
# vendored harness-basic yet, and reporting that as missing would be crying
# wolf about a file that is not supposed to exist yet.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FAILURES=0
WARNINGS=0

ok()   { printf '  [ok]     %s\n' "$1"; }
warn() { printf '  [warn]   %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '  [FAIL]   %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
section() { printf '\n== %s ==\n' "$1"; }

if [ -f "$ROOT/install.sh" ]; then
  MODE="package"
else
  MODE="installed"
fi
printf 'Validating the enterprise harness (%s)\n' "$MODE"

section "Required structure"
for f in bin/wm-harness engine/lib.sh templates/harness-config.yaml \
         flows/feature-default.yaml VERSION; do
  [ -f "$f" ] && ok "present: $f" || fail "missing: $f"
done
if [ "$MODE" = "installed" ]; then
  [ -f "harness-basic/install.sh" ] && ok "present: harness-basic/install.sh (vendored payload)" \
    || fail "missing: harness-basic/install.sh — adoption would fail"
  [ -f "projects-root" ] && ok "present: projects-root" || warn "no projects-root — scanning the install's parent"
else
  [ -d "$ROOT/../harness-basic" ] && ok "harness-basic available next to the package" \
    || fail "harness-basic not found next to the package — install.sh would fail"
fi

section "Syntax"
SYNTAX_OK=1
for f in bin/wm-harness engine/lib.sh scripts/*.sh; do
  [ -e "$f" ] || continue
  bash -n "$f" 2>/dev/null || { fail "syntax error: $f"; SYNTAX_OK=0; }
done
[ "$SYNTAX_OK" = "1" ] && ok "every script parses"

section "Executability"
for f in bin/wm-harness; do
  [ -x "$f" ] && ok "executable: $f" || fail "not executable: $f (chmod +x)"
done

section "Flow definitions"
# A flow whose steps or criteria are empty produces an empty plan — the failure
# would only surface much later, inside somebody's repository.
FLOW_N=0
for f in flows/*.yaml; do
  [ -e "$f" ] || continue
  FLOW_N=$((FLOW_N + 1))
  name="$(basename "$f" .yaml)"
  steps="$(awk '/^steps:[[:space:]]*$/{i=1;next} i&&/^[[:space:]]*-[[:space:]]+/{n++;next} i&&/^[^[:space:]]/{i=0} END{print n+0}' "$f")"
  crit="$(awk '/^exit_criteria:[[:space:]]*$/{i=1;next} i&&/^[[:space:]]*-[[:space:]]+/{n++;next} i&&/^[^[:space:]]/{i=0} END{print n+0}' "$f")"
  if [ "$steps" -eq 0 ]; then fail "flow '$name' has no steps"
  elif [ "$crit" -eq 0 ]; then fail "flow '$name' has no exit criteria"
  else ok "flow '$name': $steps step(s), $crit exit criterion/criteria"; fi
done
[ "$FLOW_N" -eq 0 ] && fail "no flow defined"

section "The orchestrator stores no project state"
# The invariant the whole design rests on. A stray database or registry here
# would mean project information lives outside the project — exactly the
# failure this harness exists to avoid.
STATE_FOUND=""
for pat in '*.sqlite' '*.db' 'registry.json' 'state.json' 'items.json'; do
  found="$(find "$ROOT" -maxdepth 2 -name "$pat" -not -path '*/harness-basic/*' 2>/dev/null | head -3)"
  [ -n "$found" ] && STATE_FOUND="$STATE_FOUND $found"
done
if [ -n "$STATE_FOUND" ]; then
  fail "project state stored in the orchestrator:$STATE_FOUND"
else
  ok "no database, registry or state file — projects are discovered by scanning"
fi

section "Result"
printf '\n%s — %d failure(s), %d warning(s)\n' \
  "$( [ "$FAILURES" -eq 0 ] && echo "ENTERPRISE HARNESS OK" || echo "ENTERPRISE HARNESS BROKEN" )" \
  "$FAILURES" "$WARNINGS"
exit "$FAILURES"
