import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from feature_planner.model_clients import _agy_reply, _claude_reply, _codex_reply, claude_code
    from feature_planner.model_router import FailureReason, ModelFailure, Route, RoutingConfig
    from feature_planner.workflow import Review
    from pydantic import ValidationError


@unittest.skipUnless(HAS_ADK, "requires the optional ADK dependency")
class FeatureModelClientsTests(unittest.IsolatedAsyncioTestCase):
    def test_sample_configuration_is_valid_and_agy_rejects_anthropic(self):
        path = Path(__file__).resolve().parents[1] / "feature_planner" / "model-router.example.json"
        RoutingConfig.model_validate_json(path.read_text())
        with self.assertRaises(ValidationError):
            Route(provider="agy", model="claude-sonnet-5-5")

    async def test_claude_requires_a_native_login_before_sending_the_prompt(self):
        route = Route(provider="claude-code", model="claude-opus-5-5")
        reply = {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}
        run = AsyncMock(return_value=(0, json.dumps(reply)))
        with patch("feature_planner.model_clients._run", run), patch.dict("os.environ", {
            "ANTHROPIC_API_KEY": "example-api-key", "CLAUDE_CODE_USE_BEDROCK": "1",
        }):
            with self.assertRaisesRegex(ModelFailure, "authentication_required"):
                await claude_code(route, Review, "Use the evidence.", {"evidence": "test"})
        run.assert_awaited_once()
        args, _, stdin, env = run.await_args.args
        self.assertEqual(args, ["claude", "auth", "status", "--json"])
        self.assertEqual(stdin, "")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)

    async def test_claude_configures_turn_budget_per_route(self):
        auth = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}
        value = {"verdict": "accept", "finding": "Supported."}
        result = {"type": "result", "subtype": "success", "is_error": False, "structured_output": value}
        for override, effective in (({}, "2"), ({"max_turns": 4}, "4")):
            route = Route(provider="claude-code", model="claude-haiku-5-5", **override)
            run = AsyncMock(side_effect=[(0, json.dumps(auth)), (0, json.dumps(result))])
            with patch("feature_planner.model_clients._run", run):
                reply = await claude_code(route, Review, "Review the evidence.", {})
            args = run.await_args.args[0]
            self.assertEqual(args[args.index("--max-turns") + 1], effective)
            self.assertEqual(reply.value, value)

        with self.assertRaises(ValidationError):
            Route(provider="codex", model="gpt-6-sol", max_turns=4)
        with self.assertRaises(ValidationError):
            Route(provider="claude-code", model="claude-haiku-5-5", max_turns=9)

    def test_claude_quota_warning_preserves_the_successful_response(self):
        value = {"verdict": "accept", "finding": "Supported."}
        reply = _claude_reply(0, [
            {"type": "system", "subtype": "init", "model": "claude-sonnet-5-5"},
            {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning"}},
            {"type": "result", "subtype": "success", "is_error": False, "structured_output": value,
             "usage": {"input_tokens": 10, "cache_read_input_tokens": 0, "extra": "not usage"}},
        ])
        self.assertEqual(reply.value, value)
        self.assertEqual(reply.usage, {"input_tokens": 10, "cache_read_tokens": 0})
        self.assertEqual(reply.reported_model, "claude-sonnet-5-5")
        self.assertTrue(reply.quota_warning)

    def test_claude_categorizes_terminal_errors_without_using_error_text(self):
        base = {"type": "result", "is_error": True, "usage": {"output_tokens": 7}}
        for failure, kind, reason in (
            ({"subtype": "error_max_turns"}, "unavailable", FailureReason.TURN_LIMIT),
            ({"subtype": "error_max_structured_output_retries"},
             "invalid_output", FailureReason.STRUCTURED_OUTPUT_RETRIES_EXHAUSTED),
            ({"subtype": "error_during_execution", "stop_reason": "refusal"},
             "unavailable", FailureReason.REFUSAL),
            ({"subtype": "error_during_execution", "errors": ["private diagnostic"]},
             "unavailable", FailureReason.CLI_EXECUTION_ERROR),
        ):
            with self.subTest(reason=reason), self.assertRaises(ModelFailure) as raised:
                _claude_reply(1, [{**base, **failure}])
            self.assertEqual(raised.exception.kind, kind)
            self.assertEqual(raised.exception.reason, reason)
            self.assertEqual(raised.exception.usage, {"output_tokens": 7})
            self.assertNotIn("private diagnostic", str(raised.exception))

        with self.assertRaises(ModelFailure) as raised:
            _claude_reply(1, [{"type": "assistant", "error": "server_error"}, base])
        self.assertEqual(raised.exception.reason, FailureReason.PROVIDER_UNAVAILABLE)

    def test_counters_come_from_the_final_cli_result(self):
        value = {"verdict": "accept", "finding": "Supported."}
        agy = _agy_reply(0, [
            {"event": "step_update", "step_update": {"usage": {"input_tokens": 30}}},
            {"event": "result", "result": {"status": "SUCCESS", "structured_output": value,
                                          "usage": {"input_tokens": 80, "thinking_tokens": 8}}},
        ])
        codex = _codex_reply(0, [
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(value)}},
            {"type": "turn.completed", "usage": {"input_tokens": 50, "reasoning_output_tokens": 8}},
        ])
        self.assertEqual(agy.value, codex.value)
        self.assertEqual(agy.usage, {"input_tokens": 80, "reasoning_tokens": 8})
        self.assertEqual(codex.usage, {"input_tokens": 50, "reasoning_tokens": 8})

    def test_transient_and_ambiguous_errors_stop_the_call(self):
        with self.assertRaisesRegex(ModelFailure, "unavailable"):
            _agy_reply(1, [{"event": "result", "result": {"status": "ERROR", "error": "limit reached"}}])
        with self.assertRaisesRegex(ModelFailure, "unavailable"):
            _codex_reply(1, [{"type": "turn.failed", "error": {"message": "HTTP 429: server busy"}}])
        with self.assertRaisesRegex(ModelFailure, "quota_exhausted"):
            _codex_reply(1, [{"type": "turn.failed", "error": {"message": "You’ve hit your usage limit."}}])
