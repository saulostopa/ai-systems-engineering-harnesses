-- A rebuildable copy of the versioned memory file, which remains the source of
-- truth. Vectors live in `embeddings`, keyed by content hash and model.
CREATE TABLE IF NOT EXISTS memories (
    project_id BIGINT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    superseded_by TEXT,
    content_hash TEXT NOT NULL,
    search_text TEXT NOT NULL,
    search_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED,
    PRIMARY KEY (project_id, id)
);

CREATE INDEX IF NOT EXISTS memories_hash_idx ON memories (content_hash);
CREATE INDEX IF NOT EXISTS memories_search_idx ON memories USING gin (search_tsv);
