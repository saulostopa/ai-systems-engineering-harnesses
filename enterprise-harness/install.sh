#!/usr/bin/env bash
# install.sh — installs the enterprise harness orchestrator (layer A).
#
# Runs once per machine. The orchestrator belongs in a root folder ABOVE the
# project folders: it scans its parent directory for adopted repositories, so
# ~/wm/wm-harness manages everything under ~/wm.
#
# Usage: install.sh [--prefix DIR] [--projects DIR] [--force] [--no-link]
#   --prefix    where the orchestrator lives  (default: $HOME/wm-harness)
#   --projects  directory to scan for repos   (default: the prefix's parent)
#   --no-link   skip the ~/.local/bin symlink (used by the test suite, which
#               installs into a temp dir — a link into a directory that is
#               about to be deleted is worse than no link at all)
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$HOME/wm-harness"
PROJECTS=""
FORCE=0
NO_LINK=0

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)   PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
    --projects) PROJECTS="${2:?--projects needs a directory}"; shift 2 ;;
    --force)    FORCE=1; shift ;;
    --no-link)  NO_LINK=1; shift ;;
    -h|--help)  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

log()  { printf '[enterprise-harness] %s\n' "$1"; }
fail() { printf '[enterprise-harness] ERROR: %s\n' "$1" >&2; exit 1; }

# The basic harness is the layer 1-2 payload. Vendoring it is what lets the
# orchestrator adopt a repository without the source tree being present.
BASIC="$SRC/../harness-basic"
[ -d "$BASIC" ] || fail "harness-basic not found next to this package ($BASIC)"

if [ -e "$PREFIX" ] && [ "$FORCE" != "1" ]; then
  fail "already exists: $PREFIX (use --force to reinstall)"
fi

log "Installing the orchestrator into: $PREFIX"
rm -rf "$PREFIX"
mkdir -p "$PREFIX"

for d in bin engine flows templates scripts; do
  cp -r "$SRC/$d" "$PREFIX/$d"
  log "installed: $PREFIX/$d"
done
cp "$SRC/VERSION" "$PREFIX/VERSION"

# Vendor the basic harness, minus the things that are ours to rebuild rather
# than to ship: a generated index would go stale the moment it is copied.
cp -r "$BASIC" "$PREFIX/harness-basic"
rm -rf "$PREFIX/harness-basic/.rag_index"
log "vendored: $PREFIX/harness-basic (layers 1-2 payload)"

[ -n "$PROJECTS" ] || PROJECTS="$(dirname "$PREFIX")"
PROJECTS="$(cd "$PROJECTS" 2>/dev/null && pwd)" || fail "projects directory does not exist"
printf '%s\n' "$PROJECTS" > "$PREFIX/projects-root"
log "projects root: $PROJECTS"

chmod +x "$PREFIX/bin/wm-harness" "$PREFIX/scripts/"*.sh 2>/dev/null
chmod +x "$PREFIX/harness-basic/install.sh" "$PREFIX/harness-basic/scripts/"*.sh 2>/dev/null

# A symlink only where the shell will actually find it — a link into a
# directory that is not on PATH looks like success and behaves like failure.
LINKED=0
if [ "$NO_LINK" = "0" ] && [ -d "$HOME/.local/bin" ] && printf '%s' ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
  ln -sf "$PREFIX/bin/wm-harness" "$HOME/.local/bin/wm-harness"
  LINKED=1
  log "linked: $HOME/.local/bin/wm-harness"
fi

log "Installation complete."
if [ "$LINKED" = "1" ]; then
  log "  wm-harness doctor"
else
  log "  Add to your PATH:  export PATH=\"$PREFIX/bin:\$PATH\""
  log "  Then:              wm-harness doctor"
fi
log "  Adopt a repo:      wm-harness adopt <repo>"
