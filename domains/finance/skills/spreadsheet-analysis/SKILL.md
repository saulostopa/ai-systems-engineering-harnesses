---
name: spreadsheet-analysis
description: Analyzes spreadsheets (CSV/XLSX) with total validation, missing-data detection and a summary with cited sources. Use when the user asks for analysis, reconciliation or a summary of a spreadsheet/tabular data.
---

# Spreadsheet analysis with sources

Consumes the Area Copilot engine (rag_harness): the spreadsheet context comes
with `FONTE: <file> (lines X-Y)` — a number without a source is forbidden (domain rule).

## Gather

1. Index the context: `python3 -m area_harness index <area_root> --verbose` (or confirm the index exists).
2. Query: `python3 -m area_harness query <area_root> "<analysis question>"`.
3. Open the file pointed to by the FONTE and confirm the number on the exact line before citing.

## Write

- **Total validation**: sum the source column and compare with the declared total — expected vs. actual in a table.
- **Missing data**: count empty cells per column and report with the line.
- **Outliers**: values beyond ±3 deviations from the column mean — cite the line of each one.
- Every number in the summary carries `FONTE: <path> (lines X-Y)`.

## Output

- Markdown summary ready for the report (or HTML via feature-report).
- If the reconciliation failed (totals do not match): the report goes out with **status RECONCILIATION FAILED** and the list of divergences with lines — never "rounded to fit".