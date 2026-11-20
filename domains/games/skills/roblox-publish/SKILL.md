---
name: roblox-publish
description: Prepares and validates the publication of a game feature on Roblox — Luau/Rojo build, monetization setup and platform checklist. Use when the user asks to publish, upload a build or validate a publication on Roblox.
---

# Validated Roblox publication

Publishing is not "upload and hope": it means going through platform validation
with a verifiable checklist (Lesson 10: E2E changes the outcome — here the
"E2E" is the publish pipeline).

## Gather

- The feature and its state in `feature_list.json`.
- The design doc (skills/game-design) — if it does not exist, do not publish: the feature has no specification.
- Configs: `default.project.json` (Rojo), monetization (Developer Product / Game Pass IDs), permissions.

## Write / Validate — the mechanical checklist

1. **Luau build** — the project compiles without errors (Rojo build / `rojo build`); exit 0 mandatory.
2. **Assets** — all referenced meshes/textures exist; no broken asset (valid IDs).
3. **Monetization** — each referenced Developer Product/Game Pass exists on the experience page; prices filled in; nothing pointing to a nonexistent product.
4. **Security** — no sensitive data in the code; scripts with least privilege.
5. **Simulated playtest** — scripts/playtest-simulate.sh passed (the feature does not ship without a playtest).

## Output

- `relatorios/YYYY-MM-DD-<slug>-publish.md`: checklist with STATUS per item (PASS/FAIL + evidence — command output).
- Any FAIL blocks the publication — record it in the harness log (log-event.sh) and in the feature.
- Only then: publish and record the published version in the feature (`passing`).