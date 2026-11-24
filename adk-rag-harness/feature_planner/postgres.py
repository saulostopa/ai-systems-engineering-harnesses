"""Read-only planning over the Postgres index with exact chunk provenance."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REFERENCE_TOP_K = 4


def docs_budget(top_k: int) -> int:
    """A third of each project's places go to documentation and the rest to code."""

    return top_k // 3


class PostgresSearch:
    def __init__(self, project: str, store=None, embedder=None, *, references=(), target_top_k=None):
        if target_top_k is not None and (type(target_top_k) is not int or not 1 <= target_top_k <= 16):
            raise ValueError("Target retrieval size must be an integer from 1 to 16.")
        root = Path(__file__).resolve().parents[2] / "adk-rag-postgres-harness"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from adk_rag_postgres_harness.embeddings import embed_query, embedder_id, memory_embedder
        from adk_rag_postgres_harness.store import PostgresStore, _require_psycopg

        self.project = project
        self.references = tuple(name for name in dict.fromkeys(references) if name != project)
        self.target_top_k = target_top_k if target_top_k is not None else (4 if self.references else 6)
        self.store = store if store is not None else PostgresStore()
        self.embedder = embedder if embedder is not None else memory_embedder()
        self.model = embedder_id(self.embedder)
        self.embed_query = embed_query
        self.database_error = _require_psycopg().Error

    def __call__(self, query: str) -> tuple[list[dict], dict]:
        try:
            vector = self.embed_query(self.embedder, query)
            projects = (self.project, *self.references)
            budgets = [self.target_top_k, *(REFERENCE_TOP_K for _ in self.references)]
            snapshots = [
                self.store.planning_snapshot(
                    project, query, vector, self.model, top_k=top_k, docs_top_k=docs_budget(top_k),
                )
                for project, top_k in zip(projects, budgets)
            ]
        except (RuntimeError, ValueError, OSError, self.database_error):
            raise OSError("Postgres retrieval or the embedding service failed.") from None

        evidence = []
        chunks = []
        baselines = {}
        for project, (stats, rows) in zip(projects, snapshots):
            origin = "target" if project == self.project else "reference"
            baselines[project] = dict(stats)
            for row in rows:
                evidence_row, chunk = self._chunk(row, len(evidence) + 1, project, origin)
                evidence.append(evidence_row)
                chunks.append(chunk)

        baseline = {key: sum(stats[key] for stats in baselines.values()) for key in ("chunks", "utf8_bytes")}
        return evidence, {
            "backend": "postgres", "project": self.project, "strategy": "hybrid per collection",
            "reference_projects": list(self.references), "project_baselines": baselines,
            "embedding_model": self.model, "retrieved": chunks, "baseline": baseline,
        }

    @staticmethod
    def _chunk(row, position, project, origin):
        text = row["indexed_text"]
        item = {
            "id": f"E{position}", "project": project, "origin": origin, "path": row["path"], "start_line": row["start_line"],
            "end_line": row["end_line"], "text": text,
        }
        return item, {
            **{key: value for key, value in item.items() if key != "text"},
            "chunk_id": row["chunk_id"], "chunk_hash": row["content_hash"],
            "file_hash": row["file_hash"], "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "embedding_dimensions": row["embedding_dimensions"],
            "semantic_rank": row["semantic_rank"], "lexical_rank": row["lexical_rank"],
        }
