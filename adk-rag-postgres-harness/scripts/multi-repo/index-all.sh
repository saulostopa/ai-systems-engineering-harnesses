#!/usr/bin/env bash
# Index every worktree of the manifest, or only the projects named, in the order given.
# A failure is logged and the next project runs; `index` resumes where it stopped, so the
# same command can simply run again. Run it from adk-rag-postgres-harness.
#
# usage: index-all.sh WORKTREES_DIR [project ...]
set -uo pipefail

: "${DATABASE_URL:?export DATABASE_URL first}" "${HARNESS_EMBED_MODEL:?export HARNESS_EMBED_MODEL first}"
dir="${1:?usage: index-all.sh WORKTREES_DIR [project ...]}"
shift
logs="$dir/index-logs"
mkdir -p "$logs"
# The URL may hold a password: show the host and database only.
echo "database: $(printf '%s' "$DATABASE_URL" | sed -E 's#//[^@/]*@#//#; s#\?.*##')  embedder: ${HARNESS_EMBED_PROVIDER:-ollama}:$HARNESS_EMBED_MODEL"

projects=("$@")
if [[ ${#projects[@]} -eq 0 ]]; then
  while IFS=$'\t' read -r project _; do projects+=("$project"); done < <(tail -n +2 "$dir/manifest.tsv")
fi

failed=()
for project in "${projects[@]}"; do
  worktree=$(awk -F'\t' -v p="$project" '$1 == p { print $2 }' "$dir/manifest.tsv")
  if [[ -z "$worktree" ]]; then
    echo "$project: not in the manifest" >&2
    failed+=("$project")
    continue
  fi
  started=$(date +%s)
  if uv run --no-sync python -m adk_rag_postgres_harness.cli index "$worktree" --project "$project" \
      > "$logs/$project.log" 2>&1; then
    echo "$project: $(tail -n 1 "$logs/$project.log") ($(( $(date +%s) - started )) s)"
  else
    echo "$project: FAILED after $(( $(date +%s) - started )) s, see $logs/$project.log" >&2
    failed+=("$project")
  fi
done

[[ ${#failed[@]} -eq 0 ]] || { echo "failed: ${failed[*]}" >&2; exit 1; }
