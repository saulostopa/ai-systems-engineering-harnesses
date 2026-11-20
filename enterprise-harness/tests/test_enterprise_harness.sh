#!/usr/bin/env bash
# test_enterprise_harness.sh — end-to-end tests for the orchestrator.
#
# Everything here runs against a real installation in a temp directory: install,
# adopt, plan, archive, aggregate. No mocks — the failures worth catching are
# the ones that only appear when the pieces are actually wired together.
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0; FAIL=0
_pass() { printf 'PASS %s\n' "$1"; PASS=$((PASS + 1)); }
_fail() { printf 'FAIL %s — %s\n' "$1" "$2"; FAIL=$((FAIL + 1)); }

# BSD sed (macOS) requires a backup suffix for in-place edits, while GNU sed
# accepts an empty suffix. Use a temporary backup so the suite behaves the same
# on both platforms.
replace_in_place() {
  sed -i.bak "$1" "$2" && rm -f "$2.bak"
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ROOT="$TMP/projects"
PREFIX="$ROOT/wm-harness"
mkdir -p "$ROOT"
WM="$PREFIX/bin/wm-harness"

new_repo() { mkdir -p "$ROOT/$1" && git -C "$ROOT/$1" init -q; }

# ── install ─────────────────────────────────────────────────────────────

t_install_creates_the_orchestrator() {
  # --projects is explicit so the test never scans the developer's real tree.
  bash "$SRC/install.sh" --prefix "$PREFIX" --projects "$ROOT" --no-link >/dev/null 2>&1
  if [ -x "$WM" ] && [ -f "$PREFIX/harness-basic/install.sh" ]; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "install did not produce a usable orchestrator"
  fi
}

t_install_refuses_to_clobber() {
  if bash "$SRC/install.sh" --prefix "$PREFIX" --projects "$ROOT" --no-link >/dev/null 2>&1; then
    _fail "${FUNCNAME[0]}" "reinstalled over an existing prefix without --force"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

t_doctor_passes_on_a_fresh_install() {
  "$WM" doctor >/dev/null 2>&1 \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "doctor failed right after install"
}

# ── adopt ───────────────────────────────────────────────────────────────

t_adopt_installs_layer_b() {
  new_repo alpha
  "$WM" adopt "$ROOT/alpha" >/dev/null 2>&1
  local missing=""
  for f in AGENTS.md feature_list.json progress.md .harness/config.yaml \
           docs/exec-plans/active docs/exec-plans/done scripts/validate-harness.sh; do
    [ -e "$ROOT/alpha/$f" ] || missing="$missing $f"
  done
  [ -z "$missing" ] && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "missing:$missing"
}

t_adopt_leaves_no_engine_in_the_repo() {
  # The whole point of layer B: control files, never the machinery.
  local junk=""
  for f in node_modules engine flows bin harness-basic; do
    [ -e "$ROOT/alpha/$f" ] && junk="$junk $f"
  done
  [ -z "$junk" ] && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "orchestrator machinery leaked into the repo:$junk"
}

t_adopt_rejects_an_unknown_flow() {
  new_repo bad
  if "$WM" adopt "$ROOT/bad" --flow does-not-exist >/dev/null 2>&1; then
    _fail "${FUNCNAME[0]}" "accepted a flow that does not exist"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

t_adopt_records_the_chosen_flow() {
  new_repo beta
  "$WM" adopt "$ROOT/beta" --flow hotfix >/dev/null 2>&1
  grep -q '^flow: hotfix' "$ROOT/beta/.harness/config.yaml" \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "config.yaml does not record the flow"
}

# ── discovery ───────────────────────────────────────────────────────────

t_discovery_finds_adopted_repos_only() {
  mkdir -p "$ROOT/not-adopted"
  local out; out="$("$WM" list 2>/dev/null)"
  if printf '%s' "$out" | grep -q 'alpha' &&
     printf '%s' "$out" | grep -q 'beta' &&
     ! printf '%s' "$out" | grep -q 'not-adopted'; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "discovery is wrong: $out"
  fi
}

# ── plans ───────────────────────────────────────────────────────────────

t_plan_new_seeds_from_the_flow() {
  # If the flow's steps do not reach the plan, a flow definition is decoration.
  ( cd "$ROOT/alpha" && "$WM" plan new feature/OEM-123 "First" >/dev/null 2>&1 )
  local p="$ROOT/alpha/docs/exec-plans/active/feature-OEM-123.md"
  if [ -f "$p" ] &&
     grep -q 'Declare the scope and open the feature' "$p" &&
     grep -q 'build green' "$p" &&
     grep -q '^status: not_started' "$p"; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "plan was not seeded from feature-default"
  fi
}

t_plan_id_keeps_the_branch_name_but_the_file_is_safe() {
  # The id is the branch name; the filename flattens the slash. If the id were
  # slugified too, the plan would stop matching the branch it belongs to.
  local p="$ROOT/alpha/docs/exec-plans/active/feature-OEM-123.md"
  if [ -f "$p" ] && grep -q '^id: feature/OEM-123$' "$p" &&
     [ ! -d "$ROOT/alpha/docs/exec-plans/active/feature" ]; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "slash handling is wrong: id or filename not as expected"
  fi
}

t_plan_new_uses_the_repos_own_flow() {
  ( cd "$ROOT/beta" && "$WM" plan new hotfix/AC-455 "Incident" >/dev/null 2>&1 )
  grep -q 'regression test fails before the fix' "$ROOT/beta/docs/exec-plans/active/hotfix-AC-455.md" \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "beta's plan did not use the hotfix flow"
}

t_plan_new_refuses_to_overwrite() {
  if ( cd "$ROOT/alpha" && "$WM" plan new feature/OEM-123 "Again" >/dev/null 2>&1 ); then
    _fail "${FUNCNAME[0]}" "overwrote an existing plan"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

t_plan_done_refuses_pending_evidence() {
  local p="$ROOT/alpha/docs/exec-plans/active/feature-OEM-123.md"
  replace_in_place 's/^| | | |$/| npm test | green | _pending_ |/' "$p"
  if ( cd "$ROOT/alpha" && "$WM" plan done feature/OEM-123 >/dev/null 2>&1 ); then
    _fail "${FUNCNAME[0]}" "archived a plan whose evidence was still pending"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

t_plan_done_requires_the_artifacts_the_flow_declares() {
  # feature-default declares a diagram. Without it the delivery is incomplete,
  # and the harness says so instead of trusting anyone to remember.
  local p="$ROOT/alpha/docs/exec-plans/active/feature-OEM-123.md"
  replace_in_place 's/| npm test | green | _pending_ |/| npm test | green | 4 passed |/' "$p"
  if ( cd "$ROOT/alpha" && "$WM" plan done feature/OEM-123 >/dev/null 2>&1 ); then
    _fail "${FUNCNAME[0]}" "archived a plan with no delivery artifacts"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

t_plan_done_names_each_missing_artifact() {
  # Producing the diagram must not make the other two disappear from the ask.
  mkdir -p "$ROOT/alpha/docs/artifacts"
  printf '<html>d</html>' > "$ROOT/alpha/docs/artifacts/feature-OEM-123.html"
  local out
  out="$( cd "$ROOT/alpha" && "$WM" plan done feature/OEM-123 2>&1 )"
  if printf '%s' "$out" | grep -q 'report'; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "after the diagram, the report was not demanded: $out"
  fi
}

t_hotfix_flow_owes_no_artifact() {
  # An incident should not wait on a diagram — the flow declares artifacts: [].
  local p="$ROOT/beta/docs/exec-plans/active/hotfix-AC-455.md"
  replace_in_place 's/^| | | |$/| pytest | regression red then green | 1 passed |/' "$p"
  if ( cd "$ROOT/beta" && "$WM" plan done hotfix/AC-455 >/dev/null 2>&1 ); then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "hotfix was blocked by an artifact it never owed"
  fi
}

t_plan_done_archives_and_sets_status() {
  local p="$ROOT/alpha/docs/exec-plans/active/feature-OEM-123.md"
  mkdir -p "$ROOT/alpha/docs/artifacts"
  printf '<html>rendered</html>' > "$ROOT/alpha/docs/artifacts/feature-OEM-123.html"
  printf '<html>report</html>'   > "$ROOT/alpha/docs/artifacts/feature-OEM-123-report.html"
  printf '<html>quiz</html>'     > "$ROOT/alpha/docs/artifacts/feature-OEM-123-quiz.html"
  ( cd "$ROOT/alpha" && "$WM" plan done feature/OEM-123 >/dev/null 2>&1 )
  local d="$ROOT/alpha/docs/exec-plans/done/feature-OEM-123.md"
  if [ -f "$d" ] && [ ! -f "$p" ] && grep -q '^status: done' "$d"; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "plan was not archived with status: done"
  fi
}

t_plan_outside_a_repo_fails_clearly() {
  if ( cd "$TMP" && "$WM" plan new feature/XYZ-1 "nope" >/dev/null 2>&1 ); then
    _fail "${FUNCNAME[0]}" "created a plan outside any adopted repository"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

# ── cross-project ───────────────────────────────────────────────────────

t_check_runs_every_repos_own_gate() {
  "$WM" check >/dev/null 2>&1 \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "check failed on healthy repos"
}

t_check_surfaces_a_broken_repo() {
  rm -f "$ROOT/beta/feature_list.json"
  if "$WM" check >/dev/null 2>&1; then
    _fail "${FUNCNAME[0]}" "check passed with a broken repository"
  else
    _pass "${FUNCNAME[0]}"
  fi
  "$WM" adopt "$ROOT/beta" --flow hotfix --force >/dev/null 2>&1
}

t_check_catches_a_flow_that_no_longer_exists() {
  replace_in_place 's/^flow: .*/flow: retired-flow/' "$ROOT/beta/.harness/config.yaml"
  if "$WM" check "$ROOT/beta" >/dev/null 2>&1; then
    _fail "${FUNCNAME[0]}" "accepted a config pointing at a flow the orchestrator does not have"
  else
    _pass "${FUNCNAME[0]}"
  fi
  replace_in_place 's/^flow: .*/flow: hotfix/' "$ROOT/beta/.harness/config.yaml"
}

t_report_aggregates_across_projects() {
  local out; out="$("$WM" report 2>/dev/null)"
  printf '%s' "$out" | grep -q 'TOTAL (2)' \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "report did not aggregate both projects: $out"
}

# ── the invariant ───────────────────────────────────────────────────────

t_deleting_the_orchestrator_loses_no_project_data() {
  # The rule the whole two-layer design rests on. If this test ever fails,
  # something started storing project state in layer A.
  rm -rf "$PREFIX"
  local d="$ROOT/alpha/docs/exec-plans/done/feature-OEM-123.md"
  if [ -f "$d" ] && grep -q '4 passed' "$d" &&
     [ -f "$ROOT/alpha/feature_list.json" ] &&
     bash "$ROOT/alpha/scripts/validate-harness.sh" >/dev/null 2>&1; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "a project lost information when the orchestrator was removed"
  fi
}

# Explicit order, not alphabetical: this is one end-to-end scenario — install,
# adopt, plan, archive, aggregate, then pull the orchestrator out from under it.
# Sorting the function names would run the teardown before the setup.
SEQUENCE=(
  t_install_creates_the_orchestrator
  t_install_refuses_to_clobber
  t_doctor_passes_on_a_fresh_install
  t_adopt_installs_layer_b
  t_adopt_leaves_no_engine_in_the_repo
  t_adopt_rejects_an_unknown_flow
  t_adopt_records_the_chosen_flow
  t_discovery_finds_adopted_repos_only
  t_plan_new_seeds_from_the_flow
  t_plan_id_keeps_the_branch_name_but_the_file_is_safe
  t_plan_new_uses_the_repos_own_flow
  t_plan_new_refuses_to_overwrite
  t_plan_done_refuses_pending_evidence
  t_plan_done_requires_the_artifacts_the_flow_declares
  t_plan_done_names_each_missing_artifact
  t_hotfix_flow_owes_no_artifact
  t_plan_done_archives_and_sets_status
  t_plan_outside_a_repo_fails_clearly
  t_check_runs_every_repos_own_gate
  t_check_surfaces_a_broken_repo
  t_check_catches_a_flow_that_no_longer_exists
  t_report_aggregates_across_projects
  t_deleting_the_orchestrator_loses_no_project_data
)

# A name in the file but not in the sequence would never run, and a green suite
# that silently skips a test is worse than a red one.
for fn in $(declare -F | awk '{print $3}' | grep '^t_'); do
  printf '%s\n' "${SEQUENCE[@]}" | grep -qx "$fn" \
    || { printf 'FAIL runner — test %s is not in SEQUENCE\n' "$fn"; FAIL=$((FAIL + 1)); }
done

for t in "${SEQUENCE[@]}"; do "$t"; done

printf '\n== %d/%d passed\n' "$PASS" "$((PASS + FAIL))"
[ "$FAIL" -eq 0 ]
