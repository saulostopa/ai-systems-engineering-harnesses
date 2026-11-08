"""Reports over one or more ledgers: table, CSV, Markdown or self-contained HTML."""

from __future__ import annotations

import calendar
import csv
import html
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .budget import budget_usd

GROUP_KEYS = {
    "day": lambda r: r.get("ts", "")[:10],
    "month": lambda r: r.get("ts", "")[:7],
    "component": lambda r: r.get("component"),
    "operation": lambda r: r.get("operation"),
    "harness": lambda r: r.get("harness"),
    "provider": lambda r: r.get("provider"),
    "model": lambda r: r.get("model"),
    "routed_model": lambda r: r.get("routed_model") or r.get("model"),
    "project": lambda r: r.get("project"),
    "feature": lambda r: r.get("feature"),
    "status": lambda r: r.get("status"),
    "request": lambda r: r.get("request_id"),
}
DEFAULT_GROUPS = ("component", "routed_model", "feature", "day")
COLUMNS = ("key", "calls", "errors", "input_tokens", "output_tokens", "cost_usd", "unpriced")


def ledger_dirs(paths: Iterable[str | Path]) -> list[Path]:
    """Accept repository roots or ledger directories."""

    dirs = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        candidate = path / ".harness" / "usage"
        dirs.append(candidate if candidate.is_dir() else path)
    return dirs


def load_records(dirs: Iterable[Path], month: str | None) -> list[dict[str, Any]]:
    records = []
    for directory in dirs:
        files = sorted(directory.glob("*.jsonl")) if month is None else [directory / f"{month}.jsonl"]
        for path in files:
            if not path.is_file():
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        continue
    return records


