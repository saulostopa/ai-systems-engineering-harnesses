"""Search a project and read each result from disk, so code is never served stale."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from .embeddings import embed_query, embedder_id, memory_embedder
from .store import PostgresStore

from rag_harness.indexer import file_hash  # noqa: E402

MAX_READ_LINES = 400


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


@dataclass(frozen=True)
class FileLines:
    path: str
    start_line: int
    end_line: int
    total_lines: int
    text: str
    truncated: bool
    stale: bool


def read_lines(path: Path, start_line: int, end_line: int) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[start_line - 1:end_line])


def safe_file(root: str | Path, relative: str) -> Path | None:
    """The file inside the repository, or None for anything a link could lead away from it."""

    base = Path(root).resolve()
    full = base / relative
    try:
        inside = full.resolve() == full and full.is_relative_to(base)
    except (OSError, RuntimeError):
        return None
    return full if inside and full.is_file() else None


def read_file(
    path: str,
    project: str,
    start_line: int = 1,
    end_line: int | None = None,
    store: PostgresStore | None = None,
) -> FileLines:
    """Read an indexed file only, so `.env` and anything outside the repository stay out of reach."""

    store = store or PostgresStore()
    found = store.project(project)
    if found is None:
        raise ValueError(f"unknown project {project!r}; index it first")
    state = store.file_states(found["id"]).get(path)
    if state is None:
        raise ValueError(f"{path!r} is not an indexed file of {project!r}")
    full = safe_file(found["root"], path)
    if full is None:
        raise ValueError(f"{path!r} no longer exists or became a link; run the index again")
    if start_line < 1 or (end_line is not None and end_line < start_line):
        raise ValueError(f"invalid line range {start_line}-{end_line}")

    lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    last = len(lines) if end_line is None else min(end_line, len(lines))
    served = min(last, start_line + MAX_READ_LINES - 1)
    return FileLines(
        path=path,
        start_line=start_line,
        end_line=served,
        total_lines=len(lines),
        text="\n".join(lines[start_line - 1:served]),
        truncated=served < last,
        stale=file_hash(str(full)) != state[0],
    )


def _project_id(store: PostgresStore, project: str) -> int:
    found = store.project(project)
    if found is None:
        raise ValueError(f"unknown project {project!r}; index it first")
    return found["id"]


def find_symbol(name: str, project: str, store: PostgresStore | None = None, limit: int = 20) -> list[dict]:
    store = store or PostgresStore()
    return store.find_symbols(_project_id(store, project), name, limit)


def where_used(name: str, project: str, store: PostgresStore | None = None, limit: int = 50) -> list[dict]:
    """Importers of a name or package, or of a file when `name` is a path."""

    store = store or PostgresStore()
    project_id = _project_id(store, project)
    if "/" in name:
        return store.find_importers(project_id, name, path=posixpath.normpath(name), limit=limit)
    return store.find_importers(project_id, name, limit=limit)


def search_code(
    query: str,
    project: str,
    collection: str | None = None,
    top_k: int = 8,
    embedder=None,
    store: PostgresStore | None = None,
    strategy: str = "hybrid",
) -> list[Hit]:
    store = store or PostgresStore()
    found = store.project(project)
    if found is None:
        raise ValueError(f"unknown project {project!r}; index it first")
    # Keyword search needs no model, so it also works without Ollama.
    vector, model = None, ""
    if strategy != "keyword":
        embedder = embedder or memory_embedder()
        vector, model = embed_query(embedder, query), embedder_id(embedder)
    rows = store.search(found["id"], query, vector, model, collection, top_k, strategy)
    hits: list[Hit] = []
    for row in rows:
        full = safe_file(found["root"], row["path"])
        if full is None:
            continue
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
            text=read_lines(full, row["start_line"], row["end_line"]),
            stale=file_hash(str(full)) != row["file_hash"],
        ))
    return hits
