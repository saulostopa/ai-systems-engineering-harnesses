"""Agentic retrieval controller (rag-harness.md: Agent Controller).

The agent decides WHICH tool to use (semantic / lexical / glob / regex),
executes it, evaluates whether the result is sufficient, and repeats —
instead of dumping everything into the prompt. Cost strategy: cheap first
(glob/regex/lexical), semantic last. Optional hook for LLM-based decisions.
"""

from __future__ import annotations

import fnmatch
import os
import re

from .chunker import Chunk
from .embeddings import cosine
from .indexer import Index
from .retrieval import hybrid_search, lexical_search, semantic_search


class AgentController:
    def __init__(self, index: Index, embedder, max_iters: int = 3) -> None:
        self.index = index
        self.embedder = embedder
        self.max_iters = max_iters
        self.used_tools: list[str] = []

    # ── Tools ────────────────────────────────────────────────────

    def tool_semantic_search(self, query: str, top_k: int = 3) -> list[Chunk]:
        self.used_tools.append("semantic_search")
        return [c for c, _s in semantic_search(self.index, self.embedder, query, top_k)]

    def tool_full_text_search(self, query: str, top_k: int = 3) -> list[Chunk]:
        self.used_tools.append("full_text_search")
        return [c for c, _s in lexical_search(self.index, query, top_k)]

    def tool_glob_search(self, pattern: str, root: str, top_k: int = 8) -> list[Chunk]:
        self.used_tools.append("glob_path_search")
        hits = [c for c in self.index.chunks if fnmatch.fnmatch(c.path, pattern)]
        return hits[:top_k]

    def tool_regex_search(self, pattern: str, top_k: int = 8) -> list[Chunk]:
        self.used_tools.append("regex_search")
        rx = re.compile(pattern, re.IGNORECASE)
        hits = [c for c in self.index.chunks if rx.search(c.text)]
        return hits[:top_k]

    @staticmethod
    def _exact_symbol_patterns(query: str) -> list[str]:
        """Extracts exact symbol patterns: quoted ('foo'), CamelCase,
        snake_case with dots (models.Veiculo), method names (registerItem)."""
        patterns: list[str] = []
        for m in re.findall(r'"([a-zA-Z_][\w.]*)"', query):
            patterns.append(re.escape(m))
        for m in re.findall(r"\b[A-Z][a-zA-Z0-9]*(?:\.[A-Z][a-zA-Z0-9]*)+", query):
            patterns.append(re.escape(m))
        for m in re.findall(r"\b[a-z]+_[a-z0-9_]+", query):
            patterns.append(re.escape(m))
        return patterns[:3]

    # ── Sufficiency heuristic ────────────────────────────────────

    def _sufficient(self, query: str, chunks: list[Chunk]) -> bool:
        """Does the top result contain at least one key term of the query?"""
        key = [t for t in re.findall(r"[a-z0-9_]{4,}", query.lower())]
        if not key:
            return True
        for c in chunks:
            text = c.text.lower()
            if any(t in text for t in key):
                return True
        return False

    # ── Agentic loop ─────────────────────────────────────────────

    def retrieve(self, query: str, root: str) -> list[Chunk]:
        """Cheap first; escalates if insufficient (max max_iters)."""
        self.used_tools = []
        gathered: list[Chunk] = []

        # Iter 1: lexical (exact) — symbol names are the most common target
        hits = self.tool_full_text_search(query, 3)
        gathered.extend(hits)
        if self._sufficient(query, hits):
            return gathered[:5]

        # Iter 2: glob by file name (likely symbol lives in a homonymous file)
        words = re.findall(r"[a-z0-9_]{4,}", query.lower())
        if words:
            globs = [f"**/*{words[0]}*" for words in [words[:1]]]
            for pat in globs:
                g = self.tool_glob_search(pat, root, 5)
                gathered.extend(g)
                if self._sufficient(query, gathered):
                    return gathered[:5]

        # Iter 2.5: regex for exact symbols (quoted or dotted
        # CamelCase/snake_case, e.g. 'registerItem', 'models.Veiculo', "exact")
        exact = AgentController._exact_symbol_patterns(query)
        for pat in exact:
            rx = self.tool_regex_search(pat, 5)
            gathered.extend(rx)
            if self._sufficient(query, gathered):
                return gathered[:5]

        # Iter 3: semantic (concept) — the most expensive, last
        sem = self.tool_semantic_search(query, 5)
        gathered.extend(sem)
        return gathered[:5]

    # ── LLM decision (optional) ──────────────────────────────────

    def decide_with_llm(self, query: str, context: list[Chunk]) -> str:
        """Extension point: call an LLM to choose the next tool.

        Returns the tool name ('semantic_search', 'regex_search', ...)
        or 'done'. Without a connected LLM, the Lesson 11 heuristic takes
        over.
        """
        return "done"


def pretty(chunks: list[Chunk] | list[tuple[Chunk, float]]) -> str:
    lines = []
    for i, entry in enumerate(chunks, 1):
        c = entry[0] if isinstance(entry, tuple) else entry
        preview = c.text[:160].replace("\n", " ")
        lines.append(f"  [{i}] {c.path}:{c.start_line} ({c.kind} {c.name})")
        lines.append(f"      {preview}...")
    return "\n".join(lines)