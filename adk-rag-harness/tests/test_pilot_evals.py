import importlib.util
import unittest

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from feature_planner.pilot_evals import PilotEvalPolicy, assess, markdown


@unittest.skipUnless(HAS_ADK, "requires the optional ADK dependency")
class PilotEvalsTests(unittest.TestCase):
    def test_missing_fipe_contract_scope_and_hash_are_reported_independently(self):
        policy = PilotEvalPolicy.model_validate({
            "version": 1,
            "required_sources": [{
                "id": "contrato-fipe", "corpus": "reference", "project": "fipe",
                "paths": ["consent.md"],
            }],
        })
        plan = {"slices": [{"id": "consent", "scope": ["adobe.md"], "evidence_ids": ["E1", "E2"]}]}
        execution = {"invocation_id": "e-test", "status": "accepted", "plan": plan}
        retrieval = {"status": "completed", "backend": "postgres", "project": "catalog",
                     "reference_projects": ["fipe"], "retrieved": [
                         {"id": "E1", "origin": "target", "project": "catalog", "path": "app.ts"},
                         {"id": "E2", "origin": "reference", "project": "fipe", "path": "adobe.md"},
                     ]}
        receipt = {"invocation_id": "e-test", "retrieval": retrieval, "model_attempts": [
            {"context": [{"id": "E1", "matches_postgres_payload": False}]},
        ]}
        report = assess(execution, receipt, policy)
        self.assertEqual(report["planning_evidence_status"], "requires_review")
        self.assertEqual(report["totals"], {"failed": 4, "passed": 1, "not_run": 2})
        self.assertIn("| escopo-do-plano | failed | critical |", markdown(report))

        plan["slices"][0]["scope"] = ["app.ts"]
        retrieval["retrieved"][1]["path"] = "consent.md"
        receipt["model_attempts"][0]["context"][0]["matches_postgres_payload"] = True
        report = assess(execution, receipt, policy)
        self.assertEqual(report["planning_evidence_status"], "passed")
        self.assertEqual(report["test_or_release_authorization"], "not_assessed")

        plan["slices"][0]["scope"] = []
        plan["slices"][0]["evidence_ids"] = ["E2"]
        report = assess(execution, receipt, policy)
        scope = next(check for check in report["checks"] if check["id"] == "escopo-do-plano")
        self.assertEqual(scope["status"], "failed")
        self.assertIn("sem mapeamento para arquivos do Catálogo (consent)", scope["finding"])
        self.assertEqual(report["planning_evidence_status"], "requires_review")
