# ADK + RAG harness

## Dynamic feature planning with ADK

The `feature_planner` app proposes and reviews vertical delivery slices using
lexical RAG over a synthetic repository. The ADK graph validates each proposed
specification and dispatches up to two independent slices in parallel. For
each slice, a nested ADK workflow produces a read-only investigation report,
verifies the report in a separate call and records its verdict. A failed
dependency skips its dependents. A retry sends the verifier's feedback back to
the worker. Global evaluation and synthesis have separate nodes.

`HARNESS_PLANNER_MAX_SLICES=5` sets the default ceiling for the planner's
proposal. Set a positive integer in `.env`, or pass it in the launch
environment for a pilot that disables dotenv. Restart ADK Web to apply the
setting. The planner can return fewer slices. The two-slice concurrency and
the two-attempt limit per slice apply regardless of this ceiling.

From `adk-rag-harness`, with Ollama running and `qwen2.5:14b` available:

```bash
uv sync --extra adk
uv run adk web --host 127.0.0.1 --port 8173
```

Open <http://127.0.0.1:8173> and choose `feature_planner`. Try a new session for
each request:

- “Add a status filter to the paginated task list and preserve it when paging.”
- “Add a weekly digest toggle to notification settings and honor it in the job.”

**Events** shows slice verdicts and `feature_model_route` as they arrive. Expand
the route event to see the role, provider, configured model, effort, status,
duration, model reported by the CLI when available, and reported token counts.
Event node paths show the individual `slice_investigation` executions below
`dispatch_slices`. The Replay links IDs such as `E1` to the source path and line range.
The **State** tab shows the last route and `feature_planning`, which holds the
plan and review results. **Artifacts** holds the validated `workflow-spec.json`
with source paths and line ranges.

Ollama is the default. Set `HARNESS_PLANNER_MODEL`, `HARNESS_VERIFIER_MODEL` or
`OLLAMA_BASE_URL` in the shell to override its defaults. The demo plans and
reviews slices in read-only mode. `adk_app` serves the separate question-answering flow.

### Optional CLI routing

Set `HARNESS_MODEL_ROUTER_CONFIG` to a JSON file to configure the ordered
provider list for each role. [The example profile](feature_planner/model-router.example.json)
uses Claude Code for planning and global evaluation, with Ollama for slice
reviews. Adjust each model ID to match the CLI installed on your machine.
The optional `slice_worker` entry controls investigation calls and inherits
the verifier chain when omitted.
Run this from `adk-rag-harness` with the CLIs on `PATH` and the selected
accounts signed in locally:

```bash
HARNESS_MODEL_ROUTER_CONFIG="$PWD/feature_planner/model-router.example.json" \
  uv run adk web --host 127.0.0.1 --port 8173
```

The Claude Code route requires a first-party Claude account reported by
`claude auth status` in the same environment that runs ADK. It uses the
installed `claude` CLI with its local sign-in. The AGY route accepts Gemini
models. Each CLI runs in a temporary working directory and receives the request
and selected demo excerpts over standard input. Configuring a remote provider
allows ADK to send those inputs to that provider.

A confirmed quota rejection advances to the next configured provider. The
router recognizes Claude Code's `credits_required` event and Codex's terminal
usage-limit and credit exhaustion messages. AGY's headless error envelope
currently lacks a verified quota signal. Later stages skip providers marked
exhausted during the same invocation. A parallel wave keeps its initial view
of available providers and merges quota outcomes before the next wave.

The slice verifier and global evaluator can retry the same request once per
configured route after a classified recoverable failure. Persistent
transport failures, timeouts, provider outages, or Claude Code turn limits
can advance review to the next configured route. A Claude Code route can
set `max_turns` from 1 to 8. The default is 2. Authentication failures
and refusals end the verifier request. An explicit review verdict of
`retry` still requests a new investigation. Events record the route position,
provider attempt number, and allowlisted failure category.

Token counts come from each provider. Missing counters are omitted. These
events report usage and elapsed time. The Postgres pilot adds a separate
estimate of context reduction.

### Run the Postgres evidence pilot

Reuse one full catalog checkout for multiple target repositories. Each pilot
has its own source worktree, Postgres project name, sessions and artifact
directory. Start with the target revision, the feature to plan and its
acceptance criteria. Identify which files the index may read.

#### 1. Prepare the shared checkout once

