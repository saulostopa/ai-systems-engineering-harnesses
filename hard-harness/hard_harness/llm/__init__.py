"""LLM providers — OpenRouter (default), Ollama (optional), Stub (offline).

Usage in agents:
    provider = make_provider()          # env: OPENROUTER_API_KEY (or auth.json) | OLLAMA_BASE_URL
    text = provider.complete(prompt, system="...")
"""

from .providers import (
    LLMError,
    LLMProvider,
    OllamaProvider,
    OpenRouterProvider,
    StubProvider,
    Usage,
    load_openrouter_api_key,
    make_provider,
)

__all__ = ["LLMError", "LLMProvider", "OllamaProvider", "OpenRouterProvider", "StubProvider", "Usage", "load_openrouter_api_key", "make_provider"]