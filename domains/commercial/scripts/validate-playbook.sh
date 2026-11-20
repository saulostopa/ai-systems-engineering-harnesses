#!/usr/bin/env bash
# validate-playbook.sh — domain playbook health (Lesson 11)
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
FAILURES=0
ok()   { printf '  [ok]     %s\n' "$1"; }
fail() { printf '  [FAIL]   %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
section() { printf '\n== %s ==\n' "$1"; }

section "Mandatory structure"
for f in AGENTS.md feature_list.json policies/scope-control.md policies/definition-of-done.md policies/evidence-required.md; do
  [ -f "$f" ] && ok "exists: $f" || fail "missing: $f"
done

section "feature_list.json"
if [ -f "feature_list.json" ] && command -v node >/dev/null 2>&1; then
  node -e "const f=require('./feature_list.json'); if(!Array.isArray(f.features)) throw new Error('no features'); const act=f.features.filter(x=>x.status==='in_progress').length; if(act>1) throw new Error(act+' in_progress'); console.log('  [ok]     valid JSON; ' + f.features.length + ' features')" 2>&1 | head -2 \
    && : || { echo "  [FAIL]   invalid feature_list.json"; FAILURES=$((FAILURES + 1)); }
fi

section "Skills"
SKILLS=$(ls skills/*/SKILL.md 2>/dev/null | wc -l)
if [ "$SKILLS" -gt 0 ]; then
  ok "$SKILLS skill(s) found"
else
  fail "no skills in skills/*/SKILL.md (the playbook needs at least one)"
fi

printf '\n%s — %d failure(s)\n' "$([ "$FAILURES" -eq 0 ] && echo "PLAYBOOK OK" || echo "PLAYBOOK BROKEN")" "$FAILURES"
exit "$FAILURES"