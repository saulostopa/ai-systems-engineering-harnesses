"""The arithmetic behind the evaluation numbers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))
sys.path.insert(0, str(Path(__file__).parents[1]))

from run_retrieval import first_relevant_rank, summarize


class MetricTests(unittest.TestCase):
    def test_rank_is_the_first_relevant_path(self):
        self.assertEqual(first_relevant_rank(["a", "b", "c"], ["c", "b"]), 2)
        self.assertIsNone(first_relevant_rank(["a"], ["b"]))

    def test_summary(self):
        summary = summarize([1, 4, None, 8])
        self.assertEqual(summary["hit@1"], 0.25)
        self.assertEqual(summary["hit@3"], 0.25)
        self.assertEqual(summary["hit@5"], 0.5)
        self.assertEqual(summary["hit@8"], 0.75)
        self.assertEqual(summary["mrr"], round((1 + 0.25 + 0.125) / 4, 3))


if __name__ == "__main__":
    unittest.main()
