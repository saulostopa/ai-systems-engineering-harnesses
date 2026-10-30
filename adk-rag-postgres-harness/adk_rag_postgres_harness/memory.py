"""Memories kept in a versioned file, so Git is the backup and Postgres can be rebuilt."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .embeddings import embed_query, embed_texts, embedder_id, memory_embedder
from .retrieval import read_lines
from .store import PostgresStore

DEFAULT_MEMORY_FILE = "docs/harness/memories.jsonl"
KINDS = ("decision", "convention", "handoff", "note")
MAX_TEXT_CHARS = 2000
# Feature logs are already versioned and indexed, so recall reads them without a second copy.
HANDOFF_PATHS = r"^docs/harness/(session-handoff\.md|features/[^/]+/(progress|handoff)\.md)$"

_CREDENTIALS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "API key": re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "URL with a password": re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
    "secret assignment": re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b[\"']?\s*[:=]\s*[\"']?[^\s\"']{8,}"
    ),
}


class MemoryRefused(ValueError):
    """The memory would put a credential or an invalid entry in the repository."""


@dataclass(frozen=True)
class Memory:
    id: str
    kind: str
    text: str
    source: str
    created_at: str
    superseded_by: str | None = None


@dataclass(frozen=True)
class RecallHit:
    origin: str  # "memory", or "file" for a feature progress or handoff log
    kind: str
    text: str
    source: str
    score: float
    memory_id: str | None = None
    created_at: str | None = None
    superseded_by: str | None = None
    start_line: int | None = None
    end_line: int | None = None


def memory_file(root: str | Path) -> Path:
    return Path(root) / os.environ.get("HARNESS_MEMORY_FILE", DEFAULT_MEMORY_FILE)


def find_credential(text: str) -> str | None:
    """The kind of credential found, never its value, so errors cannot leak it."""

    for kind, pattern in _CREDENTIALS.items():
        if pattern.search(text):
            return kind
    return None


def memory_id(kind: str, text: str) -> str:
    return "mem_" + hashlib.sha256(f"{kind}\0{text}".encode("utf-8")).hexdigest()[:12]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_memories(path: Path) -> list[Memory]:
    """Read the file; a damaged line stops here, so it can never be overwritten."""

    if not path.is_file():
        return []
    merged: dict[str, Memory] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            memory = Memory(**json.loads(line))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"{path}:{number} is not a valid memory; fix the file first (a merge conflict?)") from exc
        # A union merge can keep two versions of a line; the replaced one wins.
        previous = merged.get(memory.id)
        merged[memory.id] = memory if previous is None or memory.superseded_by else previous
    return sorted(merged.values(), key=lambda item: (item.created_at, item.id))


def write_memories(path: Path, memories: list[Memory]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(memory), ensure_ascii=False, sort_keys=True) for memory in memories]
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write("".join(line + "\n" for line in lines))
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def restore_memories(store: PostgresStore, project_id: int, root: str | Path) -> int:
    """Make the database match the file: a new machine, a pull or a branch switch all land here."""

    with store.memory_lock(project_id):
        memories = read_memories(memory_file(root))
        store.replace_memories(project_id, memories)
    return len(memories)


def remember(
    text: str,
    project: str,
    source: str,
    kind: str = "note",
    supersedes: str | None = None,
    embedder=None,
    store: PostgresStore | None = None,
) -> tuple[Memory, bool]:
    """Save a memory to the file and the database; returns it and whether it has a vector yet."""

    text = text.replace("\x00", "").strip()
    source = source.strip()
    if kind not in KINDS:
        raise MemoryRefused(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")
    if not text or not source:
        raise MemoryRefused("a memory needs text and a source")
    if len(text) > MAX_TEXT_CHARS:
        raise MemoryRefused(f"a memory has at most {MAX_TEXT_CHARS} characters; save the decision, not the document")
    credential = find_credential(f"{text}\n{source}")
    if credential:
        raise MemoryRefused(f"refused: it looks like it contains a credential ({credential}), and this file goes to Git")

    store = store or PostgresStore()
    found = store.project(project)
    if found is None:
        raise ValueError(f"unknown project {project!r}; index it first")
    path = memory_file(found["root"])
    new_id = memory_id(kind, text)
    if supersedes == new_id:
        raise MemoryRefused("a memory cannot replace itself")

    with store.memory_lock(found["id"]):
        memories = {memory.id: memory for memory in read_memories(path)}
        if supersedes and supersedes not in memories:
            raise MemoryRefused(f"unknown memory {supersedes!r}")
        existing = memories.get(new_id)
        created_at = existing.created_at if existing else datetime.now(timezone.utc).isoformat(timespec="seconds")
        memory = Memory(new_id, kind, text, source, created_at)
        memories[new_id] = memory
        if supersedes:
            memories[supersedes] = replace(memories[supersedes], superseded_by=new_id)
        ordered = sorted(memories.values(), key=lambda item: (item.created_at, item.id))
        # The file comes first: if the database fails now, the next index repairs it.
        write_memories(path, ordered)
        store.replace_memories(found["id"], ordered)

    # A memory without a vector still matches by text, and the next index embeds it.
    embedder = embedder or memory_embedder()
    try:
        vector = embed_texts(embedder, [text])[0]
    except Exception:
        return memory, False
    store.put_embeddings(embedder_id(embedder), [(text_hash(text), vector)])
    return memory, True


def recall(
    query: str,
    project: str,
    kind: str | None = None,
    top_k: int = 8,
    include_superseded: bool = False,
    embedder=None,
    store: PostgresStore | None = None,
) -> list[RecallHit]:
    store = store or PostgresStore()
    embedder = embedder or memory_embedder()
    found = store.project(project)
    if found is None:
        raise ValueError(f"unknown project {project!r}; index it first")
    if kind == "progress":
        paths = r"/progress\.md$"
    elif kind == "handoff":
        paths = r"handoff\.md$"
    else:
        paths = None
    rows = store.recall(
        found["id"], query, embed_query(embedder, query), embedder_id(embedder), HANDOFF_PATHS,
        kind_filter=kind, file_filter=paths, include_files=kind in (None, "handoff", "progress"),
        include_superseded=include_superseded, top_k=top_k,
    )
    hits: list[RecallHit] = []
    for row in rows:
        if row["origin"] == "memory":
            hits.append(RecallHit(
                "memory", row["memory_kind"], row["memory_text"], row["memory_source"], row["score"],
                memory_id=row["ref"],
                created_at=row["created_at"].isoformat(),
                superseded_by=row["superseded_by"],
            ))
            continue
        full = Path(found["root"]) / row["path"]
        if not full.is_file():
            continue
        hits.append(RecallHit(
            "file",
            "progress" if row["path"].endswith("/progress.md") else "handoff",
            read_lines(full, row["start_line"], row["end_line"]),
            row["path"],
            row["score"],
            start_line=row["start_line"],
            end_line=row["end_line"],
        ))
    return hits
