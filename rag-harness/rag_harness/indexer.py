"""Indexing with content-hash caching (rag-harness.md: embeddings as a
computation cache — re-embed only when the file changes).

Index layout:
    .rag_index/                # default profile (.rag_index/<profile>/ otherwise)
        chunks.json          # all chunks (text + metadata)
        vectors.json         # embeddings per chunk id
        hashes.json          # content-hash per file (re-index cache)
        meta.json            # embedder and profile that produced the vectors

File discovery: inside a Git work tree only files Git tracks or would track
(`git ls-files --cached --others --exclude-standard`) are indexed, so
`.gitignore` already removes build output, native folders and secrets.
Lockfiles are always skipped and `.ragignore` at the root adds
project-specific exclusions (gitignore-like patterns, no `!` negation).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass

from .chunker import Chunk, chunk_file
from .embeddings import cosine, embedder_id
from .usage import usage_context

DEFAULT_EXTS = (".py", ".md", ".txt", ".sh", ".yaml", ".yml", ".json", ".ts", ".tsx", ".js", ".mjs")
PROFILES: dict[str, tuple[str, ...]] = {
    "default": DEFAULT_EXTS,
    "docs": (".md", ".txt", ".yaml", ".yml", ".json"),
    "code": (".py", ".sh", ".ts", ".tsx", ".js", ".mjs"),
}
LOCKFILES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lock", "composer.lock", "Cargo.lock", "poetry.lock", "uv.lock", "Gemfile.lock",
})


@dataclass
class Index:
    chunks: list[Chunk]
    vectors: dict[str, list[float]]  # chunk.hash -> embedding
    file_hashes: dict[str, str]  # path -> sha256 of the file content
    embedder: str = ""  # embedder_id() that produced the vectors; "" for legacy indexes


def index_path_for(root: str, profile: str = "default") -> str:
    base = os.path.join(root, ".rag_index")
    return base if profile == "default" else os.path.join(base, profile)


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_ragignore(root: str) -> list[str]:
    path = os.path.join(root, ".ragignore")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh]
    return [line for line in lines if line and not line.startswith(("#", "!"))]


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Match a root-relative POSIX path against gitignore-like patterns."""

    parts = rel_path.split("/")
    for raw in patterns:
        pattern = raw.rstrip("/")
        dir_only = raw.endswith("/")
        if pattern.startswith("/") or "/" in pattern:
            anchored = pattern.lstrip("/")
            if fnmatch.fnmatch(rel_path, anchored) or rel_path.startswith(anchored + "/"):
                return True
            continue
        candidates = parts[:-1] if dir_only else parts
        if any(fnmatch.fnmatch(part, pattern) for part in candidates):
            return True
    return False


def _git_files(root: str) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    # A path Git holds in another encoding must not take the whole index down.
    return [p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def _walk_files(root: str) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "__")) and d != "node_modules"]
        for name in filenames:
            files.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    return files


def discover_files(root: str, exts: tuple[str, ...] = DEFAULT_EXTS) -> list[str]:
    rel_paths = _git_files(root)
    if rel_paths is None:
        rel_paths = _walk_files(root)
    patterns = load_ragignore(root)
    files: list[str] = []
    for rel in rel_paths:
        parts = rel.split("/")
        # Hidden and dunder folders stay out in both modes (.github, .rag_index, __pycache__).
        if any(part.startswith((".", "__")) for part in parts[:-1]) or "node_modules" in parts:
            continue
        if not rel.endswith(exts) or parts[-1] in LOCKFILES or is_ignored(rel, patterns):
            continue
        full = os.path.join(root, rel)
        if os.path.isfile(full):
            files.append(full)
    return sorted(files)


