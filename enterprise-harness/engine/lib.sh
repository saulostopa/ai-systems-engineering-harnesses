#!/usr/bin/env bash
# lib.sh — shared helpers for the wm-harness orchestrator (layer A).
#
# Design note that explains almost every choice in this file: the orchestrator
# keeps NO project state. It discovers repositories by scanning for
# .harness/config.yaml and reads everything else out of the repo itself.
# Deleting ~/wm-harness must never make a project lose information about
# itself — that is the invariant the enterprise harness is built on.

set -uo pipefail

# ── Output ──────────────────────────────────────────────────────────────
say()  { printf '[wm-harness] %s\n' "$1"; }
ok()   { printf '  [ok]     %s\n' "$1"; }
warn() { printf '  [warn]   %s\n' "$1"; }
bad()  { printf '  [FAIL]   %s\n' "$1"; }
die()  { printf '[wm-harness] ERROR: %s\n' "$1" >&2; exit 1; }
section() { printf '\n== %s ==\n' "$1"; }

# ── Where things are ────────────────────────────────────────────────────

# The orchestrator's own install directory (…/wm-harness).
orchestrator_home() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# The directory the orchestrator scans for adopted repositories.
# Precedence: explicit env > what install.sh recorded > the install's parent.
# The parent default is deliberate: the orchestrator is meant to sit in a root
# folder ABOVE the project folders.
projects_root() {
  local home
  home="$(orchestrator_home)"
  if [ -n "${WM_HARNESS_PROJECTS:-}" ]; then
    printf '%s\n' "$WM_HARNESS_PROJECTS"
  elif [ -f "$home/projects-root" ]; then
    head -1 "$home/projects-root"
  else
    dirname "$home"
  fi
}

# Every adopted repository under the projects root, one path per line.
# Discovery, not a registry: a stale index cannot lie about what exists.
discover_projects() {
  local root
  root="$(projects_root)"
  [ -d "$root" ] || return 0
  find "$root" -mindepth 2 -maxdepth 3 -type f -path '*/.harness/config.yaml' \
       -not -path '*/node_modules/*' 2>/dev/null |
    while read -r cfg; do
      cd "$(dirname "$(dirname "$cfg")")" && pwd
    done | sort -u
}

# ── Reading the repo's layer B ──────────────────────────────────────────

# One scalar out of a `key: value` config. No YAML parser on purpose: the file
# is a short declaration, and a dependency here would be a dependency in every
# adopted repository.
config_get() {
  local repo="$1" key="$2"
  local f="$repo/.harness/config.yaml"
  [ -f "$f" ] || return 1
  sed -n "s/^${key}:[[:space:]]*//p" "$f" | head -1 | sed 's/[[:space:]]*#.*$//' | tr -d '"'
}

project_name() {
  local repo="$1" n
  n="$(config_get "$repo" name 2>/dev/null)"
  [ -n "$n" ] && printf '%s\n' "$n" || basename "$repo"
}

# Count of features in a given status, or "?" when it cannot be read —
# never 0, because a silent zero would read as "nothing in progress".
feature_count() {
  local repo="$1" status="$2"
  local f="$repo/feature_list.json"
  [ -f "$f" ] || { printf '?\n'; return; }
  command -v node >/dev/null 2>&1 || { printf '?\n'; return; }
  node -e "
    try {
      const l = require(process.argv[1]).features || [];
      console.log(l.filter(x => x.status === process.argv[2]).length);
    } catch { console.log('?'); }
  " "$f" "$status" 2>/dev/null || printf '?\n'
}

plan_count() {
  local repo="$1" phase="$2" d="$repo/docs/exec-plans/$2"
  [ -d "$d" ] || { printf '0\n'; return; }
  find "$d" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' '
}

# Plan ids follow the branch convention — feature/OEM-123, bugfix/AC-455 — and a
# slash is a path separator. The file on disk flattens it; the id inside the
# front-matter stays exact, because that is what ties the plan to the branch.
plan_slug() { printf '%s\n' "$1" | tr '/' '-'; }

# The status a plan declares in its own front-matter. The file's location is
# organisation; this is the truth (see the exec-plans gate in harness-basic).
plan_status() {
  sed -n '1,20p' "$1" | sed -n 's/^status:[[:space:]]*\([A-Za-z_]*\).*/\1/p' | head -1
}

# ── Flows ───────────────────────────────────────────────────────────────

flow_file() {
  printf '%s/flows/%s.yaml\n' "$(orchestrator_home)" "$1"
}

flow_exists() { [ -f "$(flow_file "$1")" ]; }

list_flows() {
  local d
  d="$(orchestrator_home)/flows"
  [ -d "$d" ] || return 0
  find "$d" -maxdepth 1 -name '*.yaml' 2>/dev/null | sort |
    while read -r f; do basename "$f" .yaml; done
}

# Items under a `steps:` or `exit_criteria:` block, as plain lines.
flow_items() {
  local file="$1" key="$2"
  awk -v k="$key" '
    $0 ~ "^"k":[[:space:]]*$" { inblock = 1; next }
    inblock && /^[[:space:]]*-[[:space:]]+/ {
      sub(/^[[:space:]]*-[[:space:]]+/, ""); print; next
    }
    inblock && /^[^[:space:]]/ { inblock = 0 }
  ' "$file"
}
