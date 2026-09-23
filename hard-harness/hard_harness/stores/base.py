"""Base — StateStore interface (Protocol) and lock helpers.

Minimum persistence contract. New implementations (SQLite, an external tracker,
Redis) implement the same Protocol — the runner does not know where the
state lives.
"""

from __future__ import annotations

from typing import Protocol

from hard_harness.core.events import Event
from hard_harness.core.schemas import WorkflowState


class StateStore(Protocol):
    def read_state(self) -> WorkflowState | None: ...
    def write_state(self, state: WorkflowState) -> None: ...
    def append_event(self, event: Event) -> None: ...
    def list_events(self) -> list[Event]: ...