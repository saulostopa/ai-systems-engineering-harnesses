"""Deterministic gates — executable verification (Lesson 09/10).

A gate is a pure function that produces a GateResult with EXPLICIT failures
({check, expected, actual}) and attached evidence. It never blocks in
silence: every decision becomes a gate Event.

Real gates run commands; tests inject fake functions.
"""

from __future__ import annotations

import subprocess
from typing import Callable

from .schemas import Evidence, GateResult

GateFn = Callable[[dict[str, object]], GateResult]


def gate_node_output(node_id: str, gate_fn: GateFn) -> Callable[[object], "NodeOutput"]:
    """Turns a gate into a graph NODE: GateResult becomes NodeOutput.

    Runner contract: nodes return NodeOutput; the gate travels attached
    (output.gate) and the runner blocks the transition when it fails.
    """

    def node(ninput) -> "NodeOutput":
        from .schemas import NodeOutput

        gr = gate_fn(ninput.payload)
        return NodeOutput(
            node_id=node_id,
            ok=gr.passed,
            gate=gr,
            payload={"gate": gr.to_dict()},
            error="gate failed" if not gr.passed else "",
        )

    return node


def run_command(command: str, timeout_s: int = 120) -> tuple[int, str]:
    """Runs a command and returns (exit_code, output). Failure becomes evidence."""
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout_s)
        return proc.returncode, (proc.stdout or "")[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout_s}s"
    except OSError as exc:
        return 127, str(exc)


def gate_from_command(node_id: str, command: str, kind: str, timeout_s: int = 120) -> GateFn:
    """Creates a gate that runs a real command and requires exit 0."""

    def gate(payload: dict[str, object]) -> GateResult:
        code, out = run_command(command, timeout_s)
        ev = Evidence(kind=kind, command=command, expected="exit 0", actual=f"exit {code}", passed=code == 0, node_id=node_id)
        if code == 0:
            return GateResult(node_id=node_id, passed=True, evidence=[ev])
        return GateResult(
            node_id=node_id,
            passed=False,
            failures=[{"check": f"{kind} ({command})", "expected": "exit 0", "actual": f"exit {code}"}],
            evidence=[ev],
        )

    return gate


def combined_gate(node_id: str, gates: list[GateFn]) -> GateFn:
    """Joins multiple gates into one: ALL must pass; failures are aggregated."""

    def gate(payload: dict[str, object]) -> GateResult:
        failures: list[dict[str, str]] = []
        evidence: list[Evidence] = []
        for g in gates:
            result = g(payload)
            evidence.extend(result.evidence)
            failures.extend(result.failures)
        return GateResult(node_id=node_id, passed=not failures, failures=failures, evidence=evidence)

    return gate


def gate_scope_valid(payload: dict[str, object]) -> GateResult:
    """Scope gate (Lesson 07): the change declares the what, the why and the out-of-scope."""
    failures: list[dict[str, str]] = []
    for key in ("what", "why"):
        value = (payload.get(key) or "").strip()
        if not value:
            failures.append({"check": f"scope.{key}", "expected": "filled", "actual": "empty"})
    if "out_of_scope" not in payload:
        failures.append({"check": "scope.out_of_scope", "expected": "declared", "actual": "missing"})
    ev = Evidence(
        kind="manual",
        command="gate_scope_valid(payload)",
        expected="what+why+out_of_scope",
        actual="ok" if not failures else str(failures),
        passed=not failures,
        node_id="gate.scope",
    )
    return GateResult(node_id="gate.scope", passed=not failures, failures=failures, evidence=[ev])