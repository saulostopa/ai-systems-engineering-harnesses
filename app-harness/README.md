# App Harness — QA layer (E2E)

> Mechanical E2E gate for the app harness: frontend change without a matching
> test = blocked commit. Modeled on the `frontend-qa-gate.sh` from the factory.

## What is here

```
app-harness/
├── scripts/
│   └── e2e-gate.sh              # pre-commit gate (fail-open without config)
├── templates/
│   ├── .harness/config.yaml     # config: frontend paths + E2E suite
│   └── e2e/
│       ├── pages/search_page.py # example Page Object Model
│       └── test_search.py       # example test with intercepted network
└── skills/                      # (C2) agentic navigation with vision
```

## Installation (on top of the basic harness)

```sh
cp app-harness/scripts/e2e-gate.sh <project>/scripts/
cp app-harness/templates/.harness/config.yaml <project>/.harness/config.yaml
# adds the gate to pre-commit:
echo 'exec "$(dirname "$0")/../scripts/e2e-gate.sh"' >> <project>/.githooks/pre-commit
```

## How the gate works

1. No config (`fail-open`): nothing to check — the content harness does not break.
2. Staged frontend (e.g.: `src/*.tsx`)? No staged E2E test in `tests/e2e/` → **blocks**.
3. `pytest` available? Runs the touched suite — failure → **blocks** (with triage via trace viewer).
4. Conscious bypass: `.harness/skip-e2e-gate` (expires in 5 min) — logged, not silent.

## Required test standards (qa-playwright-e2e skill)

- Semantic locators (`get_by_role`, `get_by_label`) — never fragile CSS/XPath.
- Page Object Model — one file per screen.
- Network interception (`page.route`) — deterministic setup, no API dependency.
- Flaky is a bug: triage with `playwright show-trace`, never "re-run until it passes".

## Flaky triage — the protocol

```
pytest tests/e2e -q --trace=retain-on-failure   # captures trace on failure
playwright show-trace trace.zip                 # inspects step by step
```

Triage questions: was the locator semantic? Was the setup deterministic
(intercepted)? Was the previous screen state expected? If the answer is "no",
the test is the bug — not the app.

## Verification

- Frontend change without E2E: commit blocked with a clear message.
- With E2E: suite runs and the commit passes.
- `validate-harness.sh` stays green (new gate does not break the harness).

**Layer 2 (agentic)**: [agentic navigation with vision](/harness-designs/app-harness) — C2.