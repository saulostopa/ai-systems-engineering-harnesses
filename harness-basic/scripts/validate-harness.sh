#!/usr/bin/env bash
# validate-harness.sh — health check of the installed harness (Lesson 11).
# Exits non-zero if the harness is broken. Modeled on the factory.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FAILURES=0
WARNINGS=0

# Two places this script legitimately runs from:
#   - a project it was installed into, where the harness files sit next to it;
#   - the harness-basic package itself, where they are still in templates/
#     waiting to be copied.
# Checking $ROOT in the second case reports eight missing files that are not
# missing — and a health check that cries wolf is a health check people learn
# to ignore. So detect the package and validate the payload it will install.
if [ -f "$ROOT/install.sh" ] && [ -d "$ROOT/templates" ]; then
  MODE="package"
  HARNESS="$ROOT/templates"
else
  MODE="installed"
  HARNESS="$ROOT"
fi

ok()   { printf '  [ok]     %s\n' "$1"; }
warn() { printf '  [warn]   %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '  [FAIL]   %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
section() { printf '\n== %s ==\n' "$1"; }
require_file() {
  if [ -f "$HARNESS/$1" ]; then ok "present: $1"; else fail "missing: $1"; fi
}

if [ "$MODE" = "package" ]; then
  printf 'Validating the harness-basic PACKAGE payload (templates/)\n'
else
  printf 'Validating the harness installed in: %s\n' "$HARNESS"
fi

section "Required files"
for f in AGENTS.md feature_list.json progress.md session-handoff.md init.sh; do
  require_file "$f"
done
if [ "$MODE" = "package" ]; then
  require_file "exec-plan.md"
else
  require_file "docs/exec-plans/TEMPLATE.md"
fi
require_file "policies/definition-of-done.md"
require_file "policies/scope-control.md"
require_file "policies/evidence-required.md"
require_file "policies/git-worktrees.md"

section "feature_list.json"
FEATURE_LIST="$HARNESS/feature_list.json"
if [ -f "$FEATURE_LIST" ]; then
  if command -v node >/dev/null 2>&1; then
    node -e "
      const f = require(process.argv[1]);
      if (!Array.isArray(f.features)) throw new Error('features array missing');
      const states = ['not_started','in_progress','blocked','passing'];
      const bad = f.features.filter(x => !states.includes(x.status));
      if (bad.length) throw new Error('invalid states: ' + bad.map(b=>b.id).join(','));
      const act = f.features.filter(x => x.status==='in_progress').length;
      if (act > 1) throw new Error(act + ' features in_progress (max 1)');
      console.log('  [ok]     valid JSON; ' + f.features.length + ' features; ' + act + ' in_progress');
    " "$FEATURE_LIST" 2>/dev/null && : || { node -e "
      const f = require(process.argv[1]);
      const states = ['not_started','in_progress','blocked','passing'];
      const bad = f.features.filter(x => !states.includes(x.status));
      const act = f.features.filter(x => x.status==='in_progress').length;
      if (bad.length) console.error('invalid states: ' + bad.map(b=>b.id).join(','));
      if (act > 1) console.error(act + ' features in_progress');
      process.exit(1);
    " "$FEATURE_LIST" 2>&1 | sed 's/^/  [FAIL]   /'; FAILURES=$((FAILURES + 1)); }
  else
    warn "node missing — JSON validation skipped"
  fi
fi

section "Installed skills (skill-guard)"
# Cheap check: every declared skill must carry the verdict that approved it.
# The scan itself runs in gate-skill-scan.sh — building the scanner image on
# every health check would be too slow to be usable.
# Installed in a target project, the lock sits next to this directory. In this
# repo (harness-basic is a subfolder) it sits at the git root — without this
# fallback the check would be inert exactly where the skills live.
# SKILL_GUARD_LOCK exists so tests can point the check at a fixture lock and
# exercise THIS script, instead of reimplementing the logic inside the test.
LOCK="${SKILL_GUARD_LOCK:-$ROOT/skills-lock.json}"
[ -f "$LOCK" ] || LOCK="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)/skills-lock.json"

if [ -f "$LOCK" ]; then
  if command -v node >/dev/null 2>&1; then
    # Node prints a single line: "OK <n>" or "SEM <names>". The names of the
    # skills without a verdict are the only actionable info of the failure, so
    # they must survive into the message — they cannot be discarded.
    LOCK_OUT="$(node -e "
      const l = require(process.argv[1]);
      const skills = Object.entries(l.skills || {});
      const sem = skills.filter(([,s]) => !s.scanVerdict).map(([n]) => n);
      // Presence is not enough: a verdict above the threshold recorded in the
      // lock would make has-scanVerdict a synonym of passed-the-gate.
      const MAX = Number(process.env.SKILL_GUARD_MAX_SCORE || 50);
      const ruins = skills
        .filter(([,s]) => s.scanVerdict && Number(s.scanVerdict.score) > MAX)
        .map(([n,s]) => n + ' (' + s.scanVerdict.score + '/100)');
      if (sem.length) { console.log('SEM ' + sem.join(', ')); }
      else if (ruins.length) { console.log('RUIM ' + ruins.join(', ')); }
      else { console.log('OK ' + skills.length); }
    " "$LOCK" 2>/dev/null)"
    case "${LOCK_OUT:-}" in
      "OK 0")  ok "no third-party skill declared" ;;
      "OK "*)  ok "${LOCK_OUT#OK } skill(s) with a recorded scanVerdict" ;;
      "SEM "*)  fail "no scanVerdict in skills-lock.json: ${LOCK_OUT#SEM } — run scripts/gate-skill-scan.sh --record and record the verdict" ;;
      "RUIM "*) fail "scanVerdict above the threshold in skills-lock.json: ${LOCK_OUT#RUIM } — the skill did not pass the gate" ;;
      *)       fail "skills-lock.json unreadable or invalid" ;;
    esac
  else
    warn "node missing — scanVerdict check skipped"
  fi
