# Definition of Done — Games domain

A game feature is done when:

1. **Design doc exists** — `design-docs/YYYY-MM-DD-<slug>.md` with persona, storytelling, mechanics, economy (if any) and verification criteria.
2. **Simulated playtest passed** — `scripts/playtest-simulate.sh <doc>` ends with `PLAYTEST ACCEPTED` (0 failures).
3. **Build validates** — Rojo/Luau compiles (exit 0), assets intact.
4. **Publish validated** (when applicable) — `roblox-publish` skill checklist 100% PASS with evidence.
5. **Evidence recorded** — commands + outputs attached; feature in `passing`.

## What is NOT "done" in this domain
- Design doc without persona or acceptance criteria.
- Feature published without a simulated playtest.
- "I assumed the platform accepts it" — without the checklist executed.