def _read_meta(index_dir_path: str) -> dict:
    path = os.path.join(index_dir_path, "meta.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _embed_missing(embedder, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if hasattr(embedder, "embed_batch"):
        return embedder.embed_batch(texts)
    return [embedder.embed(text) for text in texts]


def index_dir(
    root: str,
    embedder,
    index_dir_path: str | None = None,
    verbose: bool = False,
    profile: str = "default",
) -> Index:
    if profile not in PROFILES:
        raise ValueError(f"unknown index profile: {profile} (use {', '.join(PROFILES)})")
    index_dir_path = index_dir_path or index_path_for(root, profile)
    os.makedirs(index_dir_path, exist_ok=True)

    hashes_path = os.path.join(index_dir_path, "hashes.json")
    vectors_path = os.path.join(index_dir_path, "vectors.json")
    chunks_path = os.path.join(index_dir_path, "chunks.json")
    meta_path = os.path.join(index_dir_path, "meta.json")

    current_embedder = embedder_id(embedder)
    previous_embedder = _read_meta(index_dir_path).get("embedder")
    # Vectors from another embedder are incompatible (dimension and space):
    # discard the whole cache instead of mixing them into the new index.
    reuse_cache = previous_embedder == current_embedder

    old_hashes: dict[str, str] = {}
    old_vectors: dict[str, list[float]] = {}
    old_chunks: list[Chunk] = []
    if reuse_cache and os.path.exists(hashes_path):
        with open(hashes_path, "r", encoding="utf-8") as fh:
            old_hashes = json.load(fh)
    if reuse_cache and os.path.exists(vectors_path):
        with open(vectors_path, "r", encoding="utf-8") as fh:
            old_vectors = json.load(fh)
    if reuse_cache and os.path.exists(chunks_path):
        with open(chunks_path, "r", encoding="utf-8") as fh:
            old_chunks = [Chunk(**r) for r in json.load(fh)]
    if verbose and not reuse_cache and previous_embedder:
        print(f"embedder changed ({previous_embedder} -> {current_embedder}): full re-index")

    files = discover_files(root, PROFILES[profile])
    changed = 0
    for path in files:
        h = file_hash(path)
        if old_hashes.get(path) != h:
            changed += 1

    new_chunks: list[Chunk] = []
    new_vectors: dict[str, list[float]] = {}
    new_file_hashes: dict[str, str] = {}
    pending: dict[str, str] = {}  # chunk.hash -> text still to embed
    old_paths = {c.path for c in old_chunks}

    # Reuse vectors for chunks whose hash did not change (computation cache)
    for path in files:
        h = file_hash(path)
        new_file_hashes[path] = h
        if old_hashes.get(path) == h and path in old_paths:
            for c in old_chunks:
                if c.path == path:
                    new_chunks.append(c)
                    if c.hash in old_vectors:
                        new_vectors[c.hash] = old_vectors[c.hash]
            continue
        for c in chunk_file(path):
            new_chunks.append(c)
            if c.hash in old_vectors:
                new_vectors[c.hash] = old_vectors[c.hash]
            else:
                pending[c.hash] = c.text

    hashes = list(pending)
    with usage_context(component="embedding_index", operation=f"index {profile}", project_root=os.path.abspath(root)):
        vectors = _embed_missing(embedder, [pending[k] for k in hashes])
    for chunk_hash, vector in zip(hashes, vectors):
        new_vectors[chunk_hash] = vector

    with open(hashes_path, "w", encoding="utf-8") as fh:
        json.dump(new_file_hashes, fh, indent=1)
    with open(vectors_path, "w", encoding="utf-8") as fh:
        json.dump(new_vectors, fh)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump({"embedder": current_embedder, "profile": profile}, fh, indent=1)
    with open(chunks_path, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {"path": c.path, "kind": c.kind, "name": c.name, "text": c.text,
                 "start_line": c.start_line, "end_line": c.end_line, "hash": c.hash}
                for c in new_chunks
            ],
            fh,
            ensure_ascii=False,
            indent=1,
        )

    if verbose:
        print(
            f"indexed {len(new_chunks)} chunks from {len(files)} files "
            f"({changed} changed, {len(pending)} chunks embedded with {current_embedder})"
        )
    return Index(new_chunks, new_vectors, new_file_hashes, current_embedder)


def load_index(index_dir_path: str) -> Index:
    with open(os.path.join(index_dir_path, "hashes.json"), "r", encoding="utf-8") as fh:
        file_hashes = json.load(fh)
    with open(os.path.join(index_dir_path, "vectors.json"), "r", encoding="utf-8") as fh:
        vectors = json.load(fh)
    with open(os.path.join(index_dir_path, "chunks.json"), "r", encoding="utf-8") as fh:
        chunks = [Chunk(**r) for r in json.load(fh)]
    return Index(chunks, vectors, file_hashes, _read_meta(index_dir_path).get("embedder", ""))


def semantic_search(index: Index, embedder, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
    if index.embedder and index.embedder != embedder_id(embedder):
        raise ValueError(
            f"index was built with {index.embedder} but the query uses {embedder_id(embedder)}; "
            "set the same HARNESS_EMBED_PROVIDER and HARNESS_EMBED_MODEL or re-index"
        )
    qvec = embedder.embed(query)
    scored = [(c, cosine(qvec, index.vectors[c.hash])) for c in index.chunks if c.hash in index.vectors]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]