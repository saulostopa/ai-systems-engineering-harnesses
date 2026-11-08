# ADK + RAG + Jev harness

The harness keeps the decision contract and retrieval boundary independent of
Google ADK and the Jev provider. It can run offline with fake providers, which
makes policy behavior testable before adding network clients.

It implements the operational decision principles ("The LLM writes, Jev decides"):

```text
request
  │
  ├─► [ Jev Guardrail (Filter) ] ── (abusive/injection) ──► blocked (0 LLM tokens)
  │
  ├─► [ Jev Model Router (Route) ] ──► Small ($) vs. Large ($$$) tier
  │
  ├─► RAG adapter ──► [ Jev Reranker (Score) ] ──► top-K evidence chunks
  │
  └─► [ Tripartite Policy (Release) ] ──► execute / confirm / human escalation
```


## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`). It downloads the
  Python 3.14 pinned in `.python-version`; no manual Python install is needed.
- `git` and `python3` on the `PATH` for indexing with `rag-harness`.
- An [OpenRouter](https://openrouter.ai/keys) key with credit, in
  `OPENROUTER_API_KEY` or in the `openrouter.key` entry of
  `~/.local/share/opencode/auth.json`. Never commit it.
- This whole `harnesses` repository cloned: the app imports `rag-harness`
  from the sibling folder.

## Quickstart against your repository

1. Install the dependencies once:

   ```bash
   cd adk-rag-harness
   uv sync --extra adk --extra openrouter
   ```

2. Index the target repository, one index per collection. Add a `.ragignore`
   at its root first for large generated or data files, and `.rag_index/` to
   its `.gitignore`:

   ```bash
   HARNESS_EMBED_PROVIDER=openrouter PYTHONPATH=../rag-harness \
     python3 -m rag_harness index /path/to/your-repository --profile docs
   HARNESS_EMBED_PROVIDER=openrouter PYTHONPATH=../rag-harness \
     python3 -m rag_harness index /path/to/your-repository --profile code
   ```

3. Point the app at those indexes with environment variables. They belong
   to the project, so set them in the shell or, better, in a launcher inside
   the target repository (next section); `adk-rag-harness/.env` keeps only
   machine-wide choices such as providers and budget (see `.env.example`):

   ```bash
   export HARNESS_PROJECT_ROOT=/path/to/your-repository
   export HARNESS_RAG_PROVIDER=index
   export HARNESS_RAG_DOCS_INDEX=/path/to/your-repository/.rag_index/docs
   export HARNESS_RAG_CODE_INDEX=/path/to/your-repository/.rag_index/code
   export HARNESS_EMBED_PROVIDER=openrouter
   ```

4. Start the app, open `http://localhost:8000`, select `adk_app` and ask a
   question. The agent calls `run_workflow` for every message, so Jev, not
   the chat model, decides whether retrieval is needed. The **Events** panel
   shows that call with the chosen collection, strategy, `model_tier`,
   `action_gate` and the evidence files. Reasoning models routed by
   `typesafe/jev-router` may also show **THOUGHT** entries; they are marked as
   thoughts and are not part of the answer:

   ```bash
   uv run adk web
   ```

Without steps 2 and 3 the app runs on demo evidence (`HARNESS_RAG_PROVIDER=demo`), which is enough to try
the decision flow. The sections below detail each piece.

### Shortcut from the target repository

Steps 2 to 4 can live in the target repository as one command, so nobody
edits `.env` when switching projects: variables set in the shell take
precedence over `adk-rag-harness/.env` (ADK keeps explicit variables when it
loads the file). A minimal launcher, saved for example as
`scripts/assistant.sh` in the target repository:

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HARNESSES_DIR="${HARNESSES_DIR:-$HOME/Sites/harness/harnesses}"
export HARNESS_EMBED_PROVIDER=openrouter HARNESS_EMBED_MODEL=voyageai/voyage-code-4
if [ "${1:-}" = index ]; then
  for p in docs code; do
    PYTHONPATH="$HARNESSES_DIR/rag-harness" python3 -m rag_harness index "$REPO" --profile "$p"
  done
  exit 0
fi
export HARNESS_PROJECT_ROOT="$REPO" HARNESS_RAG_PROVIDER=index \
  HARNESS_RAG_DOCS_INDEX="$REPO/.rag_index/docs" HARNESS_RAG_CODE_INDEX="$REPO/.rag_index/code"
exec uv run --directory "$HARNESSES_DIR/adk-rag-harness" adk web --port "${PORT:-8000}"
```

Expose it as a project command, for example `"assistant": "bash
scripts/assistant.sh"` in `package.json`, then run `npm run assistant -- index`
once and `npm run assistant` to open the app. The Biometrik App uses this
pattern as `npm run assistente` (`scripts/harness/assistente.sh`), with
checks for the clone, `uv` and the indexes.

The dependency-free Jev adapter targets TypeSafe's `/v1/systemone` contract and
accepts an injected transport for offline tests. `TypeSafeSdkDecisionProvider`
can use the official `typesafe-sdk` package when the optional
`[jev-sdk]` extra is installed. Provider errors fail closed in the workflow.
The `RagHarnessAdapter` loads the `rag-harness` index of an allowlisted
collection and runs the strategy Jev chose: `keyword` uses lexical search,
`semantic` uses embeddings and `hybrid` merges both with reciprocal rank
fusion. It returns typed evidence with scores and never controls
transitions. `AdkRuntimeAdapter` exposes this bounded workflow as a structured
Google ADK `LlmAgent` tool and `App` when the optional `[adk]` extra is installed.

The official TypeSafe SDK is published at
https://github.com/typesafe-ai/typesafe-sdk-python. This project depends on its
package rather than copying its source. Jev is an API service; no model weights
are downloaded.

## Settings

Every setting follows `HARNESS_<ROLE>_<SETTING>` for three roles: `CHAT`
(the model that talks to you), `DECISION` (Jev's typed routing) and `EMBED`
(RAG vectors). `.env.example` lists all of them with their defaults; copy it
to `.env` (ignored by Git) for machine-wide choices. Variables set in the
shell win over `.env`, which is how a project launcher points the app at its
own indexes.

| Role | Provider | Model (default per provider) |
|---|---|---|
| Conversation | `HARNESS_CHAT_PROVIDER` = `openrouter` \| `ollama` | `HARNESS_CHAT_MODEL`: `typesafe/jev-router` · `llama3.1:8b` |
| Decisions | `HARNESS_DECISION_PROVIDER` = `openrouter` \| `ollama` \| `typesafe` \| `demo` | `HARNESS_DECISION_MODEL`: `typesafe/jev-router` · `qwen2.5:14b` · `jev-latest` |
| Embeddings | `HARNESS_EMBED_PROVIDER` = `openrouter` \| `ollama` \| `ngram` | `HARNESS_EMBED_MODEL`: `voyageai/voyage-code-4` · `nomic-embed-text` |

Retrieval uses `HARNESS_RAG_PROVIDER` (`demo`, `index` or `postgres`), with
`HARNESS_RAG_{DOCS,CODE,AREA}_INDEX` for `index` and `HARNESS_RAG_PROJECT` for
`postgres` (see `adk-rag-postgres-harness/README.md`); `HARNESS_GUARDRAIL=on` enables the
injection filter. Endpoints are `OPENROUTER_BASE_URL` and `OLLAMA_BASE_URL`;
keys stay in `OPENROUTER_API_KEY` (or `~/.local/share/opencode/auth.json`) and
`TYPESAFE_API_KEY`, never in `.env`.

Names used before 2026-10-30 (`OPENROUTER_CHAT_MODEL`, `RAG_EMBEDDER`,
`OLLAMA_API_BASE`, `HARNESS_DECISION_PROVIDER=openrouter-system-one`,
`HARNESS_RAG_PROVIDER=rag-harness` and others) stop the app with a message
naming the replacement instead of being ignored.

## RAG provider modes

The decision provider and retrieval provider are independent:

```bash
# Demo evidence, no index required
HARNESS_RAG_PROVIDER=demo uv run adk web

# Real course-document index
HARNESS_RAG_PROVIDER=index uv run adk web

# A repository indexed by adk-rag-postgres-harness (uv sync --extra postgres)
HARNESS_RAG_PROVIDER=postgres HARNESS_RAG_PROJECT=my-repo uv run adk web
```

Create one index per collection for the target repository before using
`rag-harness`. The `docs` profile indexes `.md .txt .yaml .yml .json`; the
`code` profile indexes `.py .sh .ts .tsx .js .mjs`:

```bash
HARNESS_EMBED_PROVIDER=openrouter HARNESS_EMBED_MODEL=voyageai/voyage-code-4 \
PYTHONPATH=../rag-harness python3 -m rag_harness index /path/to/your-repository --profile docs --verbose
HARNESS_EMBED_PROVIDER=openrouter HARNESS_EMBED_MODEL=voyageai/voyage-code-4 \
PYTHONPATH=../rag-harness python3 -m rag_harness index /path/to/your-repository --profile code --verbose
```

Point each collection at its index before starting the app. Only the
collections with an index are offered to the decision provider, so it can
never route to a collection that has no evidence:

```bash
HARNESS_RAG_PROVIDER=index \
HARNESS_RAG_DOCS_INDEX=/path/to/your-repository/.rag_index/docs \
HARNESS_RAG_CODE_INDEX=/path/to/your-repository/.rag_index/code \
HARNESS_EMBED_PROVIDER=openrouter \
uv run adk web
```

`HARNESS_RAG_AREA_INDEX` adds the `area` collection. Without any of the three
variables the app falls back to a single `docs` collection.

The generated index stays local and should be ignored by Git (`.rag_index/`).
The real provider returns `blocked` when the index is missing or retrieval
fails, rather than allowing the model to invent evidence.

### Which files are indexed

Inside a Git repository only the files Git tracks or would track are indexed
(`git ls-files --cached --others --exclude-standard`), so everything in
`.gitignore` (native folders, build output, `.env`) stays out. Lockfiles such
as `package-lock.json`, `yarn.lock` and `pnpm-lock.yaml` are always skipped,
and so are hidden folders. A `.ragignore` file at the repository root adds
project-specific exclusions with gitignore-like patterns (`!` negation is not
supported):

```text
# large data dump, not useful as evidence
database/exercises.ts
generated/
*.min.js
```

### Embedding providers

`HARNESS_EMBED_PROVIDER` selects the embedding model, and it must be the same when
indexing and when querying:

| Value | Model | Notes |
|---|---|---|
| `openrouter` | `HARNESS_EMBED_MODEL`, default `voyageai/voyage-code-4` | Hosted and billed per token; reads the same OpenRouter key as the app |
| `ollama` | `HARNESS_EMBED_MODEL`, default `nomic-embed-text` | Local; requires `ollama pull nomic-embed-text` |
| `ngram` | Deterministic n-gram hashing | Offline architecture checks only; not semantic |

Without `HARNESS_EMBED_PROVIDER` the indexer uses Ollama when it is reachable and
n-grams otherwise; it never selects a billed provider automatically. Each
index records its embedder in `meta.json`. Re-indexing embeds only the chunks
whose content changed, while a different embedder triggers a full re-index.
Querying an index with another embedder fails closed instead of comparing
incompatible vectors.

To run the complete local-evidence test:

```bash
HARNESS_RAG_PROVIDER=index uv run adk web
```

## Run the ADK app

The `adk_app/agent.py` entrypoint uses OpenRouter with Jev
(`typesafe/jev-router`) by default, for both the conversation model and the
typed routing decisions. The only requirement is an OpenRouter key:

```bash
uv sync --extra adk --extra openrouter
uv run adk web
```

Open `http://localhost:8000`, select `adk_app`, and try a request such as
`find the deployment policy`. The project pins Python 3.14 in
`.python-version` because some LiteLLM dependencies have no wheels for newer
interpreters yet.

When `OPENROUTER_API_KEY` is absent, the app reads the `openrouter.key` entry
from `~/.local/share/opencode/auth.json` (or `OPENROUTER_AUTH_FILE`) and falls
back to `opencode.key`. The auth file is never copied into the repository or
printed. Jev Router chooses the underlying model per request, so its cost per
call varies.

## Conversation model modes

Select the conversation model with `HARNESS_CHAT_PROVIDER`:

```bash
# Default: OpenRouter, HARNESS_CHAT_MODEL=typesafe/jev-router
uv run adk web

# Another OpenRouter model
HARNESS_CHAT_MODEL=anthropic/claude-sonnet-5.5 uv run adk web

# Local Ollama; the server must be running and the model must support tools
uv sync --extra adk --extra ollama
HARNESS_CHAT_PROVIDER=ollama HARNESS_CHAT_MODEL=llama3.1:8b uv run adk web
```

The ADK integration uses LiteLLM's `openrouter` and `ollama_chat` providers.

## Decision provider modes

The conversational model and the typed decision provider are separate. Select
the decision provider with `HARNESS_DECISION_PROVIDER`:

```bash
# Default: OpenRouter, HARNESS_DECISION_MODEL=typesafe/jev-router
uv run adk web

# Deterministic demo provider
HARNESS_DECISION_PROVIDER=demo uv run adk web

# Local open-model decisions through Ollama's OpenAI-compatible endpoint
HARNESS_DECISION_PROVIDER=ollama \
HARNESS_DECISION_MODEL=qwen2.5:14b uv run adk web

# Official TypeSafe System One decisions
uv sync --extra adk --extra openrouter --extra jev-sdk
HARNESS_DECISION_PROVIDER=typesafe TYPESAFE_API_KEY=... uv run adk web
```

`openrouter` and `ollama` implement the same typed
decision contract with an OpenAI-compatible chat endpoint. With
`typesafe/jev-router`, Jev picks the model that answers the JSON contract;
this is not TypeSafe's `/v1/systemone` endpoint, so the confidence values are
self-reported and must be evaluated with the golden prompts before use in
production. The `typesafe` mode calls `/v1/systemone` directly.

The CLI tools `codex`, `claude` and `agy` can also be integrated as decision
providers through their non-interactive print modes and JSON-schema output. The
safe design is a separate subprocess adapter with read-only/no-tool flags,
short timeouts and strict JSON validation. They should not be invoked from the
workflow as unrestricted agents because they can carry workspace tools, session
state and side effects. The current app leaves those modes opt-in for a later
adapter; use Ollama or OpenRouter for the supported provider modes today.

## Token and cost ledger

When the sibling `harness-usage` package is present, every Jev decision,
TypeSafe call, conversation-model call (through a LiteLLM logger) and query
embedding writes one line to `<target repository>/.harness/usage/`. The
target is the repository that holds the configured `.rag_index`, or
`HARNESS_PROJECT_ROOT`. Calls of one message share the ADK invocation id, so
the report shows the cost per question. Decisions whose answer cannot be used
are still billed and are recorded as `invalid_response`.

```bash
cd ../harness-usage && python3 -m harness_usage report   # see harness-usage/README.md
```

`HARNESS_BUDGET_USD` (default 25) warns when the month passes 80% and 100%.

## Golden prompt evaluations

The natural-language examples from the course are also stored as executable
contract fixtures in `evals/golden_prompts.json`. They test the workflow's
observable result instead of comparing model prose: route, RAG call count,
collection, strategy, evidence source and blocked/clarification behavior.

These evals use scripted decision and RAG providers, so they do not require
Ollama, Jev, Google ADK or network access. Provider-backed evals belong in a
separate integration job after the offline contract is stable.

To exercise the actual ADK, LiteLLM and Ollama path, run the opt-in integration
check while Ollama is serving `llama3.1:8b`:

```bash
HARNESS_CHAT_MODEL=llama3.1:8b uv run python evals/run_ollama_evals.py
```

The runner sets `HARNESS_CHAT_PROVIDER=ollama` and
`HARNESS_DECISION_PROVIDER=ollama` unless they are already set.

It fails if Ollama does not call `run_workflow`, if the tool result has the
wrong route, or if a retrieved result has no evidence. It is intentionally
separate from the default suite because it needs a running local model and can
take several seconds per prompt.

To test the live Jev decision provider independently from the conversational
model, export `TYPESAFE_API_KEY` in the shell and run:

```bash
TYPESAFE_API_KEY=your-key uv run python evals/run_jev_evals.py
```

The runner sends only the typed routing questions to Jev, keeps retrieval in the
workflow, and prints provider model, route, confidence and evidence count. It
never prints the API key or raw provider payloads.

## Test

```bash
python3 -m unittest discover -s tests -v  # 33 tests
```

Optional runtime dependencies:

```bash
uv sync --extra adk --extra openrouter --extra ollama --extra jev-sdk
```
