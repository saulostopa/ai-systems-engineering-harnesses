"""Hard Harness — executable orchestration core.

Typed workflow contracts. stdlib dataclasses: no dependencies.
Golden rule (ADK 2, L2b): predictable work = deterministic function;
reasoning = agent; clear rule = explicit router.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    PASSED = "passed"
    FAILED = "failed"
    CLOSED = "closed"


class NodeKind(str, Enum):
    DETERMINISTIC = "deterministic"  # pure function — 0 LLM
    AGENT = "agent"                  # reasoning — 1+ LLM


@dataclass
class WorkflowState:
    """Workflow state — ONLY the runner transitions it. Agents receive
    this object as a view and NEVER change it (contract verified by test)."""

    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_node: str = ""
    data: dict[str, Any] = field(default_factory=dict)  # payload persisted between nodes
    retries: dict[str, int] = field(default_factory=dict)  # node_id -> attempts
    llm_calls: int = 0
    depth: int = 0
    error: str = ""
    updated_at: str = field(default_factory=now_iso)

    def snapshot(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "current_node": self.current_node,
            "data": self.data,
            "retries": self.retries,
            "llm_calls": self.llm_calls,
            "depth": self.depth,
            "error": self.error,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WorkflowState":
        return cls(
            workflow_id=raw["workflow_id"],
            status=WorkflowStatus(raw["status"]),
            current_node=raw.get("current_node", ""),
            data=raw.get("data", {}),
            retries=raw.get("retries", {}),
            llm_calls=raw.get("llm_calls", 0),
            depth=raw.get("depth", 0),
            error=raw.get("error", ""),
            updated_at=raw.get("updated_at", now_iso()),
        )


@dataclass(frozen=True)
class NodeInput:
    """Node input — immutable view of the state + node-specific payload."""

    node_id: str
    state: WorkflowState
    payload: dict[str, Any] = field(default_factory=dict)
    context: list[dict[str, Any]] = field(default_factory=list)  # typed context (RAG)


@dataclass
class NodeOutput:
    """Node output — a PROPOSAL. Never changes the state on its own.

    - ok: the node completed successfully.
    - payload: produced data (attached to the state by the runner, if ok).
    - artifacts: references to generated artifacts.
    - proposed_next: suggested next node — the runner DECIDES after gates.
    - review/evidence/gate: optional typed results.
    """

    node_id: str
    ok: bool = True
    payload: dict[str, Any] = field(default_factory=dict)
    artifacts: list["ArtifactRef"] = field(default_factory=list)
    proposed_next: str = ""
    error: str = ""
    gate: "GateResult | None" = None
    review: "ReviewResult | None" = None
    evidence: list["Evidence"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "ok": self.ok,
            "payload": self.payload,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "proposed_next": self.proposed_next,
            "error": self.error,
            "gate": self.gate.to_dict() if self.gate else None,
            "review": self.review.to_dict() if self.review else None,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to an artifact produced by the workflow."""

    path: str
    kind: str  # report | quiz | diagram | patch | screenshot | log
    sha256: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kind": self.kind, "sha256": self.sha256, "meta": self.meta}

    @classmethod
    def of(cls, path: str, kind: str, meta: dict[str, Any] | None = None) -> "ArtifactRef":
        digest = ""
        try:
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()[:16]
        except OSError:
            pass
        return cls(path=path, kind=kind, sha256=digest, meta=meta or {})


@dataclass
class Evidence:
    """Evidence: command, expected vs. actual, status — the harness currency (Lesson 09)."""

    kind: str  # build | test | e2e | lint | security | manual | agent
    command: str
    expected: str
    actual: str
    passed: bool
    artifact: ArtifactRef | None = None
    node_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "command": self.command,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "node_id": self.node_id,
        }


@dataclass
class GateResult:
    """Result of a deterministic gate — explicit and auditable failures."""

    node_id: str
    passed: bool
    failures: list[dict[str, str]] = field(default_factory=list)  # {check, expected, actual}
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "passed": self.passed,
            "failures": self.failures,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class ReviewResult:
    """Review verdict — proposed by the agent, applied by the runner."""

    verdict: str  # approved | changes_requested | rejected
    findings: list[dict[str, str]] = field(default_factory=list)  # {severity, location, issue}
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "findings": self.findings, "summary": self.summary}