---
name: report-generation
description: Generates and publishes the financial report with cited sources — the last step of the nightly pipeline (nightly-run.sh). Use when the user asks for the report, the early-morning summary, or 'what came out in today's report'.
---

# Financial report generation

The nightly report is the artifact of the harness sleeping: published with
sources before the team arrives (Lesson 13: autonomous loop with an exit criterion).

## Gather

- The area context (spreadsheets) — via the Area Copilot (`area_harness query`).
- The date: the report is `relatorios/YYYY-MM-DD-<slug>.md`, one per day.

## Write

Fixed report structure:

1. **Date and pipeline** — when it ran, with which playbook version.
2. **Answered questions** — each with a cited FONTE (file + lines).
3. **Reconciliation** — expected vs. actual (spreadsheet-analysis skill); failure recorded, never rounded.
4. **Alerts** — missing data, outliers, divergences; each with the cited line.
5. **Status** — `CONSOLIDATED` (everything reconciled) or `WITH DIVERGENCES` (list).

## Output

- `relatorios/YYYY-MM-DD-<slug>.md` published (versioned playbook folder).
- If the status is `WITH DIVERGENCES`: record it in the harness log (log-event.sh) — recorded friction is debt that does not become interest (Lesson 11).