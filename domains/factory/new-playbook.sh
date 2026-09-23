#!/usr/bin/env bash
# new-playbook.sh — generates the skeleton of a domain playbook (EPIC E).
# The skeleton is the SAME for every domain; only the skill content changes.
# Usage: new-playbook.sh <domain-name> [--dir domains]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME=""
DIR="domains"

for arg in "$@"; do
  case "$arg" in
    --dir) DIR_NEXT=1 ;;
    -*) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
    *)
      if [ "${DIR_NEXT:-0}" = "1" ]; then DIR="$arg"; DIR_NEXT=0; else NAME="$arg"; fi
      ;;
  esac
done

[ -n "$NAME" ] || { echo "Usage: new-playbook.sh <name> [--dir <folder>]"; exit 1; }
NAME_LC=$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')
TARGET="$ROOT/$DIR/$NAME_LC"
[ -d "$TARGET" ] && { echo "ERROR: playbook already exists: $TARGET"; exit 1; }

log() { printf '[new-playbook] %s\n' "$1"; }

mkdir -p "$TARGET/skills" "$TARGET/policies" "$TARGET/scripts"
log "playbook created at $TARGET"

# Domain router
cat > "$TARGET/AGENTS.md" <<EOF
# AGENTS.md — Domain playbook: $NAME

> Multi-domain skeleton (same for games, finance, commercial...).
> Only the skill content changes — the process does not.

## 1. What this playbook governs
$NAME deliveries. The feature list below is the source of truth for scope.

## 2. How to work
- ONE feature \`in_progress\` at a time (basic harness rule).
- Domain skills load ON DEMAND (frontmatter name+description).
- Scope declared in policies/scope-control.md before editing.

## 3. How to verify
- policies/definition-of-done.md: what proves "done" in the domain.
- policies/evidence-required.md: evidence before "done" (Lesson 09).
- scripts/validate-playbook.sh: playbook health (Lesson 11).

## 4. Where knowledge lives
- skills/ — domain instruction packages (SKILL.md).
- feature_list.json — state of each delivery.
- relatorios/ — generated artifacts (with cited source).
EOF

# Empty feature list
cat > "$TARGET/feature_list.json" <<'EOF'
{
  "features": []
}
EOF

# Policies (reference the basic harness package)
for p in scope-control definition-of-done evidence-required; do
  cat > "$TARGET/policies/$p.md" <<EOF
# $p — see the official template at templates/policies/$p.md (Story A4)
> Rule of this domain: "done" is what is in policies/definition-of-done.md.
EOF
done

# Playbook validator (mandatory structure)
cat > "$TARGET/scripts/validate-playbook.sh" <<'EOF'
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
EOF
chmod +x "$TARGET/scripts/validate-playbook.sh"

log "fill in skills/ and feature_list.json; validate with scripts/validate-playbook.sh"