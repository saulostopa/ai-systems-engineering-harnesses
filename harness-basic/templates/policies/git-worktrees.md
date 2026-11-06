# Isolated Git worktrees

The main checkout is reserved for integration. Each feature or agent gets its
own worktree and branch:

```bash
git fetch origin
git worktree add ../wt-<feature-id> -b feature/<id> origin/develop
cd ../wt-<feature-id>
```

Install dependencies and create builds inside that worktree. `.env*` files,
`node_modules`, caches and build outputs are local to a worktree. Never copy a
real `.env` file into another worktree.

Integrate in a detached worktree:

```bash
git fetch origin
git worktree add --detach ../wt-integrate origin/develop
git -C ../wt-integrate merge --no-ff feature/<id>
cd ../wt-integrate
<build and test commands>
git push origin HEAD:refs/heads/develop
```

These commands use `develop` as the consumer-project example. Replace the
integration ref when the target project uses another branch. This distribution
repository itself integrates on `main`.

Start a fixed service from a known revision and use a synthetic database. Give
the process, port and database or volume a unique test identifier:

```bash
git worktree add --detach ../wt-service <known-sha>
SERVICE_NAME=harness-test-<id> PORT=<unique-port> DATABASE_URL=<synthetic-db> <service-start-command>
```

The service must not follow a different worktree that is receiving updates.
Use `git worktree list` to inspect worktrees, `git worktree remove <path>` to
remove a finished one and `git worktree prune` to clean stale administrative
records. Remove orphaned worktrees without `--force`; use `--force` only for a
temporary local CI worktree. The same branch cannot be checked out in two
worktrees.

If a branch or remote diverges, stop and ask the repository owner.

Agents must not run:

```text
git reset --hard
git push --force
git push --force-with-lease
git checkout -B
git switch -C
git branch -f
git branch -D
git worktree add -B
git clean -f
git stash drop
git stash clear
git rebase
git commit --amend
```
