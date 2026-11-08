"""Optional link to the shared harness-usage ledger; a no-op when it is absent.

Records Jev decisions, TypeSafe calls and the ADK conversation model (through
a LiteLLM logger). Prompts and answers are never passed to the ledger.
"""

from __future__ import annotations

import contextlib
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError


def _load():
    try:
        import harness_usage

        return harness_usage
    except ImportError:
        pass
    sibling = Path(__file__).resolve().parents[2] / "harness-usage"
    if sibling.is_dir():
        sys.path.insert(0, str(sibling))
        try:
            import harness_usage

            return harness_usage
        except ImportError:
            return None
    return None


_usage = _load()


def record(**fields: Any) -> None:
    if _usage is not None:
        _usage.record(harness="adk-rag-harness", **fields)


def usage_context(**values: Any):
    return _usage.usage_context(**values) if _usage is not None else contextlib.nullcontext()


def start_request(request_id: str) -> None:
    """Group every call of one user message under the ADK invocation id."""

    if _usage is not None:
        _usage.set_context(request_id=request_id)


def error_kind(exc: BaseException) -> str:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, HTTPError):
            return f"HTTP {current.code}"
        current = current.__cause__
    return type(exc).__name__


def elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def record_decision(
    *,
    provider: str,
    model: str,
    questions: list[Any],
    started: float,
    usage: dict[str, Any] | None = None,
    routed_model: str | None = None,
    error: BaseException | None = None,
    invalid: bool = False,
) -> None:
    usage = usage or {}
    details = usage.get("prompt_tokens_details") or {}
    record(
        component="decision",
        operation=",".join(q.name for q in questions),
        provider=provider,
        model=model,
        routed_model=routed_model,
        input_tokens=usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0,
        output_tokens=usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0,
        cached_tokens=details.get("cached_tokens", 0) if isinstance(details, dict) else 0,
        cost_usd=usage.get("cost"),
        latency_ms=elapsed_ms(started),
        status="error" if error else "ok",
        error_kind="invalid_response" if invalid else error_kind(error) if error else None,
    )


def litellm_logger(provider: str, model: str):
    """A LiteLLM logger that writes one ledger line per conversation-model call."""

    if _usage is None:
        return None
    from litellm.integrations.custom_logger import CustomLogger

    def _ms(start, end) -> int | None:
        try:
            return round((end - start).total_seconds() * 1000)
        except Exception:
            return None

    class LedgerLogger(CustomLogger):
        def _success(self, kwargs, response_obj, start_time, end_time) -> None:
            usage = getattr(response_obj, "usage", None)
            details = getattr(usage, "prompt_tokens_details", None)
            cost = getattr(usage, "cost", None)
            if cost is None and provider != "ollama":
                cost = kwargs.get("response_cost")
            record(
                component="chat",
                provider=provider,
                model=model,
                routed_model=getattr(response_obj, "model", None),
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cached_tokens=getattr(details, "cached_tokens", 0) or 0 if details else 0,
                cost_usd=cost,
                latency_ms=_ms(start_time, end_time),
            )

        def _failure(self, kwargs, start_time, end_time) -> None:
            exc = kwargs.get("exception")
            code = getattr(exc, "status_code", None)
            record(
                component="chat",
                provider=provider,
                model=model,
                latency_ms=_ms(start_time, end_time),
                status="error",
                error_kind=f"HTTP {code}" if code else type(exc).__name__ if exc else "unknown",
            )

        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            self._success(kwargs, response_obj, start_time, end_time)

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            self._success(kwargs, response_obj, start_time, end_time)

        def log_failure_event(self, kwargs, response_obj, start_time, end_time):
            self._failure(kwargs, start_time, end_time)

        async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
            self._failure(kwargs, start_time, end_time)

    return LedgerLogger()
