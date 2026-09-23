"""Indexing with content-hash caching (rag-harness.md: embeddings as a
computation cache — re-embed only when the file changes).

Index layout:
    .rag_index/<sha256 of the directory>/
        chunks.json          # all chunks (text + metadata)
        vectors.json         # embeddings per chunk id
        hashes.json          # content-hash per file (re-index cache)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from .chunker import Chunk, chunk_file
from .embeddings import cosine


@dataclass
class Index:
    chunks: list[Chunk]
    vectors: dict[str, list[float]]  # chunk.hash -> embedding
    file_hashes: dict[str, str]  # path -> sha256 of the file content


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def discover_files(root: str, exts: tuple[str, ...] = (".py", ".md", ".txt", ".sh", ".yaml", ".yml", ".json")) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "__")) and d != "node_modules"]
        for name in filenames:
            if name.endswith(exts):
                files.append(os.path.join(dirpath, name))
    return sorted(files)


def index_dir(root: str, embedder, index_dir_path: str | None = None, verbose: bool = False) -> Index:
    index_dir_path = index_dir_path or os.path.join(root, ".rag_index")
    os.makedirs(index_dir_path, exist_ok=True)

    hashes_path = os.path.join(index_dir_path, "hashes.json")
    vectors_path = os.path.join(index_dir_path, "vectors.json")
    chunks_path = os.path.join(index_dir_path, "chunks.json")

    old_hashes: dict[str, str] = {}
    old_vectors: dict[str, list[float]] = {}
    old_chunks: list[Chunk] = []
    if os.path.exists(hashes_path):
        with open(hashes_path, "r", encoding="utf-8") as fh:
            old_hashes = json.load(fh)
    if os.path.exists(vectors_path):
        with open(vectors_path, "r", encoding="utf-8") as fh:
            old_vectors = json.load(fh)
    if os.path.exists(chunks_path):
        with open(chunks_path, "r", encoding="utf-8") as fh:
            old_chunks = [Chunk(**r) for r in json.load(fh)]

    files = discover_files(root)
    changed = 0
    for path in files:
        h = file_hash(path)
        if old_hashes.get(path) != h:
            changed += 1

    new_chunks: list[Chunk] = []
    new_vectors: dict[str, list[float]] = {}
    new_file_hashes: dict[str, str] = {}
    # Reuse vectors for chunks whose hash did not change (computation cache)
    old_by_hash = {c.hash: c for c in old_chunks}

    for path in files:
        h = file_hash(path)
        new_file_hashes[path] = h
        if old_hashes.get(path) == h and path in {c.path for c in old_chunks}:
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
                new_vectors[c.hash] = embedder.embed(c.text)

    with open(hashes_path, "w", encoding="utf-8") as fh:
        json.dump(new_file_hashes, fh, indent=1)
    with open(vectors_path, "w", encoding="utf-8") as fh:
        json.dump(new_vectors, fh)
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
        print(f"indexed {len(new_chunks)} chunks from {len(files)} files ({changed} changed)")
    return Index(new_chunks, new_vectors, new_file_hashes)


def load_index(index_dir_path: str) -> Index:
    with open(os.path.join(index_dir_path, "hashes.json"), "r", encoding="utf-8") as fh:
        file_hashes = json.load(fh)
    with open(os.path.join(index_dir_path, "vectors.json"), "r", encoding="utf-8") as fh:
        vectors = json.load(fh)
    with open(os.path.join(index_dir_path, "chunks.json"), "r", encoding="utf-8") as fh:
        chunks = [Chunk(**r) for r in json.load(fh)]
    return Index(chunks, vectors, file_hashes)


def semantic_search(index: Index, embedder, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
    qvec = embedder.embed(query)
    scored = [(c, cosine(qvec, index.vectors[c.hash])) for c in index.chunks if c.hash in index.vectors]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]