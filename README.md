<p align="center">
  <img src="assets/h-mark.svg" width="112" alt="Harness Foundation Course logo">
</p>

<h1 align="center">AI Systems Engineering Harnesses</h1>

<p align="center">
  A catalog of standalone, executable harnesses for reliable AI-assisted software engineering.
</p>

<p align="center">
  <a href="https://github.com/saulostopa/ai-systems-engineering-course"><strong>Course repository</strong></a>
  ·
  <a href="https://saulostopa.github.io/ai-systems-engineering-course/"><strong>Read the course</strong></a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&amp;logoColor=white">
  <img alt="Google ADK" src="https://img.shields.io/badge/Google_ADK-2.x-4285F4?logo=googlecloud&amp;logoColor=white">
  <img alt="Ollama" src="https://img.shields.io/badge/Ollama-local_models-000000?logo=ollama&amp;logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&amp;logoColor=white">
  <img alt="pgvector" src="https://img.shields.io/badge/pgvector-vector_search-336791">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&amp;logoColor=white">
  <img alt="uv" src="https://img.shields.io/badge/uv-Python_packages-DE5FE9?logo=astral&amp;logoColor=white">
</p>

This repository is the runnable companion to the
[AI Systems Engineering Course](https://github.com/saulostopa/ai-systems-engineering-course).
It contains the harness projects without the course website, lessons, or
planning artifacts. Start with the control layer you need and add retrieval,
code memory, testing, or multi-repository orchestration as the project grows.

## Project map

| Project | Purpose | Start here |
|---|---|---|
| [`harness-basic`](harness-basic/) | Installable core with routing, state, policies, plans, hooks, and deterministic gates | [Guide](harness-basic/README.md) |
| [`app-harness`](app-harness/) | End-to-end and agentic navigation quality gates | [Guide](app-harness/README.md) |
| [`domains`](domains/) | Finance, games, commercial, and factory domain packs | [Directory](domains/) |
| [`rag-harness`](rag-harness/) | Local hybrid retrieval with a JSON index and Ollama embeddings | [Package](rag-harness/rag_harness/) |
| [`area-copilot`](area-copilot/) | Business-area context with cited sources | [Package](area-copilot/area_harness/) |
| [`hard-harness`](hard-harness/) | Executable graphs, evidence, and deterministic gates | [Guide](hard-harness/README.md) |
| [`enterprise-harness`](enterprise-harness/) | Multi-repository and multi-team orchestration | [Guide](enterprise-harness/README.md) |
| [`adk-rag-harness`](adk-rag-harness/) | Google ADK question answering with typed routing and pluggable RAG | [Guide](adk-rag-harness/README.md) |
| [`adk-rag-postgres-harness`](adk-rag-postgres-harness/) | Shared PostgreSQL + pgvector code memory, CLI, MCP, and ADK adapter | [Guide](adk-rag-postgres-harness/README.md) |
| [`harness-usage`](harness-usage/) | Token, cost, and budget ledger for LLM-backed harnesses | [Guide](harness-usage/README.md) |
| [`artifacts-intranet`](artifacts-intranet/) | Searchable context built from shared engineering artifacts | [Guide](artifacts-intranet/README.md) |

## Choose a starting point

- Start with `harness-basic` for a small, installable control layer.
- Add `app-harness` when browser behavior and E2E evidence must gate delivery.
- Use `rag-harness` when one developer or one project can keep its index local.
- Use `adk-rag-postgres-harness` when several people, agents, or services share
  repository knowledge.
- Use `hard-harness` when executable graph control is the primary requirement.
- Use `enterprise-harness` when one orchestrator coordinates multiple repositories.

The local and PostgreSQL RAG implementations share the same evidence boundary.
PostgreSQL adds shared persistence while preserving typed workflow validation.

## Installation

Clone the catalog, then enter the project you want to use. Projects intentionally
keep their dependencies separate.

```bash
git clone https://github.com/saulostopa/ai-systems-engineering-harnesses.git
cd ai-systems-engineering-harnesses
```

### Basic harness

Install the core contract into another repository:

```bash
./harness-basic/install.sh /absolute/path/to/your-project
```

Course-derived distributions can also bundle the seven-skill standard profile
under `.agents/skills/` and expose `./install.sh --self`. See the
[`harness-basic` guide](harness-basic/README.md) for the exact boundary between
the standalone core and derived distributions.

### Local RAG

```bash
ollama pull nomic-embed-text
cd rag-harness
HARNESS_EMBED_PROVIDER=ollama HARNESS_EMBED_MODEL=nomic-embed-text \
  python3 -m rag_harness index /path/to/your-repository --verbose
```

### ADK repository Q&A

The `adk_app` entry point answers questions using demo evidence or a real
local index. Its decision providers include Jev and Ollama. With Ollama
running locally, load both default models before starting the app:

```bash
cd adk-rag-harness
uv sync --extra adk --extra ollama
ollama pull llama3.1:8b
ollama pull qwen2.5:14b
HARNESS_RAG_PROVIDER=demo \
HARNESS_CHAT_PROVIDER=ollama \
HARNESS_DECISION_PROVIDER=ollama \
uv run adk web
```

For a real local index, index the target repository first and pass the generated
index to ADK:

```bash
HARNESS_EMBED_PROVIDER=ollama HARNESS_EMBED_MODEL=nomic-embed-text \
PYTHONPATH=rag-harness python3 -m rag_harness index /path/to/your-repository --verbose

cd adk-rag-harness
HARNESS_RAG_PROVIDER=index \
HARNESS_RAG_DOCS_INDEX=/path/to/your-repository/.rag_index \
HARNESS_EMBED_PROVIDER=ollama \
HARNESS_CHAT_PROVIDER=ollama \
HARNESS_DECISION_PROVIDER=ollama \
uv run adk web
```

### PostgreSQL code memory

This project uses PostgreSQL 17 with pgvector. Its Compose service listens on
port `5433` and uses the local database `harness_rag` by default.

```bash
cd adk-rag-postgres-harness
uv sync --extra postgres
docker compose up -d postgres
ollama pull qwen3-embedding:4b
uv run python -m adk_rag_postgres_harness.cli migrate
uv run python -m adk_rag_postgres_harness.cli index /path/to/your-repository --project my-repo
uv run python -m adk_rag_postgres_harness.cli search "where is the login handled" --project my-repo
```

The `--project` value is the stable namespace for one indexed repository. The
same index can be queried through the CLI, served through MCP, or exposed to the
ADK app. Read the [PostgreSQL project guide](adk-rag-postgres-harness/README.md)
before indexing production repositories or configuring isolated worktrees.

## Dynamic feature planning

The `feature_planner` app is included in the repository's default checkout. It
uses lexical RAG over a synthetic repository and Ollama structured
output to generate a validated `WorkflowSpec`. Its explicit ADK graph reviews
up to five vertical slices by default, runs up to two investigations concurrently,
verifies each worker report in a separate call and synthesizes the results.
The graph skips dependants after a failed dependency and allows one worker retry
with reviewer feedback. The read-only demo produces events, state, and a
`workflow-spec.json` artifact in the ADK Dev UI.

Make sure Ollama is running and make the default `qwen2.5:14b` model available:

```bash
ollama pull qwen2.5:14b
cd adk-rag-harness
uv sync --extra adk
uv run adk web --host 127.0.0.1 --port 8173
```

Open <http://127.0.0.1:8173>, select `feature_planner`, and start a new session
for each request. The lockfile resolves Google ADK 2.14.1 on Python 3.11+
(the repository pins Python 3.14). Override the local models with
`HARNESS_PLANNER_MODEL` and `HARNESS_VERIFIER_MODEL`, or the endpoint with
`OLLAMA_BASE_URL`.

The app uses Ollama for both planning and verification. The separate
`adk_app` can use Jev for question answering.

See the [Postgres pilot setup](adk-rag-harness/README.md#run-the-postgres-evidence-pilot)
to reuse one catalog checkout across several target repositories.

## How the pieces fit

```text
repository
   │
   ├── harness-basic ── policies · plans · hooks · gates
   ├── app-harness ─── browser checks · E2E evidence
   ├── rag-harness ─── local index · lexical/semantic retrieval
   ├── ADK apps ────── typed workflows · traces · Dev UI
   └── PostgreSQL ──── shared code memory · pgvector · CLI/MCP
```

The interactive code-memory flow shows how one question travels through the
PostgreSQL-backed system, with Jev in the legacy ADK app and without Jev through
MCP or the CLI:

- [Open the interactive flow](https://claude.ai/artifact/GRLxiHpRE9oML4ngJAyvnb)
- [Open the repository copy](flowcharts/2026-10-30-code-memory-postgres-jev/code-memory-postgres-jev.html)

## Validation

Run each project's own test or validation command from its directory. The core
Python suites, App Harness gate, and portable skill-scanner checks run without
the course repository. Two scanner cases depend on the course's optional
`skills-artifacts` fixture and are skipped when it is absent.

## Course and documentation

The concepts, lessons, architecture decisions, and bilingual learning material
live in the course, while this repository remains the distribution surface for
the runnable projects:

- [AI Systems Engineering Course — source](https://github.com/saulostopa/ai-systems-engineering-course)
- [AI Systems Engineering Course — website](https://saulostopa.github.io/ai-systems-engineering-course/)

## License

The catalog's original code and documentation use the [MIT License](LICENSE.md).
Third-party components and assets retain their respective licenses and notices.
The standalone diagram files embed JetBrains Mono with its SIL Open Font
License 1.1 notice.
