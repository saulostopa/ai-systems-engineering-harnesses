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

## Ingest a collection

From the repository root, with the local RAG package available:

```bash
ollama pull nomic-embed-text
HARNESS_EMBED_PROVIDER=ollama HARNESS_EMBED_MODEL=nomic-embed-text \
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
