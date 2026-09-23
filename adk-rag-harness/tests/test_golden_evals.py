import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from adk_rag_harness.contracts import DecisionAnswer, DecisionResult, EvidenceChunk, RetrievalResponse
from adk_rag_harness.workflow import AdkRagWorkflow


GOLDEN_PATH = Path(__file__).parents[1] / "evals" / "golden_prompts.json"


class ScriptedDecisions:
    def __init__(self, answer_sets):
        self.answer_sets = answer_sets

    def decide(self, state, questions):
        answers = self.answer_sets.pop(0)
        return DecisionResult(
            {name: DecisionAnswer(value, confidence) for name, (value, confidence) in answers.items()},
            provider="golden-eval",
        )


class EvalRag:
    def __init__(self, answerable):
        self.answerable = answerable
        self.requests = []

    def retrieve(self, request):
        self.requests.append(request)
        chunks = (EvidenceChunk("eval/source.md", "golden evidence", 0.97),) if self.answerable else ()
        return RetrievalResponse(request, chunks, self.answerable, "golden eval")


def load_cases():
    return json.loads(GOLDEN_PATH.read_text())


class GoldenPromptEvalTests(unittest.TestCase):
    def test_natural_language_prompts_preserve_workflow_contract(self):
        for case in load_cases():
            with self.subTest(case=case["id"]):
                expected = case["expected"]
                rag = EvalRag(expected["status"] == "retrieved")
                decisions = ScriptedDecisions(
                    [
                        {name: tuple(answer) for name, answer in answer_set.items()}
                        for answer_set in case["decision_answers"]
                    ]
                )
                result = AdkRagWorkflow(decisions, rag).run(case["prompt"])

                self.assertEqual(result.status.value, expected["status"])
                self.assertEqual(len(rag.requests), expected["rag_calls"])
                self.assertEqual(result.collection, expected["collection"])
                self.assertEqual(result.strategy, expected["strategy"])
                self.assertEqual(bool(result.chunks), expected["source_required"])
                if expected["source_required"]:
                    self.assertTrue(result.chunks[0].source)


if __name__ == "__main__":
    unittest.main()
