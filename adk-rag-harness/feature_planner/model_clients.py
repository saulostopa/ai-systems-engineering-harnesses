"""Structured responses from Ollama and the installed model CLIs."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .model_router import CLAUDE_DEFAULT_MAX_TURNS, FailureReason, ModelFailure, ModelReply

CLI_TIMEOUT = 120


def _object(value):
    return value if isinstance(value, dict) else {}


def _json(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ModelFailure("invalid_output", reason=FailureReason.INVALID_JSON) from exc


def _events(stdout):
    return [_object(_json(line)) for line in stdout.splitlines() if line.strip()]


def _last(events, key, value):
    return next((event for event in reversed(events) if event.get(key) == value), {})


def _usage(payload, **keys):
    return {
        label: payload[key]
        for label, key in keys.items()
        if type(payload.get(key)) is int and payload[key] >= 0
    }


def _reported_model(value):
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value):
        return value
    return None


def _ollama_call(route, schema, prompt, data):
    url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    payload = {
        "model": route.model,
        "stream": False,
        "format": schema.model_json_schema(),
        "options": {"temperature": 0, "num_predict": 2048},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ],
    }
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=90) as response:
            body = _object(_json(response.read()))
    except HTTPError as exc:
        reason = FailureReason.HTTP_REQUEST_FAILED
        if exc.code == 429:
            reason = FailureReason.RATE_LIMITED
        elif 500 <= exc.code < 600:
            reason = FailureReason.PROVIDER_UNAVAILABLE
        raise ModelFailure("unavailable", reason=reason) from exc
    except (URLError, OSError) as exc:
        reason = FailureReason.TIMEOUT if isinstance(getattr(exc, "reason", exc), TimeoutError) else FailureReason.TRANSPORT_ERROR
        raise ModelFailure("unavailable", reason=reason) from exc
    usage = _usage(body, input_tokens="prompt_eval_count", output_tokens="eval_count")
    try:
        value = _json(_object(body.get("message")).get("content"))
    except ModelFailure as exc:
        raise ModelFailure(exc.kind, usage, reason=exc.reason) from exc
    return ModelReply(value, usage, reported_model=_reported_model(body.get("model")))


async def ollama(route, schema, prompt, data):
    return await asyncio.to_thread(_ollama_call, route, schema, prompt, data)


async def _run(args, cwd, stdin, env, timeout=CLI_TIMEOUT):
    try:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ModelFailure("unavailable", reason=FailureReason.CLI_START_FAILED) from exc
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(stdin.encode()), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise ModelFailure("unavailable", reason=FailureReason.TIMEOUT) from exc
    return process.returncode, stdout.decode("utf-8", errors="replace")


def _prompt(instruction, data):
    return f"{instruction}\n\nUse the supplied evidence only. Input JSON:\n{json.dumps(data, ensure_ascii=False)}\n"


def _effort(route, flag):
    return [flag, route.effort] if route.effort else []


def _claude_env(environ: Mapping[str, str]):
    return {
        key: value for key, value in environ.items()
        if not key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_OAUTH_"))
        and key not in {"CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE", "CLAUDE_CODE_SESSION_ACCESS_TOKEN"}
    }


async def claude_code(route, schema, instruction, data):
    env = _claude_env(os.environ)
    with TemporaryDirectory(prefix="adk-claude-") as cwd:
        code, status = await _run(["claude", "auth", "status", "--json"], cwd, "", env, timeout=10)
        auth = _object(_json(status)) if not code else {}
        if auth.get("loggedIn") is not True or auth.get("authMethod") != "claude.ai" or auth.get("apiProvider") != "firstParty":
            raise ModelFailure("authentication_required")
        args = [
            "claude", "--restricted", "--print", "--output-format", "stream-json", "--verbose",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--tools", "", "--no-session-persistence",
            "--max-turns", str(route.max_turns or CLAUDE_DEFAULT_MAX_TURNS), "--model", route.model,
            "--json-schema", json.dumps(schema.model_json_schema()), *_effort(route, "--effort"),
        ]
        code, stdout = await _run(args, cwd, _prompt(instruction, data), env)
    return _claude_reply(code, _events(stdout))


def _claude_reply(code, events):
    result = _last(events, "type", "result")
    limits = [_object(event.get("rate_limit_info")) for event in events if event.get("type") == "rate_limit_event"]
    usage = _usage(
        _object(result.get("usage")), input_tokens="input_tokens", output_tokens="output_tokens",
        cache_read_tokens="cache_read_input_tokens", cache_creation_tokens="cache_creation_input_tokens",
    )
    cost = result.get("total_cost_usd")
    if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
        usage["cli_estimated_cost_usd"] = cost
    assistant = _last(events, "type", "assistant")
    message = _object(assistant.get("message"))
    if "refusal" in (result.get("stop_reason"), message.get("stop_reason")) or any(
        event.get("type") == "system" and event.get("subtype") == "model_refusal_no_fallback"
        for event in events
    ):
        raise ModelFailure("unavailable", usage, reason=FailureReason.REFUSAL)
    if code or result.get("subtype") != "success" or result.get("is_error") is not False:
        exhausted = any(
            limit.get("status") == "rejected" and limit.get("errorCode") == "credits_required"
            for limit in limits
        )
        if exhausted:
            raise ModelFailure("quota_exhausted", usage)
        error = assistant.get("error")
        if error in ("authentication_failed", "oauth_org_not_allowed", "cloud_credential_error"):
            raise ModelFailure("authentication_required", usage)
        if error in ("account_on_hold", "billing_error", "invalid_request", "model_not_found"):
            raise ModelFailure("unavailable", usage, reason=FailureReason.REQUEST_REJECTED)
        if error in ("overloaded", "server_error"):
            raise ModelFailure("unavailable", usage, reason=FailureReason.PROVIDER_UNAVAILABLE)
        if error == "rate_limit":
            raise ModelFailure("unavailable", usage, reason=FailureReason.RATE_LIMITED)
        if error == "max_output_tokens" or result.get("stop_reason") == "max_tokens":
            raise ModelFailure("invalid_output", usage, reason=FailureReason.OUTPUT_LIMIT)
        if not result:
            raise ModelFailure("unavailable", usage, reason=FailureReason.MISSING_CLI_RESULT)
        if result.get("subtype") == "error_max_turns":
            raise ModelFailure("unavailable", usage, reason=FailureReason.TURN_LIMIT)
        if result.get("subtype") == "error_max_structured_output_retries":
            raise ModelFailure("invalid_output", usage, reason=FailureReason.STRUCTURED_OUTPUT_RETRIES_EXHAUSTED)
        raise ModelFailure("unavailable", usage, reason=FailureReason.CLI_EXECUTION_ERROR)
    value = result.get("structured_output")
    if value is None:
        reason = FailureReason.OUTPUT_LIMIT if result.get("stop_reason") == "max_tokens" else FailureReason.MISSING_STRUCTURED_OUTPUT
        raise ModelFailure("invalid_output", usage, reason=reason)
    init = _last(events, "subtype", "init")
    return ModelReply(
        value, usage,
        quota_warning=any(limit.get("status") == "allowed_warning" for limit in limits),
        reported_model=_reported_model(init.get("model")),
    )


async def agy(route, schema, instruction, data):
    settings = {"modelProvider": "", "allowNonWorkspaceAccess": False, "permissions": {"deny": [
        "read_file(*)", "write_file(*)", "command(*)", "mcp(*)", "read_url(*)", "execute_url(*)",
    ]}}
    args = [
        "agy", "--input-format", "stream-json", "--output-format", "stream-json", "--mode", "plan",
        "--sandbox", "--disable-slash-commands", "--settings", json.dumps(settings),
        "--model", route.model, "--json-schema", json.dumps(schema.model_json_schema()), *_effort(route, "--effort"),
    ]
    stdin = json.dumps({"event": "user", "message": {"content": _prompt(instruction, data)}}) + "\n"
    env = {key: value for key, value in os.environ.items() if key != "GEMINI_API_KEY"}
    with TemporaryDirectory(prefix="adk-agy-") as cwd:
        code, stdout = await _run(args, cwd, stdin, env)
    return _agy_reply(code, _events(stdout))


def _agy_reply(code, events):
    result = _object(_last(events, "event", "result").get("result"))
    usage = _usage(
        _object(result.get("usage")), input_tokens="input_tokens", output_tokens="output_tokens",
        cache_read_tokens="cache_read_tokens", reasoning_tokens="thinking_tokens",
    )
    if code or result.get("status") != "SUCCESS":
        reason = FailureReason.CLI_EXECUTION_ERROR if result else FailureReason.MISSING_CLI_RESULT
        raise ModelFailure("unavailable", usage, reason=reason)
    model = _object(_last(events, "event", "init").get("init")).get("model")
    if isinstance(model, str) and not model.startswith("gemini-"):
        raise ModelFailure("unavailable", usage, reason=FailureReason.MODEL_MISMATCH)
    return ModelReply(result.get("structured_output"), usage, reported_model=_reported_model(model))


async def codex(route, schema, instruction, data):
    with TemporaryDirectory(prefix="adk-codex-") as cwd:
        schema_path = Path(cwd, "output-schema.json")
        schema_path.write_text(json.dumps(schema.model_json_schema()), encoding="utf-8")
        args = [
            "codex", "-a", "never", "exec", "--ignore-user-config", "--sandbox", "read-only",
            "--ephemeral", "--skip-git-repo-check", "--json", "--output-schema", str(schema_path),
            "--model", route.model, "-c", 'model_provider="openai"', "-c", 'web_search="disabled"',
            "-c", "features.shell_tool=false", "-c", "features.unified_exec=false", "-c", "features.multi_agent=false",
        ]
        if route.effort:
            args += ["-c", f"model_reasoning_effort={json.dumps(route.effort)}"]
        env = {key: value for key, value in os.environ.items() if key not in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}}
        code, stdout = await _run([*args, "-"], cwd, _prompt(instruction, data), env)
    return _codex_reply(code, _events(stdout))


def _codex_reply(code, events):
    terminal = next((event for event in reversed(events) if event.get("type") in {"turn.completed", "turn.failed"}), {})
    if code or terminal.get("type") != "turn.completed":
        message = _object(terminal.get("error")).get("message", "")
        quota = isinstance(message, str) and message.replace("’", "'").startswith((
            "You've hit your usage limit.", "You've hit your usage limit for ", "Your workspace is out of credits.",
        ))
        if quota:
            raise ModelFailure("quota_exhausted")
        reason = FailureReason.CLI_EXECUTION_ERROR if terminal else FailureReason.MISSING_CLI_RESULT
        raise ModelFailure("unavailable", reason=reason)
    usage = _usage(
        _object(terminal.get("usage")), input_tokens="input_tokens", output_tokens="output_tokens",
        cache_read_tokens="cached_input_tokens", reasoning_tokens="reasoning_output_tokens",
        cache_creation_tokens="cache_write_input_tokens",
    )
    messages = [_object(event.get("item")) for event in events if event.get("type") == "item.completed"]
    try:
        value = _json(_last(messages, "type", "agent_message").get("text"))
    except ModelFailure as exc:
        raise ModelFailure(exc.kind, usage, reason=exc.reason) from exc
    return ModelReply(value, usage)


CLIENTS = {"ollama": ollama, "claude-code": claude_code, "codex": codex, "agy": agy}
