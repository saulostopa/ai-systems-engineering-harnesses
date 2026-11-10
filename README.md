# Harnesses

Standalone harness projects for reliable AI-assisted development. This repository contains the runnable projects from the Harness Foundation Course without the course website, lessons, or planning artifacts.

Each directory is independently usable. Start with `harness-basic` for a small project, use `app-harness` or `domains` for extensions, and choose one of the RAG projects when the agent needs repository or business context.

## Quick View: How it Works

**[Open the code memory flow](https://claude.ai/artifact/GRLxiHpRE9oML4ngJAyvnb)** ([file](flowcharts/2026-10-30-code-memory-postgres-jev/code-memory-postgres-jev.html)): how one
question travels with Jev and without it, in Portuguese.

## Catalog

| Project | Use it for | Start here |
|---|---|---|
| `harness-basic` | Installable core: router, state, policies, plans, hooks and gates | `harness-basic/README.md` |
| `app-harness` | E2E and agentic navigation checks | `app-harness/README.md` |
| `domains` | Finance, games, and commercial domain packs | Domain-specific pack |
| `rag-harness` | Local hybrid RAG with JSON index and Ollama embeddings | `rag-harness/rag_harness/__main__.py` |
| `area-copilot` | Business context with cited sources | `area-copilot/area_harness/__main__.py` |
| `hard-harness` | Executable graphs, gates, and evidence | `hard-harness/README.md` |
| `enterprise-harness` | Multi-repository orchestration | `enterprise-harness/README.md` |
| `adk-rag-harness` | ADK + RAG + Jev with 4-pillar operational decisions | `adk-rag-harness/README.md` |
| `adk-rag-postgres-harness` | Shared PostgreSQL + pgvector RAG | `adk-rag-postgres-harness/README.md` |
| `harness-usage` | Token and cost ledger, budget warning and reports for the LLM harnesses | `harness-usage/README.md` |

| `artifacts-intranet` | Searchable shared artifact context | `artifacts-intranet/README.md` |

## Quick starts

### Basic harness

```bash
./harness-basic/install.sh /path/to/your-project
```

The standalone directory installs the core contract. Course-derived
distributions can additionally bundle the seven-skill standard profile under
`.agents/skills/` and expose an explicit `./install.sh --self` mode when the
package directory is also the repository being managed. See
`harness-basic/README.md` for the boundary between both profiles.

### Local RAG

```bash
ollama pull nomic-embed-text
cd rag-harness
HARNESS_EMBED_PROVIDER=ollama HARNESS_EMBED_MODEL=nomic-embed-text \
python3 -m rag_harness index /path/to/your-repository --verbose
```

### ADK + RAG + Jev

```bash
cd adk-rag-harness
uv sync --extra adk --extra ollama --extra jev-sdk
HARNESS_RAG_PROVIDER=demo uv run adk web
```

For a real local index, point the indexer at the target repository and pass the resulting index path to the ADK app:

```bash
HARNESS_EMBED_PROVIDER=ollama HARNESS_EMBED_MODEL=nomic-embed-text \
PYTHONPATH=rag-harness python3 -m rag_harness index /path/to/your-repository --verbose
HARNESS_RAG_PROVIDER=index \
HARNESS_RAG_DOCS_INDEX=/path/to/your-repository/.rag_index \
uv run adk web
```

### ADK RAG with PostgreSQL

```bash
cd adk-rag-postgres-harness
uv sync --extra postgres
docker compose up -d postgres
uv run python -m adk_rag_postgres_harness.cli migrate
```

See the project README before ingesting a collection.

## Choosing a project

- Use `harness-basic` when the project needs a small, installable control layer.
- Use `rag-harness` when one developer or a small project can keep the index locally.
- Use `adk-rag-harness` when typed routing, 4-pillar Jev decisions (model routing, guardrails, reranking, tripartite gating), and ADK traces are useful.
- Use `adk-rag-postgres-harness` when multiple people or services share the index.

- Use `enterprise-harness` when one orchestrator manages several repositories.
- Use `hard-harness` when executable graph control and deterministic gates are the main goal.

The RAG backends implement the same evidence boundary. PostgreSQL changes persistence and retrieval scale; it does not replace typed workflow validation.

## Validation

Run each project's own tests from its directory. The projects intentionally keep their dependencies separate so a consumer can download only the harness it needs.

The core Python suites, App Harness gate and portable skill-scanner checks run without the course repository. Two scanner cases are skipped when the course's optional `skills-artifacts` fixture is absent; those cases remain available in the course-level integration environment.

## Relationship to the course

The course, explanations, architecture decisions, and bilingual documentation remain in [ai-systems-engineering-course](https://github.com/saulostopa/ai-systems-engineering-course). This repository is the distribution surface for the runnable harness projects.

## License

Add the license required by the organization before publishing a production distribution.
