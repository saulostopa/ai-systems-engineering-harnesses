# ADK + RAG + Jev harness

The harness keeps the decision contract and retrieval boundary independent of
Google ADK and the Jev provider. It can run offline with fake providers, which
makes policy behavior testable before adding network clients.

The intended runtime flow is:

```text
request → decision provider → policy code → RAG adapter → evidence gate
```

The dependency-free Jev adapter targets TypeSafe's `/v1/systemone` contract and
accepts an injected transport for offline tests. `TypeSafeSdkDecisionProvider`
can use the official `typesafe-sdk` package when the optional
`[jev-sdk]` extra is installed. Provider errors fail closed in the workflow.
The `RagHarnessAdapter` loads the existing `rag-harness` controller by an
allowlisted collection and returns typed evidence without controlling
transitions. `AdkRuntimeAdapter` exposes this bounded workflow as a structured
Google ADK `LlmAgent` tool and `App` when the optional `[adk]` extra is installed.

The official TypeSafe SDK is published at
https://github.com/typesafe-ai/typesafe-sdk-python. This project depends on its
package rather than copying its source. Jev is an API service; no model weights
are downloaded.

## RAG provider modes

The decision provider and retrieval provider are independent:

```bash
# Demo evidence, no index required
HARNESS_RAG_PROVIDER=demo uv run adk web

# Real course-document index
HARNESS_RAG_PROVIDER=rag-harness uv run adk web
```

Create an index for a target repository before using `rag-harness`:

```bash
ollama pull nomic-embed-text
RAG_EMBEDDER=ollama OLLAMA_EMBED_MODEL=nomic-embed-text \
PYTHONPATH=../rag-harness python3 -m rag_harness index /path/to/your-repository --verbose
```

Point the provider at that index before starting the app:

```bash
HARNESS_RAG_PROVIDER=rag-harness \
HARNESS_RAG_DOCS_INDEX=/path/to/your-repository/.rag_index \
uv run adk web
```

The generated index stays local and should be ignored by Git. The real provider
returns `blocked` when the index is missing or retrieval fails, rather than
allowing the model to invent evidence.

For an offline architecture check without Ollama, use
`RAG_EMBEDDER=ngram`. It is deterministic but less semantically expressive;
delete and recreate the index whenever the embedding model changes.

To run the complete local-evidence test with OpenRouter decisions:

```bash
HARNESS_DECISION_PROVIDER=openrouter-system-one \
HARNESS_RAG_PROVIDER=rag-harness \
uv run adk web
```

## Run the ADK app

The `adk_app/agent.py` entrypoint uses Ollama locally by default. The
conversation model is `llama3.1:8b`; typed routing decisions use
`qwen2.5:14b`, which can be changed independently:

```bash
uv sync --extra adk --extra ollama --extra jev-sdk
uv run adk web
```

Open `http://localhost:8000`, select `adk_app`, and try a request such as
`find the deployment policy`. The app uses Ollama by default through
`http://localhost:11434` and the
`llama3.1:8b` model. Set `OLLAMA_MODEL` to another locally installed model
when needed. Set `HARNESS_DECISION_PROVIDER=demo` for the deterministic demo or
`HARNESS_DECISION_PROVIDER=jev` with `HARNESS_OFFLINE=0` and
`TYPESAFE_API_KEY` for official Jev routing.

```bash
OLLAMA_MODEL=mistral-small3.1 HARNESS_OFFLINE=0 uv run adk web
```

The Ollama server must be running and the selected model must support tool
calling. The ADK integration uses the `ollama_chat` LiteLLM provider.

## Decision provider modes

The conversational model and the typed decision provider are separate. Select
the decision provider with `HARNESS_DECISION_PROVIDER`:

```bash
# Default: local Ollama decision provider
uv run adk web

# Deterministic demo provider
HARNESS_DECISION_PROVIDER=demo uv run adk web

# Local open-model decisions through Ollama's OpenAI-compatible endpoint
HARNESS_DECISION_PROVIDER=ollama-system-one \
OLLAMA_DECISION_MODEL=qwen2.5:14b uv run adk web

# Hosted OpenRouter decisions; the chat model can remain local Ollama
HARNESS_DECISION_PROVIDER=openrouter-system-one \
OPENROUTER_API_KEY=... \
OPENROUTER_DECISION_MODEL=deepseek/deepseek-v4-flash-0731 \
uv run adk web

# Official TypeSafe Jev decisions
HARNESS_OFFLINE=0 HARNESS_DECISION_PROVIDER=jev \
TYPESAFE_API_KEY=... uv run adk web
```

`ollama-system-one` and `openrouter-system-one` implement the same typed
decision contract with an OpenAI-compatible chat endpoint. They are compatible
with the harness contract, but they are not the Jev model and their confidence
values must be evaluated with the golden prompts before use in production.
When `OPENROUTER_API_KEY` is absent, the app reads the `openrouter.key` entry
from `~/.local/share/opencode/auth.json` and falls back to `opencode.key`.
The auth file is never copied into the repository or printed.

The CLI tools `codex`, `claude` and `agy` can also be integrated as decision
providers through their non-interactive print modes and JSON-schema output. The
safe design is a separate subprocess adapter with read-only/no-tool flags,
short timeouts and strict JSON validation. They should not be invoked from the
workflow as unrestricted agents because they can carry workspace tools, session
state and side effects. The current app leaves those modes opt-in for a later
adapter; use Ollama or OpenRouter for the supported provider modes today.

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
HARNESS_OFFLINE=1 OLLAMA_MODEL=llama3.1:8b uv run python evals/run_ollama_evals.py
```

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
python3 -m unittest discover -s tests -v  # 13 tests
```

Optional runtime dependencies:

```bash
uv sync --extra adk --extra ollama --extra jev-sdk
```
