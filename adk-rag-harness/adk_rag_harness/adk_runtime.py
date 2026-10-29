"""Optional Google ADK boundary for the provider-neutral workflow.

The package remains importable without ``google-adk``. Installing the optional
``adk`` extra enables ``build_agent`` and ``build_app`` for ADK runtimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .usage import start_request
from .workflow import AdkRagWorkflow, WorkflowResult


class AdkRuntimeUnavailable(RuntimeError):
    """Raised when an ADK runtime operation is requested without its extra."""


@dataclass(frozen=True)
class AdkRuntimeConfig:
    app_name: str = "adk_rag_harness"
    agent_name: str = "adk_rag_router"
    model: Any = "gemini-flash-latest"
    description: str = "Routes evidence requests through a deterministic RAG policy."


class AdkRuntimeAdapter:
    """Expose the deterministic workflow as an optional ADK agent and app."""

    def __init__(
        self,
        workflow: AdkRagWorkflow,
        config: AdkRuntimeConfig | None = None,
        *,
        agent_factory: Callable[..., Any] | None = None,
        app_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.workflow = workflow
        self.config = config or AdkRuntimeConfig()
        self._agent_factory = agent_factory
        self._app_factory = app_factory

    def run_workflow(self, request: str, ADK_function: str = "") -> dict[str, Any]:
        """Execute one bounded request and return JSON data.

        Some local tool-calling models have emitted a JSON-schema placeholder
        such as ``{"type": "string"}`` instead of the argument value. When
        that happens, ADK also provides the generated function label; using it
        as a text fallback preserves routing while keeping the workflow in
        control.
        """

        if not isinstance(request, str) or request.strip() in {"", "{'type': 'string'}", '{"type": "string"}'}:
            request = ADK_function.replace("_", " ").strip() or str(request)

        return self._serialize_result(self.workflow.run(request))

    def build_agent(self) -> Any:
        """Create a Google ADK ``LlmAgent`` when the optional extra is present."""

        factory = self._agent_factory or self._load_agent_factory()
        return factory(
            model=self.config.model,
            name=self.config.agent_name,
            description=self.config.description,
            instruction=(
                "Call the run_workflow tool first for every user message, "
                "greetings included: the workflow, not you, decides whether "
                "evidence is needed. Treat its status, confidence, and evidence "
                "as authoritative. If status is direct, answer without citing "
                "sources. If status is clarify or blocked, ask for clarification "
                "or explain that evidence is insufficient. When status is "
                "retrieved, cite the returned source values. If action_gate is "
                "confirm or human_review, say the answer needs human confirmation."
            ),
            tools=[self.run_workflow],
            before_agent_callback=self._start_request,
        )

    @staticmethod
    def _start_request(callback_context: Any) -> None:
        """Every ledger line of one user message shares the ADK invocation id."""

        start_request(getattr(callback_context, "invocation_id", None))
        return None

    def build_app(self) -> Any:
        """Wrap the agent in the ADK ``App`` container used by ADK runtimes."""

        app_factory = self._app_factory or self._load_app_factory()
        return app_factory(name=self.config.app_name, root_agent=self.build_agent())

    @staticmethod
    def _serialize_result(result: WorkflowResult) -> dict[str, Any]:
        return {
            "status": result.status.value,
            "route_reason": result.route_reason,
            "confidence": result.confidence,
            "collection": result.collection,
            "strategy": result.strategy,
            "model_tier": result.model_tier.value,
            "action_gate": result.action_gate.value,
            "guardrail_safe": result.guardrail_safe,
            "evidence": [
                {
                    "source": chunk.source,
                    "text": chunk.text,
                    "score": chunk.score,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                }
                for chunk in result.chunks
            ],
        }

    @staticmethod
    def _load_agent_factory() -> Callable[..., Any]:
        try:
            from google.adk.agents import LlmAgent
        except ImportError as exc:
            raise AdkRuntimeUnavailable(
                "Google ADK is unavailable; install adk-rag-harness[adk]."
            ) from exc
        return LlmAgent

    @staticmethod
    def _load_app_factory() -> Callable[..., Any]:
        try:
            from google.adk.apps import App
        except ImportError as exc:
            raise AdkRuntimeUnavailable(
                "Google ADK App is unavailable; install adk-rag-harness[adk]."
            ) from exc
        return App
