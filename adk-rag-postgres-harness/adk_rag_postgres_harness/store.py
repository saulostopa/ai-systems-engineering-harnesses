"""PostgreSQL + pgvector storage and hybrid retrieval."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable


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


class PostgresStore:
    def __init__(self, url: str | None = None, embedding_dim: int = 768) -> None:
        self.url = url or database_url()
        self.embedding_dim = embedding_dim

    def connect(self):
        psycopg = _require_psycopg()
        return psycopg.connect(self.url, row_factory=psycopg.rows.dict_row)

    def migrate(self, migrations_dir: str | Path | None = None) -> None:
        root = Path(migrations_dir or Path(__file__).parents[1] / "migrations")
        with self.connect() as conn:
            for migration in sorted(root.glob("*.sql")):
                conn.execute(migration.read_text(encoding="utf-8"))

    def replace_collection(self, collection: str, rows: Iterable[dict]) -> int:
        rows = list(rows)
        for row in rows:
            if len(row["embedding"]) != self.embedding_dim:
                raise ValueError(
                    f"embedding dimension mismatch: expected {self.embedding_dim}, "
                    f"got {len(row['embedding'])}"
                )
        statement = """
            INSERT INTO rag_chunks (
                chunk_id, collection, source, kind, name, content,
                start_line, end_line, content_hash, metadata, embedding
            ) VALUES (
                %(chunk_id)s, %(collection)s, %(source)s, %(kind)s, %(name)s,
                %(content)s, %(start_line)s, %(end_line)s, %(content_hash)s,
                %(metadata)s::jsonb, %(embedding)s::vector
            )
            ON CONFLICT (chunk_id) DO UPDATE SET
                content = EXCLUDED.content,
                start_line = EXCLUDED.start_line,
                end_line = EXCLUDED.end_line,
                content_hash = EXCLUDED.content_hash,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding,
                updated_at = now()
        """
        with self.connect() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE collection = %s", (collection,))
            with conn.cursor() as cursor:
                cursor.executemany(statement, [
                    {
                        **row,
                        "metadata": json.dumps(row.get("metadata", {})),
                        "embedding": vector_literal(row["embedding"]),
                    }
                    for row in rows
                ])
        return len(rows)

    def search(
        self,
        collection: str,
        query: str,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[dict]:
        if len(query_embedding) != self.embedding_dim:
            raise ValueError("query embedding dimension does not match the index")
        filters = filters or {}
        clauses = ["collection = %s"]
        params: list[object] = [collection]
        for key, value in sorted(filters.items()):
            clauses.append("metadata ->> %s = %s")
            params.extend([key, value])
        where = " AND ".join(clauses)
        sql = f"""
            WITH ranked AS (
                SELECT *,
                    ts_rank_cd(
                        to_tsvector('simple', content),
                        websearch_to_tsquery('simple', %s)
                    ) AS lexical_score,
                    1 - (embedding <=> %s::vector) AS semantic_score
                FROM rag_chunks
                WHERE {where}
            )
            SELECT chunk_id, source, kind, name, content, start_line, end_line,
                   lexical_score, semantic_score,
                   (0.45 * lexical_score + 0.55 * semantic_score) AS score
            FROM ranked
            ORDER BY score DESC, source ASC, start_line ASC
            LIMIT %s
        """
        params = [query, vector_literal(query_embedding), *params, top_k]
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())
