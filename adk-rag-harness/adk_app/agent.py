"""Executable Google ADK app for local development.

OpenRouter with Jev (``typesafe/jev-router``) is the default for both the
conversation model and the typed decisions, so ``uv run adk web`` only needs
an OpenRouter key. Every setting follows ``HARNESS_<ROLE>_<SETTING>``; see
``.env.example`` for the full list and defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from adk_rag_harness.adk_runtime import AdkRuntimeAdapter, AdkRuntimeConfig
from adk_rag_harness.contracts import DecisionAnswer, DecisionQuestion, DecisionResult, EvidenceChunk, RetrievalResponse
from adk_rag_harness.jev_sdk import TypeSafeSdkDecisionProvider
from adk_rag_harness.openai_compatible import OpenAICompatibleDecisionProvider, load_openrouter_api_key
from adk_rag_harness.rag_adapter import RagHarnessAdapter
from adk_rag_harness.settings import check_settings
from adk_rag_harness.usage import litellm_logger
from adk_rag_harness.workflow import DEFAULT_COLLECTIONS, AdkRagWorkflow


check_settings()

DEFAULT_MODELS = {
    "chat": {"openrouter": "typesafe/jev-router", "ollama": "llama3.1:8b"},
    "decision": {"openrouter": "typesafe/jev-router", "ollama": "qwen2.5:14b", "typesafe": "jev-latest"},
}

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

CHAT_PROVIDER = os.getenv("HARNESS_CHAT_PROVIDER", "openrouter")
CHAT_MODEL = os.getenv("HARNESS_CHAT_MODEL", DEFAULT_MODELS["chat"].get(CHAT_PROVIDER, "")).removeprefix("openrouter/")
# Qwen is the local decision default because it was more consistent than
# llama3.1:8b in the golden routing prompts.
DECISION_PROVIDER = os.getenv("HARNESS_DECISION_PROVIDER", "openrouter")
DECISION_MODEL = os.getenv(
    "HARNESS_DECISION_MODEL", DEFAULT_MODELS["decision"].get(DECISION_PROVIDER, "")
).removeprefix("openrouter/")
RAG_PROVIDER = os.getenv("HARNESS_RAG_PROVIDER", "demo")
GUARDRAIL = os.getenv("HARNESS_GUARDRAIL", "off").lower() in ("on", "1", "true", "yes")


class DemoDecisions:
    """Deterministic local provider used by the default offline app."""

    def decide(self, state, questions):
        request = str(state.get("request", "")).lower()
        tool_name = str(state.get("tool_name", "")).lower()
        q_name = questions[0].name
        if q_name == "is_safe":
            is_malicious = any(
                w in request
                for w in ("ignore previous instructions", "jailbreak", "bypass security", "drop table")
            )
            return DecisionResult({"is_safe": DecisionAnswer(not is_malicious, 0.99)}, provider="demo")
        if q_name == "tool_action":
            is_destructive = any(w in tool_name for w in ("delete", "drop", "terminate", "wipe"))
            action = "deny" if is_destructive else "allow"
            return DecisionResult({"tool_action": DecisionAnswer(action, 0.99)}, provider="demo")
        if q_name == "needs_retrieval":
            needs_retrieval = any(word in request for word in ("find", "search", "policy", "evidence", "document"))
            return DecisionResult({"needs_retrieval": DecisionAnswer(needs_retrieval, 0.98)}, provider="demo")
        return DecisionResult(
            {
                "collection": DecisionAnswer("docs", 0.98),
                "strategy": DecisionAnswer("hybrid", 0.98),
            },
            provider="demo",
        )



class DemoRag:
    """Small evidence source for exercising the ADK UI without a repository."""

    def retrieve(self, request):
        chunk = EvidenceChunk(
            source="demo/policy.md",
            text=f"Demo evidence for: {request.query}",
            score=1.0,
        )
        return RetrievalResponse(request, (chunk,), True, "demo evidence")


def _build_workflow() -> AdkRagWorkflow:
    if DECISION_PROVIDER == "demo":
        decisions = DemoDecisions()
    elif DECISION_PROVIDER == "ollama":
        decisions = OpenAICompatibleDecisionProvider(
            base_url=f"{OLLAMA_BASE_URL}/v1",
            model=DECISION_MODEL,
            provider="ollama",
        )
    elif DECISION_PROVIDER == "openrouter":
        decisions = OpenAICompatibleDecisionProvider(
            base_url=OPENROUTER_BASE_URL,
            model=DECISION_MODEL,
            api_key=_require_openrouter_key(),
            provider="openrouter",
        )
    elif DECISION_PROVIDER == "typesafe":
        decisions = TypeSafeSdkDecisionProvider(model=DECISION_MODEL)
    else:
        raise RuntimeError(
            f"Unsupported HARNESS_DECISION_PROVIDER={DECISION_PROVIDER!r}; "
            "use openrouter, ollama, typesafe or demo"
        )
    if RAG_PROVIDER == "demo":
        rag = DemoRag()
        collections = DEFAULT_COLLECTIONS
    elif RAG_PROVIDER == "index":
        repository_root = Path(__file__).parents[2]
        indexes = _rag_collection_indexes(repository_root)
        # Ledger lines belong to the repository the indexes were built from.
        for path in indexes.values():
            if ".rag_index" in Path(path).parts:
                index_root = Path(path).parts.index(".rag_index")
                os.environ.setdefault("HARNESS_PROJECT_ROOT", str(Path(*Path(path).parts[:index_root])))
                break
        rag = RagHarnessAdapter(str(repository_root / "rag-harness"), indexes)
        collections = tuple(indexes)
    elif RAG_PROVIDER == "postgres":
        rag, collections = _postgres_rag(Path(__file__).parents[2])
    else:
        raise RuntimeError(
            f"Unsupported HARNESS_RAG_PROVIDER={RAG_PROVIDER!r}; use postgres, index or demo"
        )
    return AdkRagWorkflow(decisions, rag, enable_guardrail=GUARDRAIL, collections=collections)


def _postgres_rag(repository_root: Path):
    """A wrong setting stops the app; a database that is down only blocks each retrieval."""

    project = os.getenv("HARNESS_RAG_PROJECT")
    if not project:
        raise RuntimeError("HARNESS_RAG_PROVIDER=postgres needs HARNESS_RAG_PROJECT, the name given to `index`")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL support requires the optional dependency: uv sync --extra postgres") from exc
    sys.path.insert(0, str(repository_root / "adk-rag-postgres-harness"))
    from adk_rag_postgres_harness.adapter import COLLECTIONS, PostgresRagAdapter

    rag = PostgresRagAdapter(project)
    try:
        found = rag.store.project(project)
    except psycopg.Error:
        return rag, COLLECTIONS
    if found is None:
        raise RuntimeError(f"unknown project {project!r}; run `index` in adk-rag-postgres-harness first")
    # Ledger lines belong to the repository that was indexed.
    os.environ.setdefault("HARNESS_PROJECT_ROOT", found["root"])
    return rag, COLLECTIONS


def _rag_collection_indexes(repository_root: Path) -> dict[str, str]:
    """Map each configured collection to its index; unset ones are not offered."""

    indexes = {
        name: os.getenv(f"HARNESS_RAG_{name.upper()}_INDEX", "")
        for name in DEFAULT_COLLECTIONS
    }
    indexes = {name: path for name, path in indexes.items() if path}
    return indexes or {"docs": str(repository_root / "docs" / ".rag_index")}



def _require_openrouter_key() -> str:
    openrouter_key = load_openrouter_api_key()
    if not openrouter_key:
        raise RuntimeError(
            "OpenRouter credentials are required: set OPENROUTER_API_KEY "
            "or configure ~/.local/share/opencode/auth.json"
        )
    return openrouter_key


def _install_usage_logger() -> None:
    """Record conversation-model tokens and cost; idempotent across adk web reloads."""

    import litellm

    logger = litellm_logger(CHAT_PROVIDER, CHAT_MODEL)
    callbacks = [cb for cb in litellm.callbacks if type(cb).__name__ != "LedgerLogger"]
    litellm.callbacks = callbacks + ([logger] if logger is not None else [])


def _build_model():
    try:
        from google.adk.models.lite_llm import LiteLlm
    except ImportError as exc:
        raise RuntimeError(
            "LiteLLM support requires the optional dependency: "
            "uv sync --extra adk --extra ollama"
        ) from exc
    _install_usage_logger()
    if CHAT_PROVIDER == "openrouter":
        return LiteLlm(
            model=f"openrouter/{CHAT_MODEL}",
            api_key=_require_openrouter_key(),
            api_base=OPENROUTER_BASE_URL,
        )
    if CHAT_PROVIDER == "ollama":
        return LiteLlm(model=f"ollama_chat/{CHAT_MODEL}", api_base=OLLAMA_BASE_URL)
    raise RuntimeError(
        f"Unsupported HARNESS_CHAT_PROVIDER={CHAT_PROVIDER!r}; use openrouter or ollama"
    )


root_agent = AdkRuntimeAdapter(
    _build_workflow(),
    AdkRuntimeConfig(
        app_name="adk_rag_harness",
        agent_name="adk_rag_router",
        model=_build_model(),
    ),
).build_agent()
