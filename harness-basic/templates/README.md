# Basic harness package — templates

Copy this package to the root of a small project to deliver the minimal
harness in minutes. Modeled after the `webmotors-harness-factory`.

## Installation

```sh
cp -r templates/ <your-project>/
cd <your-project>
./init.sh          # validates the environment and prints the next steps
chmod +x init.sh   # if the execution bit was lost in the copy
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
| `init.sh` | Environment initialization | 06 |

## Minimal customization

1. Edit sections 1 and 7 of `AGENTS.md` (what the repo is, real commands).
2. Replace the example features in `feature_list.json` with yours.
3. If the project does not use Node, adjust section 4 of `init.sh`.
4. (Optional) Install the skills package: `harness-agent-skills` (see the Library).

## Natural evolution

- Need mechanical gates? Add pre-commit/pre-push hooks (course Project 02).
- Need flow management? Add a workflow engine on top of this package — see the enterprise harness design for the contract it must satisfy.
- Need area context? Evolve to the Area Copilot (Project 05).

## Guarantee

No file in this package is "decorative": each one answers a question from the
agent (what, how, when to stop, where it was) or a process gate
(scope, done, evidence). If a file is not being read, remove it —
a bloated templates folder is debt, not rigor.
