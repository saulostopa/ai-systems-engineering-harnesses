# AGENTS.md — Basic harness router

> Short router (Lesson 04). Point, don't pile up. Replace the examples with
> your project's real paths.

## 1. What this repository is

[One line: the product and its context — replace]

## 2. What to read first

1. `README.md` — project overview.
2. `feature_list.json` — source of truth for what to do.
3. `progress.md` — progress of the current session.
4. `session-handoff.md` — state left by the previous session.

## 3. How to determine the current state

- `feature_list.json` — status per feature (`not_started` / `in_progress` / `blocked` / `passing`).
- `progress.md` — recent work, current work, failures, next action.
- `session-handoff.md` — what is verified, what is broken, next step.
- `git status` / `git diff` — working tree.

## 4. How to choose a task

- Only one feature `in_progress` at a time (an exception requires a record in `progress.md`).
- Choose the highest-priority `not_started`.
- Declare the scope before editing (`policies/scope-control.md`):
  - What will I change? Why?
  - Which files are expected? What is OUT of scope?
  - How will success be verified?

## 5. How to verify the work

- Follow `policies/definition-of-done.md` and `policies/evidence-required.md`.
- Run the project's build and tests (commands below).
- Nothing is "done" without recorded evidence (command + result).
- **Git is the truth**: re-run tests and check `git diff`; never trust narration.

## 6. How to end the session

1. Update `feature_list.json` (real states).
2. Update `progress.md` (what was done, what failed, next action).
3. Update `session-handoff.md` (mandatory sections in the header).
4. Run the tests — they must pass.
5. Coherent commit (`policies/git.md` if it exists).

## 6b. How to close a delivered feature

A delivery owes an explanation, not only code. Write the diagram source and let
the harness validate it:

```bash
# the agent writes docs/artifacts/<plan-id>.json describing what was built
./scripts/artifacts.sh feature/OEM-123     # renders + validates (showcase)
```

The artifact is the `feature-archify` skill's job. It is required by flows that
declare it — `wm-harness plan done` refuses to archive the plan without it.

## 7. Project commands

<!-- Replace with the real commands -->

```bash
npm run build    # build
npm test         # tests
npm run dev      # development
```

## 8. Where the documentation lives

| I need | I go to |
|---|---|
| Process rules | `policies/*.md` |
| Architecture | `docs/architecture/` |
| Skills | `.claude/skills/` (or `.agents/skills/`) |
| State | `feature_list.json`, `progress.md`, `session-handoff.md` |