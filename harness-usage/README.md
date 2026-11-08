# Harness usage — token and cost ledger

Records every LLM call the harnesses make, so a question, a feature or an
index has a known cost. Standard library only. `rag-harness`,
`adk-rag-harness` and `hard-harness` load it from this sibling folder when it
exists and skip recording when it does not, so each harness still runs alone.

## What is recorded

One JSON line per provider call, appended to
`<target repository>/.harness/usage/YYYY-MM.jsonl`. Add `.harness/` to that
repository's `.gitignore`; the ledger warns once when it is not ignored.

```json
{"schema": 1, "ts": "2026-10-29T23:41:07Z", "run_id": "…", "request_id": "e-11941ada…",
 "harness": "adk-rag-harness", "component": "decision", "operation": "collection,strategy",
 "provider": "openrouter", "model": "typesafe/jev-router", "routed_model": "openai/gpt-6-luna",
 "input_tokens": 226, "output_tokens": 113, "cached_tokens": 0,
 "cost_usd": 7.91e-05, "cost_source": "provider", "latency_ms": 3425,
 "status": "ok", "error_kind": null,
 "project": "biometrik-app-reactnative", "feature": "jev-adk-rag-harness"}
```

| Field | Meaning |
|---|---|
| `component` | `decision`, `chat`, `embedding_index`, `embedding_query` or `agent` |
| `operation` | Decision questions, index profile or hard-harness node |
| `request_id` | Groups the calls of one question (ADK invocation id) or one hard-harness workflow |
| `routed_model` | Model the provider actually used; `typesafe/jev-router` picks a different one per call |
| `cost_source` | `provider` (OpenRouter `usage.cost`), `price_table` (tokens × cached OpenRouter prices), `local` (Ollama) or `unknown` |
| `status`, `error_kind` | `ok` or `error`; `HTTP 402`, timeouts and `invalid_response` (billed, but the answer was unusable) |
| `feature` | `active_feature_id` of the target repository's harness, when it has one |

Prompts, answers, code excerpts and keys are never written. Recording never
breaks a harness: a write error is reported once on stderr and the call goes
on.

## Where the target repository comes from

1. `HARNESS_PROJECT_ROOT`;
2. `adk-rag-harness`: the repository that holds the configured `.rag_index`;
3. `rag-harness`: the repository passed to `index`, `query`, `hybrid` or `agent`;
4. otherwise the Git repository of the current directory.

`HARNESS_USAGE_DIR` replaces the ledger directory and `HARNESS_USAGE=0`
turns recording off.

## Budget

`HARNESS_BUDGET_USD` (default `25`) is a monthly ceiling summed across every
ledger this machine has written to. The first call over 80% and over 100%
prints a warning; nothing is blocked. `0` disables the warning. The ledger
directories are listed, paths only, in
`~/.local/share/harness/usage-ledgers.txt`.

## Reports

```bash
cd harness-usage
python3 -m harness_usage report                                   # this month, every ledger
python3 -m harness_usage report ~/repo-a ~/repo-b --all           # several repositories, every month
python3 -m harness_usage report --by routed_model --by feature    # choose the groupings
python3 -m harness_usage report --format markdown                 # evidence for progress.md
python3 -m harness_usage report --format csv --output usage.csv
python3 -m harness_usage report --format html --output usage.html # self-contained dashboard
python3 -m harness_usage ledgers                                  # where the ledgers live
```

Groupings: `day`, `month`, `component`, `operation`, `harness`, `provider`,
`model`, `routed_model`, `project`, `feature`, `status` and `request`. Every
report starts with total cost, errors, month-end projection, budget use and
the cost per question (average, p50, p95 and maximum).

## Test

```bash
python3 -m unittest discover -s tests -v
```
