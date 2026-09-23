"""Executable graph — the workflow structure (ADK 2, Pillar 1).

- Deterministic nodes (pure function) and agentic nodes (reasoning) are peers.
- fan-out: edges from one node to many (parallel execution in the runner).
- join: node that aggregates N inputs (JoinNode).
- router: function that chooses ONE route — ALWAYS with a mandatory default
  (a nonexistent route never closes in silence — ADK lesson L2b).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .schemas import NodeKind, NodeOutput

NodeFn = Callable[["NodeInput"], NodeOutput]
RouterFn = Callable[[dict[str, Any]], str]


@dataclass
class Node:
    id: str
    kind: NodeKind
    fn: NodeFn
    description: str = ""
    max_retries: int = 1  # additional attempts beyond the first
    timeout_s: float = 0.0  # 0 = no per-node timeout


@dataclass
class WorkflowGraph:
    """Graph: nodes + edges + fan-outs + joins + routers.

    Conventions:
      - edge(n, m): n -> m (sequential).
      - fan_out(n, [m1, m2, ...]): n dispatches N in parallel.
      - join(n, [s1, s2], m): m receives payload {s1: {...}, s2: {...}}.
      - router(n, fn, routes, default): fn(payload) -> id in routes; default MANDATORY.
    """

    name: str
    nodes: dict[str, Node] = field(default_factory=dict)
    start: str = ""
    edges: dict[str, list[str]] = field(default_factory=dict)  # n -> successors
    joins: dict[str, list[str]] = field(default_factory=dict)  # n -> sources
    routers: dict[str, tuple[RouterFn, dict[str, str], str]] = field(default_factory=dict)
    is_join: set[str] = field(default_factory=set)

    def add_node(self, node: Node) -> "WorkflowGraph":
        if node.id in self.nodes:
            raise ValueError(f"duplicate node: {node.id}")
        self.nodes[node.id] = node
        self.edges.setdefault(node.id, [])
        return self

    def set_start(self, node_id: str) -> "WorkflowGraph":
        if node_id not in self.nodes:
            raise ValueError(f"unknown start: {node_id}")
        self.start = node_id
        return self

    def edge(self, src: str, dst: str) -> "WorkflowGraph":
        self._require(src, dst)
        if dst in self.edges[src]:
            return self
        self.edges[src].append(dst)
        return self

    def fan_out(self, src: str, targets: list[str]) -> "WorkflowGraph":
        for t in targets:
            self.edge(src, t)
        return self

    def join(self, node_id: str, sources: list[str], target: str) -> "WorkflowGraph":
        """JoinNode: waits for all sources and delivers {source_id: payload}."""
        self._require(node_id, target)
        self.is_join.add(node_id)
        self.joins[node_id] = sources
        for s in sources:
            self._require(s, node_id)
            self.edge(s, node_id)
        self.edge(node_id, target)
        return self

    def router(self, node_id: str, fn: RouterFn, routes: dict[str, str], default: str) -> "WorkflowGraph":
        """Deterministic router — default MANDATORY (no silent death)."""
        if default not in routes.values():
            raise ValueError(f"router {node_id}: default '{default}' must be an existing destination in routes")
        for dst in routes.values():
            self._require(node_id, dst)
            self.edge(node_id, dst)  # routes are also edges (visible and auditable)
        self.routers[node_id] = (fn, routes, default)
        return self

    def _require(self, src: str, dst: str) -> None:
        for n in (src, dst):
            if n not in self.nodes:
                raise ValueError(f"unknown node: {n}")

    def validate(self) -> list[str]:
        """Structural validation: referenced nodes exist; routers have a default;
        every node is reachable; no silent dead-end in router routes."""
        problems: list[str] = []
        if not self.start:
            problems.append("no start node")
        for node_id, (_, routes, default) in self.routers.items():
            for route, dst in routes.items():
                if dst not in self.nodes:
                    problems.append(f"router {node_id}: route '{route}' -> nonexistent node '{dst}'")
            if default not in self.nodes:
                problems.append(f"router {node_id}: default -> nonexistent node '{default}'")
            if default not in routes.values():
                problems.append(f"router {node_id}: default '{default}' outside the routes")
        reachable: set[str] = set()
        frontier = [self.start] if self.start else []
        while frontier:
            n = frontier.pop(0)
            if n in reachable:
                continue
            reachable.add(n)
            for dst in self.edges.get(n, []):
                if dst not in self.nodes:
                    problems.append(f"edge {n} -> nonexistent node '{dst}'")
                else:
                    frontier.append(dst)
        for nid in self.nodes:
            if nid not in reachable:
                problems.append(f"unreachable node: {nid}")
        return problems