Use Node.js, an installed Archify skill, Ollama and access to a pgvector
instance. Use a dedicated database for each pilot, with migration permissions
for the initial index. The [Postgres quick start](../adk-rag-postgres-harness/README.md#start)
provides a local database for synthetic examples.

```bash
CATALOG=/absolute/path/to/ai-systems-engineering-harnesses
ARCHIFY=/absolute/path/to/archify/bin/archify.mjs

(cd "$CATALOG/adk-rag-postgres-harness" && uv sync --locked --extra postgres)
(cd "$CATALOG/adk-rag-harness" && uv sync --locked --extra adk --extra postgres)
```

The local profile uses `qwen3-embedding:4b` for the 1,024-dimension index and
`qwen2.5:14b` for planning and review. Install these models once in Ollama if
they are missing.

#### 2. Prepare and index each target project

Repeat this block with the target checkout, its approved revision and a
unique pilot name. Use an existing approved worktree or create the pinned
worktree below. Set `DATABASE_URL` locally for this pilot and verify the
index scope, including `.ragignore`, before indexing.

```bash
TARGET_REPO=/absolute/path/to/target-repository
PILOT_REVISION=HEAD    # Or the approved commit SHA
PILOT_PROJECT=project-a
PILOT_ROOT="$HOME/harness-pilots/$PILOT_PROJECT"
PILOT_WORKTREE="$PILOT_ROOT/source"
PILOT_PORT=8173        # Use a different port for each concurrent ADK instance

export HARNESS_USAGE_DIR="$PILOT_ROOT/usage"
mkdir -p "$HARNESS_USAGE_DIR"
git -C "$TARGET_REPO" worktree add --detach "$PILOT_WORKTREE" "$PILOT_REVISION"

: "${DATABASE_URL:?Set the dedicated Postgres connection for this pilot}"
export DATABASE_URL
export HARNESS_EMBED_PROVIDER=ollama HARNESS_EMBED_MODEL=qwen3-embedding:4b
export OLLAMA_BASE_URL=http://127.0.0.1:11434

(cd "$CATALOG/adk-rag-postgres-harness" && \
  uv run --no-sync python -m adk_rag_postgres_harness.cli index "$PILOT_WORKTREE" --project "$PILOT_PROJECT")
```

#### 3. Launch ADK Web for that project

Run this in the same shell. The local profile sets an empty CLI routing
configuration. Supply `PILOT_QUIZ_SPEC` as an absolute path if the pilot has
a reviewed question bank.

```bash
(cd "$CATALOG/adk-rag-harness" && \
  ADK_DISABLE_LOAD_DOTENV=1 \
  HARNESS_MODEL_ROUTER_CONFIG= \
  HARNESS_PLANNER_RAG_PROJECT="$PILOT_PROJECT" \
  HARNESS_PILOT_EVIDENCE_DIR="$PILOT_ROOT/evidence" \
  HARNESS_PILOT_QUIZ_SPEC="${PILOT_QUIZ_SPEC:-}" \
  HARNESS_ARCHIFY_BIN="$ARCHIFY" \
  uv run --no-sync adk web --host 127.0.0.1 --port "$PILOT_PORT" \
    --session_service_uri "sqlite:///$PILOT_ROOT/sessions.db" \
    --artifact_service_uri "file://$PILOT_ROOT/adk-artifacts")
```

For another project, repeat steps 2 and 3 in a separate shell with that
project's settings. ADK reads the project at startup. Reindex after changing
the source revision.

Use the `feature_planner` app and start a new session. **Events** shows the
retrieval and route attempts as they occur. **Artifacts** and the directory
named after the ADK invocation give access to the evidence bundle.
`feature_planning.evidence_bundle.status` reports publication status.

| Artifact | What it shows |
|---|---|
| `postgres-evidence.json` | Project, index hashes, selected chunk IDs and ranges, vector dimensions and search ranks. Each model attempt lists the prepared chunks and whether their hashes match the Postgres snapshot. |
| `architecture.html` | Archify architecture map, with the input and validation receipt alongside it. |
| `faq.html` | Standalone reference with four levels and collapsible answers about this run. |
| `quiz.html` | Bilingual assessment covering technical and business topics, with scoring by level, scoring by category and a review round for missed questions. |
| `replay.html` | Animated flow, selectable timeline and event details from the ADK invocation. |
| `token-usage.md` | Attempts, roles, models, latency, reported tokens and the estimated reduction in planner context. |
| `execution.json` | Sanitized event record, slice verdicts and verified worker findings. |

The planner reads the text stored at index time. Reindex when changing the
pilot revision. A semantic rank shows participation in vector retrieval.
A lexical hit can still have a stored vector. A matching payload hash
establishes which text was prepared for a model call. It does not establish
which excerpts influenced the answer. The token baseline compares the whole
indexed corpus with the retrieved context using UTF-8 bytes divided by four.
Provider counters are recorded separately.

#### 4. Close out pilot usage

After the implementation session finishes, combine the ADK evidence, the
selected Claude Code Desktop transcript and the dedicated embeddings ledger.
The report lists calls by agent and model, keeps cache counters separate, and
reports API-equivalent costs, confirmed billing and estimated RAG savings.
Only metrics are copied from the Claude transcript. Subagent transcripts next
to the selected session are included and streamed snapshots of a model response
are counted once.

```bash
CLAUDE_TRANSCRIPT=/absolute/path/to/the/implementation-session.jsonl
PILOT_SESSION=your-selected-adk-session
ADK_INVOCATION_ID=e-your-selected-invocation

(cd "$CATALOG/adk-rag-harness" && \
  uv run --no-sync python -m feature_planner.pilot_usage \
    --pilot "$PILOT_PROJECT" \
    --execution "$PILOT_ROOT/evidence/$ADK_INVOCATION_ID/execution.json" \
    --claude-session "$CLAUDE_TRANSCRIPT" \
    --embedding-ledger "$HARNESS_USAGE_DIR" \
    --output "$PILOT_ROOT/pilot-token-usage.md" \
    --publish-session "$PILOT_SESSION" --adk-port "$PILOT_PORT")
```

`--execution` and `--claude-session` can be repeated. Choose
only transcripts and invocations for this pilot. Omit `--publish-session` for
a file-only report, or set `--adk-user` if the session uses a user ID other
than `user`. `token-usage.md` remains the evidence for one ADK invocation.
The consolidated `pilot-token-usage.md` appears in **Artifacts** when published.

For actual USD billing, add `--billing /path/to/receipt.json` after matching
confirmed charges to the usage IDs in the report. The format accepts entries
like the following. A hosted call without a correlated charge stays blank.

```json
{"pilot":"project-a","currency":"USD","charges":[{"usage_id":"adk:e-example:5","usd":"0.0123"}]}
```

The embedding ledger captures the input token count reported by Ollama and the
number of texts sent per batch. Older endpoints can omit the token count.
Keep the ledger directory separate per pilot. [Ollama embed response](https://docs.ollama.com/api/embed)

#### Assessment and reference costs

The FAQ supports consultation during the pilot. The quiz follows the
course's four-level format and scores the developer's first submission
before opening a review round. The [example bank](feature_planner/quiz.example.json)
uses the synthetic task list and weekly digest. For a real feature, set
`HARNESS_PILOT_QUIZ_SPEC` to a reviewed JSON bank in the same format. Include
three questions per level, both categories in each level, three options
per question, the zero-based correct option and a source for the explanation.
Use verified rules and acceptance criteria for business questions. Use code,
tests and execution evidence for technical questions.

`token-usage.md` applies dated public API text rates to recognized CLI model
IDs and reported usage, even when the call used a subscription. The
report identifies which calls and model tariffs go into the subtotal.
Ollama stays available for local generation and embeddings. The planned
deployment will call remote models through [Databricks AI Gateway](https://docs.databricks.com/aws/en/ai-gateway/usage-tracking).
Its usage and billing records will provide the production reconciliation
source. The public API equivalent is a reproducible comparison baseline.

#### Installation boundary

A Git worktree contains a checkout of the catalog. The planner lives in
`adk-rag-harness/feature_planner` and shares the repository with two
runtime dependencies. `rag-harness` supplies the demo lexical search,
chunking and embeddings. `adk-rag-postgres-harness` supplies Postgres
indexing, retrieval and migrations. The quiz, FAQ and replay templates ship
with the planner. The Archify artifact requires Node.js and an installed
Archify skill, passed in `HARNESS_ARCHIFY_BIN`.

A standalone distribution would package the three runtime modules and
Archify together with the setup commands.

#### Choose what goes into the pilot index

Paths in the receipt are relative to the indexed worktree. The synthetic
demo uses Markdown fixtures. A pilot can index existing README and
architecture docs, ADRs, feature acceptance criteria and in-scope source
files. The index accepts supported documentation and configuration files
as well as Python, shell, JavaScript and TypeScript. Keep architecture
decisions and product rules in versioned documents near the code. Start
with a pinned worktree and review its tracked and unignored files before
indexing. Use `.ragignore` to remove paths and patterns outside the pilot,
including confidential documentation and fixture data. The filename
filters detect some sensitive names. Review the allowed content for
credentials and personal data embedded in otherwise ordinary files.

Example `.ragignore` patterns, to adapt to the pilot repository:

```gitignore
/docs/internal/
/tests/fixtures/private/
*.generated.json
```

Set `HARNESS_PLANNER_RAG_TARGET_TOP_K` to choose the target evidence budget
from 1 to 16 chunks without changing the reference budgets. The default is
4 with references and 6 for target-only retrieval.

The receipt identifies an indexed chunk by project, relative path, line range
and hashes. Reindex after changing the pilot revision. If a CLI route is
enabled, the planner and slice reviewers can send the selected indexed
excerpts to its provider. Choose routes allowed for the repository's data.

The [data guardrails backlog](docs/backlog/adk-rag-data-guardrails.md) tracks
input, output and artifact protections across the local and gateway routes.

#### Changing the Postgres embedding model

The pilot uses `qwen3-embedding:4b` through Ollama and a normalized
`vector(1024)` column in Postgres. `HARNESS_EMBED_PROVIDER` and
`HARNESS_EMBED_MODEL` select the embedder. Verify adapter support before
introducing an API route. The current shared embedding factory has local
and OpenRouter adapters. The [provider comparison](docs/adk-web-events.pt-BR.md#modelos-de-embeddings-para-a-apresentação)
includes options that may need a new integration.

1. Pin the provider, exact model revision or local digest, output dimension,
   normalization, query and document instructions, and preprocessing and
   chunking versions. Record the source commits, file manifest hashes and
   data policy version alongside the index. The current storage cache uses
   content hash and model ID, so isolate candidate runs with a distinct
   index deployment whenever that ID would otherwise reuse old vectors.
2. Build the candidate separately from the active index. Re-embed the
   included target and reference documents and use the same embedding
   configuration to encode their queries. Equal vector length alone does
   not make vector spaces compatible. For a 768-dimensional model, prepare
   a compatible Postgres vector column and index. Only apply truncation
   supported by the model and normalize the resulting vectors.
3. Compare candidate and baseline on a fixed query set and source manifest.
   Record evidence recall by corpus, scope isolation, latency, and
   indexing and query costs. Approve data egress before sending source
   text or queries to a hosted embedding provider.
4. Switch the query embedder and its index together. Keep the previous
   pair available for rollback. On provider failure, route only to
   a separately built, matching index or report the retrieval failure.
   The generation-model fallback has its own configuration.

#### Execute one approved slice locally

The executor is opt-in through `HARNESS_PILOT_EXECUTOR_POLICY`. It requires
an operator-approved policy that pins the ADK session, prior accepted plan,
worktree, base commit, file allowlist, patch and resulting file hashes. The
`Executar corte aprovado` command enters a separate subgraph that reviews
the patch through a read-only Codex call, applies the approved bytes, and
publishes the actual diff and local test results. See the [Pilot 3 runbook](docs/catalogo-adfixus-pilot3.pt-BR.md#primeiro-corte-no-executor-do-adk).

#### Evaluation, load testing and cloud execution backlog

The [Catálogo pilot 3 runbook](docs/catalogo-adfixus-pilot3.pt-BR.md) covers
the synthetic ADK Evalset and the optional per-invocation evidence report.

The [Eval Results proposal](docs/backlog/adk-evals-results.md) tracks
versioned ADK cases and a consolidated report of quality, evidence,
security, and cost. See the [pilot cost table](docs/adk-web-events.pt-BR.md#custo-de-api-equivalente-do-piloto-adfixus)
for the current measurements and the coverage needed for a full comparison.

The [load testing proposal](docs/backlog/adk-load-testing.md) measures how many
missions meet the quality criteria and deadline under concurrency, including
queue time, provider limits, and recovery.

The [Databricks cloud execution proposal](docs/backlog/adk-databricks-cloud-execution.md)
tracks unattended feature runs with an isolated worktree, an authorized
executor, production-grade guardrails, and CI and Eval gates.

## Repository question answering with the original ADK + RAG + Jev app

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
