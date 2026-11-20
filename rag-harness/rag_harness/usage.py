"""Optional link to the shared harness-usage ledger; a no-op when it is absent.

rag-harness stays standalone: the ledger is used only when the sibling
`harness-usage` package (or an installed `harness_usage`) is available.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any


def _load():
    try:
        import harness_usage

        return harness_usage
    except ImportError:
        pass
    sibling = Path(__file__).resolve().parents[2] / "harness-usage"
    if sibling.is_dir():
        sys.path.insert(0, str(sibling))
        try:
            import harness_usage

            return harness_usage
        except ImportError:
            return None
    return None


_usage = _load()


def record(**fields: Any) -> None:
    if _usage is not None:
        _usage.record(harness="rag-harness", **fields)


def usage_context(**values: Any):
    return _usage.usage_context(**values) if _usage is not None else contextlib.nullcontext()
