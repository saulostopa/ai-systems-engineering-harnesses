# Basic harness

Installable control layer for small repositories from the Harness Foundation
Course. The standalone package provides the core contract: router, explicit
state, scope/evidence policies, execution plans, mechanical gates and Git
hooks.

## Install in another repository

Run from the root of the `harnesses` checkout:

```bash
./harness-basic/install.sh /absolute/path/to/project
```

The target directory must already exist. If it is a Git repository, the
installer copies `.githooks/` and configures `core.hooksPath=.githooks`.
Existing paths are protected by default. `--force` permits overwrites and
should only be used after reviewing the target; always run the health check
after a forced installation.

After installation:

```bash
cd /absolute/path/to/project
./init.sh
./scripts/validate-harness.sh
```

Then customize sections 1 and 7 of `AGENTS.md`, replace the example entries in
`feature_list.json` and mark exactly one feature `in_progress` before the first
commit.

## Installed core

- `AGENTS.md`, `feature_list.json`, `progress.md` and `session-handoff.md`
- `policies/` with scope, Definition of Done and evidence rules
- `docs/exec-plans/` and `docs/artifacts/`
- `scripts/` with health, gatekeeper, artifact, E2E and skill-scan checks
- `.githooks/` with pre-commit and pre-push enforcement

## Standard course skill profile

The Foundation Course uses the following standard profile in derived basic
harness distributions:

| Skill | Purpose |
|---|---|
| `feature-report` | Accessible delivery report with traceable evidence |
| `feature-quiz` | Adaptive four-level feature quiz |
| `feature-archify` | Verifiable diagram of a delivered feature |
| `skill-guard` | Supply-chain scan before third-party skill installation |
| `qa-playwright-e2e` | Resilient Playwright E2E coverage |
| `qa-perf-triage` | Load-test and latency-regression triage |
| `agentic-navigation` | Visual acceptance of real application flows |

The standalone `harness-basic` directory currently installs the core only;
derived distributions may bundle this profile under `.agents/skills/`. Shared
Eleanor assets belong in `.agents/skills/assets/`. `feature-archify` still
requires the third-party `archify` skill, which must pass `skill-guard` before
installation.

## Self-installing derived distributions

A distribution that is both the package and its first managed repository must
require an explicit self-install flag:

```bash
git init
./install.sh --self
```

The explicit flag prevents an accidental `./install.sh .` from overwriting
package state. This mode belongs to the derived installer; the standalone core
installer expects a separate target directory.

## Validate the package

```bash
npm run validate
bash tests/test_e2e_gate.sh
bash tests/test_skill_guard.sh
```

Docker/network-dependent SkillSpector cases can be skipped when their runtime
is unavailable; structural gate tests must still pass.
