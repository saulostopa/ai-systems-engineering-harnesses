"""Executable Google ADK app for local development.

OpenRouter with Jev (``typesafe/jev-router``) is the default for both the
conversation model and the typed decisions, so ``uv run adk web`` only needs
an OpenRouter key. ``HARNESS_CHAT_PROVIDER`` selects the conversation model
(``openrouter`` or ``ollama``) and ``HARNESS_DECISION_PROVIDER`` selects the
typed decision provider (``demo``, ``ollama-system-one``,
``openrouter-system-one`` or ``jev``). CLI modes are intentionally opt-in and
are described in the course documentation.
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
from adk_rag_harness.usage import litellm_logger
from adk_rag_harness.workflow import DEFAULT_COLLECTIONS, AdkRagWorkflow


OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
os.environ.setdefault("OLLAMA_API_BASE", OLLAMA_API_BASE)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_OPENROUTER_MODEL = "typesafe/jev-router"
OPENROUTER_CHAT_MODEL = os.getenv("OPENROUTER_CHAT_MODEL", DEFAULT_OPENROUTER_MODEL).removeprefix("openrouter/")
OPENROUTER_DECISION_MODEL = os.getenv("OPENROUTER_DECISION_MODEL", DEFAULT_OPENROUTER_MODEL).removeprefix("openrouter/")

# Conversation model configuration:
#   HARNESS_CHAT_PROVIDER=openrouter                  # default, OPENROUTER_CHAT_MODEL
#   HARNESS_CHAT_PROVIDER=ollama                      # local, OLLAMA_MODEL
# Decision provider configuration:
#   HARNESS_DECISION_PROVIDER=openrouter-system-one   # default, OPENROUTER_DECISION_MODEL
#   HARNESS_DECISION_PROVIDER=ollama-system-one       # local, OLLAMA_DECISION_MODEL
#   HARNESS_DECISION_PROVIDER=demo                    # deterministic demo
#   HARNESS_DECISION_PROVIDER=jev                     # official TypeSafe API, needs key
#   HARNESS_RAG_PROVIDER=demo                         # demo evidence
#   HARNESS_RAG_PROVIDER=rag-harness                  # real local index
#   HARNESS_RAG_{DOCS,CODE,AREA}_INDEX=<path>         # one index per collection
# The decision settings affect only the typed routing decisions inside
# run_workflow. Qwen is the local decision default because it was more
# consistent than llama3.1:8b in the golden routing prompts.

CHAT_PROVIDER = os.getenv("HARNESS_CHAT_PROVIDER", "openrouter")
DEFAULT_DECISION_PROVIDER = "openrouter-system-one"
DECISION_PROVIDER = os.getenv("HARNESS_DECISION_PROVIDER", DEFAULT_DECISION_PROVIDER)
DECISION_MODEL = os.getenv(
    "HARNESS_DECISION_MODEL",
    os.getenv("OLLAMA_DECISION_MODEL", "qwen2.5:14b"),
)
RAG_PROVIDER = os.getenv("HARNESS_RAG_PROVIDER", "demo")


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
    elif DECISION_PROVIDER == "ollama-system-one":
        decisions = OpenAICompatibleDecisionProvider(
            base_url=os.getenv("OLLAMA_DECISION_BASE_URL", f"{OLLAMA_API_BASE}/v1"),
            model=DECISION_MODEL,
        )
    elif DECISION_PROVIDER == "openrouter-system-one":
        decisions = OpenAICompatibleDecisionProvider(
            base_url=OPENROUTER_BASE_URL,
            model=OPENROUTER_DECISION_MODEL,
            api_key=_require_openrouter_key(),
        )
    elif DECISION_PROVIDER == "jev":
        decisions = TypeSafeSdkDecisionProvider()
    else:
        raise RuntimeError(
            f"Unsupported HARNESS_DECISION_PROVIDER={DECISION_PROVIDER!r}; "
            "use demo, ollama-system-one, openrouter-system-one or jev"
        )
    if RAG_PROVIDER == "demo":
        rag = DemoRag()
        collections = DEFAULT_COLLECTIONS
    elif RAG_PROVIDER == "rag-harness":
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
    else:
        raise RuntimeError(
            f"Unsupported HARNESS_RAG_PROVIDER={RAG_PROVIDER!r}; use demo or rag-harness"
        )
    enable_guardrail = os.getenv("HARNESS_ENABLE_GUARDRAIL", "0").lower() in ("1", "true", "yes")
    return AdkRagWorkflow(decisions, rag, enable_guardrail=enable_guardrail, collections=collections)


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

    model = OPENROUTER_CHAT_MODEL if CHAT_PROVIDER == "openrouter" else OLLAMA_MODEL
    logger = litellm_logger(CHAT_PROVIDER, model)
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
            model=f"openrouter/{OPENROUTER_CHAT_MODEL}",
            api_key=_require_openrouter_key(),
            api_base=OPENROUTER_BASE_URL,
        )
    if CHAT_PROVIDER == "ollama":
        return LiteLlm(model=f"ollama_chat/{OLLAMA_MODEL}")
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
