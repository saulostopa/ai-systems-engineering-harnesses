"""ADK Web traces for model routes that run outside the native LLM flow."""

from __future__ import annotations

import json
import time

from opentelemetry import trace

_TRACER = trace.get_tracer(__name__)
_USAGE_COUNTERS = (
    "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_creation_tokens", "reasoning_tokens",
)


def _structured_result(value):
    """Project validated model output onto fields safe for the trace."""
    if "slices" in value:
        return {
            "slices": [
                {
                    "id": item["id"],
                    "evidence_ids": item["evidence_ids"],
                    "depends_on": item["depends_on"],
                    "acceptance_checks": len(item["acceptance"]),
                }
                for item in value["slices"]
            ],
        }
    if "findings" in value:
        return {
            "findings": [{"evidence_ids": item["evidence_ids"]} for item in value["findings"]],
            "gap_count": len(value["gaps"]),
        }
    return {"verdict": value["verdict"]}


def record_model_trace(ctx, event, attempt, schema, payload):
    """Publish the sanitized request and response against the terminal event ID."""
    state = event.actions.state_delta["feature_model_route"]
    model = state["reported_model"] or state["model"]
    request = {
        "role": state["role"],
        "provider": state["provider"],
        "model": state["model"],
        "effort": state["effort"],
        "route_attempt": state["attempt"],
        "provider_attempt": state["provider_attempt"],
        "max_turns": state["max_turns"],
        "slice_id": state["slice_id"],
        "slice_attempt": state["slice_attempt"],
        "response_schema": schema.__name__,
        "evidence_ids": [item["id"] for item in payload.get("evidence", [])],
        "evidence_sources": [
            {"id": item["id"], "project": item["project"], "origin": item["origin"]}
            for item in payload.get("evidence", []) if "project" in item and "origin" in item
        ],
    }
    usage = {
        key: value for key in _USAGE_COUNTERS
        if type(value := attempt.usage.get(key)) is int and value >= 0
    }
    response = {
        "status": state["status"],
        "model": model,
        "elapsed_ms": attempt.elapsed_ms,
        "usage": usage,
    }
    if attempt.failure_reason is not None:
        response["failure_reason"] = attempt.failure_reason.value
    if attempt.status == "succeeded" and attempt.reply is not None:
        response["output"] = _structured_result(attempt.reply.value)

    # ADK Web's trace exporter indexes model spans using the persisted Event ID.
    # The installed frontend also understands these JSON attributes on OTel spans.
    ended = time.time_ns()
    span = _TRACER.start_span(
        f"generate_content {model}",
        start_time=ended - (attempt.elapsed_ms or 0) * 1_000_000,
        attributes={
            "gen_ai.operation.name": "generate_content",
            "gen_ai.provider.name": state["provider"],
            "gen_ai.request.model": state["model"],
            "gen_ai.response.model": model,
            "gen_ai.conversation.id": ctx.session.id,
            "gcp.vertex.agent.invocation_id": ctx.invocation_id,
            "gcp.vertex.agent.event_id": event.id,
            "gcp.vertex.agent.llm_request": json.dumps(request, ensure_ascii=False),
            "gcp.vertex.agent.llm_response": json.dumps(response, ensure_ascii=False),
            **{f"gen_ai.usage.{key}": usage[key] for key in ("input_tokens", "output_tokens") if key in usage},
        },
    )
    if attempt.status != "succeeded":
        span.set_status(trace.StatusCode.ERROR, attempt.status)
    span.end(end_time=ended)
