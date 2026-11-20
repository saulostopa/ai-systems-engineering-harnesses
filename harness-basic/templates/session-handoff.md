# Session Handoff

> Note for the next session (Lesson 05). Mandatory sections in the header.
> Whoever reads this must be able to resume WITHOUT re-reading the previous conversation.

## Date of last work
YYYY-MM-DD

## Previous session/agent
(tool/agent name)

## What is VERIFIED
- [ ] feature/OEM-123: implementation done, `npm test` passed (3 tests, no reduction)
- [ ] feature/OEM-123: build OK

## What is BROKEN / PENDING
- [ ] feature/OEM-123: diff review still needed before the PR
- [ ] bugfix/AC-455: not started

## Next action (the single best one)
1. Review the feature/OEM-123 diff (`git diff main...HEAD`) and open the PR.

## How to verify resumption
- `git status` clean? (expected: yes)
- `npm test` green? (expected: yes — re-run before trusting)

## Risks and pending decisions
- None (or record: decision X depends on a response from team Y)