"""PostgreSQL + pgvector storage and hybrid retrieval."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Candidates taken from each search before fusion, and the usual RRF constant.
CANDIDATES = 50
RRF_K = 60
_WORD = re.compile(r"\w+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "in", "is", "it",
    "of", "on", "or", "the", "to", "what", "where", "which", "with", "who", "why",
    "as", "com", "como", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "o", "os",
    "onde", "para", "por", "qual", "que", "se", "um", "uma",
})


def _require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install the postgres extra: uv sync --extra postgres") from exc
    return psycopg


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://harness:harness@localhost:5433/harness_rag",
    )


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"


def identifier_terms(text: str) -> list[str]:
    """Lowercase words plus the parts of each identifier: handleLogin, handle, login."""

    terms: list[str] = []
    for word in _WORD.findall(text):
        for piece in word.split("_"):
            if piece:
                terms.append(piece.lower())
                parts = _CAMEL.findall(piece)
                if len(parts) > 1:
                    terms.extend(part.lower() for part in parts)
    return terms


def search_text(path: str, content: str) -> str:
    """The text behind the full-text index: the path, the code and split identifiers."""

    return " ".join([path, content, *dict.fromkeys(identifier_terms(f"{path} {content}"))])


def lexical_query(query: str) -> str:
    """A `to_tsquery` that matches any term: questions rarely contain all of them."""

    terms = dict.fromkeys(term for term in identifier_terms(query) if len(term) > 1 and term not in _STOPWORDS)
    return " | ".join(f"'{term}'" for term in terms)


@dataclass(frozen=True)
class ChunkRow:
    kind: str
    name: str
    start_line: int
    end_line: int
    content_hash: str
    content: str


@dataclass(frozen=True)
class FileRow:
    path: str
    content_hash: str
    collection: str
    language: str
    chunks: tuple[ChunkRow, ...]
    chunker_version: int = 1
    symbols: tuple = ()
    imports: tuple = ()


class PostgresStore:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or database_url()

    def connect(self):
        psycopg = _require_psycopg()
        return psycopg.connect(self.url, row_factory=psycopg.rows.dict_row)

    def migrate(self, migrations_dir: str | Path | None = None) -> None:
        root = Path(migrations_dir or Path(__file__).parents[1] / "migrations")
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(0, 0)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
            for migration in sorted(root.glob("*.sql")):
                if migration.name not in applied:
                    conn.execute(migration.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (migration.name,))

    def ensure_project(self, name: str, root: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO projects (name, root) VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET root = EXCLUDED.root, updated_at = now()
                RETURNING id
                """,
                (name, root),
            ).fetchone()
        return row["id"]

    def project(self, name: str) -> dict | None:
        with self.connect() as conn:
            return conn.execute("SELECT id, name, root FROM projects WHERE name = %s", (name,)).fetchone()

    def file_states(self, project_id: int) -> dict[str, tuple[str, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT path, content_hash, chunker_version FROM files WHERE project_id = %s", (project_id,)
            )
            return {row["path"]: (row["content_hash"], row["chunker_version"]) for row in rows}

    def apply_changes(self, project_id: int, changed: Iterable[FileRow], removed: Iterable[str]) -> None:
        """Replace changed files and their chunks in one transaction."""

        changed = list(changed)
        with self.connect() as conn:
            paths = [*removed, *(file.path for file in changed)]
            conn.execute("DELETE FROM files WHERE project_id = %s AND path = ANY(%s)", (project_id, paths))
            with conn.cursor() as cursor:
                for file in changed:
                    file_id = cursor.execute(
                        """
                        INSERT INTO files (project_id, path, content_hash, collection, language, chunker_version)
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                        """,
                        (project_id, file.path, file.content_hash, file.collection, file.language, file.chunker_version),
                    ).fetchone()["id"]
                    cursor.executemany(
                        """
                        INSERT INTO chunks (
                            project_id, file_id, collection, kind, name, start_line, end_line,
                            content_hash, content, search_text
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                project_id, file_id, file.collection, chunk.kind, chunk.name,
                                chunk.start_line, chunk.end_line, chunk.content_hash, chunk.content,
                                search_text(file.path, chunk.content),
                            )
                            for chunk in file.chunks
                        ],
                    )
                    cursor.executemany(
                        """
                        INSERT INTO symbols (project_id, file_id, name, kind, parent, exported, start_line, end_line)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (project_id, file_id, s.name, s.kind, s.parent, s.exported, s.start_line, s.end_line)
                            for s in file.symbols
                        ],
                    )
                    cursor.executemany(
                        "INSERT INTO edges (project_id, file_id, specifier, name, alias) VALUES (%s, %s, %s, %s, %s)",
                        [(project_id, file_id, ref.specifier, ref.name, ref.alias) for ref in file.imports],
                    )

    def import_edges(self, project_id: int) -> list[dict]:
        with self.connect() as conn:
            return list(conn.execute(
                """
                SELECT e.id, f.path, e.specifier, e.resolved_path
                FROM edges e JOIN files f ON f.id = e.file_id
                WHERE e.project_id = %s
                """,
                (project_id,),
            ))

    def set_resolved_paths(self, updates: Iterable[tuple[str | None, int]]) -> None:
        with self.connect() as conn, conn.cursor() as cursor:
            cursor.executemany("UPDATE edges SET resolved_path = %s WHERE id = %s", list(updates))

    def find_symbols(self, project_id: int, name: str, limit: int = 20) -> list[dict]:
        """Exact name first, ignoring case, then names that contain it."""

        with self.connect() as conn:
            return list(conn.execute(
                """
                SELECT s.name, s.kind, s.parent, s.exported, s.start_line, s.end_line, f.path
                FROM symbols s JOIN files f ON f.id = s.file_id
                WHERE s.project_id = %(project_id)s AND lower(s.name) LIKE %(pattern)s
                ORDER BY lower(s.name) = lower(%(name)s) DESC, s.exported DESC, length(s.name), f.path, s.start_line
                LIMIT %(limit)s
                """,
                {
                    "project_id": project_id,
                    "name": name,
                    "pattern": "%" + name.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
                    "limit": limit,
                },
            ))

    def find_importers(self, project_id: int, name: str, path: str | None = None, limit: int = 50) -> list[dict]:
        """Files that import a name or a package, or everything that imports a file when `path` is given."""

        scope = (
            "(e.resolved_path = %(path)s OR e.specifier = %(name)s)"
            if path
            else "(lower(e.name) = lower(%(name)s) OR lower(e.alias) = lower(%(name)s) OR e.specifier = %(name)s)"
        )
        with self.connect() as conn:
            return list(conn.execute(
                f"""
                SELECT DISTINCT f.path, e.specifier, e.name, e.alias, e.resolved_path
                FROM edges e JOIN files f ON f.id = e.file_id
                WHERE e.project_id = %(project_id)s AND {scope}
                ORDER BY f.path, e.specifier, e.name
                LIMIT %(limit)s
                """,
                {"project_id": project_id, "name": name, "path": path, "limit": limit},
            ))

    def missing_embeddings(self, project_id: int, model: str) -> list[dict]:
        """Chunks without a vector for this model, so a changed model or a crash just resumes."""

        with self.connect() as conn:
            return list(conn.execute(
                """
                SELECT DISTINCT ON (t.content_hash) t.content_hash, t.content
                FROM (
                    SELECT content_hash, content FROM chunks WHERE project_id = %(project_id)s
                    UNION ALL
                    SELECT content_hash, text FROM memories WHERE project_id = %(project_id)s
                ) AS t
                LEFT JOIN embeddings e ON e.content_hash = t.content_hash AND e.model = %(model)s
                WHERE e.content_hash IS NULL
                ORDER BY t.content_hash
                """,
                {"model": model, "project_id": project_id},
            ))

    @contextlib.contextmanager
    def sync_lock(self, project_id: int):
        """Serialize runs that change a project's files; the embedding after it runs unlocked."""

        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(1, %s)", (project_id,))
            yield

    @contextlib.contextmanager
    def memory_lock(self, project_id: int):
        """Serialize writers of a project's memory file, such as two MCP clients."""

        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (project_id,))
            yield

    def replace_memories(self, project_id: int, memories: Iterable) -> None:
        """Mirror the versioned file, so a memory removed there also leaves the database."""

        memories = list(memories)
        with self.connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM memories WHERE project_id = %s AND NOT (id = ANY(%s))",
                (project_id, [memory.id for memory in memories]),
            )
            cursor.executemany(
                """
                INSERT INTO memories (
                    project_id, id, kind, text, source, created_at, superseded_by, content_hash, search_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    text = EXCLUDED.text,
                    source = EXCLUDED.source,
                    created_at = EXCLUDED.created_at,
                    superseded_by = EXCLUDED.superseded_by,
                    content_hash = EXCLUDED.content_hash,
                    search_text = EXCLUDED.search_text
                """,
                [
                    (
                        project_id, memory.id, memory.kind, memory.text, memory.source, memory.created_at,
                        memory.superseded_by, hashlib.sha256(memory.text.encode("utf-8")).hexdigest(),
                        search_text(memory.source, memory.text),
                    )
                    for memory in memories
                ],
            )

    def recall(
        self,
        project_id: int,
        query: str,
        query_embedding: list[float],
        model: str,
        log_paths: str,
        kind_filter: str | None = None,
        file_filter: str | None = None,
        include_files: bool = True,
        include_superseded: bool = False,
        top_k: int = 8,
    ) -> list[dict]:
        """Reciprocal rank fusion over memories and the chunks of feature logs."""

        memory_scope = "" if include_superseded else "AND m.superseded_by IS NULL"
        if kind_filter:
            memory_scope += " AND m.kind = %(kind)s"
        file_scope = "AND f.path ~ %(log_paths)s"
        if file_filter:
            file_scope += " AND f.path ~ %(file_filter)s"
        if not include_files:
            file_scope += " AND false"
        sql = f"""
            WITH semantic AS (
                SELECT origin, ref, row_number() OVER (ORDER BY distance, origin, ref) AS rank
                FROM (
                    SELECT 'memory' AS origin, m.id AS ref, e.embedding <=> %(vector)s::vector AS distance
                    FROM memories m
                    JOIN embeddings e ON e.content_hash = m.content_hash AND e.model = %(model)s
                    WHERE m.project_id = %(project_id)s {memory_scope}
                    UNION ALL
                    SELECT 'file', c.id::text, e.embedding <=> %(vector)s::vector
                    FROM chunks c
                    JOIN files f ON f.id = c.file_id
                    JOIN embeddings e ON e.content_hash = c.content_hash AND e.model = %(model)s
                    WHERE c.project_id = %(project_id)s {file_scope}
                    ORDER BY distance
                    LIMIT {CANDIDATES}
                ) AS nearest
            ),
            lexical AS (
                SELECT origin, ref, row_number() OVER (ORDER BY text_rank DESC, origin, ref) AS rank
                FROM (
                    SELECT 'memory' AS origin, m.id AS ref, ts_rank_cd(m.search_tsv, q.tsq) AS text_rank
                    FROM memories m, to_tsquery('simple', %(lexical)s) AS q(tsq)
                    WHERE m.project_id = %(project_id)s {memory_scope} AND m.search_tsv @@ q.tsq
                    UNION ALL
                    SELECT 'file', c.id::text, ts_rank_cd(c.search_tsv, q.tsq)
                    FROM chunks c
                    JOIN files f ON f.id = c.file_id,
                    to_tsquery('simple', %(lexical)s) AS q(tsq)
                    WHERE c.project_id = %(project_id)s {file_scope} AND c.search_tsv @@ q.tsq
                    ORDER BY text_rank DESC
                    LIMIT {CANDIDATES}
                ) AS matched
            ),
            fused AS (
                SELECT origin, ref, COALESCE(1.0 / ({RRF_K} + s.rank), 0) + COALESCE(1.0 / ({RRF_K} + l.rank), 0) AS score
                FROM semantic s
                FULL JOIN lexical l USING (origin, ref)
            )
            SELECT x.origin, x.ref, x.score::float AS score,
                   m.kind AS memory_kind, m.text AS memory_text, m.source AS memory_source,
                   m.created_at, m.superseded_by,
                   f.path, c.start_line, c.end_line
            FROM fused x
            LEFT JOIN memories m ON x.origin = 'memory' AND m.project_id = %(project_id)s AND m.id = x.ref
            LEFT JOIN chunks c ON x.origin = 'file' AND c.id = CASE WHEN x.origin = 'file' THEN x.ref::bigint END
            LEFT JOIN files f ON f.id = c.file_id
            ORDER BY x.score DESC, x.origin DESC, x.ref
            LIMIT %(top_k)s
        """
        params = {
            "file_filter": file_filter,
            "kind": kind_filter,
            "lexical": lexical_query(query),
            "log_paths": log_paths,
            "model": model,
            "project_id": project_id,
            "top_k": top_k,
            "vector": vector_literal(query_embedding),
        }
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def put_embeddings(self, model: str, items: Iterable[tuple[str, list[float]]]) -> None:
        with self.connect() as conn, conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO embeddings (content_hash, model, embedding) VALUES (%s, %s, %s::vector)
                ON CONFLICT (content_hash, model) DO NOTHING
                """,
                [(content_hash, model, vector_literal(vector)) for content_hash, vector in items],
            )

    @staticmethod
    def _semantic_sql(collection: str | None) -> str:
        scope = "AND c.collection = %(collection)s" if collection else ""
        return f"""
            SELECT c.id
            FROM embeddings e
            JOIN chunks c ON c.content_hash = e.content_hash
            WHERE e.model = %(model)s AND c.project_id = %(project_id)s {scope}
            ORDER BY e.embedding <=> %(vector)s::vector
            LIMIT {CANDIDATES}
        """

    @staticmethod
    def _prepare_vector_scan(conn) -> None:
        # Filters run after the HNSW scan, so it keeps scanning until the limit is met.
        conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        conn.execute(f"SET LOCAL hnsw.ef_search = {CANDIDATES * 2}")

    def search(
        self,
        project_id: int,
        query: str,
        query_embedding: list[float],
        model: str,
        collection: str | None = None,
        top_k: int = 8,
    ) -> list[dict]:
        """Reciprocal rank fusion over the vector and the full-text candidates."""

        scope = "AND c.collection = %(collection)s" if collection else ""
        sql = f"""
            WITH semantic AS (
                SELECT id, row_number() OVER () AS rank
                FROM ({self._semantic_sql(collection)}) AS nearest
            ),
            lexical AS (
                SELECT id, row_number() OVER (ORDER BY text_rank DESC, id) AS rank
                FROM (
                    SELECT c.id, ts_rank_cd(c.search_tsv, q.tsq) AS text_rank
                    FROM chunks c, to_tsquery('simple', %(lexical)s) AS q(tsq)
                    WHERE c.project_id = %(project_id)s {scope} AND c.search_tsv @@ q.tsq
                    ORDER BY text_rank DESC, c.id
                    LIMIT {CANDIDATES}
                ) AS matched
            ),
            fused AS (
                SELECT COALESCE(s.id, l.id) AS id,
                       s.rank AS semantic_rank,
                       l.rank AS lexical_rank,
                       COALESCE(1.0 / ({RRF_K} + s.rank), 0) + COALESCE(1.0 / ({RRF_K} + l.rank), 0) AS score
                FROM semantic s
                FULL JOIN lexical l ON l.id = s.id
            )
            SELECT f.path, f.content_hash AS file_hash, c.collection, c.kind, c.name,
                   c.start_line, c.end_line, x.semantic_rank, x.lexical_rank, x.score::float AS score
            FROM fused x
            JOIN chunks c ON c.id = x.id
            JOIN files f ON f.id = c.file_id
            ORDER BY x.score DESC, f.path ASC, c.start_line ASC
            LIMIT %(top_k)s
        """
        params = {
            "collection": collection,
            "lexical": lexical_query(query),
            "model": model,
            "project_id": project_id,
            "top_k": top_k,
            "vector": vector_literal(query_embedding),
        }
        with self.connect() as conn:
            self._prepare_vector_scan(conn)
            return list(conn.execute(sql, params).fetchall())

    def semantic_plan(
        self,
        project_id: int,
        query_embedding: list[float],
        model: str,
        collection: str | None = None,
        force_index: bool = False,
    ) -> str:
        """EXPLAIN of the vector candidates; `force_index` proves the query shape can use HNSW."""

        with self.connect() as conn:
            self._prepare_vector_scan(conn)
            if force_index:
                conn.execute("SET LOCAL enable_seqscan = off")
                conn.execute("SET LOCAL enable_sort = off")
            rows = conn.execute(
                "EXPLAIN " + self._semantic_sql(collection),
                {
                    "collection": collection,
                    "model": model,
                    "project_id": project_id,
                    "vector": vector_literal(query_embedding),
                },
            )
            return "\n".join(row["QUERY PLAN"] for row in rows)
