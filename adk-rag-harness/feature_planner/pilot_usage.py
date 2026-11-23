"""Consolidate the explicitly selected sources of usage for one pilot."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote
from urllib.request import Request, urlopen

from .evidence_views import _cell, context_savings, total_input_tokens
from .pricing import estimate_api_cost

TOKEN_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_creation_tokens", "reasoning_tokens",
)
CLAUDE_TOKEN_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_input_tokens",
    "cache_creation_input_tokens", "thinking_tokens",
)


@dataclass
class UsageRow:
    id: str
    source: str
    role: str
    provider: str
    model: str
    at: float | None
    status: str = "ok"
    usage: dict = field(default_factory=dict)
    slice_id: str | None = None
    attempt: str | None = None
    effort: str | None = None
    elapsed_ms: int | None = None
    input_items: int | None = None
    billed_usd: Decimal | None = None


def _counter(value):
    return value if type(value) is int and value >= 0 else None


def _token_values(usage, fields=TOKEN_FIELDS):
    return {
        name: value
        for name, key in zip(TOKEN_FIELDS, fields)
        if (value := _counter(usage.get(key))) is not None
    }


def _timestamp(value):
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp.timestamp() if timestamp.tzinfo else None


def _jsonl(path):
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                # A writer may still be appending the final line.
                if not line.endswith("\n"):
                    return
                raise ValueError(f"{path.name}:{number}: JSONL inválido") from exc
            if isinstance(record, dict):
                yield number, record


def _adk_rows(run):
    for number, event in enumerate(run["events"], start=1):
        if event["stage"] != "model" or event["status"] in {"started", "skipped_quota"}:
            continue
        yield UsageRow(
            id=f"adk:{run['invocation_id']}:{number}",
            source="ADK", role=event["role"], provider=event["provider"],
            model=event.get("reported_model") or event.get("model"), at=event.get("at"),
            status=event["status"], usage=_token_values(event["usage"]),
            slice_id=event.get("slice_id"), effort=event.get("effort"),
            attempt=f"{event.get('slice_attempt') or '—'}/{event.get('attempt') or '—'}",
            elapsed_ms=event.get("elapsed_ms"),
        )


def _claude_rows(paths):
    latest = {}
    for path in paths:
        for _, entry in _jsonl(path):
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message") or {}
            model = message.get("model")
            response_id = message.get("id")
            if (not isinstance(model, str) or not model.startswith("claude-")
                    or not isinstance(response_id, str) or not response_id):
                continue
            at = _timestamp(entry.get("timestamp"))
            if at is None:
                continue
            is_worker = entry.get("isSidechain") or path.parent.name == "subagents"
            usage = _token_values(message.get("usage") or {}, CLAUDE_TOKEN_FIELDS)
            previous = latest.get(response_id)
            if previous is None or at >= previous.at:
                stable_id = hashlib.sha256(response_id.encode()).hexdigest()
                latest[response_id] = UsageRow(
                    id=f"claude:{stable_id}", source="Claude Code Desktop",
                    role="subagente de implementação" if is_worker else "implementação",
                    provider="claude-code", model=model, at=at, status="observada",
                    usage={**(previous.usage if previous else {}), **usage},
                )
    return latest.values()


def _embedding_rows(directory):
    if not directory.is_dir():
        raise ValueError("O diretório do ledger de embeddings não existe.")
    for path in sorted(directory.glob("*.jsonl")):
        for number, entry in _jsonl(path):
            if entry.get("component") not in {"embedding_index", "embedding_query"}:
                continue
            provider = entry["provider"]
            yield UsageRow(
                id=f"embedding:{path.stem}:{number}",
                source="Ledger de embeddings", role=entry["component"], provider=provider,
                model=entry.get("routed_model") or entry["model"], at=_timestamp(entry.get("ts")),
                status=entry["status"], usage=_token_values(entry),
                elapsed_ms=_counter(entry.get("latency_ms")),
                input_items=_counter(entry.get("input_items")),
                billed_usd=_usd(entry["cost_usd"]) if entry.get("cost_source") == "provider" else None,
            )


def _usd(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Valor de cobrança em USD inválido.") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("A cobrança em USD deve ser finita e não negativa.")
    return amount


def _apply_billing(path, pilot, rows):
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("pilot") != pilot or receipt.get("currency") != "USD":
        raise ValueError("O recibo deve identificar este piloto e usar USD.")
    seen = set()
    for charge in receipt["charges"]:
        id_ = charge["usage_id"]
        if id_ in seen or id_ not in rows:
            raise ValueError("O recibo contém uma chamada repetida ou ausente do relatório.")
        row = rows[id_]
        if row.provider in {"ollama", "stub", "demo"} or row.billed_usd is not None:
            raise ValueError("A chamada já tem uma origem de cobrança ou usa um provedor local.")
        row.billed_usd = _usd(charge["usd"])
        seen.add(id_)


def _money(amounts):
    return f"{sum(amounts):.6f}" if amounts else None


def _render(pilot, rows, executions):
    lines = [
        "# Uso e custos do piloto", "", f"Piloto {_cell(pilot)}.", "",
        "— indica dado indisponível ou inaplicável. A cobrança real é informada pelo provedor ou pelo "
        "recibo correlacionado. Para Ollama local, a cobrança do provedor é zero. O equivalente de API "
        "aplica as tarifas de referência do harness por chamada, incluindo cache Claude como entrada padrão.",
        "",
        "## Cobertura",
        "",
        "Inclua todas as invocações desejadas, o transcript da implementação e o ledger dedicado do piloto. "
        "Chamadas bloqueadas antes de alcançar o provedor ficam fora da contagem.",
        "",
        "| Fonte | Registros | Com entrada total | Com saída |",
        "|---|---:|---:|---:|",
    ]
    by_source = defaultdict(list)
    by_role = defaultdict(list)
    for row in rows:
        by_source[row.source].append(row)
        by_role[row.role, row.provider, row.model].append(row)
    for source in ("ADK", "Claude Code Desktop", "Ledger de embeddings"):
        group = by_source[source]
        available_input = sum(total_input_tokens(row.provider, row.usage) is not None for row in group)
        available_output = sum("output_tokens" in row.usage for row in group)
        lines.append(f"| {source} | {len(group)} | {available_input} | {available_output} |")

    estimates = {
        row.id: estimate_api_cost({
            "at": row.at, "provider": row.provider, "model": row.model, "usage": row.usage,
        })
        for row in rows
    }
    charges = {
        row.id: Decimal(0) if row.provider in {"ollama", "stub", "demo"} else row.billed_usd
        for row in rows
    }
    lines.extend(["", "## Resumo por agente e modelo", "",
                  "Totais parciais quando faltam contadores ou valores. A entrada total inclui o cache. "
                  "O Claude Code o reporta em separado e o Codex já o inclui na entrada.", "",
                  "| Agente ou etapa | Tokens de entrada (total) | Tokens de saída | Provedor | Modelo | Chamadas | "
                  "Entrada reportada | Cache lido | Cache gravado | API eq. (USD) | Cobrança real (USD) |",
                  "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|"])
    for key, group in sorted(by_role.items()):
        totals = []
        for token in TOKEN_FIELDS[:4]:
            known = [row.usage[token] for row in group if token in row.usage]
            totals.append(sum(known) if known else None)
        amounts = [estimates[row.id][0] for row in group if estimates[row.id] is not None]
        confirmed = [charges[row.id] for row in group if charges[row.id] is not None]
        inputs = [tokens for row in group if (tokens := total_input_tokens(row.provider, row.usage)) is not None]
        raw_input, output, cache_read, cache_created = totals
        values = (key[0], sum(inputs) if inputs else None, output, *key[1:], len(group),
                  raw_input, cache_read, cache_created, _money(amounts), _money(confirmed))
        lines.append("| " + " | ".join(map(_cell, values)) + " |")

    lines.extend([
        "", "## Chamadas", "",
        "| Agente ou etapa | Tokens de entrada (total) | Tokens de saída | Corte | Provedor | Modelo | Fonte | "
        "Tent. corte/rota | Esforço | Estado | Duração (ms) | Itens embedding | Entrada reportada | Cache lido | "
        "Cache gravado | Raciocínio | API equivalente (USD) | Cobrança real (USD) | ID de uso |",
        "|---|---:|---:|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    rates = {}
    equivalent, billed = [], []
    for row in rows:
        estimate = estimates[row.id]
        api_text = None
        if estimate is not None:
            amount, rate = estimate
            equivalent.append(amount)
            reference = rates.setdefault(rate, len(rates) + 1)
            api_text = f"{amount:.6f} [API {reference}]"
        charge = charges[row.id]
        if charge is not None:
            billed.append(charge)
        values = (
            row.role, total_input_tokens(row.provider, row.usage), row.usage.get("output_tokens"),
            row.slice_id, row.provider, row.model, row.source, row.attempt,
            row.effort, row.status, row.elapsed_ms, row.input_items,
            *(row.usage.get(key) for key in TOKEN_FIELDS if key != "output_tokens"), api_text,
            f"{charge:.6f}" if charge is not None else None, row.id,
        )
        lines.append("| " + " | ".join(map(_cell, values)) + " |")

    lines.append("")
    if equivalent:
        lines.append(f"Subtotal API equivalente de {len(equivalent)}/{len(rows)} registros — US$ {sum(equivalent):.6f}.")
    if billed:
        lines.append(f"Subtotal de cobrança real conhecida de {len(billed)}/{len(rows)} registros — US$ {sum(billed):.6f}.")
    if rates:
        lines.extend(["", "### Tarifas de referência", ""])
        for rate, number in rates.items():
            tier = f", a partir de {rate.min_input} tokens de entrada" if rate.min_input else ""
            lines.append(
                f"- [API {number}]({rate.source}) — {rate.model}, desde {rate.valid_from}{tier}, "
                f"US$ {rate.input_per_million} de entrada e US$ {rate.output_per_million} de saída por milhão."
            )

    lines.extend(["", "## Economia estimada pelo RAG", "",
                  "Comparação hipotética por planner com tokens estimados por bytes UTF-8 ÷ 4. "
                  "Esses valores ficam fora dos totais de uso e cobrança.", "",
                  "| Invocação | Chunks no índice | Chunks no contexto | Tokens no índice | Tokens no contexto | Redução |",
                  "|---|---:|---:|---:|---:|---:|"])
    for run in executions:
        savings = context_savings(run)
        values = (run["invocation_id"], *savings) if savings else (run["invocation_id"], None, None, None, None, None)
        lines.append("| " + " | ".join(map(_cell, values)) + " |")
    return "\n".join(lines) + "\n"


def _publish(report, session, user, port):
    if not 1 <= port <= 65535:
        raise ValueError("Porta do ADK inválida.")
    user_path = quote(user, safe="")
    session_path = quote(session, safe="")
    url = f"http://127.0.0.1:{port}/apps/feature_planner/users/{user_path}/sessions/{session_path}"
    # Avoid publishing to a mistyped session ID.
    with urlopen(url, timeout=10):
        pass
    payload = json.dumps({
        "filename": "pilot-token-usage.md",
        "artifact": {"inlineData": {
            "mimeType": "text/markdown", "data": base64.b64encode(report.encode()).decode("ascii"),
        }},
    }).encode()
    request = Request(f"{url}/artifacts", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10):
        pass


def _write_report(output, report):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(report)
            handle.close()
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--execution", type=Path, action="append", default=[])
    parser.add_argument("--claude-session", type=Path, action="append", default=[])
    parser.add_argument("--embedding-ledger", type=Path)
    parser.add_argument("--billing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish-session")
    parser.add_argument("--adk-user", default="user")
    parser.add_argument("--adk-port", type=int, default=8173)
    args = parser.parse_args()
    if not (args.execution or args.claude_session or args.embedding_ledger):
        parser.error("Informe ao menos uma fonte de uso.")
    try:
        executions = {}
        for path in args.execution:
            run = json.loads(path.read_text(encoding="utf-8"))
            previous = executions.setdefault(run["invocation_id"], run)
            if run != previous:
                raise ValueError("Foram encontradas versões diferentes da mesma invocação.")
        rows = [row for run in executions.values() for row in _adk_rows(run)]
        claude_paths = list(dict.fromkeys(args.claude_session))
        for path in args.claude_session:
            claude_paths.extend(sorted((path.with_suffix("") / "subagents").glob("agent-*.jsonl")))
        rows.extend(_claude_rows(claude_paths))
        if args.embedding_ledger:
            rows.extend(_embedding_rows(args.embedding_ledger))
        rows.sort(key=lambda row: (row.at or 0, row.id))
        if args.billing:
            _apply_billing(args.billing, args.pilot, {row.id: row for row in rows})
        report = _render(args.pilot, rows, executions.values())
        _write_report(args.output, report)
        if args.publish_session:
            _publish(report, args.publish_session, args.adk_user, args.adk_port)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
