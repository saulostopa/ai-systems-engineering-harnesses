---
name: area-report
description: Generates the area HTML report with cited sources — consumes the Area Copilot (business context), synthesizes the artifact, and attaches a SOURCE for every number. Use when the user asks for a report, summary, or analysis based on the area's spreadsheets/documents.
---

# Area report with cited sources

Produce the area artifact (report, meeting summary, goals analysis)
**with every number traceable to a source**. A number without a source is
forbidden.

## Gather

1. Query the context: `python -m area_harness query area_context "<area question>"`.
2. Open the file pointed to by the SOURCE (the exact line) — confirm the number before citing it.
3. Read the area's `feature_list.json` if the report involves feature status.

## Write

- Every number in the report comes with `FONTE: <path> (lines X-Y)` right below it.
- Without the source chunk read, the data does not enter the report.
- Format: self-contained HTML (same visual base as `feature-report`), tables for tabular data.

## Output

- Save to `relatorios/YYYY-MM-DD-<slug>.html` and open it.
- If the area context did not answer: say exactly what is missing (file, sheet, line) — do not fill in with an estimate.