#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

run_blocked() {
  local name="$1"; shift
  if "$ROOT/scripts/git-safe" "$@" >/dev/null 2>&1; then
    printf 'FAIL %s\n' "$name"; FAIL=$((FAIL + 1))
  else
    printf 'PASS %s\n' "$name"; PASS=$((PASS + 1))
  fi
}

run_allowed() {
  local name="$1"; shift
  if "$ROOT/scripts/git-safe" "$@" >/dev/null 2>&1; then
    printf 'PASS %s\n' "$name"; PASS=$((PASS + 1))
  else
    printf 'FAIL %s\n' "$name"; FAIL=$((FAIL + 1))
  fi
}

run_allowed "allows read-only status" status --short
run_blocked "blocks reset hard" reset --hard
run_blocked "blocks force push" push --force origin HEAD:refs/heads/main
run_blocked "blocks force-with-lease" push --force-with-lease origin HEAD:refs/heads/main
run_blocked "blocks checkout B" checkout -B feature/test
run_blocked "blocks switch C" switch -C feature/test
run_blocked "blocks branch delete" branch -D feature/test
run_blocked "blocks worktree add B" worktree add -B feature/test ../wt-test
run_blocked "blocks clean f" clean -fd
run_blocked "blocks stash drop" stash drop
run_blocked "blocks stash clear" stash clear
run_blocked "blocks rebase" rebase main
run_blocked "blocks amend" commit --amend

if printf '%s\n' "refs/heads/main abc refs/heads/main 0000000000000000000000000000000000000000" \
  | "$ROOT/scripts/git-policy.sh" pre-push >/dev/null 2>&1; then
  printf 'PASS allows new remote ref\n'; PASS=$((PASS + 1))
else
  printf 'FAIL allows new remote ref\n'; FAIL=$((FAIL + 1))
fi

if printf '%s\n' "0 0000000000000000000000000000000000000000 refs/heads/main abc" \
  | "$ROOT/scripts/git-policy.sh" pre-push >/dev/null 2>&1; then
  printf 'FAIL blocks remote ref deletion\n'; FAIL=$((FAIL + 1))
else
  printf 'PASS blocks remote ref deletion\n'; PASS=$((PASS + 1))
fi

TMP_REPO="$(mktemp -d)"
trap 'rm -rf "$TMP_REPO"' EXIT
git -C "$TMP_REPO" init -q
git -C "$TMP_REPO" config user.email guard@example.invalid
git -C "$TMP_REPO" config user.name git-policy-test
printf 'base\n' > "$TMP_REPO/file"
git -C "$TMP_REPO" add file
git -C "$TMP_REPO" commit -qm base
BASE="$(git -C "$TMP_REPO" rev-parse HEAD)"
printf 'next\n' > "$TMP_REPO/file"
git -C "$TMP_REPO" commit -qam next
NEXT="$(git -C "$TMP_REPO" rev-parse HEAD)"

if printf 'refs/heads/main %s refs/heads/main %s\n' "$NEXT" "$BASE" \
  | (cd "$TMP_REPO" && "$ROOT/scripts/git-policy.sh" pre-push) >/dev/null 2>&1; then
  printf 'PASS allows fast-forward update\n'; PASS=$((PASS + 1))
else
  printf 'FAIL allows fast-forward update\n'; FAIL=$((FAIL + 1))
fi

if printf 'refs/heads/main %s refs/heads/main %s\n' "$BASE" "$NEXT" \
  | (cd "$TMP_REPO" && "$ROOT/scripts/git-policy.sh" pre-push) >/dev/null 2>&1; then
  printf 'FAIL blocks non-fast-forward update\n'; FAIL=$((FAIL + 1))
else
  printf 'PASS blocks non-fast-forward update\n'; PASS=$((PASS + 1))
fi

printf '\n== %d/%d passed ==\n' "$PASS" "$((PASS + FAIL))"
[ "$FAIL" -eq 0 ]
