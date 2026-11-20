-- What people and agents actually ask, to build evaluation questions from real
-- use. Local only, and lost with the database: export it with `queries --json`.
CREATE TABLE IF NOT EXISTS queries (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    entry TEXT NOT NULL,
    tool TEXT NOT NULL,
    query TEXT NOT NULL,
    collection TEXT,
    strategy TEXT,
    results JSONB NOT NULL,
    latency_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS queries_project_idx ON queries (project_id, created_at DESC);
