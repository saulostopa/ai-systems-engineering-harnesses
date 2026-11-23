"""Deterministic checks over the published evidence of a live planner run."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["passed", "failed", "not_run"]


class SourceExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    corpus: Literal["target", "reference"]
    project: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


class PilotEvalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1]
    required_sources: list[SourceExpectation] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> PilotEvalPolicy:
        return cls.model_validate_json(path.read_bytes())


def assess(execution: dict, receipt: dict, policy: PilotEvalPolicy) -> dict:
    if execution["invocation_id"] != receipt["invocation_id"]:
        raise ValueError("Eval evidence must come from the same ADK invocation.")

    retrieval = receipt["retrieval"]
    chunks = retrieval.get("retrieved", [])
    retrieved = {item["id"]: item for item in chunks}
    results = []

    def record(id_: str, status: Status, severity: str, finding: str, evidence=()):
        results.append({"id": id_, "status": status, "severity": severity,
                        "finding": finding, "evidence_ids": sorted(evidence)})

    valid_retrieval = retrieval.get("backend") == "postgres" and retrieval.get("status") == "completed"
    plan = execution.get("plan")
    slices = plan["slices"] if plan else []
    cited = {ref for item in slices for ref in item["evidence_ids"]}

    legacy_single_corpus = "reference_projects" not in retrieval
    for expected in policy.required_sources:
        matches = {
            item["id"] for item in chunks
            if item.get("origin", "target" if legacy_single_corpus else None) == expected.corpus
            and item.get("project", retrieval.get("project") if legacy_single_corpus else None) == expected.project
            and item["path"] in expected.paths
        }
        record(f"rag-{expected.id}", "passed" if matches else "failed" if valid_retrieval else "not_run",
               "high", "A fonte esperada apareceu no conjunto recuperado." if matches
               else "A fonte esperada para este caso não foi observada.", matches)
        if expected.corpus == "reference":
            references = matches & cited
            record(f"plano-{expected.id}", "passed" if references else "failed" if slices else "not_run",
                   "high", "O plano citou uma fonte esperada." if references
                   else "A fonte esperada não foi citada por um corte.", references)

    handed_to_model = [item for attempt in receipt["model_attempts"] for item in attempt["context"]]
    if valid_retrieval and handed_to_model:
        hashes_match = all(item["matches_postgres_payload"] for item in handed_to_model)
        record("hash-do-contexto", "passed" if hashes_match else "failed", "critical",
               "Conferência de hashes entre o recibo e os trechos preparados para as chamadas.")
    else:
        record("hash-do-contexto", "not_run", "critical", "Faltou contexto registrado para conferir.")

    if slices:
        allowed_projects = {retrieval.get("project"), *retrieval.get("reference_projects", [])}
        scoped = len(retrieved) == len(chunks) and all(
            item.get("project") in allowed_projects
            and item.get("origin") == ("target" if item.get("project") == retrieval.get("project") else "reference")
            for item in chunks
        )
        unmapped = []
        mismatched = []
        for item in slices:
            refs = set(item["evidence_ids"])
            allowed_paths = {retrieved[ref]["path"] for ref in refs & retrieved.keys()
                             if retrieved[ref].get("origin") == "target"}
            if not allowed_paths or not item["scope"]:
                unmapped.append(item["id"])
            if refs - retrieved.keys() or set(item["scope"]) != allowed_paths:
                mismatched.append(item["id"])
        findings = []
        if not scoped:
            findings.append("O recibo contém fontes com identificação ou origem incompatível.")
        if unmapped:
            findings.append("Cortes sem mapeamento para arquivos do Catálogo (" + ", ".join(unmapped) + ").")
        if mismatched:
            findings.append("Cortes com escopo divergente das fontes citadas (" + ", ".join(mismatched) + ").")
        record("escopo-do-plano", "failed" if findings else "passed", "critical",
               " ".join(findings) or "Cada corte tem escopo derivado de fontes citadas do Catálogo.")
    else:
        record("escopo-do-plano", "not_run", "critical", "Sem plano validado para conferir.")

    graph_ok = execution["status"] == "accepted"
    record("veredicto-do-grafo", "passed" if graph_ok else "failed", "high",
           "O grafo aceitou o planejamento." if graph_ok else "O grafo não aceitou o planejamento.")
    planning_passed = all(result["status"] == "passed" for result in results)
    record("paridade-e-testes-do-catalogo", "not_run", "high",
           "Requer diff, build, contrato, Playwright e evidência no ambiente de teste.")
    record("guardrails-do-executor", "not_run", "critical",
           "Requer executor integrado e testes de autorização, isolamento e saída de dados.")

    totals = dict(Counter(result["status"] for result in results))
    return {
        "version": 1, "policy_version": policy.version, "invocation_id": execution["invocation_id"],
        "graph_status": execution["status"], "totals": totals, "checks": results,
        "planning_evidence_status": "passed" if planning_passed else "requires_review",
        "test_or_release_authorization": "not_assessed",
    }


def markdown(report: dict) -> str:
    counts = report["totals"]
    rows = [
        "# Evals da invocação ADK", "",
        f'Invocação `{report["invocation_id"]}` · grafo `{report["graph_status"]}` · evidências do plano `{report["planning_evidence_status"]}`.', "",
        f'{len(report["checks"])} verificações · {counts.get("passed", 0)} aprovadas · '
        f'{counts.get("failed", 0)} reprovadas · {counts.get("not_run", 0)} sem execução.', "",
        "| Verificação | Resultado | Severidade | Evidência | Observação |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        evidence = ", ".join(check["evidence_ids"]) or "—"
        rows.append(f'| {check["id"]} | {check["status"]} | {check["severity"]} | {evidence} | {check["finding"]} |')
    rows.extend(["", "O relatório mede etapas do planejamento. Qualidade da entrega e autorização para release dependem de validações próprias.", ""])
    return "\n".join(rows)


def write_reports(directory: Path, report: dict) -> None:
    (directory / "eval-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (directory / "eval-summary.md").write_text(markdown(report), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    execution = json.loads((args.bundle / "execution.json").read_bytes())
    receipt = json.loads((args.bundle / "postgres-evidence.json").read_bytes())
    report = assess(execution, receipt, PilotEvalPolicy.load(args.policy))
    args.output.mkdir(parents=True, exist_ok=True)
    write_reports(args.output, report)
    return 0 if report["planning_evidence_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
