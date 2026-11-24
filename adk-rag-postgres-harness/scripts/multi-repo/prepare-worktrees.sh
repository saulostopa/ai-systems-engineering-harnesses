#!/usr/bin/env bash
# Create a detached worktree at the remote default branch of every Git clone in CLONES_DIR
# (one or two levels down) and write WORKTREES_DIR/manifest.tsv.
#
# The clones' working trees are not changed: only `git fetch` and `git worktree add` touch
# them, so a clone on a feature branch with local edits stays as it is.
#
# usage: prepare-worktrees.sh CLONES_DIR WORKTREES_DIR
set -euo pipefail

clones=$(cd "${1:?usage: prepare-worktrees.sh CLONES_DIR WORKTREES_DIR}" && pwd)
mkdir -p "${2:?usage: prepare-worktrees.sh CLONES_DIR WORKTREES_DIR}"
out=$(cd "$2" && pwd)
manifest="$out/manifest.tsv"
printf 'project\tworktree\tbranch\tcommit\tclone\n' > "$manifest"

find "$clones" -mindepth 2 -maxdepth 3 -type d -name .git -prune -print | sort | while read -r gitdir; do
  clone=$(dirname "$gitdir")
  case "$clone" in "$out"/*) continue ;; esac
  project=$(basename "$clone" | tr '[:upper:]' '[:lower:]')
  if cut -f1 "$manifest" | grep -qx "$project"; then
    echo "skip $clone: project name $project already used" >&2
    continue
  fi
  if ! git -C "$clone" fetch --quiet origin < /dev/null; then
    echo "skip $project: fetch failed" >&2
    continue
  fi
  branch=$(git -C "$clone" ls-remote --symref origin HEAD < /dev/null | awk '/^ref:/ { sub("refs/heads/", "", $2); print $2 }')
  if [[ -z "$branch" ]]; then
    echo "skip $project: the remote has no default branch" >&2
    continue
  fi
  commit=$(git -C "$clone" rev-parse "origin/$branch")
  worktree="$out/$project"
  if [[ -e "$worktree" ]]; then
    git -C "$worktree" checkout --quiet --detach "$commit" < /dev/null
  else
    git -C "$clone" worktree add --quiet --detach "$worktree" "$commit" < /dev/null
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$project" "$worktree" "$branch" "$commit" "$clone" >> "$manifest"
  echo "$project  $branch  ${commit:0:10}"
done

echo "manifest: $manifest ($(($(wc -l < "$manifest") - 1)) repositories)"
