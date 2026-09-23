"""ADK 2 adapter (optional) — inspiration, not a core dependency.

The hard-harness core is framework-agnostic. This module exists only to:
  1. Document the conceptual ADK 2 -> hard-harness mapping;
  2. Export the graph structure in a format the ADK understands (edges),
     when google.adk is installed (optional import).

If the ADK is not installed, nothing breaks — the orchestration is ours.
"""

from __future__ import annotations

from typing import Any

from hard_harness.core.graph import WorkflowGraph


def to_adk_edges(graph: WorkflowGraph) -> list[tuple[str, str]]:
    """Projects the graph into ADK-style Workflow(edges=[...]) edges.

    Routers become pairs (router_node, {route: node}) — see the ADK 2 codelab
    L2b example. Useful for inspection and for future adapters.
    """
    edges: list[tuple[str, str]] = []
    for src, dsts in graph.edges.items():
        for dst in dsts:
            edges.append((src, dst))
    return edges


def adk_available() -> bool:
    try:
        import google.adk  # noqa: F401

        return True
    except ImportError:
        return False


def mapping_table() -> dict[str, str]:
    """ADK 2 (codelab) -> hard-harness (component)."""
    return {
        "START": "graph.start",
        "function node": "Node(kind=DETERMINISTIC)",
        "agent node": "Node(kind=AGENT)",
        "fan-out (multiple edges)": "WorkflowGraph.fan_out",
        "JoinNode": "WorkflowGraph.join (aggregates by source id)",
        "router + DEFAULT_ROUTE": "WorkflowGraph.router (default REQUIRED)",
        "input_schema/output_schema": "typed NodeInput/NodeOutput (schemas.py)",
        "Event(output, route)": "NodeOutput(payload, proposed_next) + runner decides",
        "mode=chat/task/single_turn": "agents are nodes with a single contract (run(NodeInput) -> NodeOutput)",
        "MAX_DEPTH in code (L4b)": "Limits.max_depth applied in the Runner",
        "parallel_worker runtime": "run_fanout with MAX_CHILDREN in the Runner",
    }