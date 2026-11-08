"""The ADK workflow over Postgres: real database, scripted decisions."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "adk-rag-harness"))

from adk_rag_harness.contracts import ActionGate, DecisionAnswer, DecisionResult, RetrievalRequest
from adk_rag_harness.workflow import AdkRagWorkflow, WorkflowStatus
from adk_rag_postgres_harness.adapter import COLLECTIONS, PostgresRagAdapter
from adk_rag_postgres_harness.embeddings import EMBED_DIM, embed_query, embedder_id
from adk_rag_postgres_harness.ingest import sync
from adk_rag_postgres_harness.memory import remember
from adk_rag_postgres_harness.query_log import MASKED_QUERY
from adk_rag_postgres_harness.retrieval import search_code
from adk_rag_postgres_harness.store import PostgresStore, database_url
from rag_harness.embeddings import NGramEmbedder

try:
    import psycopg
except ImportError:
    psycopg = None


def _database_available() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(database_url(), connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


class BrokenEmbedder(NGramEmbedder):
    def embed(self, text):
        raise RuntimeError("Ollama unavailable")


class Decisions:
    """Always retrieve, from the collection and with the strategy under test."""

    def __init__(self, collection, strategy):
        self.collection, self.strategy = collection, strategy

    def decide(self, state, questions):
        if questions[0].name == "needs_retrieval":
            return DecisionResult({"needs_retrieval": DecisionAnswer(True, 0.98)})
        return DecisionResult({
            "collection": DecisionAnswer(self.collection, 0.98),
            "strategy": DecisionAnswer(self.strategy, 0.98),
        })


@unittest.skipUnless(_database_available(), "PostgreSQL is not running: docker compose up -d postgres")
class PostgresWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.database = f"harness_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database}"')
        self.store = PostgresStore(urlunsplit(urlsplit(database_url())._replace(path=f"/{self.database}")))
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "shop"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "docs/harness/features/cart").mkdir(parents=True)
        (self.repo / "src/cart.ts").write_text("export function addToCart(item) {\n  return item;\n}\n")
        (self.repo / "docs/guide.md").write_text("# Guide\n\nCheckout works through addToCart.\n")
        (self.repo / "docs/harness/features/cart/progress.md").write_text("Coupons moved to the server.\n")
        self.embedder = NGramEmbedder(dim=EMBED_DIM)
        sync(str(self.repo), embedder=self.embedder, store=self.store)
        self.adapter = PostgresRagAdapter("shop", self.store, self.embedder)

    def tearDown(self):
        self.temp.cleanup()
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{self.database}" WITH (FORCE)')

    def _run(self, collection="code", strategy="hybrid", adapter=None, query="addToCart"):
        workflow = AdkRagWorkflow(Decisions(collection, strategy), adapter or self.adapter, collections=COLLECTIONS)
        return workflow.run(query)

    def _assert_blocked_for_review(self, result):
        self.assertEqual(result.status, WorkflowStatus.BLOCKED)
        self.assertEqual(result.action_gate, ActionGate.HUMAN_REVIEW)

    def test_the_chosen_collection_is_searched(self):
        result = self._run("code")
        self.assertEqual(result.status, WorkflowStatus.RETRIEVED)
        self.assertEqual({chunk.source for chunk in result.chunks}, {"src/cart.ts"})
        self.assertEqual((result.collection, result.strategy), ("code", "hybrid"))
        self.assertIn("return item", result.chunks[0].text)
        self.assertEqual(result.chunks[0].start_line, 1)
        self.assertIn("docs/guide.md", {chunk.source for chunk in self._run("docs").chunks})

    def test_each_strategy_uses_only_its_own_ranking(self):
        request = lambda strategy: RetrievalRequest("addToCart", "code", strategy)
        rows = {}
        for strategy in ("hybrid", "semantic", "keyword"):
            found = self.store.project("shop")
            vector = None if strategy == "keyword" else embed_query(self.embedder, "addToCart")
            rows[strategy] = self.store.search(
                found["id"], "addToCart", vector, embedder_id(self.embedder), "code", 5, strategy
            )
            self.assertTrue(rows[strategy], strategy)
        self.assertTrue(all(row["lexical_rank"] is None for row in rows["semantic"]))
        self.assertTrue(all(row["semantic_rank"] is None for row in rows["keyword"]))
        self.assertTrue(any(row["lexical_rank"] and row["semantic_rank"] for row in rows["hybrid"]))
        for strategy in ("hybrid", "semantic", "keyword"):
            self.assertTrue(self.adapter.retrieve(request(strategy)).chunks, strategy)

    def test_keyword_search_works_without_the_embedding_model(self):
        adapter = PostgresRagAdapter("shop", self.store, BrokenEmbedder(dim=EMBED_DIM))
        self.assertEqual(self._run("code", "keyword", adapter).status, WorkflowStatus.RETRIEVED)

    def test_memory_collection_finds_decisions_and_feature_logs(self):
        memory, _ = remember(
            "Coupons are validated on the server.", "shop", "PR 3", "decision", embedder=self.embedder, store=self.store
        )
        sources = [chunk.source for chunk in self._run("memory", query="coupons server").chunks]
        self.assertIn(f"{memory.id} (PR 3)", sources)
        self.assertIn("docs/harness/features/cart/progress.md", sources)

    def test_retrievals_are_recorded_with_the_choices_of_jev(self):
        self._run("code", "keyword")
        row = self.store.recent_queries("shop")[0]
        self.assertEqual((row["entry"], row["collection"], row["strategy"]), ("adk", "code", "keyword"))
        self.assertIn("src/cart.ts", row["results"])

    def test_a_question_with_a_credential_is_masked(self):
        secret = "sk-or-v1-abcdef0123456789abcdef"
        self._run("code", "keyword", query=f"addToCart {secret}")
        row = self.store.recent_queries("shop")[0]
        self.assertEqual(row["query"], MASKED_QUERY)

    def test_the_log_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {"HARNESS_QUERY_LOG": "off"}):
            self._run("code", "keyword")
        self.assertEqual(self.store.recent_queries("shop"), [])

    def test_a_search_survives_a_log_failure(self):
        with mock.patch.object(self.store, "add_query", side_effect=RuntimeError("no table")):
            self.assertEqual(self._run("code", "keyword").status, WorkflowStatus.RETRIEVED)

    def test_the_search_functions_do_not_record(self):
        search_code("addToCart", "shop", "code", 5, self.embedder, self.store)
        self.assertEqual(self.store.recent_queries("shop"), [])

    def test_a_changed_file_is_marked_stale(self):
        (self.repo / "src/cart.ts").write_text("// moved\nexport function addToCart(item) {\n  return item;\n}\n")
        self.assertTrue(self._run("code").chunks[0].stale)

    def test_no_evidence_blocks_for_review(self):
        self._assert_blocked_for_review(self._run("code", "keyword", query="zzzznothing"))

    def test_failures_block_for_review(self):
        down = PostgresStore("postgresql://harness:harness@localhost:1/none")
        cases = {
            "database down": PostgresRagAdapter("shop", down, self.embedder),
            "unknown project": PostgresRagAdapter("nope", self.store, self.embedder),
            "embedding model down": PostgresRagAdapter("shop", self.store, BrokenEmbedder(dim=EMBED_DIM)),
        }
        for name, adapter in cases.items():
            with self.subTest(name):
                result = self._run("code", "hybrid", adapter)
                self._assert_blocked_for_review(result)
                self.assertEqual(result.route_reason, "retrieval provider unavailable")

    def test_unknown_collection_or_strategy_blocks_for_review(self):
        self._assert_blocked_for_review(self._run("area"))
        self._assert_blocked_for_review(self._run("code", "magic"))

    def test_a_link_placed_after_indexing_is_not_evidence(self):
        outside = Path(self.temp.name) / "creds.txt"
        outside.write_text("OUTSIDE-MARKER\n")
        target = self.repo / "src/cart.ts"
        target.unlink()
        target.symlink_to(outside)
        result = self._run("code")
        self._assert_blocked_for_review(result)
        self.assertEqual(result.chunks, ())


if __name__ == "__main__":
    unittest.main()
