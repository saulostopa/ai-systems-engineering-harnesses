"""Search a project and read each result from disk, so code is never served stale."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .embeddings import embed_query, embedder_id, memory_embedder
from .store import PostgresStore

from rag_harness.indexer import file_hash  # noqa: E402


@dataclass(frozen=True)
class Hit:
    path: str
    start_line: int
    end_line: int
    collection: str
    kind: str
    name: str
    score: float
    semantic_rank: int | None
    lexical_rank: int | None
    text: str
    # The file changed after indexing, so the lines may have moved.
    stale: bool


def search_code(
    query: str,
    project: str,
    collection: str | None = None,
    top_k: int = 8,
    embedder=None,
    store: PostgresStore | None = None,
) -> list[Hit]:
    store = store or PostgresStore()
    embedder = embedder or memory_embedder()
    found = store.project(project)
    if found is None:
        raise ValueError(f"unknown project {project!r}; index it first")
    rows = store.search(
        found["id"], query, embed_query(embedder, query), embedder_id(embedder), collection, top_k
    )
    root = Path(found["root"])
    hits: list[Hit] = []
    for row in rows:
        full = root / row["path"]
        if not full.is_file():
            continue
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        hits.append(Hit(
            path=row["path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            collection=row["collection"],
            kind=row["kind"],
            name=row["name"],
            score=row["score"],
            semantic_rank=row["semantic_rank"],
            lexical_rank=row["lexical_rank"],
            text="\n".join(lines[row["start_line"] - 1:row["end_line"]]),
            stale=file_hash(str(full)) != row["file_hash"],
        ))
    return hits
