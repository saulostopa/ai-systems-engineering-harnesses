#!/usr/bin/env bash
# test_gatekeeper.sh — the pre-commit gatekeeper (Lesson 07).
#
# The bypass tests are the ones that matter. The flag age used to be read with
# `stat -c %Y`, which is GNU-only: on macOS it errored, the age came out wrong
# and the conscious 5-minute bypass never worked. Both bypass cases run on
# whatever `stat` the machine has, so a macOS run catches a GNU-only regression.
set -uo pipefail

GATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/gatekeeper.sh"
PASS=0; FAIL=0
_pass() { printf 'PASS %s\n' "$1"; PASS=$((PASS + 1)); }
_fail() { printf 'FAIL %s — %s\n' "$1" "$2"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A project with the gate installed and the given feature statuses.
make_repo() {
  local dir="$TMP/$1"; shift
  rm -rf "$dir"; mkdir -p "$dir/scripts" "$dir/.harness"
  cp "$GATE" "$dir/scripts/gatekeeper.sh"
  local features="" s
  for s in "$@"; do features="${features:+$features,}{\"id\":\"f\",\"status\":\"$s\"}"; done
  printf '{"features":[%s]}\n' "$features" > "$dir/feature_list.json"
  printf '%s\n' "$dir"
}

run_gate() { ( cd "$1" && bash scripts/gatekeeper.sh >/dev/null 2>&1; echo $? ); }

t_allows_one_feature_in_progress() {
  local d; d="$(make_repo a done in_progress todo)"
  [ "$(run_gate "$d")" = "0" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "blocked a commit with exactly one feature in_progress"
}

t_blocks_zero_features_in_progress() {
  local d; d="$(make_repo b done todo)"
  [ "$(run_gate "$d")" = "1" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "let a loose commit through"
}

t_blocks_two_features_in_progress() {
  local d; d="$(make_repo c in_progress in_progress)"
  [ "$(run_gate "$d")" = "1" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "let two parallel features through"
}

t_recent_bypass_allows() {
  # No feature in_progress, so only the bypass can let this through.
  local d; d="$(make_repo d todo)"
  touch "$d/.harness/skip-gatekeeper"
  [ "$(run_gate "$d")" = "0" ] \
    && _pass "${FUNCNAME[0]}" || _fail "${FUNCNAME[0]}" "a fresh bypass flag did not bypass"
}

t_expired_bypass_blocks_and_is_removed() {
  local d; d="$(make_repo e todo)"
  touch -t 202001010000 "$d/.harness/skip-gatekeeper"
  local rc; rc="$(run_gate "$d")"
  if [ "$rc" != "1" ]; then
    _fail "${FUNCNAME[0]}" "an expired bypass flag still bypassed (exit $rc)"
  elif [ -e "$d/.harness/skip-gatekeeper" ]; then
    _fail "${FUNCNAME[0]}" "the expired flag was left behind"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

for t in $(declare -F | awk '{print $3}' | grep '^t_' | sort); do "$t"; done

printf '\n== %d/%d passed\n' "$PASS" "$((PASS + FAIL))"
[ "$FAIL" -eq 0 ]
