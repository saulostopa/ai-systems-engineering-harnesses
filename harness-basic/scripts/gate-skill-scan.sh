#!/usr/bin/env bash
# gate-skill-scan.sh — skill installation gate (SkillSpector).
#
# Rule: no skill enters the repository without passing the scanner. A skill is
# code the agent runs with implicit trust — it is the cheapest supply chain
# surface to attack and the most expensive to audit later.
#
# Engine: NVIDIA/SkillSpector (Apache-2.0), pinned by tag and run in Docker so
# it does not depend on the local Python. Static analysis only (--no-llm): the
# verdict must be deterministic, reproducible in CI and valid offline.
#
# Usage:
#   gate-skill-scan.sh <target> [<target>...]   # directory, SKILL.md, .zip, git repo
#   gate-skill-scan.sh --all                    # every skill in the repository
#
# Exit: 0 = all approved · 1 = something rejected · 2 = execution error.
#
# Variables:
#   SKILL_GUARD_VERSION    SkillSpector tag (default: v2.11.2)
#   SKILL_GUARD_MAX_SCORE  maximum accepted score (default: 50 — the tool threshold)
#   SKILL_GUARD_WARN_SCORE score from which it warns (default: 20)
#   SKILL_GUARD_REPORTS    JSON reports directory (default: .harness/skill-scans)
#   SKILL_GUARD_TIMEOUT    deadline per target, in seconds (default: 900). Exceeding
#                          it blocks the target — the gate fails closed.
set -uo pipefail

VERSION="${SKILL_GUARD_VERSION:-v2.11.2}"
# Supply chain pin: the tag above must point to this commit. A rewritten remote
# tag changes the scanner without changing its name — the gate refuses if it diverges.
PINNED_SHA="69dcdfb74487d361ba4c811d088cfdea2ff3a9dc"
IMAGE="skillspector:${VERSION}"
REPO_URL="https://github.com/NVIDIA/SkillSpector.git"

MAX_SCORE="${SKILL_GUARD_MAX_SCORE:-50}"
WARN_SCORE="${SKILL_GUARD_WARN_SCORE:-20}"
TIMEOUT="${SKILL_GUARD_TIMEOUT:-900}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# When installed in a target project, the scan root is the project root.
SCAN_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
REPORTS="${SKILL_GUARD_REPORTS:-$SCAN_ROOT/.harness/skill-scans}"

# Baselines and the fixture allowlist live OUTSIDE the scanned tree, at the
# project root. Inside the skill directory, both would be controlled by the
# entity the gate is supposed to be measuring.
BASELINES="${SKILL_GUARD_BASELINES:-$SCAN_ROOT/.harness/baselines}"
FIXTURES_ALLOW="${SKILL_GUARD_FIXTURES:-$SCAN_ROOT/.harness/skill-guard-fixtures}"

ok()    { printf '  [ok]     %s\n' "$1"; }
warn()  { printf '  [warn]   %s\n' "$1"; }
block() { printf '  [BLOCK]  %s\n' "$1"; }
# Sourced (by the tests), `fail` returns instead of exiting: otherwise a single
# test calling a fallible function would take down the whole runner.
fail()  {
  printf '[skill-guard] ERROR: %s\n' "$1" >&2
  [ "${BASH_SOURCE[0]}" != "${0}" ] && return 2
  exit 2
}
section() { printf '\n== %s ==\n' "$1"; }

TMPDIR_RUN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RUN"' EXIT

# The thresholds come in through the environment and go straight into `[ -gt ]`.
# A non-integer value makes the test error, both branches return false and the
# target falls into the else — approved. Validating here is what stops
# `SKILL_GUARD_MAX_SCORE=abc` from silently disarming the gate.
require_int() {
  case "$2" in
    ''|*[!0-9]*) fail "$1 must be an integer from 0 to 100 — received: '$2'" ;;
  esac
  [ "$2" -le 100 ] || fail "$1 must be <= 100 — received: '$2'"
}
require_int SKILL_GUARD_MAX_SCORE  "$MAX_SCORE"
require_int SKILL_GUARD_WARN_SCORE "$WARN_SCORE"
[ "$WARN_SCORE" -le "$MAX_SCORE" ] \
  || fail "SKILL_GUARD_WARN_SCORE ($WARN_SCORE) cannot be greater than SKILL_GUARD_MAX_SCORE ($MAX_SCORE)"
