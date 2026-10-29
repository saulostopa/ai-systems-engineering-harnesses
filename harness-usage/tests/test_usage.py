import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from harness_usage import ledger, new_request_id, record, usage_context
from harness_usage import budget, prices
from harness_usage.__main__ import main as cli
from harness_usage.report import build, render_csv, render_html, render_markdown, render_table


class UsageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "target-repo"
        self.repo.mkdir()
        env = {
            "XDG_DATA_HOME": str(self.base / "data"),
            "XDG_CACHE_HOME": str(self.base / "cache"),
            "HARNESS_USAGE_OFFLINE": "1",
            "HARNESS_PROJECT_ROOT": str(self.repo),
            "HARNESS_BUDGET_USD": "25",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("HARNESS_USAGE", "HARNESS_USAGE_DIR"):
            os.environ.pop(var, None)
        ledger._warned.clear()
        ledger._features.clear()
        ledger._checked_ignore.clear()
        budget.reset()
        prices._prices = None
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self, root=None):
        directory = (root or self.repo) / ".harness" / "usage"
        path = directory / f"{datetime.now(timezone.utc):%Y-%m}.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]


class LedgerTests(UsageTestCase):
    def test_record_writes_one_line_without_content(self):
        (self.repo / "docs" / "harness").mkdir(parents=True)
        (self.repo / "docs" / "harness" / "feature_list.json").write_text(
            json.dumps({"active_feature_id": "jev-adk-rag-harness", "features": []})
        )
        entry = record(
            component="decision", provider="openrouter", model="typesafe/jev-router",
            routed_model="deepseek/x", input_tokens=812, output_tokens=64, cost_usd=0.00041,
            latency_ms=930, operation="needs_retrieval", harness="adk-rag-harness",
        )
        [line] = self.lines()
        self.assertEqual(line, entry)
        self.assertEqual(line["project"], "target-repo")
        self.assertEqual(line["feature"], "jev-adk-rag-harness")
        self.assertEqual(line["cost_source"], "provider")
        self.assertEqual(
            set(line),
            {"schema", "ts", "run_id", "request_id", "harness", "component", "operation", "provider", "model",
             "routed_model", "input_tokens", "output_tokens", "cached_tokens", "cost_usd", "cost_source",
             "latency_ms", "status", "error_kind", "project", "feature"},
        )

    def test_single_in_progress_feature_is_used_when_no_active_id(self):
        (self.repo / "feature_list.json").write_text(
            json.dumps({"features": [{"id": "a", "status": "passing"}, {"id": "b", "status": "in_progress"}]})
        )
        self.assertEqual(record(component="agent", provider="ollama", model="llama")["feature"], "b")

    def test_cost_sources(self):
        local = record(component="chat", provider="ollama", model="llama3.1:8b", input_tokens=10)
        unknown = record(component="decision", provider="typesafe", model="systemone", input_tokens=10)
        unpriced = record(component="chat", provider="openrouter", model="typesafe/jev-router", input_tokens=10)
        self.assertEqual((local["cost_usd"], local["cost_source"]), (0.0, "local"))
        self.assertEqual((unknown["cost_usd"], unknown["cost_source"]), (None, "unknown"))
        self.assertEqual(unpriced["cost_source"], "unknown")

    def test_price_table_fills_missing_cost(self):
        cache = prices.cache_path()
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({"voyageai/voyage-code-4": [1.2e-07, 0]}))
        entry = record(component="embedding_index", provider="openrouter", model="voyageai/voyage-code-4", input_tokens=1000)
        self.assertEqual(entry["cost_source"], "price_table")
        self.assertAlmostEqual(entry["cost_usd"], 1.2e-04)

    def test_context_sets_request_and_overrides_component(self):
        request_id = new_request_id()
        with usage_context(request_id=request_id, component="embedding_index", harness="rag-harness"):
            inside = record(component="embedding_query", provider="openrouter", model="m", cost_usd=0.0)
        outside = record(component="embedding_query", provider="openrouter", model="m", cost_usd=0.0)
        self.assertEqual((inside["request_id"], inside["component"], inside["harness"]), (request_id, "embedding_index", "rag-harness"))
        self.assertEqual((outside["request_id"], outside["component"], outside["harness"]), (None, "embedding_query", "unknown"))

    def test_disabled_ledger_writes_nothing(self):
        with mock.patch.dict(os.environ, {"HARNESS_USAGE": "0"}):
            self.assertIsNone(record(component="chat", provider="openrouter", model="m", cost_usd=0.1))
        self.assertFalse((self.repo / ".harness").exists())

    def test_write_failure_never_raises(self):
        blocker = self.base / "a-file"
        blocker.write_text("x")
        with mock.patch.dict(os.environ, {"HARNESS_USAGE_DIR": str(blocker / "usage")}):
            self.assertIsNone(record(component="chat", provider="openrouter", model="m", cost_usd=0.1))
        self.assertIn("could not write the usage ledger", self.stderr.getvalue())

    def test_warns_when_ledger_is_not_ignored_by_git(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        record(component="chat", provider="openrouter", model="m", cost_usd=0.1)
        self.assertIn("is not ignored by Git", self.stderr.getvalue())

    def test_no_warning_when_ledger_is_ignored(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".gitignore").write_text(".harness/\n")
        record(component="chat", provider="openrouter", model="m", cost_usd=0.1)
        self.assertNotIn("not ignored", self.stderr.getvalue())

    def test_budget_warns_at_80_and_100_percent_across_ledgers(self):
        other = self.base / "other-repo"
        other.mkdir()
        record(component="chat", provider="openrouter", model="m", cost_usd=15.0, project_root=other)
        self.assertNotIn("budget", self.stderr.getvalue())
        record(component="chat", provider="openrouter", model="m", cost_usd=6.0)
        self.assertIn("84% of the US$ 25.00 budget", self.stderr.getvalue())
        record(component="chat", provider="openrouter", model="m", cost_usd=5.0)
        self.assertIn("104% of the US$ 25.00 budget", self.stderr.getvalue())
        self.assertEqual(len(ledger.registered_ledgers()), 2)


class ReportTests(UsageTestCase):
    def setUp(self):
        super().setUp()
        with usage_context(request_id="q1", harness="adk-rag-harness"):
            record(component="decision", provider="openrouter", model="typesafe/jev-router", routed_model="kimi", input_tokens=100, output_tokens=10, cost_usd=0.001)
            record(component="chat", provider="openrouter", model="typesafe/jev-router", routed_model="haiku", input_tokens=700, output_tokens=50, cost_usd=0.003)
        with usage_context(request_id="q2"):
            record(component="decision", provider="openrouter", model="typesafe/jev-router", status="error", error_kind="HTTP 402")
        self.month = f"{datetime.now(timezone.utc):%Y-%m}"
        self.dirs = [self.repo / ".harness" / "usage"]

    def test_groups_and_request_stats(self):
        report = build(self.dirs, self.month, ["component", "routed_model"])
        s = report["summary"]
        self.assertEqual((s["calls"], s["errors"], s["unpriced"]), (3, 1, 1))
        self.assertAlmostEqual(s["cost_usd"], 0.004)
        component = {row["key"]: row for row in report["groups"]["component"]}
        self.assertEqual(component["decision"]["calls"], 2)
        self.assertEqual(component["decision"]["errors"], 1)
        self.assertEqual(report["groups"]["routed_model"][0]["key"], "haiku")
        self.assertEqual(report["requests"]["questions"], 2)
        self.assertAlmostEqual(report["requests"]["max"], 0.004)

    def test_renderers(self):
        report = build(self.dirs, self.month, ["component"])
        self.assertIn("By component", render_table(report))
        self.assertIn("| decision |", render_markdown(report))
        self.assertTrue(render_csv(report).startswith("group,key,calls"))
        page = render_html(report)
        self.assertIn("<title>Harness Usage</title>", page)
        self.assertIn("prefers-color-scheme: dark", page)

    def test_cli_reads_repository_roots_and_writes_html(self):
        out = self.base / "usage.html"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli(["report", str(self.repo), "--format", "html", "--output", str(out)]), 0)
        self.assertIn("decision", out.read_text())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli(["report", "--all", "--by", "provider"])
        self.assertIn("openrouter", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
