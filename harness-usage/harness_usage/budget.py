"""Monthly budget warnings across every registered ledger (warn only, never block)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_BUDGET_USD = 25.0
THRESHOLDS = (1.0, 0.8)

_state: dict[str, object] = {"month": None, "total": 0.0}


def budget_usd() -> float:
    """HARNESS_BUDGET_USD, default US$ 25 per month; 0 disables the warning."""

    try:
        return float(os.getenv("HARNESS_BUDGET_USD", DEFAULT_BUDGET_USD))
    except ValueError:
        return DEFAULT_BUDGET_USD


def month_total(directories: Iterable[Path], month: str) -> float:
    total = 0.0
    for directory in directories:
        path = Path(directory) / f"{month}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    total += float(json.loads(line).get("cost_usd") or 0.0)
                except (ValueError, AttributeError):
                    continue
    return total


def check_budget(
    cost: float,
    now: datetime,
    ledgers: Callable[[], list[Path]],
    warn: Callable[[str, str], None],
) -> float:
    """Track this month's spend and warn once per threshold; returns the total."""

    budget = budget_usd()
    month = f"{now:%Y-%m}"
    if _state["month"] != month:
        # First call of the month in this process: the line just written is
        # already in the files, so the total is read instead of incremented.
        _state["month"] = month
        _state["total"] = month_total(ledgers(), month)
    else:
        _state["total"] = float(_state["total"]) + cost
    total = float(_state["total"])
    if budget > 0:
        for threshold in THRESHOLDS:
            if total >= budget * threshold:
                warn(
                    f"budget:{month}:{threshold}",
                    f"US$ {total:.2f} spent in {month}, {total / budget:.0%} of the "
                    f"US$ {budget:.2f} budget (HARNESS_BUDGET_USD)",
                )
                break
    return total


def reset() -> None:
    """Forget the cached month total (tests)."""

    _state["month"] = None
    _state["total"] = 0.0
