---
name: deck-generation
description: Generates presentation decks and proposals from a briefing + context (CRM, area data) — with every number citing its source. Use when the user asks for a presentation, deck, proposal or commercial material.
---

# Deck generation with context

The deck is born from the briefing and the context — never from scratch. A
number without a source is forbidden (multi-domain rule).

## Gather

1. **Briefing** — read the demand briefing: audience, objective, deadline, tone.
2. **Context** — consult the Area Copilot (`area_harness query <area_root>`) and/or the CRM: sales numbers, targets, customer history.
3. **Source** — every collected number keeps `FONTE: <file> (lines X-Y)`.

## Write

Deck structure (self-contained slide deck in Markdown/HTML):

1. **Opening** — the audience's problem in 1 sentence (from the briefing).
2. **Proof** — 3-5 numbers with FONTE cited under each one.
3. **Solution** — what is being offered; no promise the briefing does not support.
4. **Next steps** — deadline and owner (from the briefing).

Rules:
- Every slide with a number has the source visible in the footer.
- No number = no source = no slide.
- Nothing invented: if the context does not have the number, say it is missing (do not estimate).

## Output

- `materiais/YYYY-MM-DD-<slug>.md` (or HTML) + list of cited sources.
- Update the feature in `feature_list.json` (one `in_progress` at a time).