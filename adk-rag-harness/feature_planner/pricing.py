"""Public API reference prices for estimating subscription CLI runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class Rate:
    model: str
    input_per_million: str
    output_per_million: str
    source: str
    valid_from: str = "2026-11-20"
    min_input: int = 0


_CLAUDE = "https://platform.claude.com/docs/en/models/overview"
_HAIKU = "https://platform.claude.com/docs/en/models/haiku-5-5/overview"
_GEMINI = "https://aistudio.google.com/docs/pricing#gemini-3.8-flash"
_OPENAI = "https://developers.openai.com/api/docs/models/"

_RATES = {
    "claude-fable-5-2": (Rate("claude-fable-5-2", "8", "40", _CLAUDE),),
    "claude-opus-5-5": (Rate("claude-opus-5-5", "4", "20", _CLAUDE),),
    "claude-sonnet-5-5": (Rate("claude-sonnet-5-5", "2", "10", _CLAUDE),),
    "claude-haiku-5-5": (
        Rate("claude-haiku-5-5", "0.10", "0.50", _HAIKU),
        Rate("claude-haiku-5-5", "0.50", "2.50", _HAIKU, min_input=100_001),
    ),
    "gemini-3.8-flash": (
        Rate("gemini-3.8-flash", "0.75", "3.75", _GEMINI),
        Rate("gemini-3.8-flash", "1.50", "7.50", _GEMINI, valid_from="2027-01-01"),
    ),
    "gpt-6-sol": (
        Rate("gpt-6-sol", "2", "10", _OPENAI + "gpt-6-sol"),
        Rate("gpt-6-sol", "4", "15", _OPENAI + "gpt-6-sol", min_input=272_001),
    ),
    "gpt-6.2-sol": (Rate("gpt-6.2-sol", "2", "10", _OPENAI + "gpt-6.2-sol"),),
}

_ALIASES = {
    f"gemini-3.8-flash-{effort}": "gemini-3.8-flash"
    for effort in ("low", "medium", "high")
}


def estimate_api_cost(event: dict) -> tuple[Decimal, Rate] | None:
    """Apply uncached text API rates to one completed invocation of a CLI."""
    if event["provider"] not in {"agy", "claude-code", "codex"} or event.get("at") is None:
        return None
    model = event.get("reported_model") or event["model"]
    canonical = _ALIASES.get(model, model)
    usage = event["usage"]
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens)):
        return None
    if event["provider"] == "claude-code":
        input_tokens += usage.get("cache_read_tokens", 0) + usage.get("cache_creation_tokens", 0)
    day = datetime.fromtimestamp(event["at"], timezone.utc).date()
    available = (
        rate for rate in _RATES.get(canonical, ())
        if date.fromisoformat(rate.valid_from) <= day and rate.min_input <= input_tokens
    )
    rate = max(available, key=lambda row: (row.valid_from, row.min_input), default=None)
    if rate is None:
        return None
    cost = (input_tokens * Decimal(rate.input_per_million) +
            output_tokens * Decimal(rate.output_per_million)) / 1_000_000
    return cost, rate
