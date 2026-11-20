# enterprise-harness — the multi-team orchestrator

The enterprise harness in two layers. Layer A is this package, installed **once
per machine** in a root folder above your project folders. Layer B is what it
puts inside each repository: the skeleton, the policies, the hooks, the
execution plans — and nothing else.

```
~/wm/                          ← the root that holds your projects
├── wm-harness/                ← A · orchestrator (this package, installed)
│   ├── bin/wm-harness
│   ├── engine/
│   ├── flows/
│   ├── templates/
│   └── harness-basic/         vendored layers 1-2 payload
├── catalogo/                  ← B · an adopted repository
│   ├── .harness/config.yaml
│   ├── docs/exec-plans/{active,done}
│   ├── feature_list.json · progress.md · policies/
│   └── scripts/ · .githooks/
└── fipe/                      ← B · another one
```

## The rule

> **The orchestrator owns the *how*. The repository owns the *what* and the
> *what happened*.**

And the test that settles any doubt about where a piece belongs:

> **If deleting the orchestrator would make a project lose information about
> itself, the piece is in the wrong layer.**

This package keeps no database, no registry and no state file. It finds adopted
repositories by scanning for `.harness/config.yaml` and recomputes every number
from the repositories on each run. `tests/test_enterprise_harness.sh` deletes
the whole orchestrator and asserts the projects still validate.

## Install

```sh
./install.sh                              # → $HOME/wm-harness, scans $HOME
./install.sh --prefix ~/wm/wm-harness     # → scans ~/wm  (recommended)
./install.sh --prefix ~/wm/wm-harness --projects ~/wm
```

Then, if `~/.local/bin` is not on your PATH:

```sh
export PATH="$HOME/wm/wm-harness/bin:$PATH"
```

## Use

```sh
wm-harness doctor                       # verify the installation
wm-harness adopt ~/wm/catalogo          # install layer B into a repository
wm-harness adopt ~/wm/fipe --flow hotfix
wm-harness list                         # adopted repositories found
wm-harness status                       # what each project is working on
wm-harness check                        # run every project's own gates
wm-harness report                       # cross-project aggregation
wm-harness flows                        # available flow definitions
```

Inside an adopted repository:

```sh
wm-harness plan new feature/OEM-123 "Email validation"   # seeded from the repo's flow
wm-harness plan done feature/OEM-123                     # archives, evidence required
```

## Flows

A flow is a file in `flows/`. Its `steps` and `exit_criteria` are copied into
every plan created under it — which is what makes a flow a mechanism instead of
a document somebody is supposed to remember.

| Flow | For |
|---|---|
| `feature-default` | the ordinary path for a feature |
| `hotfix` | a production incident: shorter, not laxer |

Adding one is adding a file. `wm-harness check` fails a repository whose
declared flow no longer exists, so retiring a flow can never be silent.

## What it does not do

- **No UI and no server.** Aggregation is a CLI report, computed live.
- **No cross-machine sync.** Two developers see the same numbers because they
  read the same repositories, not because a service reconciles them.
- **No vendor lock.** `.harness/config.yaml` is thirteen lines. Walking away
  costs deleting a directory.

## Verify

```sh
./scripts/validate-enterprise-harness.sh   # health check of this package
./tests/test_enterprise_harness.sh         # 19 end-to-end tests
```
