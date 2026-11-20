---
name: proposal-workflow
description: Validates a proposal/deck against the briefing before submission — requirements checklist, cross review and approval record. Use when the user asks to review, validate, approve or send a proposal/presentation.
---

# Proposal validation before submission

Sending before validating is the commercial's "commit without a gate" (Lessons 07/10).
The proposal only goes out with the checklist passing.

## Gather

- The proposal (materiais/) and the source briefing.
- The verification script: `scripts/proposal-check.sh <proposal> <briefing>`.

## Write / Validate — checklist

1. **Briefing requirements** — every briefing requirement has an answer in the proposal (scripts/proposal-check.sh compares item by item).
2. **Numbers with source** — every number in the deck has `FONTE:` cited; no loose numbers.
3. **Cross review** — the proposal was read by a reviewer different from the one who generated it (another agent/person); the reviewer records the verdict.
4. **Approval record** — approved/rejected is recorded in the feature (comment/state), never only in the conversation.

## Output

- `relatorios/YYYY-MM-DD-<slug>-aprovacao.md`: checklist with STATUS per item + reviewer verdict.
- Any FAIL blocks the submission (log-event.sh records the friction).