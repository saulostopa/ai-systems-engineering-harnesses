---
name: agentic-navigation
description: Navigates the app like a user and validates the UI with vision — starts the build, opens the app, walks real flows, takes screenshots and issues a verdict per criterion. Use when the user asks to validate/accept a screen or flow of the app, visually verify the result of a feature, or "open the app and test it". Requires an agent with vision capability.
---

# Agentic navigation with vision

Close the app's acceptance loop: the agent does not ask "does it work?" — it
starts the app, navigates, **sees** and issues a verdict per criterion, with
screenshots as evidence (Lesson 09: proof, not opinion).

## Gather — before navigating

- The feature in question: read the diff and the existing E2E tests (what QA already covers).
- The app: how to start it (`package.json` scripts — `dev`, `build`, `preview`), port, test environment credentials (or how to create test data via interception).
- The feature's acceptance criteria (from the item/report — never invent them).

## Navigate — the 5-step protocol

1. **Start the app** — build (or dev server) with the real command; confirm the port is responding.
2. **Create deterministic state** — intercept the API (`page.route` / mock) when you need specific data; never rely on random data.
3. **Walk the real flow** — from the entry point to the end, like a user: click, fill, submit, go back. Also navigate the **edge states**: empty, error, loading, duplicated data.
   - **Fast Reactive Loop (~300ms)**: Drive high-frequency DOM transitions and micro-actions using fast typed decisions, reserving heavy multimodal vision calls for visual layout verification checkpoints.
   - **Action Safety Guardrail**: Filter actions through `allow` / `ask` / `deny`. Never execute destructive actions (real checkouts, account deletion, drop data) without operator confirmation (HITL).
4. **Validate with vision** — at checkpoint steps: layout (overlap, clipping, overflow), readable contrast, infinite loading, correct error messages, acceptable empty states. Take **screenshots as evidence** of every important step.
5. **Issue a verdict per criterion** — for each acceptance criterion: `ACCEPTED` or `REJECTED`, with the screenshot and the observation that justifies it.


## Verdict — required format

```markdown
## Navigation verdict — <feature/screen>

| Criterion | Verdict | Evidence |
|---|---|---|
| Full flow works | ACCEPTED | <screenshot> |
| No visual breakage | REJECTED — header overlap | <screenshot> |
| Acceptable empty state | ACCEPTED | <screenshot> |
| Loading is not infinite | ACCEPTED | <screenshot> |

### Findings
- **[REJECTED] Header overlap** — when scrolling with the keyboard, the header
  covers the content (screenshot). Likely cause: sticky header z-index.
- Recommendation: turn it into an E2E test (QA layer) to immortalize the regression.
```

## Output

- Verdict per criterion + screenshots saved in `reports/navigation/YYYY-MM-DD-<slug>/` (with the step name in the file name).
- Every **finding** becomes a recommendation for a new E2E test — the loop closes (exploratory finds, deterministic immortalizes).
- No "seems to work": every ACCEPTED has a screenshot; every REJECTED has a likely cause.

## Rules

- Never navigate with random data: intercept for determinism.
- Do not "fix" what you found — record the finding (the fix is another feature).
- If you could not start the app, stop and report the blocker — do not invent a verdict.
