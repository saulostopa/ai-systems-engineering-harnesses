# Definition of Done

> Lesson 09. "Done" is a verifiable state, not a word.

A feature is done when:

1. **Build passes** — command executed and output attached (exit 0).
2. **Tests pass, with no reduction** — the full suite runs green; no test was
   deleted, renamed, skipped or weakened compared to the start.
3. **Diff in scope** — `git diff` contains only what was declared in
   `policies/scope-control.md`.
4. **Evidence recorded** — command + expected vs. actual result, attached
   to the feature item/report.
5. **State updated** — `feature_list.json` reflects the real state (`passing`).

## What is NOT "done"
- "It seems to work" (without build/tests executed).
- "I tested it" (without commands and results).
- A green suite with fewer tests than at the start — that is regression, not a pass.