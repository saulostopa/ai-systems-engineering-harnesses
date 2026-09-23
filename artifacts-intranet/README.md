# Artifacts intranet — package

```
artifacts-intranet/
├── artifacts_intranet/
│   ├── __init__.py        # path setup (rag_harness engine)
│   ├── indexer.py         # scans artifact dirs, indexes (HTML/MD/TXT) into rag_harness
│   └── server.py          # stdlib server: / (UI) and /search?q= (JSON)
├── index.html             # Eleanor UI (system.css v2 reused)
├── tests/test_intranet.py # 3 tests
└── README.md
```

## Usage

```sh
python3 -m artifacts_intranet index   # indexes the configured dirs (repo)
python3 -m artifacts_intranet serve   # http://localhost:8765
# UI: hybrid RAG search (lexical + semantic + RRF)
# API: GET /search?q=gatekeeper blocks
```

## Idea (Story F2)

The artifacts (reports, quizzes, flowcharts, area reports) become the
**company knowledge corpus** (Lesson 03: repo as system of record;
Lesson 11: observability). The intranet is the entry point: RAG search over
everything the harness generated — with cited sources, like everything in
this project.