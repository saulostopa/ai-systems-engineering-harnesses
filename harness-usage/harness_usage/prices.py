"""OpenRouter price list, cached for a day, used only when a response has no cost."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

PRICE_URLS = (
    "https://openrouter.ai/api/v1/models",
    "https://openrouter.ai/api/v1/embeddings/models",
)
TTL_S = 24 * 3600

_prices: dict[str, tuple[float, float]] | None = None


def cache_path() -> Path:
    base = os.getenv("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "harness" / "openrouter-prices.json"


def _fetch() -> dict[str, tuple[float, float]]:
    prices: dict[str, tuple[float, float]] = {}
    for url in PRICE_URLS:
        with urllib.request.urlopen(url, timeout=10) as res:
            for model in json.loads(res.read()).get("data", []):
                pricing = model.get("pricing") or {}
                try:
                    prompt = float(pricing.get("prompt", "nan"))
                    completion = float(pricing.get("completion", 0) or 0)
                except (TypeError, ValueError):
                    continue
                # Routers such as typesafe/jev-router publish -1: no fixed price.
                if prompt >= 0 and completion >= 0:
                    prices[model["id"]] = (prompt, completion)
    return prices


def load_prices() -> dict[str, tuple[float, float]]:
    global _prices
    if _prices is not None:
        return _prices
    path = cache_path()
    if path.is_file() and time.time() - path.stat().st_mtime < TTL_S:
        _prices = {k: tuple(v) for k, v in json.loads(path.read_text()).items()}
        return _prices
    if os.getenv("HARNESS_USAGE_OFFLINE", "0").lower() in {"1", "true", "yes"}:
        _prices = {}
        return _prices
    try:
        _prices = _fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_prices))
    except Exception:
        _prices = {}
    return _prices


def price_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = load_prices()
    key = model.removeprefix("openrouter/")
    if key not in prices:
        return None
    prompt, completion = prices[key]
    return input_tokens * prompt + output_tokens * completion