case "$TIMEOUT" in
  ''|*[!0-9]*) fail "SKILL_GUARD_TIMEOUT must be an integer number of seconds — received: '$TIMEOUT'" ;;
esac

# `realpath --relative-to` is from GNU coreutils. On BSD/macOS/busybox it does
# not exist, `rel` would come out empty and the scan would become `scan ./` —
# the whole repository instead of the skill, diluting exactly the target that
# was meant to be measured.
command -v realpath >/dev/null 2>&1 \
  || fail "realpath missing — the gate requires GNU coreutils"
realpath --relative-to=/ / >/dev/null 2>&1 \
  || fail "realpath without --relative-to (non-GNU) — the gate requires GNU coreutils"

# --- engine ------------------------------------------------------------------

ensure_image() {
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    return 0
  fi
  command -v docker >/dev/null 2>&1 \
    || { fail "docker missing — install docker or run skillspector natively"; return 2; }
  printf '[skill-guard] image %s missing — building from %s#%s (1-2 min)\n' "$IMAGE" "$REPO_URL" "$VERSION"
  docker build -q -t "$IMAGE" "${REPO_URL}#${VERSION}" >/dev/null \
    || { fail "failed to build the SkillSpector image"; return 2; }
  ok "image built: $IMAGE"
}

# Confirms the tag still points to the pinned commit. Without network, warns
# and proceeds — the local image was already built from a previously verified pin.
verify_pin() {
  local refs sha
  # Annotated tag resolves to refs/tags/X^{} (the commit); lightweight tag only
  # has refs/tags/X. We ask for both and keep the peeled form when it exists.
  refs="$(git ls-remote "$REPO_URL" "refs/tags/${VERSION}" "refs/tags/${VERSION}^{}" 2>/dev/null)"
  sha="$(printf '%s\n' "$refs" | awk '/\^\{\}$/ {print $1; found=1} END {exit !found}')" \
    || sha="$(printf '%s\n' "$refs" | awk 'NR==1 {print $1}')"
  if [ -z "$sha" ]; then
    warn "could not verify the pin (no network?) — using the local image $IMAGE"
    return 0
  fi
  if [ "$sha" != "$PINNED_SHA" ]; then
    block "pin diverged: ${VERSION} points to ${sha}, expected ${PINNED_SHA}"
    fail "the SkillSpector tag was rewritten — review before trusting the scanner"
    return 2   # `fail` only exits when the script is executed; sourced it
               # returns, and without this `return` the function would go on
               # and say "pin confirmed" right after detecting the divergence.
  fi
  ok "pin confirmed: ${VERSION} = ${PINNED_SHA:0:12}"
}