def group(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    keyfn = GROUP_KEYS[key]
    rows: dict[str, dict[str, Any]] = {}
    for r in records:
        name = keyfn(r) or "—"
        row = rows.setdefault(
            name,
            {"key": name, "calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced": 0},
        )
        row["calls"] += 1
        row["errors"] += r.get("status") != "ok"
        row["input_tokens"] += int(r.get("input_tokens") or 0)
        row["output_tokens"] += int(r.get("output_tokens") or 0)
        if r.get("cost_usd") is None:
            row["unpriced"] += 1
        else:
            row["cost_usd"] += float(r["cost_usd"])
    ordered = sorted(rows.values(), key=lambda row: (-row["cost_usd"], -row["calls"]))
    if key == "day":
        ordered.sort(key=lambda row: row["key"])
    return ordered


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[index]


def request_stats(records: list[dict[str, Any]]) -> dict[str, float] | None:
    per_request: dict[str, float] = {}
    for r in records:
        if r.get("request_id"):
            per_request[r["request_id"]] = per_request.get(r["request_id"], 0.0) + float(r.get("cost_usd") or 0.0)
    if not per_request:
        return None
    values = list(per_request.values())
    return {
        "questions": len(values),
        "average": sum(values) / len(values),
        "p50": _percentile(values, 0.5),
        "p95": _percentile(values, 0.95),
        "max": max(values),
    }


def summary(records: list[dict[str, Any]], month: str | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    total = sum(float(r.get("cost_usd") or 0.0) for r in records)
    info: dict[str, Any] = {
        "period": month or "all",
        "calls": len(records),
        "errors": sum(r.get("status") != "ok" for r in records),
        "cost_usd": total,
        "unpriced": sum(r.get("cost_usd") is None for r in records),
        "budget_usd": budget_usd(),
        "projection_usd": None,
    }
    if month == f"{now:%Y-%m}":
        days = calendar.monthrange(now.year, now.month)[1]
        info["projection_usd"] = total / now.day * days
    if info["budget_usd"] > 0 and month:
        info["budget_used"] = total / info["budget_usd"]
    return info


def build(dirs: list[Path], month: str | None, keys: Iterable[str]) -> dict[str, Any]:
    records = load_records(dirs, month)
    return {
        "ledgers": [str(d) for d in dirs],
        "summary": summary(records, month),
        "requests": request_stats(records),
        "groups": {key: group(records, key) for key in keys},
    }


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"US$ {value:.4f}" if value < 1 else f"US$ {value:.2f}"


def _summary_lines(report: dict[str, Any]) -> list[tuple[str, str]]:
    s = report["summary"]
    lines = [
        ("Period", s["period"]),
        ("Calls", f"{s['calls']} ({s['errors']} errors, {s['unpriced']} without price)"),
        ("Cost", _money(s["cost_usd"])),
    ]
    if s.get("projection_usd") is not None:
        lines.append(("Month-end projection", _money(s["projection_usd"])))
    if s.get("budget_used") is not None:
        lines.append(("Budget", f"{s['budget_used']:.1%} of {_money(s['budget_usd'])}"))
    r = report["requests"]
    if r:
        lines.append((
            "Per question",
            f"{r['questions']} questions; average {_money(r['average'])}, p50 {_money(r['p50'])}, "
            f"p95 {_money(r['p95'])}, max {_money(r['max'])}",
        ))
    return lines


def _cells(row: dict[str, Any]) -> list[str]:
    return [
        str(row["key"]), str(row["calls"]), str(row["errors"]),
        f"{row['input_tokens']:,}", f"{row['output_tokens']:,}", _money(row["cost_usd"]), str(row["unpriced"]),
    ]


def render_table(report: dict[str, Any]) -> str:
    out = io.StringIO()
    width = max(len(k) for k, _ in _summary_lines(report))
    for label, value in _summary_lines(report):
        out.write(f"{label:<{width}}  {value}\n")
    for key, rows in report["groups"].items():
        cells = [list(COLUMNS)] + [_cells(row) for row in rows]
        widths = [max(len(c[i]) for c in cells) for i in range(len(COLUMNS))]
        out.write(f"\nBy {key}\n")
        for i, row in enumerate(cells):
            out.write("  ".join(c.ljust(w) if j == 0 else c.rjust(w) for j, (c, w) in enumerate(zip(row, widths))) + "\n")
            if i == 0:
                out.write("  ".join("-" * w for w in widths) + "\n")
    return out.getvalue()


def render_markdown(report: dict[str, Any]) -> str:
    out = io.StringIO()
    out.write("| Item | Value |\n|---|---|\n")
    for label, value in _summary_lines(report):
        out.write(f"| {label} | {value} |\n")
    for key, rows in report["groups"].items():
        out.write(f"\n**By {key}**\n\n| " + " | ".join(COLUMNS) + " |\n|" + "---|" * len(COLUMNS) + "\n")
        for row in rows:
            out.write("| " + " | ".join(c.replace("|", "\\|") for c in _cells(row)) + " |\n")
    return out.getvalue()


def render_csv(report: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(("group",) + COLUMNS)
    for key, rows in report["groups"].items():
        for row in rows:
            writer.writerow([key] + [row[c] for c in COLUMNS])
    return out.getvalue()


HTML_STYLE = """
:root { --bg:#f7f7f5; --panel:#ffffff; --text:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc; --bar:#3d6fb6; --warn:#b5651d; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --panel:#1f1f1e; --text:#ecebe6; --muted:#a3a29b; --line:#33332f; --bar:#79a6e8; --warn:#e3a35c; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 -apple-system, "Segoe UI", sans-serif; }
main { max-width:1080px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 8px; }
.muted { color:var(--muted); font-size:13px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-top:16px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
.card b { display:block; font-size:20px; } .card span { color:var(--muted); font-size:13px; }
.card.warn b { color:var(--warn); }
.scroll { overflow-x:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { padding:7px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; } th { color:var(--muted); font-weight:600; font-size:13px; }
.bar { height:6px; background:var(--bar); border-radius:3px; min-width:1px; }
"""


def render_html(report: dict[str, Any]) -> str:
    s = report["summary"]
    esc = html.escape
    cards = [("Cost", _money(s["cost_usd"]), False), ("Calls", f"{s['calls']} ({s['errors']} errors)", s["errors"] > 0)]
    if s.get("projection_usd") is not None:
        cards.append(("Month-end projection", _money(s["projection_usd"]), False))
    if s.get("budget_used") is not None:
        cards.append(("Budget used", f"{s['budget_used']:.1%} of {_money(s['budget_usd'])}", s["budget_used"] >= 0.8))
    if report["requests"]:
        r = report["requests"]
        cards.append(("Per question (p50 / p95)", f"{_money(r['p50'])} / {_money(r['p95'])}", False))
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>Harness Usage</title><style>{HTML_STYLE}</style></head><body><main>",
        f"<h1>Harness usage — {esc(s['period'])}</h1>",
        f"<div class=\"muted\">Ledgers: {esc(', '.join(report['ledgers']))}</div><div class=\"cards\">",
    ]
    for label, value, warn in cards:
        parts.append(f"<div class=\"card{' warn' if warn else ''}\"><span>{esc(label)}</span><b>{esc(value)}</b></div>")
    parts.append("</div>")
    for key, rows in report["groups"].items():
        top = max((row["cost_usd"] for row in rows), default=0.0) or 1.0
        parts.append(f"<h2>By {esc(key)}</h2><div class=\"scroll\"><table><tr>")
        parts.extend(f"<th>{esc(c)}</th>" for c in COLUMNS)
        parts.append("<th></th></tr>")
        for row in rows:
            parts.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in _cells(row)))
            parts.append(f"<td style=\"width:120px\"><div class=\"bar\" style=\"width:{row['cost_usd'] / top * 100:.1f}%\"></div></td></tr>")
        parts.append("</table></div>")
    parts.append("</main></body></html>\n")
    return "".join(parts)


RENDERERS = {"table": render_table, "markdown": render_markdown, "csv": render_csv, "html": render_html}
