# AGENTS.md — Area harness (Area Copilot template)

> Copy to the area root. Golden rule: **a number without a source is forbidden**.

## 1. How to work

- Before any task, read `area_context/index.md` (the area map).
- Specific context? Use the Area Copilot (`python -m area_harness query area_context "<question>"`) or open the file pointed to by the index — **never guess**.
- Every cited datum comes from a file you read: spreadsheet, document, or image.

## 2. How to verify

- Every artifact cites its source: `FONTE: <path> (lines X-Y)`.
- "I don't know" is a valid answer; **a made-up number is not**.
- No number leaves without its source chunk attached.

## 3. State

- The area's features live in `feature_list.json` (one `in_progress` at a time).
- Scheduled reports (nightly mode) publish to `relatorios/` with the date in the name.

## 4. Where the context lives

| Folder | What it contains |
|---|---|
| `area_context/planilhas/` | Tabular data (CSV/XLSX) |
| `area_context/documentos/` | Briefings, rules, processes |
| `area_context/imagens/` | Visual evidence (screenshots, parts) |
| `area_context/index.md` | Area map (tags + summaries) — regenerate when you add files |