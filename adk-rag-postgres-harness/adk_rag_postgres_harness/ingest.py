"""Sync a repository into PostgreSQL + pgvector, embedding only what changed."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .code_chunks import (
    CHUNKER_VERSION,
    TREE_SITTER_EXTS,
    Symbol,
    load_aliases,
    parse_python_imports,
    parse_tree_sitter,
    resolve_import,
)
from .embeddings import embed_texts, embedder_id, memory_embedder
from .memory import restore_memories
from .store import ChunkRow, FileRow, PostgresStore

from rag_harness.chunker import chunk_file  # noqa: E402
from rag_harness.indexer import DEFAULT_EXTS, PROFILES, discover_files  # noqa: E402
from rag_harness.usage import usage_context  # noqa: E402

BATCH_SIZE = 32
# Past these sizes a file is generated data: it would exceed the full-text limit
# or stall the embedding model, and one such file must not stop the others.
MAX_FILE_BYTES = 512 * 1024
MAX_LINE_BYTES = 5000
SENSITIVE_NAME = re.compile(r"(?i)^\.env|secret|credential")
INDEXED_EXTS = tuple(dict.fromkeys((*DEFAULT_EXTS, *TREE_SITTER_EXTS)))
# Python chunk kinds that define something; the rest are only text.
_PYTHON_SYMBOLS = frozenset({"function", "class", "method"})


@dataclass(frozen=True)
class SyncReport:
    project: str
    files: int
    changed: int
    removed: int
    embedded: int
    model: str
    memories: int = 0
    skipped: tuple[tuple[str, str], ...] = ()  # path and reason


def _collection(path: str) -> str:
    return "docs" if path.endswith(PROFILES["docs"]) else "code"


def _inspect(root: Path, full_path: str) -> tuple[str | None, str | None]:
    """The hash of a file, or the reason it stays out of the index."""

    path = Path(full_path)
    if SENSITIVE_NAME.search(path.name):
        return None, "sensitive name"
    try:
        path.relative_to(root).as_posix().encode("utf-8")
    except UnicodeEncodeError:
        return None, "path is not UTF-8"
    # A link can lead outside the repository or to a file Git ignores, such as `.env`.
    if path.resolve() != path:
        return None, "symbolic link"
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None, f"over {MAX_FILE_BYTES} bytes"
        data = path.read_bytes()
    except OSError as exc:
        return None, f"unreadable: {exc.strerror}"
    if b"\0" in data[:8192]:
        return None, "binary"
    if any(len(line) > MAX_LINE_BYTES for line in data.split(b"\n")):
        return None, f"a line over {MAX_LINE_BYTES} bytes"
    return hashlib.sha256(data).hexdigest(), None


def _read_file(root: Path, full_path: str, digest: str) -> FileRow:
    relative = Path(full_path).relative_to(root).as_posix()
    source = Path(full_path).read_text(encoding="utf-8", errors="replace")
    symbols: tuple = ()
    imports: tuple = ()
    if relative.endswith(TREE_SITTER_EXTS):
        parsed = parse_tree_sitter(full_path, source)
        # A file with no syntax to split, such as an empty one, still gets line chunks.
        file_chunks = parsed.chunks or chunk_file(full_path)
        symbols, imports = tuple(parsed.symbols), tuple(parsed.imports)
    else:
        file_chunks = chunk_file(full_path)
        if relative.endswith(".py"):
            imports = tuple(parse_python_imports(source))
            symbols = tuple(
                Symbol(chunk.name, chunk.kind, chunk.start_line, chunk.end_line)
                for chunk in file_chunks
                if chunk.kind in _PYTHON_SYMBOLS
            )
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
        for chunk in file_chunks
        if chunk.text.strip()
    )
    return FileRow(
        relative, digest, _collection(relative), Path(relative).suffix.lstrip("."), chunks,
        CHUNKER_VERSION, symbols, imports,
    )


def _resolve_edges(store: PostgresStore, project_id: int, root: Path, paths: set[str]) -> None:
    """Every sync that changes a file can change where an unchanged file's import points."""

    aliases = load_aliases(root)
    updates = []
    for edge in store.import_edges(project_id):
        resolved = resolve_import(edge["path"], edge["specifier"], paths, aliases)
        if resolved != edge["resolved_path"]:
            updates.append((resolved, edge["id"]))
    store.set_resolved_paths(updates)


def sync(
    root: str,
    project: str | None = None,
    embedder=None,
    store: PostgresStore | None = None,
    exts: tuple[str, ...] = INDEXED_EXTS,
    verbose: bool = False,
    move: bool = False,
) -> SyncReport:
    root_path = Path(root).resolve()
    name = project or root_path.name
    if not root_path.is_dir():
        raise ValueError(f"{root} is not a folder")
    embedder = embedder or memory_embedder()
    store = store or PostgresStore()
    store.migrate()
    existing = store.project(name)
    if existing and existing["root"] != str(root_path) and not move:
        raise ValueError(
            f"project {name!r} is indexed from {existing['root']}; "
            "pass --move if it moved, or --project to index this folder under another name"
        )
    project_id = store.ensure_project(name, str(root_path))

    with store.sync_lock(project_id):
        known = store.file_states(project_id)
        current: dict[str, tuple[str, str]] = {}
        skipped: list[tuple[str, str]] = []
        for full in discover_files(str(root_path), exts):
            relative = Path(full).relative_to(root_path).as_posix()
            digest, reason = _inspect(root_path, full)
            if reason:
                skipped.append((relative.encode("utf-8", "backslashreplace").decode(), reason))
            else:
                current[relative] = (full, digest)
        changed = [
            _read_file(root_path, full, digest)
            for relative, (full, digest) in current.items()
            if known.get(relative) != (digest, CHUNKER_VERSION)
        ]
        removed = [path for path in known if path not in current]
        store.apply_changes(project_id, changed, removed)
        if changed or removed:
            _resolve_edges(store, project_id, root_path, set(current))

    memories = restore_memories(store, project_id, root_path)

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
    return SyncReport(name, len(current), len(changed), len(removed), len(missing), model, memories, tuple(skipped))
