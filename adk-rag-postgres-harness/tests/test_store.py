from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from adk_rag_postgres_harness.store import database_url, vector_literal


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


if __name__ == "__main__":
    unittest.main()
