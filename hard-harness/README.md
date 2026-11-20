"""Hard Harness — framework-agnostic executable orchestration.

Modules:
  core/     graph, runner, schemas, gates, events (the core)
  stores/   persistence (FileStateStore — state stays in the repo)
  adapters/ adk2 (optional inspiration), rag (context provider)
  agents/   specialists: planner, coder, reviewer, evidence
  llm/      providers: OpenRouter (default), Ollama (optional), Stub (offline)
"""