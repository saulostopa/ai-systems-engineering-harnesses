"""Required example — full hard harness graph.

START
  → boot
  → load scope
  → planner_agent
  → validate plan (gate)
  → coder_agent
  → fan-out: [build, tests, E2E, lint/security]
  → join results
  → deterministic router
      - failed: correction_agent (loop with limit)
      - passed: reviewer_agent
  → evidence
  → close

Rules demonstrated:
  - functions for predictable work (boot, scope, gates, join, close);
  - agents only for reasoning (planner, coder, reviewer, correction);
  - router with a MANDATORY default;
  - the agent proposes the next node; the runner decides;
  - FileStateStore persistence + resume.
"""

from __future__ import annotations

import os

from hard_harness.adapters.adk2 import to_adk_edges
from hard_harness.agents import CoderAgent, EvidenceAgent, PlannerAgent, ReviewerAgent
from hard_harness.core import Limits, Node, NodeInput, NodeKind, NodeOutput, Runner, WorkflowGraph
from hard_harness.core.gates import gate_scope_valid
from hard_harness.stores import FileStateStore


def boot(ninput: NodeInput) -> NodeOutput:
    """Deterministic: initializes workflow data."""
    return NodeOutput(node_id="boot", ok=True, payload={"booted_at": True, "scope": ninput.payload.get("scope", {})})


def load_scope(ninput: NodeInput) -> NodeOutput:
    """Deterministic: loads the declared scope."""
    scope = ninput.payload.get("scope", {})
    return NodeOutput(node_id="load_scope", ok=True, payload={"scope": scope})


def validate_plan_gate(ninput: NodeInput) -> NodeOutput:
    """Deterministic gate: the planner's plan must exist and be non-empty."""
    from hard_harness.core.schemas import GateResult

    plan = (ninput.state.data.get("planner_agent") or {}).get("plan_steps", [])
    if plan:
        return NodeOutput(node_id="validate_plan", ok=True, payload={"plan_ok": True},
                          gate=GateResult(node_id="validate_plan", passed=True))
    return NodeOutput(
        node_id="validate_plan",
        ok=False,
        error="empty planner plan",
        gate=GateResult(node_id="validate_plan", passed=False,
                        failures=[{"check": "plan_steps", "expected": ">=1 step", "actual": "0"}]),
    )


from hard_harness.core.gates import gate_from_command, gate_node_output

build = gate_node_output("build", gate_from_command("build", "echo 'build ok'", "build"))
tests = gate_node_output("tests", gate_from_command("tests", "echo 'tests ok'", "test"))
e2e = gate_node_output("e2e", gate_from_command("e2e", "echo 'e2e ok'", "e2e"))
lint = gate_node_output("lint", gate_from_command("lint", "echo 'lint ok'", "lint"))


def join_results(ninput: NodeInput) -> NodeOutput:
    """Deterministic: consolidates the fan-out; failures explicit in the payload."""
    fanout = ninput.state.data.get("fanout_coder_agent", ninput.payload)
    checks = {k: ("ok" if v.get("error") is None else f"FAIL: {v['error']}") for k, v in fanout.items()}
    all_ok = all(v == "ok" for v in checks.values())
    return NodeOutput(node_id="join", ok=True, payload={"checks": checks, "all_ok": all_ok})


def route_by_checks(state_data: dict) -> str:
    """Deterministic router (if-statement, 0 LLM — ADK lesson L2b).
    Reads the join's consolidated payload."""
    join_payload = state_data.get("join", {})
    return "passed" if join_payload.get("all_ok") else "failed"


def route_node(ninput: NodeInput) -> NodeOutput:
    """Deterministic node that exists only to host the router."""
    return NodeOutput(node_id="router", ok=True, payload={"routed": True})


def close(ninput: NodeInput) -> NodeOutput:
    return NodeOutput(node_id="close", ok=True, payload={"closed": True})


