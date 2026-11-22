import base64
import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from feature_planner import pilot_usage


@unittest.skipUnless(HAS_ADK, "requires the optional ADK dependency")
class PilotUsageTests(unittest.TestCase):
    def test_consolidates_selected_sources_and_deduplicates_claude_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            execution = root / "execution.json"
            execution.write_text(json.dumps({
                "invocation_id": "run-1",
                "retrieval": {"baseline": {"chunks": 5, "utf8_bytes": 1000}},
                "events": [
                    {"stage": "model", "status": "started"},
                    {"stage": "model", "status": "skipped_quota"},
                    {
                        "stage": "model", "status": "succeeded", "role": "planner",
                        "provider": "claude-code", "model": "claude-haiku-5-5",
                        "at": 1795262400, "elapsed_ms": 120,
                        "context": [{"utf8_bytes": 80}],
                        "usage": {"input_tokens": 100, "output_tokens": 30,
                                  "cache_read_tokens": 0, "cache_creation_tokens": 0},
                    },
                ],
            }))
            transcript = root / "desktop.jsonl"
            message = {
                "id": "internal-provider-id", "model": "claude-opus-5-5",
                "content": [{"text": "private context"}],
                "usage": {"input_tokens": 10, "cache_read_input_tokens": 25,
                          "cache_creation_input_tokens": 0, "output_tokens": 1},
            }
            first = {"type": "assistant", "timestamp": "2026-11-21T00:00:00Z", "message": message}
            second = {
                **first, "timestamp": "2026-11-21T00:01:00Z",
                "message": {**message, "usage": {"output_tokens": 40}},
            }
            transcript.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n" + '{"incomplete":')
            subagents = root / "desktop" / "subagents"
            subagents.mkdir(parents=True)
            (subagents / "agent-a.jsonl").write_text(json.dumps({
                **second, "message": {**message, "id": "worker", "model": "claude-sonnet-5-5"},
            }) + "\n")
            ledger = root / "ledger"
            ledger.mkdir()
            embedding = {
                "component": "embedding_index", "provider": "ollama", "model": "qwen3-embedding:4b",
                "input_tokens": 88, "output_tokens": 0, "input_items": 3,
                "ts": "2026-11-20T12:00:00Z", "status": "ok",
            }
            missing = {**embedding, "component": "embedding_query", "input_tokens": None, "input_items": 1}
            (ledger / "2026-11.jsonl").write_text(json.dumps(embedding) + "\n" + json.dumps(missing) + "\n")

            billing = root / "billing.json"
            billing.write_text(json.dumps({
                "pilot": "catalogo", "currency": "USD",
                "charges": [{"usage_id": "adk:run-1:3", "usd": "0.35"}],
            }))
            report = root / "pilot-token-usage.md"
            with patch("sys.argv", [
                "pilot_usage", "--pilot", "catalogo", "--execution", str(execution),
                "--execution", str(execution), "--claude-session", str(transcript),
                "--embedding-ledger", str(ledger), "--billing", str(billing), "--output", str(report),
            ]):
                pilot_usage.main()
            text = report.read_text()
            self.assertIn("| ADK | 1 | 1 | 1 |", text)
            self.assertIn("| Claude Code Desktop | 2 | 2 | 2 |", text)
            self.assertIn("| Ledger de embeddings | 2 | 1 | 2 |", text)
            self.assertIn("| implementação | 35 | 40 | claude-code | claude-opus-5-5 | 1 | 10 | 25 |", text)
            self.assertIn("| subagente de implementação | 35 | 1 | claude-code | claude-sonnet-5-5 | 1 |", text)
            self.assertIn("| run-1 | 5 | 1 | 250 | 20 | 230 |", text)
            self.assertIn("US$ 0.350000", text)
            self.assertNotIn("private context", text)
            self.assertNotIn("internal-provider-id", text)

    def test_publishes_markdown_to_the_selected_local_adk_session(self):
        response = MagicMock()
        with patch.object(pilot_usage, "urlopen", return_value=response) as request:
            pilot_usage._publish("# Métricas\n", "pilot-v2", "user", 8180)
        self.assertEqual(request.call_count, 2)
        req = request.call_args.args[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:8180/apps/feature_planner/users/user/sessions/pilot-v2/artifacts")
        self.assertEqual(req.get_method(), "POST")
        payload = json.loads(req.data)
        self.assertEqual(payload["filename"], "pilot-token-usage.md")
        self.assertEqual(base64.b64decode(payload["artifact"]["inlineData"]["data"]).decode(), "# Métricas\n")
