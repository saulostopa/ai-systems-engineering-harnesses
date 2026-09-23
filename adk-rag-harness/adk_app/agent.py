"""Executable Google ADK app for local development.

Offline mode is the default so ``adk web`` never calls external providers by
accident. Change ``HARNESS_DECISION_PROVIDER`` to select the typed decision
provider. Supported values are ``demo``, ``ollama-system-one``,
``openrouter-system-one`` and ``jev``. CLI modes are intentionally opt-in and
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
from adk_rag_harness.workflow import AdkRagWorkflow


OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
os.environ.setdefault("OLLAMA_API_BASE", OLLAMA_API_BASE)

# Decision provider configuration:
#   HARNESS_DECISION_PROVIDER=ollama-system-one       # default, local
#   HARNESS_DECISION_PROVIDER=demo                    # deterministic demo
#   HARNESS_DECISION_PROVIDER=openrouter-system-one   # hosted, needs key
#   HARNESS_DECISION_PROVIDER=jev                    # official Jev, needs key
#   HARNESS_RAG_PROVIDER=demo                         # demo evidence
#   HARNESS_RAG_PROVIDER=rag-harness                  # real local index
# The conversational model remains controlled by OLLAMA_MODEL. These settings
# affect only the typed routing decisions inside run_workflow. Qwen is the
# local decision default because it was more consistent than llama3.1:8b in the
# golden routing prompts.

DEFAULT_DECISION_PROVIDER = "ollama-system-one"
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
        if questions[0].name == "needs_retrieval":
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
        openrouter_key = load_openrouter_api_key()
        if not openrouter_key:
            raise RuntimeError(
                "OpenRouter credentials are required: set OPENROUTER_API_KEY "
                "or configure ~/.local/share/opencode/auth.json"
            )
        decisions = OpenAICompatibleDecisionProvider(
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model=os.getenv("OPENROUTER_DECISION_MODEL", "deepseek/deepseek-v4-flash-0731").removeprefix("openrouter/"),
            api_key=openrouter_key,
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
    elif RAG_PROVIDER == "rag-harness":
        repository_root = Path(__file__).parents[2]
        rag_root = repository_root / "rag-harness"
        docs_index = Path(
            os.getenv("HARNESS_RAG_DOCS_INDEX", str(repository_root / "docs" / ".rag_index"))
        )
        rag = RagHarnessAdapter(str(rag_root), {"docs": str(docs_index)})
    else:
        raise RuntimeError(
            f"Unsupported HARNESS_RAG_PROVIDER={RAG_PROVIDER!r}; use demo or rag-harness"
        )
    return AdkRagWorkflow(decisions, rag)


def _build_model():
    try:
        from google.adk.models.lite_llm import LiteLlm
    except ImportError as exc:
        raise RuntimeError(
            "Ollama support requires the optional dependency: "
            "uv sync --extra adk --extra ollama"
        ) from exc
    return LiteLlm(model=f"ollama_chat/{OLLAMA_MODEL}")


root_agent = AdkRuntimeAdapter(
    _build_workflow(),
    AdkRuntimeConfig(
        app_name="adk_rag_harness",
        agent_name="adk_rag_router",
        model=_build_model(),
    ),
).build_agent()
