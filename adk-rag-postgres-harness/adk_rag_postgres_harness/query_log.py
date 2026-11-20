"""Record real questions locally; a failure here must never break a search."""

from __future__ import annotations

import os
import time
from typing import Iterable

from .memory import find_credential
from .store import PostgresStore

MASKED_QUERY = "[masked: it looks like it contains a credential]"


def log_query(
    store: PostgresStore,
    project: str,
    entry: str,
    tool: str,
    query: str,
    started: float,
    paths: Iterable[str] = (),
    collection: str | None = None,
    strategy: str | None = None,
) -> None:
    if os.environ.get("HARNESS_QUERY_LOG", "on").lower() in ("off", "0", "false", "no"):
        return
    latency_ms = round((time.perf_counter() - started) * 1000)
    text = MASKED_QUERY if find_credential(query) else query.replace("\x00", "")
    try:
        store.add_query(project, entry, tool, text, collection, strategy, list(paths), latency_ms)
    except Exception:  # noqa: BLE001, such as a database without this table yet
        return
