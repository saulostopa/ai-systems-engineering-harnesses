"""Publish a standalone evidence bundle from the events of one ADK invocation."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from google.genai import types

from .evidence_views import faq, replay, token_report
from .pilot_evals import PilotEvalPolicy, assess, write_reports
from .quiz import load_quiz, render_quiz

ARCHITECTURE = Path(__file__).with_name("architecture.json")
MIME_TYPES = {".json": "application/json", ".md": "text/markdown", ".html": "text/html"}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _execution(ctx, outcome):
    events = []
    retrieval = {"status": "not_run"}
    for event in ctx.session.events:
        if event.invocation_id != ctx.invocation_id:
            continue
        delta = event.actions.state_delta
        if "feature_retrieval" in delta:
            retrieval = delta["feature_retrieval"]
            events.append({"stage": "retrieval", "status": retrieval["status"], "at": event.timestamp})
        if "feature_model_route" in delta:
            events.append({"stage": "model", **delta["feature_model_route"], "at": event.timestamp})
        if "feature_slice_review" in delta:
            review = delta["feature_slice_review"]
            events.append({"stage": "slice_review", **review, "status": review["verdict"], "at": event.timestamp})
        if "feature_planning" in delta:
            events.append({"stage": "graph", "status": delta["feature_planning"]["status"], "at": event.timestamp})
    plan = outcome.get("plan")
    return {
        "version": 1, "invocation_id": ctx.invocation_id, "status": outcome["status"],
        "plan": {"slices": [
            {key: item[key] for key in ("id", "evidence_ids", "scope", "depends_on")}
            for item in plan["slices"]
        ]} if plan else None,
        "retrieval": retrieval, "events": events,
        "slices": [
            {
                **{key: result[key] for key in ("slice_id", "attempt", "verdict", "finding")},
                "report": result.get("report") if result["verdict"] == "accept" else None,
            }
            for result in outcome.get("results", {}).values()
        ],
    }


def _postgres_receipt(execution):
    retrieval = execution["retrieval"]
    terminal = [event for event in execution["events"] if event["stage"] == "model"
                and event["status"] not in {"started", "skipped_quota"}]
    references = {chunk["id"]: chunk for chunk in retrieval.get("retrieved", [])}
    calls = []
    for event in terminal:
        context = [{
            **item, "matches_postgres_payload": (
                references.get(item["id"], {}).get("payload_sha256") == item["payload_sha256"]
            ),
        } for item in event["context"]]
        calls.append({
            **{key: event[key] for key in ("role", "slice_id", "slice_attempt", "attempt", "provider", "status")},
            "provider_attempt": event.get("provider_attempt"),
            "failure_reason": event.get("failure_reason"),
            "context": context,
        })
    return {
        "invocation_id": execution["invocation_id"], "retrieval": retrieval, "model_attempts": calls,
        "interpretation": "Um hash igual liga o trecho preparado para a chamada ao snapshot indexado. "
                          "O resultado do modelo não prova que ele se baseou em cada trecho.",
    }


class EvidencePublisher:
    def __init__(
        self, output: Path, archify_bin: Path, quiz_spec: Path | None = None,
        *, eval_policy: PilotEvalPolicy | None = None,
    ):
        self.output = output.resolve()
        self.archify_bin = archify_bin.resolve(strict=True)
        if not self.archify_bin.is_file() or shutil.which("node") is None:
            raise ValueError("Pilot evidence requires Node.js and the Archify CLI.")
        self.quiz = load_quiz(quiz_spec)
        self.eval_policy = eval_policy

    def _render(self, execution):
        invocation = execution["invocation_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", invocation):
            raise ValueError("Invalid ADK invocation ID.")
        self.output.mkdir(parents=True, exist_ok=True)
        destination = self.output / invocation
        with TemporaryDirectory(prefix=".evidence-", dir=self.output) as staging:
            folder = Path(staging, "bundle")
            folder.mkdir()
            _write_json(folder / "execution.json", execution)
            postgres_receipt = _postgres_receipt(execution)
            _write_json(folder / "postgres-evidence.json", postgres_receipt)
            if self.eval_policy:
                write_reports(folder, assess(execution, postgres_receipt, self.eval_policy))
            for name, view in (("faq.html", faq), ("replay.html", replay), ("token-usage.md", token_report)):
                (folder / name).write_text(view(execution), encoding="utf-8")
            (folder / "quiz.html").write_text(render_quiz(execution, self.quiz), encoding="utf-8")
            shutil.copyfile(ARCHITECTURE, folder / "architecture.json")
            result = subprocess.run(
                ["node", str(self.archify_bin), "deliver", "architecture", "architecture.json",
                 "architecture.html", "--quality", "showcase", "--json"],
                cwd=folder, capture_output=True, text=True, encoding="utf-8", timeout=25, check=True,
            )
            receipt = json.loads(result.stdout)
            if receipt.get("ok") is not True:
                raise ValueError("Archify rejected the architecture artifact.")
            # The CLI reports absolute paths. Keep hashes and strip local checkout paths.
            for key in ("input", "output"):
                if isinstance(receipt.get(key), str):
                    receipt[key] = Path(receipt[key]).name
            _write_json(folder / "architecture-receipt.json", receipt)
            folder.rename(destination)
        return destination

    async def publish(self, ctx, outcome):
        execution = _execution(ctx, outcome)
        try:
            directory = await asyncio.to_thread(self._render, execution)
            files = []
            for path in sorted(directory.iterdir()):
                data = await asyncio.to_thread(path.read_bytes)
                await ctx.save_artifact(path.name, types.Part.from_bytes(data=data, mime_type=MIME_TYPES[path.suffix]))
                files.append(path.name)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return {"status": "failed", "invocation_id": ctx.invocation_id}
        return {"status": "published", "invocation_id": ctx.invocation_id, "files": files}
