"""Run the feature planning graph over the demo or an indexed Postgres project."""

import os
import sys
from pathlib import Path

from .model_clients import CLIENTS
from .model_router import ModelRouter, Route, RoutingConfig
from .workflow import DEFAULT_MAX_SLICES, build_workflow

RAG_ROOT = Path(__file__).resolve().parents[2] / "rag-harness"
sys.path.insert(0, str(RAG_ROOT))

from rag_harness.chunker import chunk_file
from rag_harness.indexer import Index
from rag_harness.retrieval import lexical_search

DEMO_ROOT = Path(__file__).resolve().parent / "demo_repository"


def demo_search(query):
    chunks = []
    for path in sorted(DEMO_ROOT.glob("*.md")):
        for chunk in chunk_file(str(path)):
            chunk.path = path.relative_to(DEMO_ROOT).as_posix()
            chunks.append(chunk)
    return [
        {
            "id": f"E{position}",
            "path": chunk.path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "text": chunk.text,
        }
        for position, (chunk, _) in enumerate(
            lexical_search(Index(chunks, {}, {}), query, top_k=6), start=1
        )
    ]


def routing_config():
    config_path = os.getenv("HARNESS_MODEL_ROUTER_CONFIG")
    if config_path:
        return RoutingConfig.model_validate_json(Path(config_path).read_bytes())
    planner = Route(provider="ollama", model=os.getenv("HARNESS_PLANNER_MODEL", "qwen2.5:14b"))
    verifier = Route(provider="ollama", model=os.getenv("HARNESS_VERIFIER_MODEL", "qwen2.5:14b"))
    return RoutingConfig(planner=[planner], slice_verifier=[verifier], global_evaluator=[verifier])


def build_agent():
    max_slices = DEFAULT_MAX_SLICES
    configured_limit = os.getenv("HARNESS_PLANNER_MAX_SLICES")
    if configured_limit:
        try:
            max_slices = int(configured_limit)
            if max_slices < 1:
                raise ValueError
        except ValueError:
            raise ValueError("HARNESS_PLANNER_MAX_SLICES must be a positive integer.") from None
    search = demo_search
    project = os.getenv("HARNESS_PLANNER_RAG_PROJECT")
    if project:
        from .postgres import PostgresSearch

        references = tuple(
            name.strip()
            for name in os.getenv("HARNESS_PLANNER_RAG_REFERENCES", "").split(",")
            if name.strip()
        )
        target_limit = os.getenv("HARNESS_PLANNER_RAG_TARGET_TOP_K")
        search = PostgresSearch(
            project, references=references,
            target_top_k=int(target_limit) if target_limit else None,
        )
    publisher = None
    output = os.getenv("HARNESS_PILOT_EVIDENCE_DIR")
    if output:
        from .evidence import EvidencePublisher

        archify_bin = os.getenv("HARNESS_ARCHIFY_BIN")
        if not archify_bin:
            raise ValueError("Set HARNESS_ARCHIFY_BIN to the course's Archify CLI when publishing evidence.")
        from .pilot_evals import PilotEvalPolicy

        quiz_spec = os.getenv("HARNESS_PILOT_QUIZ_SPEC")
        eval_policy = os.getenv("HARNESS_PILOT_EVAL_POLICY")
        publisher = EvidencePublisher(
            Path(output), Path(archify_bin), Path(quiz_spec) if quiz_spec else None,
            eval_policy=PilotEvalPolicy.load(Path(eval_policy)) if eval_policy else None,
        )
    executor = None
    executor_policy = os.getenv("HARNESS_PILOT_EXECUTOR_POLICY")
    if executor_policy:
        from .slice_executor import ApprovedSlice, build_slice_executor

        policy = ApprovedSlice.model_validate_json(Path(executor_policy).read_bytes())
        executor = build_slice_executor(policy)
    return build_workflow(
        search, ModelRouter(routing_config(), CLIENTS), publisher, max_slices=max_slices, executor=executor,
    )


root_agent = build_agent()
