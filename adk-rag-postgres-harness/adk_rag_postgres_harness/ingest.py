"""Index source files into PostgreSQL + pgvector."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from rag_harness.chunker import chunk_file
from rag_harness.embeddings import make_embedder

from .store import PostgresStore


def ingest(root: str, collection: str = "docs") -> int:
    root_path = Path(root).resolve()
    embedder = make_embedder()
    rows: list[dict] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix not in {".py", ".md", ".txt", ".sh", ".yaml", ".yml", ".json", ".ts", ".tsx"}:
            continue
        relative = path.relative_to(root_path).as_posix()
        for chunk in chunk_file(str(path)):
            chunk_id = hashlib.sha256(
                f"{relative}:{chunk.start_line}:{chunk.hash}".encode("utf-8")
            ).hexdigest()
            rows.append({
                "chunk_id": chunk_id,
                "collection": collection,
                "source": relative,
                "kind": chunk.kind,
                "name": chunk.name,
                "content": chunk.text,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content_hash": chunk.hash,
                "metadata": {"language": path.suffix.lstrip(".")},
                "embedding": embedder.embed(chunk.text),
            })
    store = PostgresStore(embedding_dim=len(rows[0]["embedding"]) if rows else 768)
    store.migrate()
    count = store.replace_collection(collection, rows)
    print(f"indexed {count} chunks from {root_path} into collection {collection!r}")
    return count
