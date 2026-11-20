---
name: game-design
description: Designs game features — persona, storytelling, mechanics and economy — and generates the design doc. Use when the user asks to create/design a character, narrative, mechanic, mission or game feature.
---

# Game design with the harness

Design the game feature as a product feature: scope, verification and
artifact — except the "test" is a simulated playtest.

## Gather

- The game feature list (`feature_list.json` from the playbook): which feature, in what state.
- The game universe (lore docs, existing characters, narrative tone).
- Platform constraints (Roblox: Luau engine, mesh/part limitations).

## Write

The design doc in 5 sections, always in this order:

1. **Persona** — who plays this feature: age, motivation, pain point. (Persona first — mechanics later.)
2. **Storytelling** — the narrative: hook, conflict, reward. In one sentence: "the player does X because Y".
3. **Mechanics** — the playable loop: input → rule → feedback. Describe ONE core mechanic per doc.
4. **Economy** (if applicable) — costs, rewards and progression in a table; no invented numbers — every value justified.
5. **Verification** — the simulated playtest criteria (scripts/playtest-simulate.sh): what must happen for the feature to be ACCEPTED.

## Output

- `design-docs/YYYY-MM-DD-<slug>.md` (or HTML via feature-report if the team uses the visual base).
- Update the feature to `in_progress` (one at a time) and record the design decision in the doc — never only in the conversation.