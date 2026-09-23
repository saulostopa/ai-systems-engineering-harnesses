# Hybrid RAG POC — decision (D1)

> Status: **POC validated**. Reopens the proposal from `rag-harness.md` (webmotors-harness-factory)
> with a minimal, functional implementation. What was validated, what was left
> out and why — decide by evidence (Lesson 11), not by intuition.

## What was built

```
rag-harness/
├── rag_harness/
│   ├── chunker.py      # AST-aware chunking (stdlib ast) — complete functions/classes
│   ├── embeddings.py   # NGramEmbedder (local, deterministic) OR Ollama (nomic-embed-text)
│   ├── indexer.py      # content-hash cache: re-embeds only what changed
│   ├── retrieval.py    # lexical (BM25-ish) + semantic (cosine) + RRF
│   ├── agentic.py      # Agent Controller: glob→lexical→semantic, enough? decides
│   └── __main__.py     # CLI: index / query / hybrid / agent
└── tests/test_rag.py   # 5 tests (pytest or plain python)
```

## What the POC validated (vs. the rag-harness.md)

| Idea from rag-harness.md | Status in the POC | Evidence |
|---|---|---|
| AST chunking (complete unit) | ✅ validated | `test_chunk_python_extrai_funcoes_e_classes` — every function/class is an intact chunk |
| Embeddings as a computation cache (content-hash) | ✅ validated | `indexer.py` reuses vectors of unchanged chunks; 2nd indexing does not re-embed |
| Hybrid lexical+semantic with RRF | ✅ validated | `rrf_merge` + `hybrid_search`; test covers the merge |
| Agentic retrieval (tools + sufficiency) | ✅ validated | `AgentController.retrieve` — cheap first, scales on demand |
| No hardcoded provider | ✅ validated | `make_embedder()`: Ollama if reachable, otherwise local NGram |

## What was LEFT OUT (intentionally) — and why

| Piece from rag-harness.md | Out of the POC | Reason |
|---|---|---|
| File watcher (Rust/Go, inotify) | Yes | POC runs on-demand indexing; watcher is a scale optimization, not a validity one |
| Queue (LISTEN/NOTIFY, Redis) | Yes | No concurrent workers in the POC — nothing to queue |
| Postgres + pgvector | Yes | SQLite/JSON is enough to validate the *pattern*; pgvector solves volume |
| Image OCR | Yes | D3 (Area Copilot) covers business; OCR is a separate item |
| LLM-based tool decision | Partial | `decide_with_llm` is the extension point; the heuristic already decides well in the POC |

## Reopening conditions (from the rag-harness.md) — revisited

1. **Harness in real use on large code** — ❌ not yet (pilots in EPIC G).
2. **Real retrieval friction logged** — ⚠️ partial: the POC measures retrieval
   *quality* (precision@k can be measured), but the cost-benefit of *adopting*
   depends on EPIC G.
3. **Agents in use do not solve natively** — ⚠️ to be decided: modern agents
   already come with native glob/grep; the POC shows the added value of hybrid
   RAG lies in **business context** (D3) and in **chunking quality** for large
   repos, not in simple code search.

## Decision

- **Adopt the architecture**: yes, as the RAG code base — the pattern
  (AST chunks + hash cache + RRF + agency) is validated and portable to
  pgvector without redesign.
- **Adopt in production (watcher+pg)**: **not yet** — wait for evidence from
  EPIC G (conditions 1-2). The POC already runs without infrastructure:
  on-demand indexing.
- **Value priority**: invert the plan order — **business RAG (D3)** has more
  immediate ROI than the watcher; heavy infrastructure only when volume
  demands it.

## How to run

```sh
cd rag-harness
python tests/test_rag.py                    # tests (stdlib)
python -m rag_harness index ../harness-basic --verbose
python -m rag_harness hybrid ../harness-basic "gatekeeper pre-commit"
python -m rag_harness agent ../harness-basic "how to validate the harness"
# with Ollama (real semantics):
OLLAMA_API_URL=http://localhost:11434 python -m rag_harness index ../harness-basic
```