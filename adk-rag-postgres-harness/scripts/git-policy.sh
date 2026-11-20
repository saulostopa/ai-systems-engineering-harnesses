#!/usr/bin/env bash
set -u

fail() {
  printf '[git-policy] BLOCKED: %s\n' "$1" >&2
  exit 1
}

has_arg() {
  local wanted="$1" arg
  shift
  for arg in "$@"; do
    [ "$arg" = "$wanted" ] && return 0
  done
  return 1
}

check_command() {
  local subcommand="${1:-}" arg
  shift || true
  [ -n "$subcommand" ] || fail "use git-safe <command>"

  case "$subcommand" in
    reset) has_arg --hard "$@" && fail "git reset --hard is prohibited" ;;
    push)
      for arg in "$@"; do
        case "$arg" in
          --force|--force-with-lease|-f) fail "forced pushes are prohibited" ;;
        esac
      done ;;
    checkout) has_arg -B "$@" && fail "git checkout -B is prohibited" ;;
    switch) has_arg -C "$@" && fail "git switch -C is prohibited" ;;
    branch)
      for arg in "$@"; do
        case "$arg" in
          -f|-D|-f*|-*D*) fail "forced or destructive branch changes are prohibited" ;;
        esac
      done ;;
    worktree)
      if [ "${1:-}" = "add" ] && has_arg -B "$@"; then
        fail "git worktree add -B is prohibited"
      fi ;;
    clean)
      for arg in "$@"; do
        case "$arg" in -*f*) fail "git clean -f is prohibited" ;; esac
      done ;;
    stash)
      case "${1:-}" in drop|clear) fail "stash drop and stash clear are prohibited" ;; esac ;;
    rebase) fail "git rebase is prohibited" ;;
    commit) has_arg --amend "$@" && fail "amending a published commit is prohibited" ;;
  esac
}

check_push() {
  local local_ref local_sha remote_ref remote_sha
  while read -r local_ref local_sha remote_ref remote_sha; do
    [ -n "${local_ref:-}" ] || continue
    case "$local_sha" in
      0000000000000000000000000000000000000000) fail "deleting remote refs is prohibited" ;;
    esac
    case "$remote_sha" in
      0000000000000000000000000000000000000000) continue ;;
    esac
    command git merge-base --is-ancestor "$remote_sha" "$local_sha" \
      || fail "non-fast-forward update for $remote_ref is prohibited"
  done
}

case "${1:-}" in
  check) shift; check_command "$@" ;;
  pre-push) check_push ;;
  *) fail "usage: git-policy.sh check <git-command>... | pre-push" ;;
esac
