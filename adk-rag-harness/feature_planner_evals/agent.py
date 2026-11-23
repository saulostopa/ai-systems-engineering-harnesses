"""Run the real planner graph with synthetic sources and model responses."""

from feature_planner.model_router import ModelReply, ModelRouter, RoutingConfig
from feature_planner.workflow import build_workflow

POSITIVE = "Planeje a integração sandbox do AdFixus com consentimento FIPE."
MISSING = "Planeje a integração sandbox do AdFixus sem evidência de consentimento."
SCOPE = "Planeje a integração sandbox do AdFixus com referência fora do escopo."
OUTCOME = "Integrar o consentimento do AdFixus no Catálogo."
APPROVED = "A evidência sintética cobre a integração e o consentimento."
GAP = "Falta evidência do contrato de consentimento da FIPE."
FINDING = "A referência descreve o contrato de consentimento."


def search(mission):
    if mission not in {POSITIVE, MISSING, SCOPE}:
        return []
    reference = (
        ("docs/adobe.md", "Configuração de Adobe Target.")
        if mission == MISSING
        else ("docs/consentimento.md", "Contrato sintético de consentimento da FIPE.")
    )
    return [
        {
            "id": "E1", "origin": "target", "path": "src/consent.ts",
            "text": "Ponto de integração no Catálogo.",
        },
        {"id": "E2", "origin": "reference", "path": reference[0], "text": reference[1]},
    ]


async def model(_route, schema, _prompt, payload):
    mission = payload["mission"]
    missing = mission == MISSING
    if schema.__name__ == "WorkflowProposal":
        references = {POSITIVE: ["E1", "E2"], MISSING: ["E1"], SCOPE: ["E99"]}
        return ModelReply({
            "version": 1,
            "slices": [{
                "id": "consentimento",
                "outcome": OUTCOME,
                "acceptance": ["Verificar o contrato de consentimento antes de implementar."],
                "evidence_ids": references[mission],
                "depends_on": [],
            }],
        })
    if schema.__name__ == "SliceReport":
        findings = [] if missing else [{"observation": FINDING, "evidence_ids": ["E2"]}]
        return ModelReply({"findings": findings, "gaps": [GAP] if missing else []})
    return ModelReply({
        "verdict": "reject" if missing else "accept",
        "finding": GAP if missing else APPROVED,
    })


fallback = [{"provider": "ollama", "model": "synthetic-fixture"}]
root_agent = build_workflow(
    search, ModelRouter(
        RoutingConfig(planner=fallback, slice_verifier=fallback, global_evaluator=fallback),
        {"ollama": model},
    ),
)
