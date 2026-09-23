"""FileStateStore — initial persistence WITHOUT a database.

.harness/
├── state.json       # WorkflowState snapshot (atomic write: tmp+rename)
├── events.jsonl     # audit trail (append-only)
├── artifacts/       # artifacts produced by the nodes
└── locks/           # file locks (O_EXCL) for mutual exclusion
"""

from __future__ import annotations

import json
import os

from hard_harness.core.events import Event
from hard_harness.core.schemas import WorkflowState

from .base import StateStore


class FileStateStore(StateStore):
    def __init__(self, root: str) -> None:
        self.root = root
        self.harness_dir = os.path.join(root, ".harness")
        self.state_path = os.path.join(self.harness_dir, "state.json")
        self.events_path = os.path.join(self.harness_dir, "events.jsonl")
        self.artifacts_dir = os.path.join(self.harness_dir, "artifacts")
        self.locks_dir = os.path.join(self.harness_dir, "locks")
        os.makedirs(self.artifacts_dir, exist_ok=True)
        os.makedirs(self.locks_dir, exist_ok=True)

    # ── State ───────────────────────────────────────────────────

    def read_state(self) -> WorkflowState | None:
        if not os.path.exists(self.state_path):
            return None
        with open(self.state_path, "r", encoding="utf-8") as fh:
            return WorkflowState.from_dict(json.load(fh))

    def write_state(self, state: WorkflowState) -> None:
        os.makedirs(self.harness_dir, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.snapshot(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)  # atomic

    # ── Events ──────────────────────────────────────────────────

    def append_event(self, event: Event) -> None:
        os.makedirs(self.harness_dir, exist_ok=True)
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def list_events(self) -> list[Event]:
        if not os.path.exists(self.events_path):
            return []
        events: list[Event] = []
        with open(self.events_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(Event(**json.loads(line)))
        return events

    # ── Artifacts ───────────────────────────────────────────────

    def save_artifact(self, name: str, content: str | bytes) -> str:
        path = os.path.join(self.artifacts_dir, name)
        mode = "wb" if isinstance(content, bytes) else "w"
        kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as fh:
            fh.write(content)
        return path

    # ── Locks (simple mutual exclusion) ─────────────────────────

    def acquire_lock(self, name: str) -> bool:
        """Non-blocking lock via O_EXCL. Returns True if acquired."""
        path = os.path.join(self.locks_dir, name + ".lock")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def release_lock(self, name: str) -> None:
        path = os.path.join(self.locks_dir, name + ".lock")
        try:
            os.remove(path)
        except FileNotFoundError:
            pass