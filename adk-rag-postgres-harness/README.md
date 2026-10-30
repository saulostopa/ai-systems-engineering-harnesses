# ADK RAG PostgreSQL Harness

A code memory on PostgreSQL and `pgvector`, built from open source parts. It
keeps a repository indexed incrementally and searches it by meaning and by text.

The plan is in the course backlog (`docs/tasks/code-memory-postgres.md`). Phases 1
to 5 are done: the Postgres core, incremental sync, hybrid search, syntax-aware
chunks, symbols, imports, memory, the MCP server and the ADK wiring.

## Start

```bash
uv sync --extra postgres
docker compose up -d postgres
ollama pull qwen3-embedding:4b
```

The default connection is
`postgresql://harness:harness@localhost:5433/harness_rag`. Copy `.env.example`
to `.env` and export it to change a setting.

## Index and search

```bash
uv run python -m adk_rag_postgres_harness.cli index /path/to/repo --project my-repo
uv run python -m adk_rag_postgres_harness.cli search "where is the login handled" --project my-repo
```

Use `--collection code` or `docs` to narrow a search, and `--json` to get the
text of each result. To go from a name to its definition and its importers:

```bash
uv run python -m adk_rag_postgres_harness.cli symbol useUser --project my-repo
uv run python -m adk_rag_postgres_harness.cli uses useUser --project my-repo
uv run python -m adk_rag_postgres_harness.cli uses src/contexts/user/useUser.tsx --project my-repo
```

`tests/test_sync.py` needs the container running and creates
a temporary database for each test; without the container it is skipped.

## Memory

```bash
uv run python -m adk_rag_postgres_harness.cli remember "Retries live in the API client." \
  --project my-repo --kind decision --source "PR 12"
uv run python -m adk_rag_postgres_harness.cli recall "where do retries live" --project my-repo
```

`remember` writes to `docs/harness/memories.jsonl` in the target repository
(`HARNESS_MEMORY_FILE` changes the path) and to the database. **Commit that file:**
Git is the backup, and `index` makes the database match it. On a new machine, clone
the repository and run `index`; a branch switch works the same way. A damaged line,
such as a merge conflict, stops `index` and is never overwritten. To merge parallel
branches without conflicts, add `docs/harness/memories.jsonl merge=union` to the
repository's `.gitattributes`.

- **Credentials:** `remember` refuses text or sources that look like a credential,
  without repeating the value, and `index` stops on one edited into the file. The
  check uses patterns, so it reduces the risk but does not replace reviewing the file
  in the diff.
- **Replacing a decision:** `--supersedes <id>` keeps the old memory in the file and
  hides it from `recall`, unless you pass `--include-superseded`. A memory is replaced
  only once, and repeating a replaced text is refused instead of bringing it back.
- **Editing by hand:** `index` validates the file and applies the edits. An invalid
  line stops it with the line number.
- **Feature logs:** `recall` also searches `docs/harness/session-handoff.md` and each
  feature's `progress.md` and `handoff.md`. They are already versioned and indexed,
  so they are not copied into the memory file.
- **Without Ollama:** the memory is saved and matches by text, and the next `index`
  embeds it.

## MCP server

The server gives an agent the same functions as the CLI, without Google ADK:
`search_code`, `find_symbol`, `read_lines`, `remember` and `recall`. Each server
serves one indexed project. To register it for Claude Code, run this in the target
repository; the `local` scope keeps it out of Git, because the path is yours:

```bash
claude mcp add --scope local code-memory -- uv run --directory /path/to/adk-rag-postgres-harness \
  --extra postgres python -m adk_rag_postgres_harness.cli mcp --project my-repo
```

Other stdio clients, such as `codex mcp add`, take the same command, but only Claude
Code has been tested.

- **Always loaded:** the tools set `anthropic/alwaysLoad`. Otherwise Claude Code hides
  them behind its tool search, and the agent uses grep without ever seeing them.
- **Reading files:** `read_lines` serves indexed files only, up to 400 lines per call,
  and neither it nor the search follows a link. See what stays out of the index below.
- **Failures:** the tools return an error that says what to do. Without Ollama,
  `search_code` and `recall` fail, while `remember`, `find_symbol` and `read_lines`
  keep working.
- **Freshness:** the server does not reindex. Until you run `index` again, new files
  are not found, and `stale` marks files that changed.
- **Worktrees:** the server reads the folder that was indexed, not the agent's
  worktree.

## With Jev in ADK

The same index serves `adk web`, where Jev decides whether to search, which collection
to use (`code`, `docs` or `memory`) and which strategy (`hybrid`, `semantic` or
`keyword`). This path only reads: `remember` stays in the CLI and MCP.

```bash
cd ../adk-rag-harness
uv sync --extra adk --extra openrouter --extra postgres
HARNESS_RAG_PROVIDER=postgres HARNESS_RAG_PROJECT=my-repo uv run adk web
```

- **Cost:** Jev and the conversation model are billed through OpenRouter by default.
  The search itself stays local.
- **Failures:** with the database or the embedding model down, a retrieval ends in
  `blocked` with `human_review`, and so does a search with no evidence. `keyword` needs
  no model, so it still works without Ollama. A missing or unknown project stops the
  app when it starts.
- **Embedding model:** keep the same `HARNESS_EMBED_PROVIDER` and `HARNESS_EMBED_MODEL`
  used by `index`, because other vectors do not exist in the database.
- **`memory`:** it always searches by meaning and by text, whatever strategy was chosen.

## How it works

- **Discovery:** files come from Git and `.ragignore`, as in `rag-harness`.
- **Left out:** symbolic links, names that start with `.env` or contain `secret` or
  `credential`, binary and unreadable files, files over 512 KB and lines over 5,000
  bytes. `index` lists each one with its reason, and they do not stop the others. The
  name check also leaves out code such as `useCredentials.ts`.
- **Moving a project:** `index` refuses a missing folder, and a folder other than the
  one the project was indexed from unless you pass `--move`.
- **Syntax-aware chunks:** tree-sitter splits TS, TSX and JS into components,
  hooks, functions, classes and types, with their leading comments. Definitions
  over 80 lines split between statements; short neighbors stay together. Python
  keeps its AST chunks, and other files keep line chunks.
- **Symbols and imports:** definitions and imports are stored per file. Imports
  resolve to indexed files through relative paths and the `tsconfig.json` aliases.
- **Incremental sync:** a file is chunked again only when its hash or the chunker
  version changes. Chunks are saved before embedding, so an interrupted run resumes on the next one.
- **Embedding cache:** `embeddings` is keyed by content hash and model. Identical
  text is embedded once, vectors of several models coexist, and returning to a
  model recomputes nothing.
- **Hybrid search:** reciprocal rank fusion over the top 50 from HNSW and the top
  50 from full text. Identifiers are split, so `login` finds `handleLogin`.
- **Results:** the database gives the path and lines, and the text is read from
  disk. `stale` marks a file that changed after indexing, because its lines may
  have moved.

## Embedding model

The default is `qwen3-embedding:4b` on Ollama: local, free and open. The column
holds 1,024 dimensions, because a pgvector HNSW index accepts at most 2,000, so
longer vectors are cut and normalized again. A model with fewer dimensions, such
as `nomic-embed-text` (768), fails with a clear error instead of being padded.

Vectors from different models cannot be converted. To change models, set
`HARNESS_EMBED_MODEL` and run `index` again: only the embeddings are computed.
