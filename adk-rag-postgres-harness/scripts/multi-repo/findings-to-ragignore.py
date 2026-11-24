"""Keep every file with a gitleaks finding out of the index.

Appends `/path` lines to the `.ragignore` at each worktree's root. The file is untracked in the
worktree, so the repository itself does not change. Review the reports first: a real credential
must also be rotated by the repository's owners, and removing it from the index does not do that.

usage: python3 findings-to-ragignore.py WORKTREES_DIR REPORTS_DIR
"""

import csv
import json
import sys
from pathlib import Path

worktrees, reports = Path(sys.argv[1]), Path(sys.argv[2])
with open(worktrees / "manifest.tsv", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))

for row in rows:
    report = reports / f"{row['project']}.json"
    if not report.exists():
        continue
    root = Path(row["worktree"]).resolve()
    paths = set()
    for finding in json.loads(report.read_text() or "[]"):
        path = Path(finding["File"])
        path = (path if path.is_absolute() else Path.cwd() / path).resolve()
        if path.is_relative_to(root):
            paths.add(path.relative_to(root).as_posix())
    if not paths:
        continue
    ignore = root / ".ragignore"
    present = set(ignore.read_text().splitlines()) if ignore.exists() else set()
    new = sorted(f"/{path}" for path in paths if f"/{path}" not in present)
    with open(ignore, "a") as handle:
        handle.write("".join(f"{line}\n" for line in new))
    print(f"{row['project']}: {len(new)} files added to {ignore}")
