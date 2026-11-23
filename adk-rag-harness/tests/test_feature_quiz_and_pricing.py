import importlib.util
import unittest
from collections import Counter
from datetime import datetime
from decimal import Decimal

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from pydantic import ValidationError

    from feature_planner.evidence_views import token_report
    from feature_planner.pricing import estimate_api_cost
    from feature_planner.quiz import QuizSpec, load_quiz, render_quiz


def cli_event(provider, model, day="2026-11-21", **usage):
    return {
        "provider": provider, "model": model, "reported_model": None, "usage": usage,
        "at": datetime.fromisoformat(day + "T12:00:00+00:00").timestamp(),
        "stage": "model", "role": "global_evaluator", "status": "succeeded", "elapsed_ms": 400,
        "slice_id": None, "slice_attempt": None, "attempt": 1, "effort": "medium",
    }


@unittest.skipUnless(HAS_ADK, "requires the optional ADK dependency")
class QuizAndPricingTests(unittest.TestCase):
    def test_reference_costs_are_dated_and_distinct_from_cli_cost(self):
        event = cli_event("agy", "gemini-3.8-flash-medium", input_tokens=10_000, output_tokens=2_000,
                          reasoning_tokens=1_000, cache_read_tokens=4_000, cli_estimated_cost_usd=0.001)
        old, rate = estimate_api_cost(event)
        self.assertEqual(old, Decimal("0.015"))
        self.assertEqual(rate.model, "gemini-3.8-flash")
        report = token_report({"events": [event], "invocation_id": "test", "retrieval": {}})
        self.assertIn("0.015000 [API 1] | 0.001", report)
        self.assertIn(rate.source, report)
        event["at"] = datetime.fromisoformat("2027-01-02T00:00:00+00:00").timestamp()
        self.assertEqual(estimate_api_cost(event)[0], Decimal("0.030"))

    def test_pricing_uses_supported_counters_and_routes(self):
        claude = cli_event("claude-code", "claude-haiku-5-5", input_tokens=3_000, output_tokens=2_000,
                           cache_read_tokens=6_000, cache_creation_tokens=1_000)
        self.assertEqual(estimate_api_cost(claude)[0], Decimal("0.002"))
        codex = cli_event("codex", "gpt-6-sol", input_tokens=10_000, output_tokens=2_000, cache_read_tokens=6_000)
        self.assertEqual(estimate_api_cost(codex)[0], Decimal("0.040"))
        codex["reported_model"] = "unpriced-gpt-model"
        self.assertIsNone(estimate_api_cost(codex))
        self.assertIsNone(estimate_api_cost(cli_event("ollama", "qwen2.5:14b", input_tokens=1, output_tokens=1)))
        self.assertIsNone(estimate_api_cost(cli_event("codex", "gpt-6-sol", output_tokens=2_000)))

    def test_token_report_shows_total_input_without_counting_codex_cache_twice(self):
        claude = cli_event("claude-code", "claude-haiku-5-5", input_tokens=2, output_tokens=4_853,
                           cache_read_tokens=20_491, cache_creation_tokens=395)
        codex = cli_event("codex", "gpt-6-sol", input_tokens=10_000, output_tokens=2_000,
                          cache_read_tokens=6_000)
        partial = cli_event("claude-code", "claude-haiku-5-5", input_tokens=2, output_tokens=1)
        report = token_report({"events": [claude, codex, partial], "invocation_id": "test", "retrieval": {}})
        self.assertIn("| Etapa | Tokens de entrada (total) | Tokens de saída |", report)
        self.assertIn("| global_evaluator | 20888 | 4853 |", report)
        self.assertIn("| global_evaluator | 10000 | 2000 |", report)
        self.assertIn("| global_evaluator | — | 1 |", report)

    def test_quiz_has_two_categories_per_level_and_escapes_its_data(self):
        quiz = load_quiz()
        self.assertEqual(Counter(item.category for item in quiz.questions), {"technical": 6, "business": 6})
        self.assertEqual(Counter(item.level for item in quiz.questions), {1: 3, 2: 3, 3: 3, 4: 3})
        bank = quiz.model_dump()
        bank["questions"][0]["stem"]["pt"] = "</script><b>untrusted</b>"
        rendered = render_quiz({"invocation_id": "test"}, QuizSpec.model_validate(bank))
        self.assertIn(r"\u003c/script>", rendered)
        self.assertNotIn("</script><b>untrusted</b>", rendered)
        bank["questions"][0]["category"] = "business"
        with self.assertRaises(ValidationError):
            QuizSpec.model_validate(bank)
