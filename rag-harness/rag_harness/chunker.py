"""AST-aware chunking for Python code (stdlib `ast`).

rag-harness.md principle: a chunk is always a complete unit (function,
class, method) — never an arbitrary cut in the middle of the body. For
non-Python files, falls back to overlapping line windows.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from dataclasses import dataclass, field


@dataclass
class Chunk:
    path: str
    kind: str  # "function" | "class" | "method" | "module" | "lines"
    name: str
    text: str
    start_line: int
    end_line: int
    hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _module_doc(module: ast.Module) -> str:
    return ast.get_docstring(module) or ""


def _chunk_python(source: str, path: str) -> list[Chunk]:
    tree = ast.parse(source)
    chunks: list[Chunk] = []
    header_doc = _module_doc(tree)
    if header_doc:
        chunks.append(Chunk(path, "module", "__doc__", header_doc, 1, 1))

    def add(node: ast.AST, kind: str, name: str) -> None:
        text = ast.get_source_segment(source, node)
        if text:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            chunks.append(Chunk(path, kind, name, text, start, end))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node, "function", node.name)
        elif isinstance(node, ast.ClassDef):
            add(node, "class", node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(child, "method", f"{node.name}.{child.name}")
    return chunks


def _chunk_lines(source: str, path: str, size: int = 100, overlap: int = 20) -> list[Chunk]:
    lines = source.splitlines(keepends=True)
    chunks: list[Chunk] = []
    for start in range(0, len(lines), size - overlap):
        seg = lines[start : start + size]
        if not seg:
            break
        text = "".join(seg)
        chunks.append(Chunk(path, "lines", f"L{start + 1}", text, start + 1, start + len(seg)))
    return chunks


def chunk_file(path: str) -> list[Chunk]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    if path.endswith(".py"):
        try:
            return _chunk_python(source, path)
        except SyntaxError:
            pass  # fall back to line chunks
    return _chunk_lines(source, path)


def index_chunks_to_file(chunks: list[Chunk], out_path: str) -> None:
    records = [
        {
            "path": c.path,
            "kind": c.kind,
            "name": c.name,
            "text": c.text,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "hash": c.hash,
        }
        for c in chunks
    ]
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=1)


def main() -> None:
    for path in sys.argv[1:]:
        chunks = chunk_file(path)
        print(f"{path}: {len(chunks)} chunks")
        for c in chunks[:8]:
            print(f"  [{c.kind}] {c.name}  L{c.start_line}-{c.end_line}  ({len(c.text)} chars)")


if __name__ == "__main__":
    main()