# Runs the scanner on a target and returns the JSON on stdout.
# The timeout is part of the gate, not a convenience: a large package (many
# files, thousands-of-lines examples) takes minutes, and a scan that never
# returns would be a gate that never blocks. Exceeding the deadline fails
# CLOSED — whoever handles the empty output blocks the target.
scan_target() {
  local target="$1" rel cname rc base=()
  cname="skillguard-$$-${RANDOM}"

  # The baseline is looked up in .harness/baselines/<slug>.yaml, OUTSIDE the
  # scanned tree, and never inside the target. A baseline living inside the
  # skill is controlled by the skill itself: a hostile author would only need
  # to iterate the scanner until writing a YAML that suppresses all their own
  # findings, and the gate would start measuring what the attacker wants.
  # "It stays reviewable in PR" does not save — the same PR that brings the
  # skill brings the baseline.
  # Being outside also makes the baseline apply to the `<skill>/SKILL.md`
  # target, not just the directory target: the key is the slug, not the path form.
  local slug bmount=()
  slug="$(report_slug "$1")"
  # File target (`<skill>/SKILL.md`) inherits the baseline of the skill
  # directory: otherwise the same content would have two verdicts, one per
  # calling form.
  [ -f "$BASELINES/$slug.yaml" ] || { [ -f "$1" ] && slug="$(report_slug "$(dirname "$1")")"; }
  if [ -f "$BASELINES/$slug.yaml" ]; then
    base=(--baseline "/baselines/$slug.yaml")
    bmount=(-v "$BASELINES:/baselines:ro")
  fi

  # `-s KILL` is not overkill, it is what makes the deadline count. The docker
  # client ignores SIGTERM: with the default signal `timeout` returns 124 at
  # the deadline but the scan keeps going to the end and writes the full
  # report — a deadline that limits nothing. With SIGKILL the client dies at
  # the agreed second, the output comes out empty or truncated and the caller
  # blocks the target.
  # `--sig-proxy=false` stops the signal from being forwarded to the process
  # inside the container instead of the client; `docker rm -f` drops the orphan
  # container.
  # Output goes to a file, not a command substitution. With `$(...)` the gate
  # waits for the stdout to CLOSE: if the docker client dies at the deadline
  # leaving an orphan child holding the pipe open, the gate hangs far beyond
  # the timeout — verified with a fake docker, which held it for 600s. Reading
  # from a file, the deadline holds: whatever is written is what is read, and
  # truncated blocks.
  local outf="$TMPDIR_RUN/scan.$cname.json"
  if [ -e "$target" ]; then
    # Local path: mounts the repo root and references the target relative to it.
    rel="$(realpath --relative-to="$SCAN_ROOT" "$target")"
    timeout -s KILL "$TIMEOUT" docker run --rm --name "$cname" --sig-proxy=false \
      -v "$SCAN_ROOT:/scan:ro" ${bmount[@]+"${bmount[@]}"} "$IMAGE" \
      scan "./$rel" --no-llm --format json ${base[@]+"${base[@]}"} >"$outf" 2>/dev/null
  else
    # Git repo URL or zip: the scanner fetches it by itself, without mounting anything.
    timeout -s KILL "$TIMEOUT" docker run --rm --name "$cname" --sig-proxy=false \
      "$IMAGE" scan "$target" --no-llm --format json >"$outf" 2>/dev/null
  fi
  rc=$?
  cat "$outf" 2>/dev/null
  rm -f "$outf" 2>/dev/null

  # 124 = deadline exceeded. The container survives the dead client: drop it.
  if [ "$rc" -ge 124 ]; then
    docker rm -f "$cname" >/dev/null 2>&1
  fi
}

# --- verdict ----------------------------------------------------------------

# Reads the scanner JSON and prints: score|severity|recommendation|n_issues|complete|worst
read_verdict() {
  python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print("ERRO|%s" % e)
    sys.exit(3)
r = d.get("risk_assessment", {})
c = d.get("analysis_completeness", {})
print("|".join([
    str(r.get("score", "?")),
    str(r.get("severity", "?")),
    str(r.get("recommendation", "?")),
    str(len(d.get("issues", []))),
    str(c.get("status", "?")),
    str(r.get("max_issue_severity", "NONE")),
    str(d.get("metadata", {}).get("skillspector_version", "?")),
]))
'
}

# Report name: derived from the PATH, not the basename. .claude/skills/agenfk
# and .agents/skills/agenfk are two distinct copies of the same skill and each
# one needs its own report — with basename the second would overwrite the first.
# Leading dots drop too: skills live in .claude/ and .agents/, and without this
# the report would become a hidden file — an `ls` of the reports directory
# would show nothing, which is the same as having no report.
report_slug() {
  printf '%s' "${1#"$SCAN_ROOT"/}" | tr -c 'A-Za-z0-9._-' '-' | sed 's/^[.-]*//;s/[.-]*$//'
}

# --- discovery --------------------------------------------------------------

# Discovers the repository skills, skipping the deliberately bad fixtures
# (they exist to prove the gate blocks).
#
# The allowlist lives in .harness/skill-guard-fixtures, at the ROOT — never a
# marker inside the skill directory. An internal marker is controlled by the
# skill itself: a hostile PR would only need to bring `SKILL.md` + the marker
# for the skill to vanish from `--all` without being approved or blocked.
# Saying the marker is "reviewable in PR" is circular — it is the same PR.
#
# Format: one path relative to the root per line; `#` comments it out.
is_fixture() {
  local rel line
  [ -f "$FIXTURES_ALLOW" ] || return 1
  rel="${1#"$SCAN_ROOT"/}"
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | tr -d '[:space:]')"
    [ -n "$line" ] || continue
    [ "$line" = "$rel" ] && return 0
  done < "$FIXTURES_ALLOW"
  return 1
}

