"""Business chunker — spreadsheets (CSV/stdlib, XLSX via optional openpyxl),
Markdown documents and plain text. Every chunk carries a citable SOURCE
(file + line/sheet) — the Area Copilot golden rule: never a number without
a source.

Uses the rag_harness engine (hybrid indexing + agentic control); this
module only converts business files into chunks with source metadata.
"""

from __future__ import annotations

import csv
import io
import os

from rag_harness.chunker import Chunk


def _csv_rows_to_chunks(path: str, max_rows_per_chunk: int = 50) -> list[Chunk]:
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    chunks: list[Chunk] = []
    for start in range(1, len(rows), max_rows_per_chunk):
        block = rows[start : start + max_rows_per_chunk]
        text_lines = [", ".join(header)]
        for i, row in enumerate(block, start=start):
            cells = [f"{h}:{v}" for h, v in zip(header, row) if v]
            text_lines.append(f"row {i + 1}: " + " | ".join(cells))
        text = "\n".join(text_lines)
        chunks.append(
            Chunk(
                path=path,
                kind="sheet",
                name=f"{os.path.basename(path)} L{start + 1}-{start + len(block)}",
                text=text,
                start_line=start + 1,
                end_line=start + len(block),
            )
        )
    return chunks


def _xlsx_sheets_to_chunks(path: str, max_rows_per_chunk: int = 50) -> list[Chunk]:
    try:
        import openpyxl  # optional
    except ImportError:
        raise RuntimeError("openpyxl not installed — use CSV or: pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    chunks: list[Chunk] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h) if h is not None else "" for h in rows[0]]
        for start in range(1, len(rows), max_rows_per_chunk):
            block = rows[start : start + max_rows_per_chunk]
            lines = [f"sheet: {sheet_name} | columns: {', '.join(header)}"]
            for i, row in enumerate(block, start=start):
                cells = [f"{h}:{v}" for h, v in zip(header, row) if v is not None and str(v)]
                lines.append(f"row {i + 1}: " + " | ".join(cells))
            chunks.append(
                Chunk(
                    path=f"{path}#{sheet_name}",
                    kind="sheet",
                    name=f"{sheet_name} L{start + 1}-{start + len(block)}",
                    text="\n".join(lines),
                    start_line=start + 1,
                    end_line=start + len(block),
                )
            )
    return chunks


def _md_to_chunks(path: str) -> list[Chunk]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    sections: list[tuple[int, str]] = []
    current: list[str] = []
    start_line = 1
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        if line.startswith("## ") or line.startswith("# "):
            if current:
                sections.append((start_line, "".join(current)))
            start_line = lineno
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((start_line, "".join(current)))
    if not sections:
        sections = [(1, text)]
    return [
        Chunk(
            path=path,
            kind="section",
            name=f"{os.path.basename(path)} L{start}",
            text=seg,
            start_line=start,
            end_line=start + seg.count("\n"),
        )
        for start, seg in sections
        if seg.strip()
    ]


def chunk_business_file(path: str) -> list[Chunk]:
    lower = path.lower()
    if lower.endswith(".csv"):
        return _csv_rows_to_chunks(path)
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return _xlsx_sheets_to_chunks(path)
    if lower.endswith((".md", ".markdown", ".txt")):
        return _md_to_chunks(path)
    raise ValueError(f"unsupported extension for business files: {path}")


def chunk_business_dir(root: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                chunks.extend(chunk_business_file(path))
            except (ValueError, RuntimeError) as exc:
                print(f"[area-copilot] skipping {path}: {exc}")
    return chunks