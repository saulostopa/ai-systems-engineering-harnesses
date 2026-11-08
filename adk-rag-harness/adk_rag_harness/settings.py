"""Setting names of the ADK app; removed names fail loudly instead of being ignored."""

from __future__ import annotations

import os
from collections.abc import Mapping

REMOVED_SETTINGS = {
    "OLLAMA_API_BASE": "OLLAMA_BASE_URL",
    "OLLAMA_DECISION_BASE_URL": "OLLAMA_BASE_URL",
    "OLLAMA_MODEL": "HARNESS_CHAT_MODEL",
    "OPENROUTER_CHAT_MODEL": "HARNESS_CHAT_MODEL",
    "OLLAMA_DECISION_MODEL": "HARNESS_DECISION_MODEL",
    "OPENROUTER_DECISION_MODEL": "HARNESS_DECISION_MODEL",
    "HARNESS_ENABLE_GUARDRAIL": "HARNESS_GUARDRAIL=on",
    "HARNESS_OFFLINE": "nothing (remove it)",
}
REMOVED_VALUES = {
    ("HARNESS_DECISION_PROVIDER", "openrouter-system-one"): "openrouter",
    ("HARNESS_DECISION_PROVIDER", "ollama-system-one"): "ollama",
    ("HARNESS_DECISION_PROVIDER", "jev"): "typesafe",
    ("HARNESS_RAG_PROVIDER", "rag-harness"): "index",
}


def check_settings(environ: Mapping[str, str] = os.environ) -> None:
    problems = [f"{old} was renamed to {new}" for old, new in REMOVED_SETTINGS.items() if old in environ]
    problems += [
        f"{name}={value} is now {name}={new}"
        for (name, value), new in REMOVED_VALUES.items()
        if environ.get(name) == value
    ]
    if problems:
        raise RuntimeError("Outdated harness settings: " + "; ".join(problems) + ". See adk-rag-harness/.env.example.")

