"""Hard harness tests — pytest or plain asserts.

Usage: python3 tests/test_hard_harness.py   (from hard-harness/)

Required coverage:
  - valid and invalid transitions
  - gate blocking build/test
  - fan-out and join (including explicit child failure)
  - deterministic router + default route (no silent death)
  - file persistence + resume after interruption
  - limits: retries, depth, children, LLM calls
  - agent trying to advance status without authorization (audited)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Tests never write to the real usage ledger unless a test enables it.
os.environ.setdefault("HARNESS_USAGE", "0")
# Never pick up the developer's real OpenRouter key (that would bill).
os.environ["OPENROUTER_AUTH_FILE"] = os.devnull
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "examples"))

from hard_harness.core import Limits, Node, NodeInput, NodeKind, NodeOutput, Runner, WorkflowGraph  # noqa: E402
from hard_harness.core.events import EventBus  # noqa: E402
from hard_harness.core.gates import gate_from_command, gate_jev_decision, gate_node_output  # noqa: E402

from hard_harness.core.schemas import WorkflowStatus  # noqa: E402
from hard_harness.stores import FileStateStore  # noqa: E402
from hard_harness.llm.providers import StubProvider  # noqa: E402


def example_providers() -> dict:
    """Structured stubs: responses the agents know how to parse."""
    return {
        "planner": StubProvider("- passo 1\n- passo 2\n- passo 3"),
        "coder": StubProvider("```diff\n+ def nova():\n+     pass\n```"),
        "reviewer": StubProvider("revisão ok\nVERDICT: approved"),
    }

DET = NodeKind.DETERMINISTIC
AGT = NodeKind.AGENT


def noop(node_id: str, payload: dict | None = None):
    def fn(ninput: NodeInput) -> NodeOutput:
        return NodeOutput(node_id=node_id, ok=True, payload=payload or {"n": node_id})

    return fn


def fail_node(node_id: str, message: str = "failure"):
    def fn(ninput: NodeInput) -> NodeOutput:
        return NodeOutput(node_id=node_id, ok=False, error=message)

    return fn


def chain_graph(fail_id: str | None = None) -> WorkflowGraph:
    g = WorkflowGraph(name="chain")
    g.add_node(Node("a", DET, noop("a")))
    g.add_node(Node("b", DET, noop("b")))
    g.add_node(Node("c", DET, fail_node("c") if fail_id == "c" else noop("c")))
    g.set_start("a")
    g.edge("a", "b")
    g.edge("b", "c")
    return g


def run(g: WorkflowGraph, limits: Limits | None = None, store=None, bus=None) -> object:
    return Runner(g, store=store, bus=bus, limits=limits or Limits()).run()


# ═══ Transitions ════════════════════════════════════════════════════

def test_transicao_valida():
    state = run(chain_graph())
    assert state.status is WorkflowStatus.CLOSED
    assert state.current_node == "c"
    assert state.data["a"]["n"] == "a"
    assert state.data["c"]["n"] == "c"


def test_transicao_invalida_bloqueada_na_construcao():
    g = chain_graph()
    try:
        g.edge("c", "node_que_nao_existe")
        assert False, "edge to a nonexistent node must fail at construction"
    except ValueError:
        pass
    problems = g.validate()
    assert not problems


# ═══ Gates ══════════════════════════════════════════════════════════

def test_gate_bloqueia_build():
    g = WorkflowGraph(name="gate_fail")
    g.add_node(Node("build", DET, gate_node_output("build", gate_from_command("build", "exit 1", "build"))))
    g.set_start("build")
    state = run(g, Limits(max_retries=0))
    assert state.status is WorkflowStatus.FAILED
    assert "MAX_RETRIES" in state.error


def test_gate_passa_com_exit_zero():
    g = WorkflowGraph(name="gate_ok")
    g.add_node(Node("build", DET, gate_node_output("build", gate_from_command("build", "echo ok", "build"))))
    g.set_start("build")
    state = run(g, Limits(max_retries=0))
    assert state.status is WorkflowStatus.CLOSED
    assert state.data["build"]["gate"]["passed"] is True


def test_gate_jev_decision_bloqueia_e_passa():
    # Pass path: score meets threshold
    g_ok = WorkflowGraph(name="jev_gate_ok")
    g_ok.add_node(Node("check", DET, gate_node_output("check", gate_jev_decision("check", "artifact_quality", min_score=0.85))))
    g_ok.set_start("check")
    state_ok = run(g_ok)
    assert state_ok.status is WorkflowStatus.CLOSED
    assert state_ok.data["check"]["gate"]["passed"] is True

    # Block path: score below threshold
    g_fail = WorkflowGraph(name="jev_gate_fail")
    fail_gate = gate_jev_decision("check", "artifact_quality", min_score=0.85, evaluator=lambda p: (False, 0.60, "score 0.60 below 0.85"))
    g_fail.add_node(Node("check", DET, gate_node_output("check", fail_gate)))
    g_fail.set_start("check")
    state_fail = run(g_fail, Limits(max_retries=0))
    assert state_fail.status is WorkflowStatus.FAILED
    assert "MAX_RETRIES" in state_fail.error


# ═══ Fan-out and join ═══════════════════════════════════════════════


def test_fanout_e_join():
    g = WorkflowGraph(name="fanjoin")
    g.add_node(Node("src", DET, noop("src")))
    g.add_node(Node("x", DET, noop("x")))
    g.add_node(Node("y", DET, noop("y")))

    def join_node(ninput: NodeInput) -> NodeOutput:
        fanout = ninput.state.data.get("fanout_src", {})
        return NodeOutput(node_id="join", ok=True, payload={
            "x": "ok" if "error" not in fanout.get("x", {}) else "fail",
            "y": "ok" if "error" not in fanout.get("y", {}) else "fail",
        })

    g.add_node(Node("join", DET, join_node))
    g.add_node(Node("end", DET, noop("end")))
    g.set_start("src")
    g.fan_out("src", ["x", "y"])
    g.join("join", ["x", "y"], "end")
    state = run(g)
    assert state.status is WorkflowStatus.CLOSED
    assert state.data["join"]["x"] == "ok"
    assert state.data["join"]["y"] == "ok"


def test_fanout_falha_e_explicita_no_join():
    g = WorkflowGraph(name="fanjoin_fail")
    g.add_node(Node("src", DET, noop("src")))
    g.add_node(Node("x", DET, fail_node("x")))
    g.add_node(Node("y", DET, noop("y")))

    def join_node(ninput: NodeInput) -> NodeOutput:
        fanout = ninput.state.data.get("fanout_src", {})
        return NodeOutput(node_id="join", ok=True, payload={
            "x_error": fanout.get("x", {}).get("error", ""),
            "y_ok": "error" not in fanout.get("y", {}),
        })

    g.add_node(Node("join", DET, join_node))
    g.add_node(Node("end", DET, noop("end")))
    g.set_start("src")
    g.fan_out("src", ["x", "y"])
    g.join("join", ["x", "y"], "end")
    state = run(g)
    assert state.status is WorkflowStatus.CLOSED
    assert state.data["join"]["x_error"] != ""  # a failure NEVER disappears
    assert state.data["join"]["y_ok"] is True


def test_fanout_sem_join_nao_e_silencioso():
    g = WorkflowGraph(name="fanjoin_missing")
    g.add_node(Node("src", DET, noop("src")))
    g.add_node(Node("x", DET, noop("x")))
    g.add_node(Node("y", DET, noop("y")))
    g.set_start("src")
    g.fan_out("src", ["x", "y"])
    state = run(g)
    assert state.status is WorkflowStatus.FAILED
    assert "JoinNode" in state.error  # nonexistent transition = explicit error


# ═══ Deterministic router ═══════════════════════════════════════════

def test_router_deterministico():
    g = WorkflowGraph(name="router")
    g.add_node(Node("src", DET, noop("src")))
    g.add_node(Node("route", DET, noop("route")))
    g.add_node(Node("ok", DET, noop("ok")))
    g.add_node(Node("fix", DET, noop("fix")))

    def decide(state_data: dict) -> str:
        return "ok" if state_data.get("src", {}).get("n") == "src" else "fix"

    g.set_start("src")
    g.edge("src", "route")
    g.router("route", decide, {"ok": "ok", "fix": "fix"}, default="fix")
    state = run(g)
    assert state.current_node == "ok"
    assert state.status is WorkflowStatus.CLOSED


def test_router_rota_default_sem_morte_silenciosa():
    g = WorkflowGraph(name="router_default")
    g.add_node(Node("src", DET, noop("src")))
    g.add_node(Node("route", DET, noop("route")))
    g.add_node(Node("fix", DET, noop("fix")))

    def decide(state_data: dict) -> str:
        return "rota_que_nao_existe"  # unknown route -> default takes over

    g.set_start("src")
    g.edge("src", "route")
    g.router("route", decide, {"ok": "fix"}, default="fix")
    state = run(g)
    assert state.status is WorkflowStatus.CLOSED
    assert state.current_node == "fix"  # NEVER closes silently


def test_router_default_fora_das_rotas_e_rejeitado():
    g = WorkflowGraph(name="router_nodefault")
    g.add_node(Node("route", DET, noop("route")))
    g.add_node(Node("fix", DET, noop("fix")))
    try:
        g.router("route", lambda s: "fix", {"ok": "fix"}, default="nao_existe")
        assert False, "default outside the routes must fail at construction"
    except ValueError:
        pass


# ═══ Persistence and resume ═════════════════════════════════════════

def test_persistencia_em_arquivo():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileStateStore(tmp)
        runner = Runner(chain_graph(), store=store, limits=Limits())
        runner.bus.subscribe(lambda ev: store.append_event(ev))
        runner.run()
        saved = store.read_state()
        assert saved is not None
        assert saved.status is WorkflowStatus.CLOSED
        assert os.path.exists(os.path.join(tmp, ".harness", "state.json"))
        assert os.path.exists(os.path.join(tmp, ".harness", "events.jsonl"))
        assert len(store.list_events()) >= 5
        # locks
        assert store.acquire_lock("test") is True
        assert store.acquire_lock("test") is False
        store.release_lock("test")
        assert store.acquire_lock("test") is True
        store.release_lock("test")


def test_retomada_apos_interrupcao():
    """Node that fails on the 1st attempt; runner with retry completes and persists."""
    attempts = {"n": 0}

    def flaky(ninput: NodeInput) -> NodeOutput:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("simulated interruption")
        return NodeOutput(node_id="flaky", ok=True, payload={"recovered": True})

    g = WorkflowGraph(name="resume")
    g.add_node(Node("a", DET, noop("a")))
    g.add_node(Node("flaky", DET, flaky))
    g.add_node(Node("z", DET, noop("z")))
    g.set_start("a")
    g.edge("a", "flaky")
    g.edge("flaky", "z")

    with tempfile.TemporaryDirectory() as tmp:
        store = FileStateStore(tmp)
        state = Runner(g, store=store, limits=Limits(max_retries=1)).run()
        assert state.status is WorkflowStatus.CLOSED
        assert state.data["flaky"]["recovered"] is True
        saved = store.read_state()
        assert saved is not None and saved.status is WorkflowStatus.CLOSED


# ═══ Limits ═════════════════════════════════════════════════════════

def test_limite_de_retries():
    state = run(chain_graph(fail_id="c"), Limits(max_retries=1))
    assert state.status is WorkflowStatus.FAILED
    assert "MAX_RETRIES" in state.error
    assert state.retries["c"] == 2  # 1 initial + 1 retry


def test_limite_de_profundidade():
    g = WorkflowGraph(name="deep")
    g.add_node(Node("n0", DET, noop("n0")))
    g.set_start("n0")
    prev = "n0"
    for i in range(1, 12):
        nid = f"n{i}"
        g.add_node(Node(nid, DET, noop(nid)))
        g.edge(prev, nid)
        prev = nid
    state = run(g, Limits(max_depth=5))
    assert state.status is WorkflowStatus.FAILED
    assert "MAX_DEPTH" in state.error


def test_limite_de_children():
    g = WorkflowGraph(name="wide")
    g.add_node(Node("src", DET, noop("src")))
    children = [f"c{i}" for i in range(20)]
    for c in children:
        g.add_node(Node(c, DET, noop(c)))
    g.add_node(Node("join", DET, noop("join")))
    g.add_node(Node("end", DET, noop("end")))
    g.set_start("src")
    g.fan_out("src", children)
    g.join("join", children, "end")
    state = run(g, Limits(max_children=5))
    assert state.status is WorkflowStatus.FAILED
    assert "MAX_CHILDREN" in state.error


def test_limite_de_llm_calls():
    g = WorkflowGraph(name="llm")
    g.add_node(Node("src", DET, noop("src")))
    g.add_node(Node("a1", AGT, noop("a1")))
    g.add_node(Node("a2", AGT, noop("a2")))
    g.add_node(Node("a3", AGT, noop("a3")))
    g.set_start("src")
    g.edge("src", "a1")
    g.edge("a1", "a2")
    g.edge("a2", "a3")
    state = run(g, Limits(max_llm_calls=2))
    assert state.status is WorkflowStatus.FAILED
    assert "MAX_LLM_CALLS" in state.error


# ═══ Authority: agent never advances status ═════════════════════════

def test_agente_nao_pode_avancar_status():
    """Agent proposes a next node outside the edges: the runner REFUSES with an
    auditable event and the workflow follows the graph (nothing advances by shortcut)."""
    events: list = []
    bus = EventBus()
    bus.subscribe(events.append)

    def rebel_agent(ninput: NodeInput) -> NodeOutput:
        return NodeOutput(node_id="rebel", ok=True, payload={"intent": "will advance"},
                          proposed_next="node_inexistente")

    g = WorkflowGraph(name="rebel")
    g.add_node(Node("a", DET, noop("a")))
    g.add_node(Node("rebel", AGT, rebel_agent))
    g.add_node(Node("z", DET, noop("z")))
    g.set_start("a")
    g.edge("a", "rebel")
    g.edge("rebel", "z")

    state = run(g, bus=bus)
    assert state.status is WorkflowStatus.CLOSED
    assert state.current_node == "z"  # went through the graph, not the shortcut
    kinds = [e.kind for e in events]
    assert "agent_proposal" in kinds  # the refusal was audited, not silent


def test_agente_nao_transiciona_por_codigo():
    """Contract: the agent only has NodeInput (view) and returns NodeOutput.
    There is no transition API for it — the state arrives intact."""
    g = WorkflowGraph(name="authority")
    seen_statuses: list = []

    def spy_agent(ninput: NodeInput) -> NodeOutput:
        seen_statuses.append(ninput.state.status.value)
        return NodeOutput(node_id="spy", ok=True, payload={"saw": ninput.state.status.value})

    g.add_node(Node("a", DET, noop("a")))
    g.add_node(Node("spy", AGT, spy_agent))
    g.set_start("a")
    g.edge("a", "spy")
    state = run(g)
    assert seen_statuses == ["running"]
    assert state.status is WorkflowStatus.CLOSED


# ═══ Complete example ═══════════════════════════════════════════════

def test_exemplo_completo_fecha_com_evidencia():
    import tempfile as _tmp
    import examples.basic_workflow.workflow as wf

    with _tmp.TemporaryDirectory() as tmp:
        result = wf.run(scope={"what": "demo", "why": "course", "out_of_scope": "nothing"}, root=tmp, providers=example_providers())
        assert result["status"] == "closed", f"expected closed, got {result['status']}"
        state = result["state"]
        assert state.data["join"]["all_ok"] is True
        assert state.data["evidence"]["passed"] is True
        assert len(result["store"].list_events()) >= 15  # full trail



def test_contexto_do_ledger_chega_ao_no_com_timeout():
    from hard_harness import usage

    if usage._usage is None:
        return  # standalone copy without harness-usage
    seen: dict = {}

    def fn(ninput: NodeInput) -> NodeOutput:
        seen.update(usage._usage.current_context())
        return NodeOutput(node_id="a", ok=True, payload={})

    g = WorkflowGraph(name="ctx")
    g.add_node(Node("a", DET, fn, timeout_s=5))
    g.set_start("a")
    state = run(g)
    assert seen["operation"] == "a"
    assert seen["request_id"] == state.workflow_id

if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n== {sum(1 for n in globals() if n.startswith('test_')) - failed}/{sum(1 for n in globals() if n.startswith('test_'))} passed")
    sys.exit(1 if failed else 0)