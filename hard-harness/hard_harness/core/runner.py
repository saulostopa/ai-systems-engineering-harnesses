"""Runner — the ONLY authority for state transitions.

Principles (course requirements):
  1. Agents produce proposals (NodeOutput.proposed_next); the runner DECIDES.
  2. An agent never changes status — an attempt becomes an error Event (auditable).
  3. Transitions pass through gates; invalid data is blocked.
  4. Every transition becomes an Event and a store checkpoint.
  5. Limits: MAX_DEPTH, MAX_CHILDREN, MAX_RETRIES, MAX_LLM_CALLS, timeout,
     optional LLM budget — applied IN CODE (ADK 2, L4b).
"""

from __future__ import annotations

import contextvars
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .events import Event, EventBus
from .graph import Node, WorkflowGraph
from .schemas import NodeInput, NodeOutput, NodeKind, WorkflowState, WorkflowStatus
from ..usage import usage_context


@dataclass
class Limits:
    """Mandatory limits — applied by the runner, not by the agents."""

    max_depth: int = 8
    max_children: int = 16
    max_retries: int = 3
    max_llm_calls: int = 40
    run_timeout_s: float = 1800.0
    llm_budget: float = 0.0  # 0 = no budget; >0 = ceiling in cost units


class Runner:
    """Executes the graph. The only object that calls state transitions."""

    def __init__(
        self,
        graph: WorkflowGraph,
        store=None,            # StateStore (None = no persistence)
        bus: EventBus | None = None,
        limits: Limits | None = None,
        node_dispatch: dict[str, Callable[[NodeInput], NodeOutput]] | None = None,
    ) -> None:
        self.graph = graph
        self.store = store
        self.bus = bus or EventBus()
        self.limits = limits or Limits()
        # extra dispatch (e.g.: injected gates) by node id
        self.node_dispatch = node_dispatch or {}
        self._started_at = 0.0
        self._llm_cost = 0.0

    # ── Public API ───────────────────────────────────────────────

    def run(self, initial: dict[str, Any] | None = None, state: WorkflowState | None = None) -> WorkflowState:
        """Runs from the start (or resumes from a saved state)."""
        self._started_at = time.monotonic()
        if state is None:
            state = WorkflowState(workflow_id=self._new_workflow_id(), data=initial or {})
            self._transition(state, WorkflowStatus.RUNNING, "init", "workflow started")
            node_id = self.graph.start
        else:
            node_id = state.current_node  # resume
        self._checkpoint(state)
        try:
            return self._advance_from(state, node_id, depth=0)
        except TimeoutError as exc:
            state.error = str(exc)
            self._transition(state, WorkflowStatus.FAILED, "runner", f"timeout: {exc}")
            self._checkpoint(state)
            return state
        except Exception as exc:  # unexpected failure: explicit and auditable
            state.error = f"{type(exc).__name__}: {exc}"
            self._transition(state, WorkflowStatus.FAILED, "runner", state.error)
            self._checkpoint(state)
            return state

    # ── Core: state advancement (internal use) ───────────────────

    def _advance_from(self, state: WorkflowState, node_id: str, depth: int) -> WorkflowState:
        if depth > self.limits.max_depth:
            raise RuntimeError(f"MAX_DEPTH exceeded ({self.limits.max_depth})")
        if self._elapsed() > self.limits.run_timeout_s:
            raise TimeoutError(f"run_timeout_s exceeded ({self.limits.run_timeout_s})")

        node = self.graph.nodes[node_id]
        state.current_node = node_id
        state.depth = max(state.depth, depth)
        self._transition(state, WorkflowStatus.RUNNING, node_id, f"entering {node_id}")

        output = self._execute_node(node, state, depth)

        # ── Transition authority: agent proposal ≠ transition ──
        if not output.ok:
            return self._handle_failure(state, node, output, depth)

        state.data[node_id] = output.payload
        state.llm_calls += 1 if node.kind is NodeKind.AGENT else 0
        self._apply_llm_cost(output, node)
        self._check_llm_limits(state, node)

        # Gates attached to the output (e.g.: plan validation) block the transition
        if output.gate and not output.gate.passed:
            self.bus.emit(Event("gate", node_id, f"gate failed: {output.gate.failures}", {"failures": output.gate.failures}))
            return self._handle_failure(state, node, output, depth)

        for ev in output.evidence:
            self.bus.emit(Event("evidence", node_id, f"evidence {ev.kind} {'PASS' if ev.passed else 'FAIL'}", {"evidence": ev.to_dict()}))

        self._checkpoint(state)

        # ── Native fan-out: a node with N successors dispatches children in parallel ──
        # (exception: nodes with an explicit router — the router decides the single route)
        successors = self.graph.edges.get(node_id, [])
        if len(successors) > 1 and node_id not in self.graph.routers:
            children = [self.graph.nodes[s] for s in successors if s in self.graph.nodes]
            aggregated = run_fanout(self, state, node_id, children)
            state.data[f"fanout_{node_id}"] = aggregated
            join_id = self._join_after(node_id, successors)
            if join_id is None:
                raise RuntimeError(f"fan-out from {node_id} without JoinNode — transition cannot be silent")
            self._transition(state, WorkflowStatus.RUNNING, join_id, f"join after fan-out from {node_id}")
            self._checkpoint(state)
            return self._advance_from(state, join_id, depth + 1)

        next_node = self._next_node(state, node_id, output)
        if next_node is None:
            self._transition(state, WorkflowStatus.CLOSED, node_id, "workflow closed (end of graph)")
            self._checkpoint(state)
            return state
        return self._advance_from(state, next_node, depth + 1)

    def _execute_node(self, node: Node, state: WorkflowState, depth: int) -> NodeOutput:
        payload = state.data.get(node.id, {})
        ninput = NodeInput(node_id=node.id, state=state, payload=payload)
        fn = self.node_dispatch.get(node.id, node.fn)
        # Ledger lines of this node carry the node id and the workflow id.
        with usage_context(operation=node.id, request_id=state.workflow_id):
            if node.timeout_s > 0:
                return self._run_with_timeout(fn, ninput, node.timeout_s)
            try:
                return fn(ninput)
            except Exception as exc:
                return NodeOutput(node_id=node.id, ok=False, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _run_with_timeout(fn: Callable[[NodeInput], NodeOutput], ninput: NodeInput, timeout_s: float) -> NodeOutput:
        import threading

        result: dict[str, Any] = {"output": None}

        def target() -> None:
            try:
                result["output"] = fn(ninput)
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"

        context = contextvars.copy_context()
        thread = threading.Thread(target=context.run, args=(target,), daemon=True)
        thread.start()
        thread.join(timeout_s)
        if thread.is_alive():
            return NodeOutput(node_id=ninput.node_id, ok=False, error=f"node timeout ({timeout_s}s)")
        if result.get("error"):
            return NodeOutput(node_id=ninput.node_id, ok=False, error=result["error"])
        return result["output"]

    # ── Failures, retries and routing ──────────────────────────────

    def _join_after(self, node_id: str, successors: list[str]) -> str | None:
        """Finds the JoinNode whose sources are the fan-out successors."""
        wanted = set(successors)
        for join_id, sources in self.graph.joins.items():
            if set(sources) == wanted:
                return join_id
        return None

    def _handle_failure(self, state: WorkflowState, node: Node, output: NodeOutput, depth: int) -> WorkflowState:
        state.retries[node.id] = state.retries.get(node.id, 0) + 1
        attempts = state.retries[node.id]
        self.bus.emit(Event("error", node.id, output.error or "node failure", {"attempts": attempts}))
        if attempts <= self.limits.max_retries:
            self._transition(state, WorkflowStatus.RUNNING, node.id, f"retry {attempts}/{self.limits.max_retries}")
            self._checkpoint(state)
            return self._advance_from(state, node.id, depth + 1)
        state.error = f"MAX_RETRIES exceeded at {node.id} ({self.limits.max_retries})"
        self._transition(state, WorkflowStatus.FAILED, node.id, state.error)
        self._checkpoint(state)
        return state

    def _next_node(self, state: WorkflowState, node_id: str, output: NodeOutput) -> str | None:
        """Post-node routing:
        1. explicit router (mandatory default);
        2. agent proposal (the runner decides — it may refuse);
        3. sequential edges;
        4. None = end."""
        if node_id in self.graph.routers:
            fn, routes, default = self.graph.routers[node_id]
            route = fn(state.data)
            dst = routes.get(route, default)
            self.bus.emit(Event("transition", node_id, f"router: {route} -> {dst}", {"route": route, "dst": dst}))
            return dst
        if output.proposed_next:
            dst = output.proposed_next
            if dst not in self.graph.nodes:
                self.bus.emit(Event("agent_proposal", node_id, f"invalid proposal ignored: {dst}", {"proposed": dst}))
            elif dst not in self.graph.edges.get(node_id, []):
                self.bus.emit(Event("agent_proposal", node_id, f"proposal outside the edges ignored: {dst}", {"proposed": dst}))
            else:
                self.bus.emit(Event("agent_proposal", node_id, f"proposal accepted: {dst}", {"proposed": dst}))
                return dst
        succ = self.graph.edges.get(node_id, [])
        if len(succ) == 1:
            return succ[0]
        return None  # fan-out is handled by the dispatch node; join by the next node

    # ── Limits ──────────────────────────────────────────────────

    def _apply_llm_cost(self, output: NodeOutput, node: Node) -> None:
        """The real LLM cost (provider usage) enters the runner's budget."""
        if node.kind is NodeKind.AGENT:
            cost = output.payload.get("llm_cost", 1.0)
            try:
                self._llm_cost += float(cost)
            except (TypeError, ValueError):
                self._llm_cost += 1.0

    def _check_llm_limits(self, state: WorkflowState, node: Node) -> None:
        if state.llm_calls > self.limits.max_llm_calls:
            raise RuntimeError(f"MAX_LLM_CALLS exceeded ({self.limits.max_llm_calls})")
        if self.limits.llm_budget > 0 and self._llm_cost > self.limits.llm_budget:
            raise RuntimeError(f"llm_budget exceeded ({self.limits.llm_budget})")

    def _elapsed(self) -> float:
        return time.monotonic() - self._started_at

    # ── Transitions and persistence (only here!) ─────────────────

    def _transition(self, state: WorkflowState, status: WorkflowStatus, node_id: str, message: str) -> None:
        """The ONLY function that changes the status. No agent/node can call it."""
        state.status = status
        state.current_node = node_id
        state.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.bus.emit(Event("transition", node_id, message, {"status": status.value}))

    def _checkpoint(self, state: WorkflowState) -> None:
        if self.store:
            self.store.write_state(state)

    @staticmethod
    def _new_workflow_id() -> str:
        import uuid

        return f"wf_{uuid.uuid4().hex[:12]}"


# ── Parallel fan-out helper (deterministic nodes) ────────────────────

def run_fanout(runner: Runner, state: WorkflowState, parent_id: str, children: list[Node]) -> dict[str, dict[str, Any]]:
    """Runs N nodes in parallel and aggregates payloads by id (JoinNode).

    - MAX_CHILDREN is applied here (maximum width).
    - Each child runs as a sub-step; a failure becomes an {'error': ...} payload
      for the join to decide — never silent death.
    """
    if len(children) > runner.limits.max_children:
        raise RuntimeError(f"MAX_CHILDREN exceeded ({len(children)} > {runner.limits.max_children})")
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(children))) as pool:
        futures = {pool.submit(runner._execute_node, n, state, 0): n for n in children}
        for fut, node in futures.items():
            output = fut.result()
            runner.bus.emit(Event("transition", parent_id, f"fan-out: {node.id} {'ok' if output.ok else 'FAILED'}", {"child": node.id}))
            results[node.id] = output.payload if output.ok else {"error": output.error}
    return results