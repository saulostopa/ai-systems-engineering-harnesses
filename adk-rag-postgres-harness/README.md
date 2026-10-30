# ADK RAG PostgreSQL Harness

A code memory on PostgreSQL and `pgvector`, built from open source parts. It
keeps a repository indexed incrementally and searches it by meaning and by text.

The plan is in the course backlog (`docs/tasks/code-memory-postgres.md`). Phases 1
and 2 are done: the Postgres core, incremental sync, hybrid search, syntax-aware
chunks, symbols and imports. Memory, the MCP server and the ADK wiring come next.

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

## How it works

- **Discovery:** files come from Git and `.ragignore`, as in `rag-harness`.
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

`PostgresRagAdapter` keeps the ADK retrieval contract, but `adk web` does not
select it yet.