discover_skills() {
  local dir
  find "$SCAN_ROOT" -name SKILL.md \
    -not -path '*/node_modules/*' \
    -not -path '*/.git/*' \
    -print0 | xargs -0 -n1 dirname | sort -u | while IFS= read -r dir; do
      is_fixture "$dir" || printf '%s\n' "$dir"
    done
}

# --- verdict recording ------------------------------------------------------

# Writes the skill scanVerdict into skills-lock.json. Without this, the
# validate-harness message ("run the gate and record the verdict") would point
# at a flow that does not exist, and the lock could only be edited by hand.
# Only records skills already declared in the lock: the gate checks verdicts,
# it does not decide what a third-party dependency is.
record_verdict() {
  local target="$1" json="$2" lock="$SCAN_ROOT/skills-lock.json" name
  name="$(basename "$target")"
  [ -f "$lock" ] || { warn "$name — skills-lock.json not found; verdict not recorded"; return 0; }
  LOCK_PATH="$lock" SKILL_NAME="$name" SCANNER="skillspector@$VERSION" PIN="$PINNED_SHA" \
  python3 -c '
import json, os, sys, datetime
lock_path = os.environ["LOCK_PATH"]
name = os.environ["SKILL_NAME"]
rep = json.load(sys.stdin)
with open(lock_path) as fh:
    lock = json.load(fh)
entry = lock.get("skills", {}).get(name)
if entry is None:
    sys.exit(3)  # not declared in the lock — nothing to record
r = rep.get("risk_assessment", {})
# Merges, does not replace: what the scanner measured is updated, and what a
# person wrote while triaging (decision, notes, rawScore, baseline...) stays.
# A re-scan that wiped the triage would destroy the only auditable part of
# the verdict.
verdict = dict(entry.get("scanVerdict") or {})
verdict.update({
    "scanner": os.environ["SCANNER"],
    "scannerCommit": os.environ["PIN"],
    "mode": "static",
    "scannedAt": datetime.date.today().isoformat(),
    "score": r.get("score"),
    "severity": r.get("severity"),
    "issues": len(rep.get("issues", [])),
    "suppressed": rep.get("suppressed_count", 0),
    "coverage": rep.get("analysis_completeness", {}).get("status"),
})
entry["scanVerdict"] = verdict
with open(lock_path, "w") as fh:
    json.dump(lock, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
' <<< "$json"
  case "$?" in
    0) ok "$name — scanVerdict recorded in skills-lock.json" ;;
    3) : ;;  # skill not declared in the lock: silence, not an error
    *) warn "$name — failed to record the scanVerdict" ;;
  esac
}

# --- main -------------------------------------------------------------------

# Only runs when the script is invoked; sourced, it exposes the functions to
# the test (harness-basic/tests/test_skill_guard.sh) without firing any scan.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
  return 0
fi

TARGETS=()
RECORD=0
ONLY_TARGETS=0   # after `--`, everything is a target (allows targets starting with `-`)
for arg in "$@"; do
  if [ "$ONLY_TARGETS" = 1 ]; then TARGETS+=("$arg"); continue; fi
  case "$arg" in
    --)       ONLY_TARGETS=1 ;;
    --all)    while IFS= read -r d; do TARGETS+=("$d"); done < <(discover_skills) ;;
    --record) RECORD=1 ;;   # writes the scanVerdict of scanned skills into skills-lock.json
    -*)       fail "unknown option: $arg (use \`--\` before a target that starts with a hyphen)" ;;
    *)        TARGETS+=("$arg") ;;
  esac
done

[ "${#TARGETS[@]}" -gt 0 ] || {
  echo "Usage: gate-skill-scan.sh <target> [<target>...] | --all"
  exit 2
}

section "SkillSpector ${VERSION} — skill installation gate"
verify_pin
ensure_image
mkdir -p "$REPORTS" || fail "could not create the reports directory: $REPORTS"

BLOCKED=0
WARNED=0
PASSED=0

