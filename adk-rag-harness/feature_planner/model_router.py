"""Role-based provider routing for the read-only feature planning graph."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Role = Literal["planner", "slice_worker", "slice_verifier", "global_evaluator"]
Failure = Literal["quota_exhausted", "unavailable", "authentication_required", "invalid_output"]


class FailureReason(str, Enum):
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    REQUEST_REJECTED = "request_rejected"
    HTTP_REQUEST_FAILED = "http_request_failed"
    CLI_START_FAILED = "cli_start_failed"
    CLI_EXECUTION_ERROR = "cli_execution_error"
    MISSING_CLI_RESULT = "missing_cli_result"
    TURN_LIMIT = "turn_limit"
    REFUSAL = "refusal"
    MODEL_MISMATCH = "model_mismatch"
    OUTPUT_LIMIT = "output_limit"
    INVALID_JSON = "invalid_json"
    STRUCTURED_OUTPUT_RETRIES_EXHAUSTED = "structured_output_retries_exhausted"
    MISSING_STRUCTURED_OUTPUT = "missing_structured_output"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"


REVIEW_ROLES = frozenset({"slice_verifier", "global_evaluator"})
MAX_REVIEW_PROVIDER_ATTEMPTS = 2
CLAUDE_DEFAULT_MAX_TURNS = 2

REVIEW_FALLBACK_REASONS = frozenset({
    FailureReason.TIMEOUT, FailureReason.TRANSPORT_ERROR, FailureReason.PROVIDER_UNAVAILABLE,
    FailureReason.TURN_LIMIT,
})
REVIEW_RETRY_REASONS = REVIEW_FALLBACK_REASONS | {
    FailureReason.CLI_EXECUTION_ERROR, FailureReason.MISSING_CLI_RESULT, FailureReason.RATE_LIMITED,
    FailureReason.OUTPUT_LIMIT, FailureReason.INVALID_JSON,
    FailureReason.STRUCTURED_OUTPUT_RETRIES_EXHAUSTED, FailureReason.MISSING_STRUCTURED_OUTPUT,
    FailureReason.SCHEMA_VALIDATION_FAILED,
}


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["ollama", "claude-code", "codex", "agy"]
    model: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")]
    effort: Literal["minimal", "low", "medium", "high", "xhigh", "max"] | None = None

    max_turns: Annotated[int, Field(strict=True, ge=1, le=8)] | None = None

    @model_validator(mode="after")
    def validate_provider(self):
        if self.max_turns is not None and self.provider != "claude-code":
            raise ValueError("max_turns is only supported by Claude Code.")
        if self.provider == "agy" and not self.model.startswith("gemini-"):
            raise ValueError("The AGY provider accepts Gemini models only.")
        if self.provider == "ollama" and self.effort is not None:
            raise ValueError("Ollama does not accept an effort setting in this app.")
        if self.effort == "minimal" and self.provider != "codex":
            raise ValueError("Minimal effort is only supported by Codex.")
        if self.effort == "max" and self.provider == "codex":
            raise ValueError("Use xhigh for the highest Codex effort.")
        return self


Chain = Annotated[list[Route], Field(min_length=1, max_length=4)]


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner: Chain
    slice_worker: Chain | None = None
    slice_verifier: Chain
    global_evaluator: Chain

    @model_validator(mode="after")
    def unique_providers(self):
        for chain in (self.planner, self.slice_worker or self.slice_verifier, self.slice_verifier, self.global_evaluator):
            if len({route.provider for route in chain}) != len(chain):
                raise ValueError("Each role may list a provider at most once.")
        return self


class ModelFailure(Exception):
    def __init__(self, kind: Failure, usage: dict | None = None, *, reason: FailureReason | None = None):
        super().__init__(kind)
        self.kind = kind
        self.usage = usage or {}
        self.reason = FailureReason(reason) if reason is not None else None


@dataclass(frozen=True)
class ModelReply:
    value: object
    usage: dict = field(default_factory=dict)
    quota_warning: bool = False
    reported_model: str | None = None


@dataclass(frozen=True)
class Attempt:
    route: Route
    number: int
    status: str
    elapsed_ms: int | None = None
    reply: ModelReply | None = None
    usage: dict = field(default_factory=dict)
    provider_attempt: int | None = None
    failure_reason: FailureReason | None = None

    def metadata(self):
        return {
            **self.route.model_dump(),
            "max_turns": (self.route.max_turns or CLAUDE_DEFAULT_MAX_TURNS)
            if self.route.provider == "claude-code" else None,
            "attempt": self.number,
            "provider_attempt": self.provider_attempt,
            "status": self.status,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "elapsed_ms": self.elapsed_ms,
            "reported_model": self.reply.reported_model if self.reply else None,
            "quota_warning": self.reply.quota_warning if self.reply else False,
            "usage": self.usage,
        }


ModelClient = Callable[[Route, type[BaseModel], str, dict], Awaitable[ModelReply]]


class ModelRouter:
    def __init__(self, config: RoutingConfig, clients: dict[str, ModelClient]):
        self.config = config
        self.clients = clients

    async def attempts(
        self, role: Role, schema: type[BaseModel], prompt: str, data: dict, blocked: set[str]
    ) -> AsyncIterator[Attempt]:
        chain = getattr(self.config, role) or self.config.slice_verifier
        review_role = role in REVIEW_ROLES
        limit = MAX_REVIEW_PROVIDER_ATTEMPTS if review_role else 1
        for number, route in enumerate(chain, start=1):
            if route.provider in blocked:
                yield Attempt(route, number, "skipped_quota")
                continue
            for provider_attempt in range(1, limit + 1):
                yield Attempt(route, number, "started", provider_attempt=provider_attempt)
                outcome = await self._call(route, number, provider_attempt, schema, prompt, data)
                if outcome.status == "quota_exhausted":
                    blocked.add(route.provider)
                yield outcome
                if outcome.status == "quota_exhausted":
                    break
                if not review_role or outcome.failure_reason not in REVIEW_RETRY_REASONS:
                    return
                if provider_attempt == limit and outcome.failure_reason not in REVIEW_FALLBACK_REASONS:
                    return

    async def _call(self, route, number, provider_attempt, schema, prompt, data) -> Attempt:
        start = monotonic()
        reply = None
        usage = {}
        reason = None
        try:
            reply = await self.clients[route.provider](route, schema, prompt, data)
            usage = reply.usage
            schema.model_validate(reply.value)
        except ModelFailure as exc:
            status = exc.kind
            usage = exc.usage
            reason = exc.reason
        except ValueError:
            status = "invalid_output"
            reason = FailureReason.SCHEMA_VALIDATION_FAILED
        else:
            status = "succeeded"
        return Attempt(
            route, number, status, round((monotonic() - start) * 1000), reply, usage,
            provider_attempt=provider_attempt, failure_reason=reason,
        )
