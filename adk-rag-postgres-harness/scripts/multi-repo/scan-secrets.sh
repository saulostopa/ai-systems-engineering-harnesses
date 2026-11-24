#!/usr/bin/env bash
# Scan every worktree of the manifest with gitleaks before indexing. Reports stay outside
# the worktrees and are redacted. Exits 1 when any repository has findings.
#
# usage: scan-secrets.sh WORKTREES_DIR REPORTS_DIR
set -uo pipefail

command -v gitleaks > /dev/null || { echo "gitleaks is not installed (macOS: brew install gitleaks)" >&2; exit 2; }
manifest="${1:?usage: scan-secrets.sh WORKTREES_DIR REPORTS_DIR}/manifest.tsv"
reports="${2:?usage: scan-secrets.sh WORKTREES_DIR REPORTS_DIR}"
mkdir -p "$reports"
status=0

while IFS=$'\t' read -r project worktree _; do
  report="$reports/$project.json"
  gitleaks dir "$worktree" --redact --no-banner --report-format json --report-path "$report" > /dev/null 2>&1
  case $? in
    0) echo "$project: clean" ;;
    1) echo "$project: $(python3 -c 'import json, sys; print(len(json.load(open(sys.argv[1]))))' "$report") findings -> $report"; status=1 ;;
    *) echo "$project: gitleaks failed" >&2; status=1 ;;
  esac
done < <(tail -n +2 "$manifest")

exit $status
