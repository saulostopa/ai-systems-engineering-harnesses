#!/usr/bin/env bash
# install.sh — installs the basic harness into a target project.
# Usage: install.sh <target-repo> [--force]
# Modeled on webmotors-harness-factory/scripts/bootstrap-project.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -*) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
    *) TARGET="$arg" ;;
  esac
done

[ -n "$TARGET" ] || { echo "Usage: install.sh <target-repo> [--force]"; exit 1; }
[ -d "$TARGET" ] || { echo "ERROR: directory does not exist: $TARGET"; exit 1; }

log() { printf '[harness-basic] %s\n' "$1"; }
fail() { printf '[harness-basic] ERROR: %s\n' "$1" >&2; exit 1; }

copy() {
  local src="$1" dst="$2"
  if [ -e "$dst" ] && [ "$FORCE" != "1" ]; then
    fail "refusing to overwrite: $dst (use --force)"
  fi
  mkdir -p "$(dirname "$dst")"
  cp -r "$src" "$dst"
  log "installed: $dst"
}

log "Installing basic harness into: $TARGET"

# 1. Templates
for f in AGENTS.md feature_list.json progress.md session-handoff.md; do
  copy "$ROOT/templates/$f" "$TARGET/$f"
done
copy "$ROOT/templates/policies" "$TARGET/policies"
copy "$ROOT/templates/init.sh" "$TARGET/init.sh"

# The execution-plan structure, ready to use. TEMPLATE.md sits at the root of
# exec-plans/ on purpose: the gate only reads active/ and done/, so the template
# is never mistaken for a plan.
copy "$ROOT/templates/exec-plan.md" "$TARGET/docs/exec-plans/TEMPLATE.md"
mkdir -p "$TARGET/docs/exec-plans/active" "$TARGET/docs/exec-plans/done"
touch "$TARGET/docs/exec-plans/active/.gitkeep" "$TARGET/docs/exec-plans/done/.gitkeep"
log "installed: $TARGET/docs/exec-plans/{active,done}"

# Where the delivery diagrams land (scripts/artifacts.sh writes here).
mkdir -p "$TARGET/docs/artifacts"
touch "$TARGET/docs/artifacts/.gitkeep"
log "installed: $TARGET/docs/artifacts"

# 2. Validation scripts
copy "$ROOT/scripts" "$TARGET/scripts"

# 3. Mechanical hooks
if git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
  copy "$ROOT/.githooks" "$TARGET/.githooks"
  git -C "$TARGET" config core.hooksPath .githooks
  log "hooks enabled (core.hooksPath = .githooks)"
else
  warn() { printf '[harness-basic] warning: %s\n' "$1"; }
  warn "not a git repo — hooks not installed (run git init and re-run)"
fi

chmod +x "$TARGET/init.sh" "$TARGET/scripts/"*.sh 2>/dev/null
chmod +x "$TARGET/scripts/git-safe" 2>/dev/null

log "Installation complete. Next steps:"
log "  1. edit AGENTS.md (sections 1 and 7) and feature_list.json"
log "  2. run ./init.sh"
log "  3. initial commit (pre-commit will validate the harness)"
