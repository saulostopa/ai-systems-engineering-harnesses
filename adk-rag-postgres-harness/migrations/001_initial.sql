CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    content_hash TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rag_chunks_collection_idx
    ON rag_chunks (collection);

CREATE INDEX IF NOT EXISTS rag_chunks_source_idx
    ON rag_chunks (collection, source);

CREATE INDEX IF NOT EXISTS rag_chunks_metadata_idx
    ON rag_chunks USING gin (metadata);

CREATE INDEX IF NOT EXISTS rag_chunks_text_search_idx
    ON rag_chunks USING gin (to_tsvector('simple', content));

CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);
