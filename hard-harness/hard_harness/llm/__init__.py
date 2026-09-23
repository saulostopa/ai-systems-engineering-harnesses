"""LLM providers — OpenRouter (default), Ollama (optional), Stub (offline).

Usage in agents:
    provider = make_provider()          # env: OPENROUTER_API_KEY | OLLAMA_API_URL
    text = provider.complete(prompt, system="...")
"""

from .providers import (
    LLMError,
    LLMProvider,
    OllamaProvider,
    OpenRouterProvider,
    StubProvider,
    Usage,
    make_provider,
)

__all__ = ["LLMError", "LLMProvider", "OllamaProvider", "OpenRouterProvider", "StubProvider", "Usage", "make_provider"]