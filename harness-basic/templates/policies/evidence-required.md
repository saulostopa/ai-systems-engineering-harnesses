# Required evidence

> Lessons 09 and 11. Evidence is what turns "claiming victory" into "proving
> victory". Never state "done" without proof.

## What counts as evidence

| Claim | Minimum evidence |
|---|---|
| "It is built" | `build` executed, exit 0, output attached |
| "It is tested" | Test names + count + green output |
| "It is in scope" | `git diff` showing only what was declared |
| "It is integrated" | E2E/gates/hooks executed and passing |
| "It is published" | URL/artifact generated and verified |

## Evidence format

```
COMMAND: <executed command>
EXPECTED: <what should have happened>
ACTUAL: <what happened>
STATUS: PASSED | FAILED
```

## Golden rule
- Git is the truth: re-run and check — never trust narration.
- A green suite with fewer tests than at the start is regression, not a pass.