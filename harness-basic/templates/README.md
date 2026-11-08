# Basic harness package — templates

These files are the payload installed at the root of a small project. Use the
package installer instead of copying `templates/` manually so scripts, hooks
and execution-plan directories are installed consistently.

## Installation

```bash
./harness-basic/install.sh /absolute/path/to/project
cd /absolute/path/to/project
./init.sh
```

## Contents

| File | Role | Lesson |
|---|---|---|
| `AGENTS.md` | Router: what to read, how to choose, how to verify, how to finish | 04 |
| `feature_list.json` | Source of truth for scope (state per feature) | 08 |
| `progress.md` | Diary of the current session | 05 |
| `session-handoff.md` | Note for the next session (mandatory header) | 05 |
| `exec-plan.md` | Template for `docs/exec-plans/` — the route of one feature, with evidence | 13 |
| `policies/scope-control.md` | Scope declared before editing | 07 |
| `policies/definition-of-done.md` | Verifiable "done" criteria | 09 |
| `policies/evidence-required.md` | Evidence format (command → expected → actual) | 09 |
| `policies/git-worktrees.md` | Isolated feature, integration and service worktrees | 14 |
| `scripts/git-safe` | Provider-neutral guard for destructive Git commands | 14 |
| `init.sh` | Environment initialization | 06 |

## Minimal customization

1. Edit sections 1 and 7 of `AGENTS.md` (what the repo is, real commands).
2. Replace the example features in `feature_list.json` with yours.
3. If the project does not use Node, adjust section 4 of `init.sh`.
4. Optionally add the course standard skill profile under `.agents/skills/`;
   the standalone core package does not bundle it.

## Natural evolution

- Mechanical pre-commit/pre-push gates are installed by `install.sh` when the
  target is already a Git repository.
- Need flow management? Add a workflow engine on top of this package — see the enterprise harness design for the contract it must satisfy.
- Need area context? Evolve to the Area Copilot (Project 05).

## Guarantee

No file in this package is "decorative": each one answers a question from the
agent (what, how, when to stop, where it was) or a process gate
(scope, done, evidence). If a file is not being read, remove it —
a bloated templates folder is debt, not rigor.
