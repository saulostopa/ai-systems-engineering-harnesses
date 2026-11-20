"""Integration C example — App Harness with a QA fan-out.

The same hard-harness core orchestrates the FOUR App Harness checks in
parallel (unit tests, E2E, accessibility, exploratory navigation) and the
join consolidates before the router decides.

Run:
    cd hard-harness
    PYTHONPATH=. python3 examples/app_harness/workflow.py
"""

from __future__ import annotations

import tempfile

from hard_harness.core import Limits, Node, NodeInput, NodeKind, NodeOutput, Runner, WorkflowGraph
from hard_harness.core.gates import gate_from_command, gate_node_output
from hard_harness.stores import FileStateStore


def start(ninput: NodeInput) -> NodeOutput:
    return NodeOutput(node_id="start", ok=True, payload={"app": "pilot", "feature": "busca"})


def navigation(ninput: NodeInput) -> NodeOutput:
    """Simulated exploratory navigation (C2) — verdict per criterion."""
    return NodeOutput(node_id="navigation", ok=True, payload={"verdict": "ACCEPTED", "screenshots": 4})


def join_qa(ninput: NodeInput) -> NodeOutput:
    fanout = ninput.state.data.get("fanout_start", {})
    results = {}
    for key, value in fanout.items():
        if "error" in value:
            results[key] = f"FAIL: {value['error']}"
        elif "gate" in value:
            gate = value["gate"]
            results[key] = "PASS" if gate.get("passed") else f"FAIL: {gate.get('failures')}"
        else:
            results[key] = f"PASS ({value.get('verdict', 'ok')})"
    all_ok = all(r == "PASS" or r.startswith("PASS") for r in results.values())
    return NodeOutput(node_id="join_qa", ok=True, payload={"checks": results, "all_ok": all_ok})


def approve(ninput: NodeInput) -> NodeOutput:
    return NodeOutput(node_id="approve", ok=True, payload={"approved": True})


def fix(ninput: NodeInput) -> NodeOutput:
    return NodeOutput(node_id="fix", ok=True, payload={"fixed": True})


def build_graph() -> WorkflowGraph:
    g = WorkflowGraph(name="app_harness")
    g.add_node(Node("start", NodeKind.DETERMINISTIC, start))
    g.add_node(Node("unit_tests", NodeKind.DETERMINISTIC, gate_node_output("unit_tests", gate_from_command("unit_tests", "echo 'unit ok'", "test"))))
    g.add_node(Node("e2e", NodeKind.DETERMINISTIC, gate_node_output("e2e", gate_from_command("e2e", "echo 'e2e ok'", "e2e"))))
    g.add_node(Node("a11y", NodeKind.DETERMINISTIC, gate_node_output("a11y", gate_from_command("a11y", "echo 'a11y ok'", "lint"))))
    g.add_node(Node("navigation", NodeKind.DETERMINISTIC, navigation))
    g.add_node(Node("join_qa", NodeKind.DETERMINISTIC, join_qa))
    g.add_node(Node("approve", NodeKind.DETERMINISTIC, approve))
    g.add_node(Node("fix", NodeKind.DETERMINISTIC, fix))

    g.set_start("start")
    g.fan_out("start", ["unit_tests", "e2e", "a11y", "navigation"])
    g.add_node(Node("router", NodeKind.DETERMINISTIC, lambda n: NodeOutput(node_id="router", ok=True)))

    def route(state_data: dict) -> str:
        return "passed" if state_data.get("join_qa", {}).get("all_ok") else "failed"

    g.join("join_qa", ["unit_tests", "e2e", "a11y", "navigation"], "router")
    g.router("router", route, {"passed": "approve", "failed": "fix"}, default="fix")
    return g


def run() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        store = FileStateStore(tmp)
        runner = Runner(build_graph(), store=store, limits=Limits(max_depth=16))
        runner.bus.subscribe(lambda ev: store.append_event(ev))
        state = runner.run()
        events = store.list_events()
        return {"status": state.status.value, "checks": state.data.get("join_qa", {}).get("checks", {}), "events": len(events)}


if __name__ == "__main__":
    result = run()
    print(f"== App Harness: status {result['status']}")
    for check, value in result["checks"].items():
        print(f"   {check}: {value}")
    print(f"== events: {result['events']}")