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
from .retrieval import read_lines, safe_file
from .store import PostgresStore

DEFAULT_MEMORY_FILE = "docs/harness/memories.jsonl"
KINDS = ("decision", "convention", "handoff", "note")
MAX_TEXT_CHARS = 2000
# Feature logs are already versioned and indexed, so recall reads them without a second copy.
HANDOFF_PATHS = r"^docs/harness/(session-handoff\.md|features/[^/]+/(progress|handoff)\.md)$"

_CREDENTIALS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # One long random part, so a name like `sk-learn-integration` passes.
    "API key": re.compile(r"\b(?:sk|pk|rk)-(?:[A-Za-z0-9]+[-_])*[A-Za-z0-9]{16,}"),
    "Stripe key": re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    "GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    "npm token": re.compile(r"\bnpm_[A-Za-z0-9]{20,}"),
    "bearer token": re.compile(r"(?i)\bbearer\s+(?P<value>[A-Za-z0-9._~+/$<{-]{16,}=*)"),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "URL with a password": re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
    # No left boundary, because `\\b` does not match after `_` in `DB_PASSWORD`.
    "secret assignment": re.compile(
        r"(?i)(?:password|passwd|pwd|senha|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
        r"(?:[_-](?:key|value|access[_-]key))?[\"']?\s*[:=]\s*[\"']?(?P<value>[^\s\"',;]{8,})"
    ),
    # In prose only a value with a digit or symbol counts: "the password is encrypted" passes.
    "secret in a sentence": re.compile(
        r"(?i)\b(?:password|senha|secret)\s+(?:is|é)\s+(?P<value>(?=\S*[0-9!@#$%^&*])\S{8,})"
    ),
}
# Values that name a secret or describe a field, instead of holding one.
_NOT_A_VALUE = re.compile(
    r"(?i)^(?:process\.env|os\.environ|import\.meta\.env|env\.|[$<{%]|\S*\()"
    r"|^(?:required|optional|undefined|string|boolean|disabled|enabled|validated)\b"
)


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
        for match in pattern.finditer(text):
            if "value" not in pattern.groupindex or not _NOT_A_VALUE.search(match["value"]):
                return kind
    return None


def memory_id(kind: str, text: str) -> str:
    return "mem_" + hashlib.sha256(f"{kind}\0{text}".encode("utf-8")).hexdigest()[:12]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_memory(raw: dict) -> Memory:
    """A line the database can hold; errors never repeat its content."""

    memory = Memory(**raw)
    fields = (memory.id, memory.kind, memory.text, memory.source, memory.created_at)
    if not all(isinstance(value, str) and value and "\x00" not in value for value in fields):
        raise ValueError("a field is empty or not valid text")
    if not isinstance(memory.superseded_by, (str, type(None))):
        raise ValueError("superseded_by is not an id")
    if memory.kind not in KINDS:
        raise ValueError(f"the kind must be one of {', '.join(KINDS)}")
    datetime.fromisoformat(memory.created_at)
    credential = find_credential(f"{memory.text}\n{memory.source}")
    if credential:
        raise ValueError(f"it looks like it contains a credential ({credential}); remove it and rotate it")
    return memory


def read_memories(path: Path) -> list[Memory]:
    """Read the file; a damaged line stops here, so it can never be overwritten."""

    if not path.is_file():
        return []
    merged: dict[str, Memory] = {}
    # Only "\\n" ends a line: `splitlines` also splits on U+2028, which JSON keeps as text.
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            memory = _check_memory(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number} is not a valid memory; fix the file first (a merge conflict?)") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{number} is not a valid memory: {exc}") from exc
        # A union merge can keep two versions of a line; the replaced one wins.
        previous = merged.get(memory.id)
        merged[memory.id] = memory if previous is None or memory.superseded_by else previous
    for memory in merged.values():
        seen = {memory.id}
        following = memory.superseded_by
        while following:
            if following not in merged or following in seen:
                raise ValueError(f"{path}: {memory.id} would stay hidden forever: fix its superseded_by")
            seen.add(following)
            following = merged[following].superseded_by
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
    source = source.replace("\x00", "").strip()
    try:
        f"{text}{source}".encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MemoryRefused("the text has characters that cannot be saved") from exc
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
        if supersedes and memories[supersedes].superseded_by:
            raise MemoryRefused(f"{supersedes} was already replaced by {memories[supersedes].superseded_by}; replace that one")
        existing = memories.get(new_id)
        if existing and existing.superseded_by:
            raise MemoryRefused(f"this text was replaced by {existing.superseded_by}; reword it to make a new decision")
        # Repeating a memory keeps its first source and date.
        memory = existing or Memory(new_id, kind, text, source, datetime.now(timezone.utc).isoformat(timespec="seconds"))
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
        full = safe_file(found["root"], row["path"])
        if full is None:
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