else
  ok "no skills-lock.json (no third-party skill installed)"
fi

section "Local patches on third-party skills"
# A local patch only counts while applied. Reinstalling the skill silently
# discards it — and without this check skills-lock.json would keep claiming a
# fix that no longer exists. Each patch declares what must be present
# (verifyContains) and what must not come back (verifyAbsent).
if [ -f "$LOCK" ] && command -v node >/dev/null 2>&1; then
  PATCH_OUT="$(node -e "
    const l = require(process.argv[1]);
    const fs = require('fs'), path = require('path');
    const root = path.dirname(process.argv[1]);
    const out = [];
    let n = 0;
    for (const [name, s] of Object.entries(l.skills || {})) {
      for (const p of (s.localPatches || [])) {
        n++;
        const f = path.join(root, p.verifyFile || '');
        if (!p.verifyFile || !fs.existsSync(f)) { out.push(name + ': file missing (' + p.verifyFile + ')'); continue; }
        const txt = fs.readFileSync(f, 'utf8');
        if (p.verifyContains && !txt.includes(p.verifyContains)) out.push(name + ': patch lost — missing ' + p.verifyContains);
        else if (p.verifyAbsent && txt.includes(p.verifyAbsent)) out.push(name + ': patch reverted — ' + p.verifyAbsent + ' is back');
      }
    }
    console.log(out.length ? 'QUEBRADO ' + out.join('; ') : 'OK ' + n);
  " "$LOCK" 2>/dev/null)"
  case "${PATCH_OUT:-}" in
    "OK 0")       ok "no local patch declared" ;;
    "OK "*)       ok "${PATCH_OUT#OK } local patch(es) still applied" ;;
    "QUEBRADO "*) fail "${PATCH_OUT#QUEBRADO } — reapply the patch and run scripts/gate-skill-scan.sh" ;;
    *)            warn "could not verify the local patches" ;;
  esac
