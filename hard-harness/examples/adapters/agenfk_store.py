"""AgEnFKStore — EXAMPLE adapter, not part of the harness.

The hard harness ships one store: `FileStateStore`, which keeps every byte of
state inside the repository. This file exists to show that `StateStore` is a
real interface — you can put an external management system behind it without
the runner knowing. AgEnFK is the system we had at hand; the same shape works
for Jira, GitHub Projects or anything with a CLI.

Nothing in `hard_harness/` imports this. To use it, import it from here and
pass it to the runner yourself. The CLI is resolved from the `AGENFK_CLI`
environment variable, then from PATH — never from a hardcoded location.

When the external system is the source of truth for item progress and
evidence, the runner does NOT duplicate it:
  - read_state: reads the item/status from AgEnFK (when the workflow maps an item);
  - append_event: records events as auditable comments;
  - write_state: records status progress via `agenfk verify` (evidence) —
    the runner remains the flow authority; AgEnFK is the management system
    behind it (consistent with EPIC B2).

If AgEnFK is unavailable, we do NOT work around it: the store raises an
explicit error (the caller decides between a FileStateStore fallback or stopping).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from hard_harness.core.events import Event
from hard_harness.core.schemas import WorkflowState, WorkflowStatus
from hard_harness.stores import StateStore


class AgEnFKUnavailableError(RuntimeError):
    pass


def resolve_cli() -> str:
    """AGENFK_CLI, then PATH. No absolute path belongs in version control."""
    explicit = os.environ.get("AGENFK_CLI")
    if explicit:
        return explicit
    found = shutil.which("agenfk")
    if not found:
        raise AgEnFKUnavailableError(
            "agenfk CLI not found — set AGENFK_CLI or put it on PATH"
        )
    return found


class AgEnFKStore(StateStore):
    def __init__(self, item_id: str, cli: str | None = None, project_root: str | None = None) -> None:
        self.item_id = item_id
        self.cli = cli or resolve_cli()
        self.project_root = project_root or os.getcwd()

    # ── CLI helpers ──────────────────────────────────────────────

    def _run(self, *args: str) -> str:
        cmd = [self.cli, *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=self.project_root)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AgEnFKUnavailableError(f"AgEnFK unavailable: {exc}") from exc
        if proc.returncode != 0:
            raise AgEnFKUnavailableError(f"AgEnFK error ({proc.returncode}): {proc.stderr[-500:]}")
        return proc.stdout

    def check_available(self) -> bool:
        try:
            self._run("get", self.item_id, "--json")
            return True
        except AgEnFKUnavailableError:
            return False

    # ── State ───────────────────────────────────────────────────

    def read_state(self) -> WorkflowState | None:
        """Reads the item from AgEnFK and projects it into a WorkflowState (if any)."""
        out = self._run("get", self.item_id, "--json")
        try:
            item = json.loads(out)
        except json.JSONDecodeError as exc:
            raise AgEnFKUnavailableError(f"invalid response: {exc}") from exc
        status = str(item.get("status", "TODO")).upper()
        wf_status = {
            "TODO": WorkflowStatus.PENDING,
            "IN_PROGRESS": WorkflowStatus.RUNNING,
            "REVIEW": WorkflowStatus.RUNNING,
            "TEST": WorkflowStatus.RUNNING,
            "DONE": WorkflowStatus.PASSED,
            "BLOCKED": WorkflowStatus.BLOCKED,
        }.get(status, WorkflowStatus.PENDING)
        return WorkflowState(
            workflow_id=f"agenfk_{self.item_id[:8]}",
            status=wf_status,
            data={"item_id": self.item_id, "title": item.get("title", ""), "agenfk_status": status},
        )

    def write_state(self, state: WorkflowState) -> None:
        """Records progress in AgEnFK (evidence via verify). NEVER duplicates the
        runner's state as a second source of truth — AgEnFK manages it."""
        if state.status is WorkflowStatus.PASSED:
            self._run("verify", self.item_id, "--evidence", "workflow completed by the hard harness")
        elif state.status is WorkflowStatus.BLOCKED:
            self._run("comment", self.item_id, f"[hard-harness] blocked: {state.error[:200]}")

    # ── Events ──────────────────────────────────────────────────

    def append_event(self, event: Event) -> None:
        """Mirrors critical events as comments (auditability)."""
        if event.kind in ("gate", "error", "close"):
            self._run("comment", self.item_id, f"[hard-harness:{event.kind}] {event.message[:300]}")

    def list_events(self) -> list[Event]:
        raise NotImplementedError("AgEnFK events are read via telemetry/comments")

    def record_evidence(self, command: str, output: str, status: str) -> None:
        """Records test/evidence in AgEnFK (existing mechanism)."""
        self._run("log-test", self.item_id, "--command", command, "--output", output[:500], "--status", status)