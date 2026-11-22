"""Course-style FAQ, execution replay and token comparison from sanitized events."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from string import Template

from .pricing import estimate_api_cost


def _count(value):
    return str(value) if value is not None else "—"


def _cell(value):
    return escape(_count(value)).replace("|", "&#124;").replace("\n", " ")


def _estimate(size):
    return (size + 3) // 4


def total_input_tokens(provider, usage):
    """Read total input using the provider's cache counter convention."""
    counters = ["input_tokens"]
    if provider == "claude-code":
        counters.extend(("cache_read_tokens", "cache_creation_tokens"))
    values = [usage.get(counter) for counter in counters]
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return sum(values)


def context_savings(run):
    baseline = run["retrieval"].get("baseline")
    planned = next(
        (event for event in run["events"]
         if event["stage"] == "model" and event["status"] == "succeeded" and event["role"] == "planner"),
        None,
    )
    if baseline is None or planned is None:
        return None
    full = _estimate(baseline["utf8_bytes"])
    selected = _estimate(sum(item["utf8_bytes"] for item in planned["context"]))
    return baseline["chunks"], len(planned["context"]), full, selected, full - selected


def token_report(run):
    events = [e for e in run["events"] if e["stage"] == "model"]
    terminal = [e for e in events if e["status"] != "started"]
    starts = sum(e["status"] == "started" for e in events)
    lines = [
        "# Uso de tokens", "",
        f"Execução {run['invocation_id']} · {starts} tentativas iniciadas · "
        f"{len({e['slice_id'] for e in events if e['status'] == 'started' and e['slice_id']})} cortes com chamada.",
        "",
        "Valores reportados pelo provedor variam por API. — indica dado indisponível. "
        "O total de entrada soma a leitura e a gravação de cache do Claude Code à entrada reportada. "
        "No Codex o cache já faz parte da entrada reportada. "
        "A coluna API equivalente aplica tarifas públicas de texto padrão aos contadores reportados. "
        "Ela é uma referência analítica para as assinaturas, separada da cobrança do provedor e do Databricks.",
        "",
        "| Etapa | Tokens de entrada (total) | Tokens de saída | Corte | Tent. corte | Rota | Tent. provedor | "
        "Provedor | Modelo | Esforço | Estado | Motivo | ms | Entrada reportada | Cache lido | Cache gravado | "
        "Raciocínio | API equivalente (USD) | Estimativa CLI (USD) |",
        "|---|---:|---:|---|---:|---:|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    estimates = []
    rates = {}
    for event in terminal:
        usage = event["usage"]
        estimate = estimate_api_cost(event)
        equivalent = "—"
        if estimate is not None:
            amount, rate = estimate
            estimates.append(amount)
            reference = rates.setdefault(rate, len(rates) + 1)
            equivalent = f"{amount:.6f} [API {reference}]"
        row = [
            event["role"], total_input_tokens(event["provider"], usage), usage.get("output_tokens"),
            event["slice_id"], event["slice_attempt"], event["attempt"], event.get("provider_attempt"),
            event["provider"], event["reported_model"] or event["model"], event["effort"],
            event["status"], event.get("failure_reason"), event["elapsed_ms"],
            *[usage.get(name) for name in ("input_tokens", "cache_read_tokens",
                                          "cache_creation_tokens", "reasoning_tokens")],
            equivalent, usage.get("cli_estimated_cost_usd"),
        ]
        lines.append("| " + " | ".join(map(_cell, row)) + " |")
    if estimates:
        lines.extend(["", f"Subtotal API equivalente das {len(estimates)} chamadas precificadas: "
                          f"US$ {sum(estimates):.6f}."])
        for rate, number in rates.items():
            tier = f", a partir de {rate.min_input:,} tokens de entrada" if rate.min_input else ""
            lines.append(
                f"- [API {number}]({rate.source}) — {rate.model}, tabela vigente desde {rate.valid_from}{tier}, "
                f"US$ {rate.input_per_million} entrada e US$ {rate.output_per_million} saída por milhão."
            )
    lines.extend(["", "A estimativa tarifa os tokens de cache do Claude Code como entrada padrão. "
                  "Codex e AGY usam os totais de entrada e saída reportados. O cálculo exclui cache com desconto, "
                  "taxas do gateway e acréscimos por raciocínio já contabilizado. "
                  "Rotas locais, modelos sem tarifa cadastrada e chamadas sem contadores ficam sem estimativa."])
    lines.extend(["", "## Economia estimada no contexto do planner", ""])
    savings = context_savings(run)
    if savings is not None:
        indexed_chunks, selected_chunks, full, selected, reduction = savings
        lines.extend([
            "| Comparação | Chunks | Tokens estimados |", "|---|---:|---:|",
            f"| Corpus indexado no snapshot | {indexed_chunks} | {full} |",
            f"| Contexto preparado para o planner | {selected_chunks} | {selected} |",
            f"| Redução estimada | — | {reduction} |", "",
        ])
    else:
        lines.extend(["A estimativa depende de um snapshot Postgres e de um planner concluído.", ""])
    lines.append("Método. Arredondamento para cima de bytes UTF-8 do texto divididos por quatro. "
                 "A comparação exclui instruções, serialização, demais etapas e o custo de embeddings. "
                 "O cenário com o corpus inteiro é hipotético e pode ultrapassar a janela do modelo.")
    return "\n".join(lines) + "\n"


_TEMPLATES = Path(__file__).with_name("templates")

_LABELS = {
    "accepted": ("Aceito", "good"),
    "needs_review": ("Requer revisão", "attention"),
    "clarify": ("Requer esclarecimento", "attention"),
    "blocked": ("Bloqueado", "attention"),
    "retrieving": ("Buscando fontes", "active"),
    "completed": ("Concluída", "good"),
    "planning": ("Planejando", "active"),
    "validated": ("Plano validado", "good"),
    "verifying": ("Revisando", "active"),
    "started": ("Iniciada", "active"),
    "succeeded": ("Concluída", "good"),
    "quota_exhausted": ("Cota esgotada", "attention"),
    "skipped_quota": ("Pulada por cota", "neutral"),
    "authentication_required": ("Requer autenticação", "attention"),
    "unavailable": ("Indisponível", "attention"),
    "invalid_output": ("Saída inválida", "attention"),
    "failed": ("Falhou", "attention"),
    "accept": ("Aceito", "good"),
    "reject": ("Rejeitado", "attention"),
    "retry": ("Nova tentativa", "attention"),
    "skipped": ("Pulado", "neutral"),
}

_ROLE_NAMES = {
    "planner": "Planejamento",
    "slice_worker": "Investigação do corte",
    "slice_verifier": "Revisão de corte",
    "global_evaluator": "Avaliação final",
}
_GRAPH_STEPS = {
    "retrieving": ("retrieval", "Solicitação recebida"),
    "planning": ("planner", "Contexto disponível"),
    "validated": ("planner", "Especificação validada"),
    "verifying": ("slice_verifier", "Revisões reunidas"),
    "synthesizing": ("result", "Síntese dos resultados"),
}


def _label(status):
    return _LABELS.get(status, (str(status), "neutral"))


def _asset(name):
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def _page(name, run, **items):
    status, tone = _label(run["status"])
    return Template(_asset(name)).substitute(
        css=_asset("pilot.css"), invocation=escape(run["invocation_id"]),
        status=escape(status), tone=tone, **items,
    )


def faq(run):
    retrieval = run["retrieval"]
    chunks = retrieval.get("retrieved", [])
    embedded = sum(bool(chunk.get("embedding_dimensions")) for chunk in chunks)
    status, _ = _label(run["status"])
    groups = (
        ("basico", "Básico", (
            ("O que o grafo produziu nesta execução?",
             f"O estado final foi {escape(status)}. Abra o <a href='replay.html'>replay</a> para ver os cortes e as tentativas."),
            ("Onde vejo como o harness está conectado?",
             "O <a href='architecture.html'>mapa da arquitetura</a> mostra como ADK, Postgres e os provedores se conectam."),
        )),
        ("intermediario", "Intermediário", (
            ("Como confirmo se os trechos recuperados têm embeddings?",
             f"Foram recuperados {len(chunks)} trechos. {embedded} tinham um vetor para o modelo do snapshot. "
             "Veja <code>embedding_dimensions</code> no <a href='postgres-evidence.json'>registro de recuperação</a>."),
            ("Por que o campo path às vezes aponta para um Markdown?",
             "O campo aponta para um arquivo de origem. Pode ser uma documentação ou um arquivo de código. "
             "Use <code>start_line</code> e <code>end_line</code> para localizar o trecho na revisão indexada."),
        )),
        ("avancado", "Avançado", (
            ("Como ligo um trecho do índice a uma chamada?",
             "Compare o ID e o <code>payload_sha256</code> do trecho recuperado com os da chamada. "
             "Hashes iguais confirmam o mesmo texto preparado para envio. O veredito precisa de avaliação separada."),
            ("O que a economia de tokens mede?",
             "O <a href='token-usage.md'>relatório</a> estima quanto texto indexado deixou de entrar no contexto do planner. "
             "As colunas de entrada e saída registram os contadores dos provedores."),
        )),
        ("limites", "Casos-limite", (
            ("Um rank semântico ausente significa que o trecho está sem vetor?",
             "O rank ausente indica que o trecho entrou pelo ramo textual. <code>embedding_dimensions</code> informa se "
             "havia um vetor compatível no índice."),
            ("O que acontece quando um provedor esgota a cota?",
             "Quando o router reconhece o sinal de cota, o grafo tenta a próxima rota configurada. "
             "Procure “Cota esgotada” no <a href='replay.html'>replay</a> ou <code>quota_exhausted</code> "
             "no <a href='execution.json'>registro JSON</a>."),
        )),
    )
    navigation = "".join(f'<li><a href="#{key}">{label}</a></li>' for key, label, _ in groups)
    sections = []
    for key, label, questions in groups:
        items = "".join(
            f'<details class="panel"><summary>{escape(question)}</summary><p class="answer">{answer}</p></details>'
            for question, answer in questions
        )
        sections.append(f'<section class="faq-group" id="{key}"><h2>{label}</h2>{items}</section>')
    return _page("faq.html", run, navigation=navigation, groups="".join(sections))


def _replay_events(run):
    retrieval = run["retrieval"]
    references = {chunk["id"]: chunk for chunk in retrieval.get("retrieved", [])}
    origin = next((event["at"] for event in run["events"]), 0)
    events = []
    for event in run["events"]:
        details = []
        if event["stage"] == "model":
            node = event["role"]
            title = _ROLE_NAMES.get(node, node)
            for label, key in (
                ("Corte", "slice_id"), ("Provedor", "provider"), ("Esforço", "effort"),
                ("Tentativa do corte", "slice_attempt"), ("Posição da rota", "attempt"),
                ("Tentativa no provedor", "provider_attempt"), ("Limite de turnos da CLI", "max_turns"),
                ("Categoria da falha", "failure_reason"),
            ):
                if event.get(key) is not None:
                    details.append([label, event[key]])
            model = event.get("reported_model") or event.get("model")
            if model:
                details.append(["Modelo", model])
            ids = [item["id"] for item in event.get("context", [])]
            details.append(["Trechos", ", ".join(ids) if ids else "Sem trechos diretos"])
            for ref in ids:
                chunk = references.get(ref)
                if chunk and "path" in chunk:
                    details.append([ref, f'{chunk["path"]}:{chunk["start_line"]}–{chunk["end_line"]}'])
            if event.get("elapsed_ms") is not None:
                details.append(["Duração", f"{event['elapsed_ms']} ms"])
            for key, label in [("input_tokens", "Tokens de entrada"), ("output_tokens", "Tokens de saída")]:
                if key in event.get("usage", {}):
                    details.append([label, event["usage"][key]])
        elif event["stage"] == "slice_review":
            node, title = "slice_verifier", "Veredito do corte"
            details = [["Corte", event["slice_id"]], ["Tentativa", event["attempt"]]]
        elif event["stage"] == "retrieval":
            node, title = "retrieval", "Recuperação de trechos"
            details = [["Trechos", len(retrieval.get("retrieved", []))]]
            for key, label in [("strategy", "Estratégia"), ("embedding_model", "Modelo de embedding")]:
                if key in retrieval:
                    details.append([label, retrieval[key]])
        else:
            node, title = _GRAPH_STEPS.get(event["status"], ("result", "Estado do grafo"))
        status, tone = _label(event["status"])
        events.append({
            "title": title, "node": node, "status": status, "tone": tone, "details": details,
            "offset": max(0, round((event["at"] - origin) * 1000)),
        })
    status, tone = _label(run["status"])
    outcome_details = []
    for item in run["slices"]:
        verdict = _label(item["verdict"])[0]
        note = f' · {item["finding"]}' if item.get("finding") else ""
        outcome_details.append([item["slice_id"], verdict + note])
        if item.get("report"):
            for observed in item["report"]["findings"]:
                outcome_details.append([", ".join(observed["evidence_ids"]), observed["observation"]])
            outcome_details.extend(["Lacuna", gap] for gap in item["report"]["gaps"])
    events.append({
        "title": "Resultado do grafo", "status": status, "tone": tone, "node": "result",
        "details": outcome_details,
        "offset": events[-1]["offset"] if events else 0,
    })
    return events


def replay(run):
    events = _replay_events(run)
    timeline = "".join(
        f'<li><button type="button"><span class="time">+{item["offset"] / 1000:.2f} s</span>'
        f'<strong>{escape(item["title"])}</strong>'
        f'<span class="event-state" data-tone="{item["tone"]}">{escape(item["status"])}</span></button></li>'
        for item in events
    )
    data = json.dumps(events, ensure_ascii=False).replace("<", "\\u003c")
    retrieval = run["retrieval"]
    chunks = len(retrieval.get("retrieved", []))
    backend = "Postgres + pgvector" if retrieval.get("backend") == "postgres" else "Índice de fontes"
    return _page(
        "replay.html", run, script=_asset("replay.js"), events=data, timeline=timeline,
        event_count=f"Eventos: {len(events)}", retrieval_summary=f"Trechos recuperados: {chunks}", backend=backend,
    )