section "Scan (${#TARGETS[@]} target(s), static)"
for target in "${TARGETS[@]}"; do
  name="$(basename "$target")"
  report="$REPORTS/$(report_slug "$target").json"

  # A baseline inside the target is an attempt to rewrite its own verdict: the
  # gate does not use it (it only reads from .harness/baselines/) and blocks
  # the target, instead of silently ignoring it — whoever put it there needs
  # to know it was seen.
  if [ -d "$target" ] && [ -f "$target/.skillspector-baseline.yaml" ]; then
    block "$name — baseline inside the skill directory ($target/.skillspector-baseline.yaml); move it to $BASELINES/$(report_slug "$target").yaml and review"
    BLOCKED=$((BLOCKED + 1))
    continue
  fi

  # Scanning only the SKILL.md of a skill that has other files measures the
  # text and ignores the scripts that ship with it — a 0/100 there is not
  # "clean", it is smaller scope. The gate does not refuse (the contract
  # accepts a file), but it says what was left out, because the number alone
  # is misleading.
  if [ -f "$target" ]; then
    outros="$(find "$(dirname "$target")" -type f ! -name "$(basename "$target")" 2>/dev/null | wc -l)"
    [ "$outros" -eq 0 ] || warn "$name — target is a file; $outros other file(s) in the directory did NOT enter the scan"
  fi

  json="$(scan_target "$target")"
  if [ -z "$json" ]; then
    block "$name — no report (timeout of ${TIMEOUT}s or scanner failure) — blocked by precaution"
    BLOCKED=$((BLOCKED + 1))
    continue
  fi
  printf '%s' "$json" > "$report" \
    || warn "$name — could not write the report to $report (verdict below still valid)"

  verdict="$(printf '%s' "$json" | read_verdict)"
  case "$verdict" in
    ERRO*) block "$name — unreadable report: ${verdict#ERRO|}"; BLOCKED=$((BLOCKED + 1)); continue ;;
  esac

  IFS='|' read -r score severity recommendation issues complete worst _ver <<< "$verdict"

  label="$name — score ${score}/100 (${severity}), ${issues} finding(s), coverage ${complete}"

  # Non-numeric score blocks. Without this guard the `-gt` below errors
  # ("integer expression expected"), both branches return false and the target
  # falls into the else — that is, a report without a score would be APPROVED.
  # Gates must fail closed.
  case "$score" in
    ''|*[!0-9]*)
      block "$name — report has no usable score ('${score}') — blocked by precaution"
      printf '           report: %s\n' "$report"
      BLOCKED=$((BLOCKED + 1))
      continue
      ;;
  esac

  # Recording comes after the numeric guard and never for a blocked target:
  # the lock is the record of what was approved. Writing the verdict of a
  # rejected skill would make it satisfy the validate-harness check — "has a
  # scanVerdict" must not become a synonym for "passed".
  [ "$RECORD" = 1 ] && [ "$score" -le "$MAX_SCORE" ] && record_verdict "$target" "$json"

  if [ "$score" -gt "$MAX_SCORE" ]; then
    block "$label — worst finding: ${worst}"
    printf '           report: %s\n' "$report"
    BLOCKED=$((BLOCKED + 1))
  elif [ "$score" -gt "$WARN_SCORE" ]; then
    warn "$label — review before installing"
    printf '           report: %s\n' "$report"
    WARNED=$((WARNED + 1))
  else
    ok "$label"
    PASSED=$((PASSED + 1))
  fi
done

section "Result"
printf 'threshold: blocks score > %s · warns score > %s · mode: static (--no-llm)\n' "$MAX_SCORE" "$WARN_SCORE"
printf 'reports: %s\n' "$REPORTS"
printf '\n%s — %d passed, %d warned, %d blocked\n' \
  "$( [ "$BLOCKED" -eq 0 ] && echo "SKILL GUARD OK" || echo "SKILL GUARD BLOCKED" )" \
  "$PASSED" "$WARNED" "$BLOCKED"

# A clean static scan is not the same as an audited skill: static mode does
# not judge intent. The verdict below covers known patterns, not semantics.
[ "$BLOCKED" -eq 0 ] || exit 1
exit 0
