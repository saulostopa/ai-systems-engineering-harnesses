#!/usr/bin/env bash
# test_skill_guard.sh — tests for the skill installation gate.
#
# Logic tests (verdict, discovery, report naming) always run. The ones that
# exercise the real scanner need the Docker image and are skipped with a
# warning when it is absent — but they never pass silently.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$ROOT/scripts/gate-skill-scan.sh"
REPO="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0; SKIP=0
_pass() { printf 'PASS %s\n' "$1"; PASS=$((PASS + 1)); }
_fail() { printf 'FAIL %s — %s\n' "$1" "$2"; FAIL=$((FAIL + 1)); }
_skip() { printf 'SKIP %s — %s\n' "$1" "$2"; SKIP=$((SKIP + 1)); }

# shellcheck source=../scripts/gate-skill-scan.sh
source "$GATE"

has_image() { docker image inspect "$IMAGE" >/dev/null 2>&1; }

# --- verdict ----------------------------------------------------------------

t_read_verdict_parseia_relatorio_valido() {
  local out
  out="$(printf '%s' '{"risk_assessment":{"score":42,"severity":"MEDIUM","recommendation":"CAUTION","max_issue_severity":"HIGH"},"issues":[1,2,3],"analysis_completeness":{"status":"partial"},"metadata":{"skillspector_version":"2.11.2"}}' | read_verdict)"
  [ "$out" = "42|MEDIUM|CAUTION|3|partial|HIGH|2.11.2" ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "unexpected verdict: $out"
}

# A truncated report (timeout mid-stream) must not become an approval.
t_read_verdict_rejeita_json_truncado() {
  local out
  out="$(printf '%s' '{"risk_assessment":{"score":0,' | read_verdict)"
  case "$out" in
    ERRO*) _pass "${FUNCNAME[0]}" ;;
    *)     _fail "${FUNCNAME[0]}" "truncated JSON should become ERRO, got: $out" ;;
  esac
}

t_read_verdict_sem_campos_nao_inventa_score() {
  local out
  out="$(printf '%s' '{}' | read_verdict)"
  case "$out" in
    "?|"*) _pass "${FUNCNAME[0]}" ;;
    *)     _fail "${FUNCNAME[0]}" "expected score '?', got: $out" ;;
  esac
}

# --- discovery --------------------------------------------------------------