def build_graph(agent_impls: dict[str, object] | None = None,
                providers: dict[str, object] | None = None) -> WorkflowGraph:
    """Builds the graph. agent_impls: whole nodes; providers: LLM providers per agent."""
    planner = PlannerAgent(provider=(providers or {}).get("planner"))
    coder = CoderAgent(provider=(providers or {}).get("coder"))
    reviewer = ReviewerAgent(provider=(providers or {}).get("reviewer"))

    def correction_agent(ninput: NodeInput) -> NodeOutput:
        return NodeOutput(node_id="correction_agent", ok=True, payload={"corrected": True}, proposed_next="coder_agent")

    g = WorkflowGraph(name="basic_workflow")
    g.add_node(Node("boot", NodeKind.DETERMINISTIC, boot))
    g.add_node(Node("load_scope", NodeKind.DETERMINISTIC, load_scope))
    g.add_node(Node("planner_agent", NodeKind.AGENT, planner.run))
    g.add_node(Node("validate_plan", NodeKind.DETERMINISTIC, validate_plan_gate))
    g.add_node(Node("coder_agent", NodeKind.AGENT, coder.run))
    g.add_node(Node("build", NodeKind.DETERMINISTIC, build))
    g.add_node(Node("tests", NodeKind.DETERMINISTIC, tests))
    g.add_node(Node("e2e", NodeKind.DETERMINISTIC, e2e))
    g.add_node(Node("lint", NodeKind.DETERMINISTIC, lint))
    g.add_node(Node("join", NodeKind.DETERMINISTIC, join_results))
    g.add_node(Node("router", NodeKind.DETERMINISTIC, route_node))
    g.add_node(Node("reviewer_agent", NodeKind.AGENT, reviewer.run))
    g.add_node(Node("correction_agent", NodeKind.AGENT, correction_agent))
    g.add_node(Node("evidence", NodeKind.AGENT, EvidenceAgent().run))
    g.add_node(Node("close", NodeKind.DETERMINISTIC, close))

    g.set_start("boot")
    g.edge("boot", "load_scope")
    g.edge("load_scope", "planner_agent")
    g.edge("planner_agent", "validate_plan")
    g.edge("validate_plan", "coder_agent")
    g.fan_out("coder_agent", ["build", "tests", "e2e", "lint"])
    g.join("join", ["build", "tests", "e2e", "lint"], "router")
    g.router("router", route_by_checks, {"passed": "reviewer_agent", "failed": "correction_agent"}, default="correction_agent")
    g.edge("reviewer_agent", "evidence")
    g.edge("correction_agent", "coder_agent")
    g.edge("evidence", "close")
    return g


def run(scope: dict | None = None, root: str = "example_run", providers: dict[str, object] | None = None) -> dict:
    """Runs the workflow with persistence in <root>/.harness and returns the state.

    providers: LLM providers per agent (e.g.: StubProvider in tests; with no
    argument, make_provider() decides by env — OpenRouter/Ollama/Stub).
    """
    graph = build_graph(providers=providers)
    problems = graph.validate()
    if problems:
        raise RuntimeError(f"invalid graph: {problems}")

    store = FileStateStore(root)
    limits = Limits(max_retries=2, max_llm_calls=40, run_timeout_s=120, max_depth=16)
    runner = Runner(graph, store=store, limits=limits)

    # audit: events go to the store and stdout
    runner.bus.subscribe(lambda ev: store.append_event(ev))
    runner.bus.subscribe(lambda ev: print(f"[{ev.kind}] {ev.node_id}: {ev.message[:80]}"))

    state = runner.run(initial={"scope": scope or {"what": "feature demo", "why": "hard harness", "out_of_scope": "nothing"}})
    return {"status": state.status.value, "state": state, "store": store}


if __name__ == "__main__":
    result = run()
    print(f"\n== final status: {result['status']}")
    events = result["store"].list_events()
    print(f"== persisted events: {len(events)}")
    for ev in events[-8:]:
        print(f"   [{ev.ts}] {ev.kind} {ev.node_id}: {ev.message[:70]}")