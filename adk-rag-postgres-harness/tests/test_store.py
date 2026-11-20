from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from adk_rag_postgres_harness.embeddings import fit_dimension, query_text
from adk_rag_postgres_harness.store import database_url, identifier_terms, lexical_query, vector_literal


class StoreContractTests(unittest.TestCase):
    def test_vector_literal_is_pgvector_compatible(self):
        self.assertEqual(vector_literal([0.1, -2.0, 3.25]), "[0.1,-2,3.25]")

    def test_database_url_can_be_overridden(self):
        original = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = "postgresql://example/db"
            self.assertEqual(database_url(), "postgresql://example/db")
        finally:
            if original is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original

    def test_fit_dimension_cuts_and_normalizes(self):
        self.assertEqual(fit_dimension([3.0, 4.0, 9.0], dim=2), [0.6, 0.8])

    def test_fit_dimension_rejects_a_smaller_vector(self):
        with self.assertRaises(ValueError):
            fit_dimension([1.0], dim=2)

    def test_only_qwen3_queries_get_the_instruction(self):
        self.assertTrue(query_text("ollama:qwen3-embedding:4b", "login").startswith("Instruct: "))
        self.assertEqual(query_text("openrouter:voyageai/voyage-code-4", "login"), "login")

    def test_identifier_terms_split_camel_and_snake_case(self):
        self.assertEqual(
            identifier_terms("handleLogin user_id"),
            ["handlelogin", "handle", "login", "user", "id"],
        )

    def test_lexical_query_matches_any_term_and_skips_stopwords(self):
        self.assertEqual(lexical_query("onde fica o handleLogin?"), "'fica' | 'handlelogin' | 'handle' | 'login'")
        self.assertEqual(lexical_query("o que"), "")


if __name__ == "__main__":
    unittest.main()
