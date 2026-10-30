"""Sync a repository into PostgreSQL + pgvector, embedding only what changed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .embeddings import embed_texts, embedder_id, memory_embedder
from .store import ChunkRow, FileRow, PostgresStore

from rag_harness.chunker import chunk_file  # noqa: E402
from rag_harness.indexer import DEFAULT_EXTS, PROFILES, discover_files, file_hash  # noqa: E402
from rag_harness.usage import usage_context  # noqa: E402

BATCH_SIZE = 32


@dataclass(frozen=True)
class SyncReport:
    project: str
    files: int
    changed: int
    removed: int
    embedded: int
    model: str


def _collection(path: str) -> str:
    return "docs" if path.endswith(PROFILES["docs"]) else "code"


def _read_file(root: Path, full_path: str, digest: str) -> FileRow:
    relative = Path(full_path).relative_to(root).as_posix()
    chunks = tuple(
        ChunkRow(
            kind=chunk.kind,
            name=chunk.name,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content_hash=chunk.hash,
            # PostgreSQL text cannot hold NUL bytes.
            content=chunk.text.replace("\x00", ""),
        )
        for chunk in chunk_file(full_path)
        if chunk.text.strip()
    )
    return FileRow(relative, digest, _collection(relative), Path(relative).suffix.lstrip("."), chunks)


def sync(
    root: str,
    project: str | None = None,
    embedder=None,
    store: PostgresStore | None = None,
    exts: tuple[str, ...] = DEFAULT_EXTS,
    verbose: bool = False,
) -> SyncReport:
    root_path = Path(root).resolve()
    name = project or root_path.name
    embedder = embedder or memory_embedder()
    store = store or PostgresStore()
    store.migrate()
    project_id = store.ensure_project(name, str(root_path))

    known = store.file_hashes(project_id)
    current = {
        Path(full).relative_to(root_path).as_posix(): (full, file_hash(full))
        for full in discover_files(str(root_path), exts)
    }
    changed = [
        _read_file(root_path, full, digest)
        for relative, (full, digest) in current.items()
        if known.get(relative) != digest
    ]
    removed = [path for path in known if path not in current]
    store.apply_changes(project_id, changed, removed)

    # Chunks are written first: an interrupted run embeds the rest on the next one.
    model = embedder_id(embedder)
    missing = store.missing_embeddings(project_id, model)
    with usage_context(component="embedding_index", operation="index postgres", project_root=str(root_path)):
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start:start + BATCH_SIZE]
            vectors = embed_texts(embedder, [row["content"] for row in batch])
            store.put_embeddings(model, zip((row["content_hash"] for row in batch), vectors))
            if verbose:
                print(f"embedded {start + len(batch)}/{len(missing)}", flush=True)
    return SyncReport(name, len(current), len(changed), len(removed), len(missing), model)
