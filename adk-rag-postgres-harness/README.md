# ADK RAG PostgreSQL Harness

This is the larger-project reference implementation for the course. It keeps
the same typed decision, evidence and blocked-state boundary as
`adk-rag-harness`, but stores chunks and embeddings in PostgreSQL with
`pgvector`.

## Start PostgreSQL

```bash
uv sync --extra postgres
docker compose up -d postgres
uv run python -m adk_rag_postgres_harness.cli migrate
```

The default connection is
`postgresql://harness:harness@localhost:5433/harness_rag`. Copy `.env.example`
to `.env` and adjust it for another database.

## Work in isolated worktrees

Keep the main checkout for integration. Give each feature or agent its own
worktree and branch:

```bash
git fetch origin
git worktree add ../wt-<feature-id> -b feature/<id> origin/main
cd ../wt-<feature-id>
uv sync --extra postgres
```

Each worktree owns its dependencies, caches, builds, index path and database
project. Never copy a real `.env*` file into a worktree. Use a synthetic
database and explicit test configuration for local services. The environment,
`.venv`, Docker Compose project name, ports and volumes must be unique to the
worktree or test identifier; never reuse a running service from another
worktree.

For a fixed service or evaluation, pin the checkout to a known SHA:

```bash
git worktree add --detach ../wt-service <known-sha>
cd ../wt-service
uv sync --extra postgres
docker compose -p harness-test-<id> up -d postgres
```

The service and database must read this pinned worktree. They must not follow
the agent's other worktree while it receives updates. The index is tied to the
repository folder and revision used during indexing; re-run ingestion for a
new revision instead of silently mixing files from two worktrees.

Integrate in a detached worktree and validate the merged tip before publishing:

```bash
git fetch origin
git worktree add --detach ../wt-integrate origin/main
git -C ../wt-integrate merge --no-ff feature/<id>
cd ../wt-integrate
uv sync --extra postgres
docker compose -p harness-integrate-<id> up -d postgres
uv run --with pytest pytest
git push origin HEAD:refs/heads/main
```

This standalone distribution uses `main` as its integration branch. When the
harness is installed in a consumer repository, replace `origin/main` and
`refs/heads/main` with that repository's integration ref, such as `develop`.

Use `git worktree list` to inspect worktrees, `git worktree remove <path>` to
remove a finished one and `git worktree prune` to clean stale administrative
records. Remove orphaned worktrees without `--force`; reserve `--force` for
temporary local CI worktrees. The same branch cannot be checked out in two
worktrees. If a branch, remote or indexed revision diverges, stop and ask the
repository owner.

Agents must not run `reset --hard`, force pushes, `checkout -B`, `switch -C`,
`branch -f/-D`, `worktree add -B`, `clean -f`, `stash drop/clear`, rebase or
amend of a published commit.

## Ingest a collection

From the repository root, with the local RAG package available:

```bash
ollama pull nomic-embed-text
RAG_EMBEDDER=ollama OLLAMA_EMBED_MODEL=nomic-embed-text \
PYTHONPATH=.:../rag-harness \
uv run python -m adk_rag_postgres_harness.cli ingest ../docs --collection docs
```

The initial implementation replaces one collection atomically. It supports
Python AST chunks and line chunks for documentation and configuration files.
The SQL retrieval combines PostgreSQL full-text ranking with pgvector cosine
similarity and applies stable ordering by score, source and line.

The ADK adapter is available as `PostgresRagAdapter`. It is intentionally
separate from the local JSON adapter so the course can show the storage tradeoff
without changing the workflow contract.