t_discover_pula_fixture_marcada() {
  local encontrados
  encontrados="$(discover_skills)"
  if printf '%s\n' "$encontrados" | grep -q 'fixture-reprovada'; then
    _fail "${FUNCNAME[0]}" "fixture marked with .skill-guard-fixture appeared in --all"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

# Asserts discovery actually works, by name — a bare count would only be a
# threshold calibrated to whatever happened to be installed that week.
t_discover_acha_as_skills_do_repo() {
  local encontrados n
  encontrados="$(discover_skills)"
  n="$(printf '%s\n' "$encontrados" | grep -c . )"
  if [ "$n" -lt 1 ]; then
    _fail "${FUNCNAME[0]}" "discovered no skills at all"
  elif ! printf '%s\n' "$encontrados" | grep -q 'archify'; then
    _fail "${FUNCNAME[0]}" "catalogued skill 'archify' was not discovered ($n found)"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

# --- report name ------------------------------------------------------------

# .claude/skills/agenfk and .agents/skills/agenfk share the same basename:
# with basename, the second would overwrite the first report.
t_slug_distingue_mesmo_basename() {
  local a b
  a="$(report_slug "$SCAN_ROOT/.claude/skills/agenfk")"
  b="$(report_slug "$SCAN_ROOT/.agents/skills/agenfk")"
  if [ "$a" = "$b" ]; then
    _fail "${FUNCNAME[0]}" "slugs collided: $a"
  elif [ "$a" = "agenfk" ] || [ "$b" = "agenfk" ]; then
    _fail "${FUNCNAME[0]}" "slug fell back to basename: $a / $b"
  else
    _pass "${FUNCNAME[0]}"
  fi
}

t_slug_preserva_o_caminho_da_skill() {
  local s
  s="$(report_slug "$SCAN_ROOT/skills-artifacts/feature-quiz")"
  [ "$s" = "skills-artifacts-feature-quiz" ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "expected skills-artifacts-feature-quiz, got: $s"
}

# Skills live in .claude/ and .agents/: without trimming the leading dot the
# report becomes a hidden file and vanishes from an `ls` of the directory.
t_slug_nao_gera_arquivo_oculto() {
  local a b
  a="$(report_slug "$SCAN_ROOT/.agents/skills/agenfk")"
  b="$(report_slug "$SCAN_ROOT/.claude/skills/agenfk")"
  case "$a$b" in
    .*) _fail "${FUNCNAME[0]}" "slug starts with a dot: $a / $b" ;;
    *)  [ "$a" != "$b" ] \
          && _pass "${FUNCNAME[0]}" \
          || _fail "${FUNCNAME[0]}" "slugs collided: $a" ;;
  esac
}

# --- exit codes -------------------------------------------------------------

t_opcao_invalida_sai_2() {
  "$GATE" --does-not-exist >/dev/null 2>&1
  [ "$?" -eq 2 ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "expected exit 2"
}

t_sem_alvo_sai_2() {
  "$GATE" >/dev/null 2>&1
  [ "$?" -eq 2 ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "expected exit 2"
}

# --- real gate (needs the image) --------------------------------------------

t_gate_bloqueia_skill_ruim() {
  has_image || { _skip "${FUNCNAME[0]}" "image $IMAGE absent"; return; }
  SKILL_GUARD_REPORTS="$TMP/r1" "$GATE" "$REPO/pilots/skillspector-demo/fixture-reprovada" >/dev/null 2>&1
  [ "$?" -eq 1 ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "bad fixture should exit 1"
}

t_gate_aprova_skill_limpa() {
  has_image || { _skip "${FUNCNAME[0]}" "image $IMAGE absent"; return; }
  SKILL_GUARD_REPORTS="$TMP/r2" "$GATE" "$REPO/skills-artifacts/feature-quiz" >/dev/null 2>&1
  [ "$?" -eq 0 ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "clean skill should exit 0"
}

# The deadline exists to block, not to warn: exceeding it fails CLOSED.
# Uses a fake docker that stalls forever — with the real scanner the test
# would be a race (a fast scan would finish before the deadline) and prove
# nothing. Also checks the MESSAGE: a gate that blocks on any docker failure
# would pass without ever exercising the timeout.
t_timeout_falha_fechado() {
  local fake="$TMP/binto" out rc
  mkdir -p "$fake"
  cat > "$fake/docker" <<'SH'
#!/usr/bin/env bash
case "$1" in
  image|rm) exit 0 ;;
esac
sleep 600
SH
  chmod +x "$fake/docker"
  out="$(PATH="$fake:$PATH" SKILL_GUARD_TIMEOUT=2 SKILL_GUARD_REPORTS="$TMP/r3" \
    "$GATE" "$REPO/skills-artifacts/feature-quiz" 2>&1)"
  rc=$?
  if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q 'no report (timeout'; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "expected timeout block (exit 1 + message), got exit $rc"
  fi
}

t_gate_grava_relatorio_json() {
  has_image || { _skip "${FUNCNAME[0]}" "image $IMAGE absent"; return; }
  SKILL_GUARD_REPORTS="$TMP/r4" "$GATE" "$REPO/skills-artifacts/feature-quiz" >/dev/null 2>&1
  local rc=$? f
  f="$(find "$TMP/r4" -name '*.json' | head -1)"
  if [ "$rc" -eq 0 ] && [ -n "$f" ] \
     && python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if 'risk_assessment' in d else 1)" "$f" 2>/dev/null; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "JSON report was not written or is invalid"
  fi
}

# Syntactically valid report without a score: the gate must BLOCK, not fall
# into the approval branch because the numeric comparison failed.
t_score_nao_numerico_bloqueia() {
  local fake="$TMP/fakebin" out
  mkdir -p "$fake"
  # fake docker: returns a valid JSON report, but without risk_assessment
  cat > "$fake/docker" <<'SH'
#!/usr/bin/env bash
case "$1" in
  image|rm) exit 0 ;;
esac
printf '%s' '{"issues":[],"analysis_completeness":{"status":"complete"},"metadata":{}}'
SH
  chmod +x "$fake/docker"
  out="$(PATH="$fake:$PATH" SKILL_GUARD_REPORTS="$TMP/r5" \
    "$GATE" "$REPO/skills-artifacts/feature-quiz" 2>&1)"
  local rc=$?
  if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q 'no usable score'; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "expected block for missing score (exit 1), got exit $rc"
  fi
}

# --- pin --------------------------------------------------------------------

# Calls THE GATE's verify_pin, not a reimplementation: a gate that lost its
# pin check must fail here.
t_verify_pin_confirma_o_commit_fixado() {
  local out
  git ls-remote "$REPO_URL" "refs/tags/${VERSION}" >/dev/null 2>&1 \
    || { _skip "${FUNCNAME[0]}" "no network"; return; }
  out="$(verify_pin 2>&1)"
  printf '%s' "$out" | grep -q "pin confirmed: ${VERSION} = ${PINNED_SHA:0:12}" \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "verify_pin did not confirm the pin: $out"
}

# A diverged pin must abort the gate (exit 2), not continue with a scanner
# whose provenance does not check out.
t_verify_pin_rejeita_sha_divergente() {
  local out rc
  git ls-remote "$REPO_URL" "refs/tags/${VERSION}" >/dev/null 2>&1 \
    || { _skip "${FUNCNAME[0]}" "no network"; return; }
  out="$(PINNED_SHA=0000000000000000000000000000000000000000 verify_pin 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q 'pin diverged'; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "diverged pin should abort, got rc=$rc: $out"
  fi
}

# --- bypass (external review findings) --------------------------------------

# CRITICAL: a baseline inside the skill directory is controlled by the skill
# itself. The gate must not use it — and must not ignore it silently.
t_baseline_dentro_do_alvo_bloqueia() {
  local dir="$TMP/skillmal" out rc
  mkdir -p "$dir"
  printf -- '---\nname: mal\ndescription: x\n---\n' > "$dir/SKILL.md"
  printf 'version: 2\nrules:\n  - id: "SC2"\n    reason: "suppresses everything"\n' \
    > "$dir/.skillspector-baseline.yaml"
  out="$(SKILL_GUARD_REPORTS="$TMP/rb" "$GATE" "$dir" 2>&1)"; rc=$?
  if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q 'baseline inside the skill directory'; then
    _pass "${FUNCNAME[0]}"
  else
    _fail "${FUNCNAME[0]}" "expected block WITH the reason 'baseline inside the skill directory' (exit 1); got exit $rc — if it blocked for another reason, the guard does not exist"
  fi
}

# HIGH: the fixture allowlist lives outside the tree. A file dropped inside
# the skill directory must no longer be able to hide it from --all.
t_marcador_interno_nao_esconde_mais_a_skill() {
  local dir="$TMP/repo_fake/skills/evil"
  mkdir -p "$dir"
  printf -- '---\nname: evil\n---\n' > "$dir/SKILL.md"
  : > "$dir/.skill-guard-fixture"
  SCAN_ROOT="$TMP/repo_fake" FIXTURES_ALLOW="$TMP/repo_fake/.harness/skill-guard-fixtures" \
    bash -c 'source "'"$GATE"'"; SCAN_ROOT="'"$TMP"'/repo_fake"; FIXTURES_ALLOW="'"$TMP"'/does-not-exist"; discover_skills' \
    2>/dev/null | grep -q 'skills/evil' \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "internal marker still hid the skill from --all"
}

# The external allowlist keeps working for legitimate fixtures.
t_allowlist_externa_pula_a_fixture() {
  discover_skills | grep -q 'fixture-reprovada' \
    && _fail "${FUNCNAME[0]}" "fixture listed in the allowlist appeared in --all" \
    || _pass "${FUNCNAME[0]}"
}

# HIGH: non-integer threshold disarmed the gate (score 70 was approved).
t_limiar_nao_inteiro_aborta() {
  local rc
  SKILL_GUARD_MAX_SCORE=abc "$GATE" "$REPO/skills-artifacts/feature-quiz" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq 2 ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "MAX_SCORE=abc should abort with exit 2, got $rc"
}

t_limiar_de_aviso_acima_do_de_bloqueio_aborta() {
  local rc
  SKILL_GUARD_WARN_SCORE=80 SKILL_GUARD_MAX_SCORE=50 \
    "$GATE" "$REPO/skills-artifacts/feature-quiz" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq 2 ] \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "WARN > MAX should abort with exit 2, got $rc"
}

t_separador_permite_alvo_com_hifen() {
  local out
  out="$("$GATE" -- -alvo-inexistente 2>&1)"
  printf '%s' "$out" | grep -q 'unknown option' \
    && _fail "${FUNCNAME[0]}" "target after -- was treated as an option" \
    || _pass "${FUNCNAME[0]}"
}

# Recording a verdict must not erase the triage written by a person.
t_record_preserva_campos_de_triagem() {
  local lock="$TMP/lockrepo/skills-lock.json"
  mkdir -p "$TMP/lockrepo"
  cat > "$lock" <<'JSON'
{"version":1,"skills":{"x":{"source":"a/b","scanVerdict":{"decision":"ACEITO_COM_RESSALVA","notes":"manual triage","rawScore":100}}}}
JSON
  SCAN_ROOT="$TMP/lockrepo" record_verdict "$TMP/lockrepo/x" \
    '{"risk_assessment":{"score":7,"severity":"LOW"},"issues":[],"suppressed_count":3,"analysis_completeness":{"status":"partial"}}' \
    >/dev/null 2>&1
  python3 -c "
import json,sys
v=json.load(open('$lock'))['skills']['x']['scanVerdict']
sys.exit(0 if v.get('decision')=='ACEITO_COM_RESSALVA' and v.get('rawScore')==100 and v.get('score')==7 else 1)" \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "record_verdict erased the triage fields"
}

# The lock records what was APPROVED. Writing the verdict of a blocked skill
# would make "has a scanVerdict" a synonym for "passed the gate".
t_record_nao_grava_skill_bloqueada() {
  local fake="$TMP/binrec" lock="$TMP/recrepo/skills-lock.json"
  mkdir -p "$fake" "$TMP/recrepo/evil"
  printf -- '---\nname: evil\n---\n' > "$TMP/recrepo/evil/SKILL.md"
  cat > "$lock" <<'JSON'
{"version":1,"skills":{"evil":{"source":"x/y"}}}
JSON
  # fake docker: always returns a CRITICAL report above the threshold
  cat > "$fake/docker" <<'SH'
#!/usr/bin/env bash
case "$1" in
  image|rm) exit 0 ;;
esac
printf '%s' '{"risk_assessment":{"score":91,"severity":"CRITICAL","max_issue_severity":"CRITICAL"},"issues":[1],"suppressed_count":0,"analysis_completeness":{"status":"complete"},"metadata":{}}'
SH
  chmod +x "$fake/docker"
  PATH="$fake:$PATH" SKILL_GUARD_REPORTS="$TMP/rr" \
    bash -c 'SCAN_ROOT="'"$TMP"'/recrepo" exec "'"$GATE"'" --record "'"$TMP"'/recrepo/evil"' >/dev/null 2>&1
  python3 -c "
import json,sys
v=json.load(open('$lock'))['skills']['evil'].get('scanVerdict')
sys.exit(1 if v else 0)" \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "verdict of a blocked skill was recorded in the lock"
}

