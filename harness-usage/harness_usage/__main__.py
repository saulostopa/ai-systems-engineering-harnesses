"""CLI: python -m harness_usage report|ledgers.

    python -m harness_usage report                      # current month, all registered ledgers
    python -m harness_usage report ~/repo --all --by model --format csv
    python -m harness_usage report --format html --output usage.html
    python -m harness_usage ledgers                     # where the ledgers live
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ledger import registered_ledgers
from .report import DEFAULT_GROUPS, GROUP_KEYS, RENDERERS, build, ledger_dirs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness_usage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_report = sub.add_parser("report", help="summarize token use and cost")
    p_report.add_argument("paths", nargs="*", help="repository roots or ledger directories (default: registered ledgers)")
    period = p_report.add_mutually_exclusive_group()
    period.add_argument("--month", help="YYYY-MM (default: current month)")
    period.add_argument("--all", action="store_true", help="every month")
    p_report.add_argument("--by", action="append", choices=sorted(GROUP_KEYS), help="grouping; repeatable")
    p_report.add_argument("--format", choices=sorted(RENDERERS), default="table")
    p_report.add_argument("--output", help="write to a file instead of stdout")
    sub.add_parser("ledgers", help="list the registered ledger directories")
    args = parser.parse_args(argv)

    if args.cmd == "ledgers":
        for path in registered_ledgers():
            print(path)
        return 0

    dirs = ledger_dirs(args.paths) if args.paths else registered_ledgers()
    if not dirs:
        print("no ledgers found; pass a repository root or record a call first", file=sys.stderr)
        return 1
    month = None if args.all else (args.month or f"{datetime.now(timezone.utc):%Y-%m}")
    report = build(dirs, month, args.by or DEFAULT_GROUPS)
    text = RENDERERS[args.format](report)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
