#!/usr/bin/env bash
# test_e2e_gate.sh — the E2E gate (Lesson 10).
#
# The test that matters here is the third one. The gate's config parser used to
# anchor on the end of the line, so an inline comment made the pattern miss and
# the variable became the whole line — the gate matched nothing and printed
# "ok". A gate that waves everything through while reporting success is worse
# than no gate, and nothing would have caught it except a test that puts a
# comment in the config.
set -uo pipefail

GATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/e2e-gate.sh"
PASS=0; FAIL=0
_pass() { printf 'PASS %s\n' "$1"; PASS=$((PASS + 1)); }
_fail() { printf 'FAIL %s — %s\n' "$1" "$2"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A repo with the gate installed and a given qa: block.
make_repo() {
  local dir="$TMP/$1"; shift
  rm -rf "$dir"; mkdir -p "$dir/scripts" "$dir/.harness" "$dir/src" "$dir/e2e"
  git -C "$dir" init -q
  git -C "$dir" config user.email t@t; git -C "$dir" config user.name t
  cp "$GATE" "$dir/scripts/e2e-gate.sh"
  printf 'name: t\nqa:\n%s\n' "$1" > "$dir/.harness/config.yaml"
  printf '%s\n' "$dir"
}

run_gate() { ( cd "$1" && bash scripts/e2e-gate.sh >/dev/null 2>&1; echo $? ); }

PLAIN='  frontend_paths: "src"
  frontend_extensions: "tsx ts"
  e2e_test_path: "e2e"'

COMMENTED='  frontend_paths: "src"     # e.g. "src" or "src|app"
  frontend_extensions: "tsx ts" # e.g. "tsx ts jsx js"
  e2e_test_path: "e2e"      # e.g. "tests/e2e"'

t_allows_when_no_frontend_is_staged() {
  local d; d="$(make_repo a "$PLAIN")"
  [ "$(run_gate "$d")" = "0" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "blocked a commit with nothing staged"
}

t_blocks_frontend_without_an_e2e_test() {
  local d; d="$(make_repo b "$PLAIN")"
  echo 'export const A = 1' > "$d/src/a.tsx"
  git -C "$d" add src/a.tsx
  [ "$(run_gate "$d")" = "1" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "let a frontend change through with no E2E test"
}

t_blocks_the_same_way_with_inline_comments() {
  # The regression. Identical config, comments appended.
  local d; d="$(make_repo c "$COMMENTED")"
  echo 'export const A = 1' > "$d/src/a.tsx"
  git -C "$d" add src/a.tsx
  [ "$(run_gate "$d")" = "1" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "an inline comment silently disabled the gate"
}

t_allows_when_the_e2e_test_comes_along() {
  local d; d="$(make_repo e "$COMMENTED")"
  echo 'export const A = 1' > "$d/src/a.tsx"
  echo 'def test_a(): pass' > "$d/e2e/test_a.py"
  git -C "$d" add src/a.tsx e2e/test_a.py
  [ "$(run_gate "$d")" = "0" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "blocked a change that did bring its test"
}

t_fails_open_when_qa_is_left_empty() {
  # Absent config is a choice: a project with no frontend pays nothing.
  local d; d="$(make_repo f '  frontend_paths: ""
  frontend_extensions: ""
  e2e_test_path: ""')"
  echo 'export const A = 1' > "$d/src/a.tsx"
  git -C "$d" add src/a.tsx
  [ "$(run_gate "$d")" = "0" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "blocked a project that never opted in"
}

t_blocks_when_the_config_cannot_be_parsed() {
  # Unparseable config is a mistake, and a mistake must not read as "ok".
  local d; d="$(make_repo g '  frontend_paths: "src
  frontend_extensions: "tsx"
  e2e_test_path: "e2e"')"
  echo 'export const A = 1' > "$d/src/a.tsx"
  git -C "$d" add src/a.tsx
  [ "$(run_gate "$d")" = "1" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "a broken config failed open"
}

t_fails_open_without_any_config() {
  local d; d="$(make_repo h "$PLAIN")"
  rm -f "$d/.harness/config.yaml"
  [ "$(run_gate "$d")" = "0" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "blocked a repo with no .harness/config.yaml"
}

for t in $(declare -F | awk '{print $3}' | grep '^t_' | sort); do "$t"; done

printf '\n== %d/%d passed\n' "$PASS" "$((PASS + FAIL))"
[ "$FAIL" -eq 0 ]