# --- local patches on third-party skills ------------------------------------

VH="$ROOT/scripts/validate-harness.sh"

# A local patch only counts while applied. Reinstalling the skill silently
# discards it, and the lock would keep claiming a fix that no longer exists.
_patch_fixture() {  # $1 = contents of the "patched" file
  local d="$TMP/patchrepo"
  mkdir -p "$d/vendor"
  printf '%s' "$1" > "$d/vendor/package-lock.json"
  cat > "$d/skills-lock.json" <<'JSON'
{"version":1,"skills":{"x":{"source":"a/b","scanVerdict":{"score":0},
 "localPatches":[{"verifyFile":"vendor/package-lock.json",
                  "verifyContains":"dep-2.0.0.tgz","verifyAbsent":"dep-1.0.0.tgz"}]}}}
JSON
  printf '%s' "$d/skills-lock.json"
}

t_patch_local_aplicado_passa() {
  local lock; lock="$(_patch_fixture 'resolved: dep-2.0.0.tgz')"
  local out
  out="$(SKILL_GUARD_LOCK="$lock" "$VH" 2>&1 || true)"
  printf '%s' "$out" | grep -q 'local patch(es) still applied' \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "applied patch should pass"
}

t_patch_local_perdido_falha() {
  local lock; lock="$(_patch_fixture 'resolved: something-else.tgz')"
  local out
  out="$(SKILL_GUARD_LOCK="$lock" "$VH" 2>&1 || true)"
  printf '%s' "$out" | grep -q 'patch lost' \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "missing patch should fail"
}

t_patch_local_revertido_falha() {
  local lock; lock="$(_patch_fixture 'resolved: dep-2.0.0.tgz and dep-1.0.0.tgz')"
  local out
  out="$(SKILL_GUARD_LOCK="$lock" "$VH" 2>&1 || true)"
  printf '%s' "$out" | grep -q 'patch reverted' \
    && _pass "${FUNCNAME[0]}" \
    || _fail "${FUNCNAME[0]}" "return of the vulnerable version should fail"
}

# --- execution --------------------------------------------------------------

for t in $(declare -F | awk '{print $3}' | grep '^t_'); do "$t"; done

printf '\n== %d/%d passed' "$PASS" "$((PASS + FAIL))"
[ "$SKIP" -gt 0 ] && printf ' (%d skipped)' "$SKIP"
printf '\n'
exit "$FAIL"
