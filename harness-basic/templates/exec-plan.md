---
id: feature/ABC-000
status: not_started
flow: feature-default
owner: <team or person>
exit_criteria:
  - build green
  - tests passing with no reduction in coverage
  - diff limited to the declared scope
---

<!--
  Execution plan — the ROUTE of one feature (Lessons 13, 14).

  Naming: the id is the branch name — feature/OEM-123, bugfix/AC-455,
  release/EST-3445, hotfix/… , improvement/… . The file flattens the slash
  (feature-OEM-123.md) because a slash is a path separator; the id in the
  front-matter stays exact, so the plan and the branch are the same thing.

  Where it lives:
    docs/exec-plans/active/   while status is not_started | in_progress | blocked
    docs/exec-plans/done/     once status is done

  Two rules the gate enforces (scripts/validate-harness.sh):
    1. the `status` above is the truth — never the directory the file sits in;
    2. a plan cannot reach `done` without a filled Evidence section.

  Do not confuse this with the other three artifacts:
    feature_list.json    the MAP     — what exists, in what state (Lesson 08)
    this file            the ROUTE   — how THIS feature gets done
    progress.md          the DIARY   — what happened in THIS session (Lesson 05)
    session-handoff.md   the NOTE    — what is left for the next session
-->

# feature/ABC-000 — <title>

## Scope

Declared before any edit (policies/scope-control.md). Files this plan is
allowed to touch:

- `src/...`
- `tests/...`

Out of scope: <what will explicitly NOT be touched>

## Steps

Each step has an observable outcome. A step with no way to check it is not a
step, it is a wish.

1. [ ] Declare the scope and open the feature in `feature_list.json`
2. [ ] Implement <the change>
3. [ ] Cover with tests <the case>
4. [ ] Record the evidence below
5. [ ] Close: update `progress.md` and `session-handoff.md`

## Blockers

- None (or: what is blocked, what was tried, what is missing)

## Artifacts

What this delivery leaves behind so the next person understands it without
reading the diff. Required by flows that declare it.

- [ ] `docs/artifacts/<plan-id>.json` — diagram source (written by the agent)
- [ ] `docs/artifacts/<plan-id>.html` — rendered and validated: `./scripts/artifacts.sh <plan-id>`

## Evidence

Required before `status: done`. Command → expected → actual, with real output —
never a summary in prose (Lesson 09, policies/evidence-required.md).

| Command | Expected | Actual |
|---|---|---|
| `npm run build` | exit 0 | _pending_ |
| `npm test` | N passing, 0 failing | _pending_ |
| `git diff --stat` | only the files declared in Scope | _pending_ |
