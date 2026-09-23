# Definition of Done — Finance domain

A financial delivery is done when:

1. **Pipeline really ran** — `scripts/nightly-run.sh <area_root>` executed (or the item was processed manually with the same engine).
2. **Reconciliation done** — totals checked: expected vs. actual in a table; divergence recorded with the cited line, **never rounded**.
3. **Every source cited** — no number without `FONTE: <file> (lines X-Y)` (nightly exit criterion: 0 lines with an unsourced number).
4. **Artifact published** — `relatorios/YYYY-MM-DD-<slug>.md` versioned in the playbook.
5. **Evidence recorded** — pipeline output attached; feature in `passing`.

## What is NOT "done" in this domain
- Report with an unsourced number.
- Total "rounded to fit" — divergence is data, not a bug.
- "The cron should run" — without today's recorded execution.