elif [ -f "$LOCK" ]; then
  # Without node this section would go silent, and silence in a health check
  # reads as approval — the patch could vanish without anyone noticing.
  warn "node missing — local patch check skipped"
else
  ok "no skills-lock.json (no local patch to verify)"
fi

section "Execution plans"
# The directory is a context budget; the front-matter is the truth. Two sources
# that can disagree eventually will, so the gate reconciles them: a plan's
# location must match its declared status, and a plan cannot claim `done`
# without evidence. Archiving stops being a convention somebody remembers.
PLANS_DIR="${EXEC_PLANS_DIR:-$HARNESS/docs/exec-plans}"
if [ -d "$PLANS_DIR" ]; then
  PLAN_N=0
  PLAN_BAD=0
  for phase in active done; do
    [ -d "$PLANS_DIR/$phase" ] || continue
    for plan in "$PLANS_DIR/$phase"/*.md; do
      [ -e "$plan" ] || continue
      PLAN_N=$((PLAN_N + 1))
      # status: from the front-matter only (first 20 lines), never the path.
      status="$(sed -n '1,20p' "$plan" | sed -n 's/^status:[[:space:]]*\([A-Za-z_]*\).*/\1/p' | head -1)"
      if [ -z "$status" ]; then
        fail "$plan: no 'status:' in the front-matter"
        PLAN_BAD=$((PLAN_BAD + 1))
        continue
      fi
      case "$phase:$status" in
        active:done)
          fail "$plan: status is 'done' but the plan is still in active/ — move it to $PLANS_DIR/done/"
          PLAN_BAD=$((PLAN_BAD + 1)) ;;
        done:done)
          if ! grep -qiE '^#+[[:space:]]*(evidence|evid.ncia)' "$plan"; then
            fail "$plan: marked 'done' with no evidence section"
            PLAN_BAD=$((PLAN_BAD + 1))
          fi ;;
        done:*)
          fail "$plan: filed under done/ but status is '$status'"
          PLAN_BAD=$((PLAN_BAD + 1)) ;;
      esac
    done
  done
  if [ "$PLAN_N" -eq 0 ]; then
    ok "$PLANS_DIR/ present, no plan yet"
  elif [ "$PLAN_BAD" -eq 0 ]; then
    ok "$PLAN_N execution plan(s) checked (location matches status)"
  fi
else
  ok "no $PLANS_DIR/ (optional until the enterprise layer)"
fi

section "Hooks"
if [ "$MODE" = "package" ]; then
  # Nothing has been installed yet: what matters is that the payload exists.
  if [ -d "$ROOT/.githooks" ]; then
    ok ".githooks/ present in the package (installed by install.sh)"
  else
    fail ".githooks/ missing from the package — install.sh would enable nothing"
  fi
else
  HOOKS=$(git config core.hooksPath 2>/dev/null || echo "")
  if [ "$HOOKS" = ".githooks" ]; then
    ok "core.hooksPath = .githooks"
  else
    warn "core.hooksPath = ${HOOKS:-not configured} (run: git config core.hooksPath .githooks)"
  fi
fi

# A template that install.sh never copies is a template that does not exist for
# anyone but us — the failure is silent, which is the worst kind.
if [ "$MODE" = "package" ]; then
  section "install.sh covers the payload"
  MISSED=""
  for t in "$HARNESS"/*; do
    [ -e "$t" ] || continue
    name="$(basename "$t")"
    [ "$name" = "README.md" ] && continue
    grep -q -- "$name" "$ROOT/install.sh" || MISSED="$MISSED $name"
  done
  if [ -n "$MISSED" ]; then
    fail "templates never installed by install.sh:$MISSED"
  else
    ok "every template is referenced by install.sh"
  fi
fi

section "Result"
printf '\n%s — %d failure(s), %d warning(s)\n' "$( [ "$FAILURES" -eq 0 ] && echo "HARNESS OK" || echo "HARNESS BROKEN" )" "$FAILURES" "$WARNINGS"
exit "$FAILURES"
