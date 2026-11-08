"""Append-only token and cost ledger shared by the harnesses.

Each provider call becomes one JSON line in
``<project>/.harness/usage/YYYY-MM.jsonl``. Prompts, answers, code and keys
are never written. Recording is best effort: any failure is reported once on
stderr and never interrupts the caller.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .budget import check_budget
from .prices import price_cost

SCHEMA = 1
LOCAL_PROVIDERS = {"ollama", "stub", "demo"}
COMPONENTS = {"decision", "chat", "embedding_index", "embedding_query", "agent"}

RUN_ID = uuid.uuid4().hex[:12]

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("harness_usage_context", default={})
_warned: set[str] = set()
_features: dict[str, str | None] = {}
_checked_ignore: set[str] = set()


def warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(f"[harness-usage] {message}", file=sys.stderr)


def enabled() -> bool:
    return os.getenv("HARNESS_USAGE", "1").lower() not in {"0", "false", "no", "off"}


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


@contextlib.contextmanager
def usage_context(**values: Any) -> Iterator[None]:
    """Set request_id, component, operation, harness or project_root for nested calls."""

    token = _context.set({**_context.get(), **{k: v for k, v in values.items() if v is not None}})
    try:
        yield
    finally:
        _context.reset(token)


def set_context(**values: Any) -> None:
    """Like usage_context, without a scope; used by framework callbacks."""

    _context.set({**_context.get(), **{k: v for k, v in values.items() if v is not None}})


def current_context() -> dict[str, Any]:
    return dict(_context.get())


def _git_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def resolve_project_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    candidate = explicit or _context.get().get("project_root") or os.getenv("HARNESS_PROJECT_ROOT")
    if candidate:
        return Path(candidate).expanduser().resolve()
    cwd = Path.cwd()
    return _git_root(cwd) or cwd


def ledger_dir(project_root: Path) -> Path:
    override = os.getenv("HARNESS_USAGE_DIR")
    return Path(override).expanduser().resolve() if override else project_root / ".harness" / "usage"


def ledger_file(directory: Path, when: datetime) -> Path:
    return directory / f"{when:%Y-%m}.jsonl"


def active_feature(project_root: Path) -> str | None:
    """Read the target repository's active feature, when its harness has one."""

    key = str(project_root)
    if key in _features:
        return _features[key]
    feature = None
    for relative in ("docs/harness/feature_list.json", "feature_list.json"):
        path = project_root / relative
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            break
        feature = data.get("active_feature_id")
        if not feature:
            active = [f.get("id") for f in data.get("features", []) if f.get("status") == "in_progress"]
            feature = active[0] if len(active) == 1 else None
        break
    _features[key] = feature
    return feature


def _check_ignored(project_root: Path, path: Path) -> None:
    key = str(path.parent)
    if key in _checked_ignore:
        return
    _checked_ignore.add(key)
    if _git_root(project_root) is None:
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "check-ignore", "-q", str(path)],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if result.returncode == 1:
        warn_once(
            f"ignore:{key}",
            f"{path.parent} is not ignored by Git; add '.harness/' to {project_root}/.gitignore",
        )


def registry_path() -> Path:
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "harness" / "usage-ledgers.txt"


def registered_ledgers() -> list[Path]:
    path = registry_path()
    if not path.is_file():
        return []
    return [Path(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _register(directory: Path) -> None:
    """Remember where ledgers live (paths only) so budget and reports can sum them."""

    known = {str(p) for p in registered_ledgers()}
    if str(directory) in known:
        return
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{directory}\n")


def record(
    *,
    component: str,
    provider: str,
    model: str,
    routed_model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    status: str = "ok",
    error_kind: str | None = None,
    operation: str | None = None,
    harness: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Write one ledger line and return it; never raises."""

    if not enabled():
        return None
    try:
        ctx = _context.get()
        now = datetime.now(timezone.utc)
        root = resolve_project_root(project_root)
        cost, source = _cost(provider, routed_model or model, input_tokens, output_tokens, cost_usd)
        entry = {
            "schema": SCHEMA,
            "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": RUN_ID,
            "request_id": ctx.get("request_id"),
            "harness": harness or ctx.get("harness") or "unknown",
            "component": ctx.get("component") or component,
            "operation": operation or ctx.get("operation"),
            "provider": provider,
            "model": model,
            "routed_model": routed_model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cached_tokens": int(cached_tokens or 0),
            "cost_usd": cost,
            "cost_source": source,
            "latency_ms": latency_ms,
            "status": status,
            "error_kind": error_kind,
            "project": root.name,
            "feature": active_feature(root),
        }
        directory = ledger_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        path = ledger_file(directory, now)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _check_ignored(root, path)
        _register(directory)
        check_budget(cost or 0.0, now, registered_ledgers, warn_once)
        return entry
    except Exception as exc:  # recording must never break a harness
        warn_once("record-error", f"could not write the usage ledger: {exc}")
        return None


def _cost(
    provider: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float | None
) -> tuple[float | None, str]:
    if cost_usd is not None:
        return float(cost_usd), "provider"
    if provider in LOCAL_PROVIDERS:
        return 0.0, "local"
    if provider == "openrouter":
        estimated = price_cost(model, input_tokens, output_tokens)
        if estimated is not None:
            return estimated, "price_table"
    return None, "unknown"
