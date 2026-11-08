-- Files from an older chunker are chunked again on the next sync.
ALTER TABLE files ADD COLUMN IF NOT EXISTS chunker_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS symbols (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    file_id BIGINT NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    parent TEXT NOT NULL DEFAULT '',
    exported BOOLEAN NOT NULL DEFAULT false,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS symbols_file_idx ON symbols (file_id);
CREATE INDEX IF NOT EXISTS symbols_name_idx ON symbols (project_id, lower(name));

CREATE TABLE IF NOT EXISTS edges (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    file_id BIGINT NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'import',
    specifier TEXT NOT NULL,
    name TEXT NOT NULL,
    alias TEXT NOT NULL,
    -- Null for packages and for modules that are not indexed.
    resolved_path TEXT
);

CREATE INDEX IF NOT EXISTS edges_file_idx ON edges (file_id);
CREATE INDEX IF NOT EXISTS edges_name_idx ON edges (project_id, lower(name));
CREATE INDEX IF NOT EXISTS edges_alias_idx ON edges (project_id, lower(alias));
CREATE INDEX IF NOT EXISTS edges_resolved_idx ON edges (project_id, resolved_path);
