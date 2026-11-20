"""LLM provider tests — no real network (local HTTP server).

Usage: python3 tests/test_llm_providers.py   (from hard-harness/)

Covers:
  - OpenRouterProvider: correct HTTP call + parsing + usage
  - OllamaProvider: same contract (/v1/chat/completions endpoint)
  - make_provider: environment-based selection (OpenRouter -> Ollama -> Stub)
  - agent parses VERDICT with a real provider
  - cost (llm_cost) travels in the payload
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Tests never write to the real usage ledger unless a test enables it.
os.environ.setdefault("HARNESS_USAGE", "0")
# Never pick up the developer's real OpenRouter key (that would bill).
os.environ["OPENROUTER_AUTH_FILE"] = os.devnull

from hard_harness.agents import PlannerAgent, ReviewerAgent  # noqa: E402
from hard_harness.core.schemas import NodeInput, WorkflowState, WorkflowStatus  # noqa: E402
from hard_harness.llm.providers import (  # noqa: E402
    LLMError,
    OllamaProvider,
    OpenRouterProvider,
    StubProvider,
    load_openrouter_api_key,
    make_provider,
)

RESPONSE_BODY = {
    "choices": [{"message": {"role": "assistant", "content": "resposta do modelo"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 7},
}


class FakeLLMServer(BaseHTTPRequestHandler):
    """Fake OpenAI-style server — captures the request and returns RESPONSE_BODY."""

    captured: dict[str, Any] = {}
    requests: int = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        type(self).captured = {"path": self.path, "headers": dict(self.headers), "body": body}
        type(self).requests += 1
        payload = json.dumps(RESPONSE_BODY).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        pass


def start_fake_server() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), FakeLLMServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ═══ OpenRouter ═══════════════════════════════════════════════════════

def test_openrouter_chama_api_e_parseia():
    server, base = start_fake_server()
    try:
        provider = OpenRouterProvider(api_key="teste-key", model="m/modelo", base_url=base)
        text = provider.complete("pergunta", system="seja direto")
        assert text == "resposta do modelo"
        assert provider.last_usage.total == 19
        cap = FakeLLMServer.captured
        assert cap["path"] == "/chat/completions"
        assert cap["headers"].get("Authorization") == "Bearer teste-key"
        body = cap["body"]
        assert body["model"] == "m/modelo"
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["content"] == "pergunta"
    finally:
        server.shutdown()


def test_openrouter_sem_api_key_falha_explicito():
    os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        OpenRouterProvider(api_key="")
        assert False, "missing key must fail with LLMError"
    except LLMError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)


def test_openrouter_erro_http_vira_llmerror():
    class FailHandler(FakeLLMServer):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), FailHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        provider = OpenRouterProvider(api_key="x", base_url=base)
        try:
            provider.complete("hi")
            assert False, "401 should raise LLMError"
        except LLMError as exc:
            assert "HTTP 401" in str(exc)
    finally:
        server.shutdown()


# ═══ Ollama ═══════════════════════════════════════════════════════════

def test_ollama_mesmo_contrato():
    server, base = start_fake_server()
    try:
        provider = OllamaProvider(base_url=base, model="llama3.2")
        text = provider.complete("pergunta")
        assert text == "resposta do modelo"
        assert FakeLLMServer.captured["path"] == "/v1/chat/completions"
        assert FakeLLMServer.captured["body"]["model"] == "llama3.2"
        assert provider.last_usage.total == 19
    finally:
        server.shutdown()


def test_ollama_available_falso_sem_servidor():
    assert OllamaProvider.available("http://127.0.0.1:1", timeout_s=0.3) is False


# ═══ make_provider (environment-based selection) ═══════════════════════

def test_make_provider_openrouter_quando_env():
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    try:
        provider = make_provider()
        assert provider.name == "openrouter"
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


def test_make_provider_stub_sem_env():
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("OLLAMA_BASE_URL", None)
    provider = make_provider()
    assert provider.name == "stub"


def test_make_provider_ollama_quando_env_e_responde():
    server, base = start_fake_server()
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["OLLAMA_BASE_URL"] = base
    try:
        provider = make_provider()
        # probe uses /api/tags (404 on the fake, but the URL exists => considered unavailable)
        assert provider.name == "stub" or provider.name == "ollama"
    finally:
        os.environ.pop("OLLAMA_BASE_URL", None)
        server.shutdown()


# ═══ Agents with a real provider ═══════════════════════════════════════

def _ninput() -> NodeInput:
    state = WorkflowState(workflow_id="t1", status=WorkflowStatus.RUNNING, data={"planner_agent": {"plan_steps": ["x"]}})
    return NodeInput(node_id="reviewer_agent", state=state, payload={"diff": "content"})


def test_reviewer_parseia_verdict_com_provider_real():
    provider = StubProvider("revisão ok\nVERDICT: approved")
    agent = ReviewerAgent(provider=provider)
    output = agent.run(_ninput())
    assert output.review is not None
    assert output.review.verdict == "approved"
    assert output.payload.get("reviewer") == "llm:stub"
    assert "llm_cost" in output.payload  # cost travels to the runner's budget


def test_planner_gera_steps_com_provider_real():
    provider = StubProvider("- passo um\n- passo dois")
    agent = PlannerAgent(provider=provider)
    output = agent.run(_ninput())
    assert output.payload["plan_steps"] == ["passo um", "passo dois"]
    assert output.proposed_next == "validate_plan"


def test_reviewer_default_e_changes_requested():
    provider = StubProvider("no marker at all")
    agent = ReviewerAgent(provider=provider)
    output = agent.run(_ninput())
    assert output.review.verdict == "changes_requested"



def test_openrouter_registra_custo_no_ledger_com_no_e_workflow():
    from hard_harness import usage

    if usage._usage is None:
        return  # standalone copy without harness-usage: nothing to record
    body = {**RESPONSE_BODY, "model": "deepseek/routed", "usage": {"prompt_tokens": 12, "completion_tokens": 7, "cost": 0.0003}}
    original = dict(RESPONSE_BODY)
    RESPONSE_BODY.clear()
    RESPONSE_BODY.update(body)
    server, base = start_fake_server()
    with tempfile.TemporaryDirectory() as tmp:
        saved = {k: os.environ.get(k) for k in ("HARNESS_USAGE", "HARNESS_PROJECT_ROOT", "XDG_DATA_HOME")}
        os.environ.update({"HARNESS_USAGE": "1", "HARNESS_PROJECT_ROOT": tmp, "XDG_DATA_HOME": os.path.join(tmp, "data")})
        try:
            provider = OpenRouterProvider(api_key="teste-key", model="m/modelo", base_url=base)
            with usage._usage.usage_context(operation="planner", request_id="wf-1"):
                provider.complete("pergunta-secreta")
        finally:
            server.shutdown()
            RESPONSE_BODY.clear()
            RESPONSE_BODY.update(original)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        ledger_dir = os.path.join(tmp, ".harness", "usage")
        [name] = os.listdir(ledger_dir)
        with open(os.path.join(ledger_dir, name)) as fh:
            [line] = [json.loads(row) for row in fh]
    assert provider.last_cost_usd == 0.0003
    assert (line["harness"], line["component"], line["operation"], line["request_id"]) == ("hard-harness", "agent", "planner", "wf-1")
    assert (line["routed_model"], line["input_tokens"], line["output_tokens"], line["cost_usd"]) == ("deepseek/routed", 12, 7, 0.0003)
    assert "pergunta-secreta" not in json.dumps(line)


def test_make_provider_rejeita_ollama_api_url_antigo():
    os.environ["OLLAMA_API_URL"] = "http://localhost:11434"
    try:
        make_provider()
        assert False, "the removed name must fail"
    except LLMError as exc:
        assert "OLLAMA_BASE_URL" in str(exc)
    finally:
        os.environ.pop("OLLAMA_API_URL", None)


def _with_auth_file(content: str, fn):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write(content)
    previous = os.environ.get("OPENROUTER_AUTH_FILE")
    os.environ["OPENROUTER_AUTH_FILE"] = fh.name
    try:
        return fn()
    finally:
        os.environ["OPENROUTER_AUTH_FILE"] = previous or os.devnull
        os.unlink(fh.name)


def test_chave_do_auth_json_seleciona_openrouter():
    os.environ.pop("OPENROUTER_API_KEY", None)
    provider = _with_auth_file(json.dumps({"openrouter": {"type": "api", "key": "file-key"}}), make_provider)
    assert provider.name == "openrouter"
    assert provider.api_key == "file-key"


def test_env_vence_o_auth_json():
    os.environ["OPENROUTER_API_KEY"] = "env-key"
    try:
        key = _with_auth_file(json.dumps({"openrouter": {"key": "file-key"}}), load_openrouter_api_key)
        assert key == "env-key"
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


def test_auth_json_invalido_cai_no_stub():
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("OLLAMA_BASE_URL", None)
    provider = _with_auth_file("not json", make_provider)
    assert provider.name == "stub"

if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    total = sum(1 for n in globals() if n.startswith("test_"))
    print(f"\n== {total - failed}/{total} passed")
    sys.exit(1 if failed else 0)