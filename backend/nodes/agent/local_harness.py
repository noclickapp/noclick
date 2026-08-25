"""Local-process CLI harness runner.

Runs a CLI coding agent (Claude Code, Codex, OpenCode, Hermes, or OpenClaw)
as a one-shot subprocess on the machine serving the backend, using the
operator's installed and authenticated CLI. The harness registry uses this
runner by default for CLI model types.

Each conversation has a stable workspace and fresh CLI configuration. Wired
tools are exposed over a turn-scoped MCP endpoint on this backend and share
the normal tool execution and audit path. Model usage is charged through the
operator's CLI subscription or API credentials. Harnesses with a known
upstream MCP-discovery race are retried once when no tools were discovered.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

LOCAL_HARNESS_MODEL_TYPES = ("claude_code", "codex", "opencode", "hermes_agent", "openclaw")

TURN_TIMEOUT_S = float(os.environ.get("NOCLICK_LOCAL_HARNESS_TIMEOUT", "900"))

router = APIRouter()


# ── Turn-scoped tool sessions ────────────────────────────────────────────


@dataclass
class _ToolSession:
    node: Any
    tool_configs: Dict[str, Dict]
    user_id: str
    conversation_id: str
    # Set when the harness actually fetched the tool list — the signal the
    # discovery-race retry keys on.
    saw_tools: bool = False


_sessions: Dict[str, _ToolSession] = {}


# Harnesses whose upstream release races MCP discovery on a cold connect.
_DISCOVERY_RACE_HARNESSES = ("hermes_agent",)


def _session_saw_tools(token: str) -> bool:
    session = _sessions.get(token)
    return bool(session and session.saw_tools)


def _register_session(session: _ToolSession) -> str:
    token = secrets.token_urlsafe(24)
    _sessions[token] = session
    return token


def _step_text(tool_name: str, arguments: Dict[str, Any]) -> str:
    from wss.sender.events import tool_call_step_text

    return tool_call_step_text(tool_name, arguments)


def _spawn_step(session: "_ToolSession", step_id: str, text: str, status: str) -> None:
    """Fire-and-forget agentic-step frame to the user's chat — never on the
    tool call's critical path, never raises."""
    try:
        from utils.async_helpers import spawn
        from utils.event_relay import broadcast_to_user_safe
        from wss.sender.events import tool_step_event

        spawn(
            broadcast_to_user_safe(
                session.user_id,
                tool_step_event(step_id, text, status, conversation_id=session.conversation_id),
            ),
            name=f"local-step:{step_id}:{status}",
        )
    except Exception as e:
        logger.debug(f"[LocalHarness] step emit failed ({step_id}): {e}")


def _tool_list(tool_configs: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """MCP tools/list from the node_op `_description`/`_parameters` convention
    every collected tool config carries."""
    tools = []
    for name, cfg in tool_configs.items():
        tools.append({
            "name": name,
            "description": cfg.get("_description") or "",
            "inputSchema": cfg.get("_parameters") or {"type": "object", "properties": {}},
        })
    return tools


@router.post("/local-agent-mcp/{token}")
async def local_agent_mcp(token: str, request: Request):
    """Stateless MCP Streamable-HTTP endpoint scoped to one agent turn."""
    session = _sessions.get(token)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown or expired tool session")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    def result(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": payload}

    if method == "initialize":
        return result({
            "protocolVersion": params.get("protocolVersion") or "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "noclick-local-agent", "version": "1.0.0"},
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return {}
    if method == "ping":
        return result({})
    if method == "tools/list":
        session.saw_tools = True
        return result({"tools": _tool_list(session.tool_configs)})
    if method == "tools/call":
        from nodes.agent.tool_execution import execute_tool
        from utils.tool_call_log import record_tool_call

        tool_name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        # This endpoint is the CLI harnesses' only tool path, so it is also the
        # chat UI's live mid-turn signal — same id-keyed step frames (shared
        # builders in wss.sender.events) used by the agent chat UI.
        step_id = f"local-{secrets.token_hex(6)}"
        _spawn_step(session, step_id, _step_text(tool_name, arguments), "in_progress")
        started = time.monotonic()
        try:
            call_result = await execute_tool(session.node, tool_name, arguments, session.tool_configs)
            is_error = isinstance(call_result, dict) and call_result.get("success") is False
            error_text = call_result.get("error") if is_error else None
        except Exception as e:
            logger.error(f"[LocalHarness] tools/call {tool_name} failed: {e}", exc_info=True)
            # Tool exceptions can contain request details, credentials, or a
            # local stack-derived path. Keep that detail in operator logs and
            # return a stable public error to the CLI client/agent.
            call_result = {"success": False, "error": "Tool execution failed"}
            is_error, error_text = True, "Tool execution failed"

        info = session.tool_configs.get(tool_name) or {}
        record_tool_call(
            user_id=session.user_id,
            tool_name=tool_name,
            tool_type=info.get("tool_type", "unknown"),
            result_status="error" if is_error else "success",
            workflow_id=str(getattr(session.node, "workflow_id", "") or ""),
            conversation_id=session.conversation_id,
            provider_node_id=info.get("node_id"),
            operation=info.get("operation"),
            credential_id=info.get("credential_id"),
            arguments=arguments,
            error=error_text,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        _spawn_step(session, step_id, json.dumps(call_result, default=str), "completed")
        return result({
            "content": [{"type": "text", "text": json.dumps(call_result, default=str)}],
            "isError": is_error,
        })

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


# ── Workspace + command assembly ─────────────────────────────────────────


def _workspace_dir(workflow_id: str, node_id: str, conversation_key: Optional[str]) -> Path:
    """Durable per-conversation working directory, stored as a volume so the
    chat's Files panel (resolve_workspace_source → the volume backend) lists
    exactly what the harness wrote. Also the stable cwd `claude --continue`
    keys on."""
    from utils.volume_backend import local_volume_root, workspace_volume_name

    ck = str(conversation_key) if conversation_key else "default"
    path = local_volume_root() / workspace_volume_name(workflow_id, node_id, ck)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mount_filesystem_volumes(
    workdir: Path, workflow_id: str,
    filesystem_configs: List[Dict[str, Any]], conversation_key: Optional[str],
) -> str:
    """Symlink each wired FilesystemNode's volume directory into the
    conversation workdir (cwd must stay per-conversation for `--continue`,
    so shared volumes mount as links rather than becoming the cwd). Returns
    a note for the model describing the mounts; empty when none."""
    from nodes.filesystem_node import get_volume_name
    from utils.volume_backend import local_volume_root

    notes = []
    for fs in filesystem_configs or []:
        volume_dir = local_volume_root() / get_volume_name(
            workflow_id, fs["node_id"], fs.get("volume_mode", "common"), conversation_key,
        )
        volume_dir.mkdir(parents=True, exist_ok=True)
        link_name = os.path.basename((fs.get("mount_path") or "/workspace").rstrip("/")) or "workspace"
        link = workdir / link_name
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(volume_dir, target_is_directory=True)
            notes.append(
                f"The folder ./{link_name} is persistent shared storage (the workflow's "
                f"Filesystem node) — files there survive across conversations and runs."
            )
        else:
            logger.warning(
                f"[LocalHarness] cannot mount volume at {link}: a real entry exists"
            )
    return (" ".join(notes)) if notes else ""


def _require_binary(name: str, install_hint: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise RuntimeError(
            f"The '{name}' CLI is not installed on this machine (required for this "
            f"agent's model). Install it and sign in first: {install_hint}"
        )
    return binary


def _mcp_url(token: str) -> str:
    port = os.environ.get("PORT", "8000")
    return f"http://127.0.0.1:{port}/local-agent-mcp/{token}"


def _compose_prompt(config: Any, *, inline_system: bool, extra_note: str = "") -> str:
    message = getattr(config, "message", "") or ""
    if extra_note:
        message = f"{message}\n\n[Environment note: {extra_note}]"
    system_prompt = (getattr(config, "system_prompt", "") or "").strip()
    if inline_system and system_prompt:
        return f"System instructions:\n{system_prompt}\n\n---\n\n{message}"
    return message


def _apply_subscription_login(model_type: str, workdir: Path, env: Dict[str, str]) -> None:
    """Hand a subscription sign-in to the CLI in the form it reads.

    claude and codex authenticate from a file in their config directory, not
    from an environment variable, so a Claude or ChatGPT sign-in stored on the
    agent node has to be written out before the process starts — otherwise the
    CLI reports itself logged out and the turn comes back blank.

    Only when a sign-in is actually attached. With no OAuth credential the
    config directory is left alone, so the CLI the operator is already signed
    into on this machine keeps working, which is the point of running these
    locally.
    """
    from nodes.agent.harness_oauth import oauth_expires_ms

    if model_type == "claude_code" and env.get("CLAUDE_CODE_ACCESS_TOKEN"):
        home = workdir / ".claude"
        home.mkdir(parents=True, exist_ok=True)
        creds = home / ".credentials.json"
        creds.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": env["CLAUDE_CODE_ACCESS_TOKEN"],
                "refreshToken": env.get("CLAUDE_CODE_REFRESH_TOKEN", ""),
                # The real expiry from the credential row, which the server keeps
                # fresh. A fabricated one suppresses the CLI's own refresh.
                "expiresAt": oauth_expires_ms(
                    env, "CLAUDE_CODE_EXPIRES_AT", "CLAUDE_CODE_EXPIRES_IN",
                    default_expires_in=28800,
                ),
                "scopes": ["user:inference", "user:profile"],
            }
        }))
        creds.chmod(0o600)
        env["CLAUDE_CONFIG_DIR"] = str(home)

    elif model_type == "codex" and env.get("CODEX_ACCESS_TOKEN"):
        home = workdir / ".codex"
        home.mkdir(parents=True, exist_ok=True)
        auth = home / "auth.json"
        auth.write_text(json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": env.get("CODEX_ID_TOKEN", ""),
                "access_token": env["CODEX_ACCESS_TOKEN"],
                "refresh_token": env.get("CODEX_REFRESH_TOKEN", ""),
            },
            "last_refresh": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }))
        auth.chmod(0o600)
        env["CODEX_HOME"] = str(home)


def _build_command(
    model_type: str, config: Any, workdir: Path, mcp_url: Optional[str],
    extra_note: str = "",
) -> Tuple[List[str], str]:
    """Returns (argv, parser_kind). Raises if the CLI is missing."""
    if model_type == "claude_code":
        binary = _require_binary("claude", "https://docs.anthropic.com/en/docs/claude-code")
        cmd = [binary, "-p", _compose_prompt(config, inline_system=False, extra_note=extra_note),
               "--output-format", "stream-json", "--verbose"]
        system_prompt = (getattr(config, "system_prompt", "") or "").strip()
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        model = getattr(config, "claude_code_model", "") or ""
        if model:
            cmd += ["--model", model]
        if mcp_url:
            mcp_config = workdir / ".noclick-mcp.json"
            mcp_config.write_text(json.dumps(
                {"mcpServers": {"noclick": {"type": "http", "url": mcp_url}}}
            ))
            cmd += ["--mcp-config", str(mcp_config), "--allowedTools", "mcp__noclick__*"]
        if (workdir / ".noclick-turns").exists():
            cmd += ["--continue"]
        return cmd, "claude_stream_json"

    if model_type == "codex":
        binary = _require_binary("codex", "https://github.com/openai/codex")
        cmd = [binary, "exec", "--json", "--skip-git-repo-check"]
        model = getattr(config, "codex_model", "") or ""
        if model:
            cmd += ["-m", model]
        if mcp_url:
            cmd += ["-c", f'mcp_servers.noclick.url="{mcp_url}"',
                    "-c", "experimental_use_rmcp_client=true"]
        cmd += [_compose_prompt(config, inline_system=True, extra_note=extra_note)]
        return cmd, "codex_jsonl"

    if model_type == "opencode":
        binary = _require_binary("opencode", "https://opencode.ai")
        if mcp_url:
            (workdir / "opencode.json").write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "mcp": {"noclick": {"type": "remote", "url": mcp_url, "enabled": True}},
            }))
        cmd = [binary, "run", _compose_prompt(config, inline_system=True, extra_note=extra_note)]
        model = getattr(config, "opencode_model", "") or ""
        if model:
            cmd += ["-m", model]
        return cmd, "plain_text"

    if model_type == "hermes_agent":
        binary = _require_binary("hermes", "pip install 'hermes-agent[mcp]'")
        home = workdir / ".hermes"
        home.mkdir(parents=True, exist_ok=True)
        if mcp_url:
            # Config format per hermes docs: HTTP MCP servers + the discovery
            # bound. Upstream's `-z` oneshot does NOT join discovery before the
            # first tool snapshot (checked against 0.14.0), so tools can be
            # missing on a cold connect — the runner's retry covers that here
            # while keeping the upstream binary unmodified.
            (home / "config.yaml").write_text(
                "agent:\n  disabled_toolsets: [messaging, gateway]\n\n"
                "mcp_discovery_timeout: 20\n"
                "mcp_servers:\n"
                "  noclick:\n"
                f"    url: {json.dumps(mcp_url)}\n"
                "    timeout: 120\n"
                "    connect_timeout: 60\n"
            )
        cmd = [binary, "-z", _compose_prompt(config, inline_system=True, extra_note=extra_note)]
        model = getattr(config, "hermes_agent_model", "") or ""
        if model:
            cmd += ["-m", model]
        return cmd, "plain_text"

    if model_type == "openclaw":
        binary = _require_binary("openclaw", "npm install -g openclaw")
        home = workdir / ".openclaw"
        home.mkdir(parents=True, exist_ok=True)
        # `--local` runs the agent embedded, which fits a one-shot runner.
        # Sandbox/approvals off:
        # the operator's machine is the trust boundary in the open build.
        oc_config: Dict[str, Any] = {
            "agents": {
                "defaults": {
                    "workspace": str(workdir),
                    "sandbox": {"mode": "off"},
                }
            },
            "tools": {"exec": {"ask": "off", "security": "full"}},
        }
        if mcp_url:
            oc_config["mcp"] = {
                "servers": {"noclick": {"transport": "http", "url": mcp_url}}
            }
        (home / "config.json").write_text(json.dumps(oc_config, indent=2))
        cmd = [
            binary, "agent", "--local", "--json",
            "--message", _compose_prompt(config, inline_system=True, extra_note=extra_note),
            # Session id keyed to the conversation: openclaw owns continuity
            # internally, the same way claude keys on cwd.
            "--session-id", f"noclick-{hashlib.sha256(str(workdir).encode()).hexdigest()[:16]}",
        ]
        model = getattr(config, "openclaw_model", "") or ""
        if model:
            cmd += ["--model", model]
        return cmd, "openclaw_json"

    raise RuntimeError(f"Local harness has no adapter for model type '{model_type}'")


# ── Output parsing ───────────────────────────────────────────────────────


def _human_error(value: Any, depth: int = 0) -> str:
    """Pull the human-readable message out of a harness error payload.

    Harness errors arrive nested and often double-encoded — codex wraps the
    provider's JSON error body in a string inside its own error event — so the
    useful sentence ("The 'x' model requires a newer version of Codex") sits two
    levels down. Without this the raw envelope reached the user as the node's
    error, which reads like a crash rather than an instruction.
    """
    if depth > 4 or value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                return _human_error(json.loads(text), depth + 1) or text
            except json.JSONDecodeError:
                return text
        return text
    if isinstance(value, dict):
        for key in ("error", "message", "detail"):
            if key in value:
                found = _human_error(value[key], depth + 1)
                if found:
                    return found
    return ""


def _parse_output(parser_kind: str, stdout: str, stderr: str, returncode: int) -> Tuple[str, bool]:
    """Extract (response_text, is_error) from a finished CLI run."""
    if parser_kind == "claude_stream_json":
        response, is_error = "", returncode != 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                response = event.get("result") or event.get("error") or ""
                is_error = bool(event.get("is_error")) or returncode != 0
        if not response:
            response = stdout.strip() or stderr.strip()
        return response, is_error

    if parser_kind == "codex_jsonl":
        response, failure = "", ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Tolerate both codex exec JSON schemas: item.completed carrying an
            # agent_message item, and flat agent-message events with text.
            item = event.get("item") if isinstance(event.get("item"), dict) else None
            # The item's kind has been spelled both `item_type` and `type`
            # across codex releases; accept either.
            item_kind = (item or {}).get("item_type") or (item or {}).get("type")
            if item and item_kind == "agent_message" and item.get("text"):
                response = item["text"]
            elif event.get("type") in ("agent_message", "assistant_message") and event.get("text"):
                response = event["text"]
            elif isinstance(event.get("msg"), dict) and event["msg"].get("type") == "agent_message":
                response = event["msg"].get("message") or response
            # Failures: keep the LAST one — codex emits a soft warning
            # ("model metadata not found") before the fatal error.
            elif event.get("type") == "turn.failed":
                failure = _human_error(event.get("error")) or failure
            elif event.get("type") == "error":
                failure = _human_error(event.get("message")) or failure
            elif item and item_kind == "error" and item.get("message"):
                failure = _human_error(item.get("message")) or failure
        if failure:
            # A failed turn is a failure even when the CLI exits 0.
            return failure, True
        if not response:
            response = stdout.strip() or stderr.strip()
        return response, returncode != 0

    if parser_kind == "openclaw_json":
        # `--json` emits one result object (older builds emit JSONL; take the
        # last parseable object either way).
        response, payload = "", None
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
        if payload is None and stdout.strip().startswith("{"):
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = None
        if isinstance(payload, dict):
            # openclaw --json: {"payloads": [{"text": ...}], "meta": {...}}
            payloads = payload.get("payloads")
            if isinstance(payloads, list):
                texts = [
                    p["text"] for p in payloads
                    if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip()
                ]
                if texts:
                    return "\n\n".join(texts), returncode != 0
            for key in ("reply", "text", "message", "response", "content", "result"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    response = value
                    break
                if isinstance(value, dict):
                    inner = value.get("text") or value.get("content")
                    if isinstance(inner, str) and inner.strip():
                        response = inner
                        break
        if not response:
            response = stdout.strip() or stderr.strip()
        return response, returncode != 0

    # plain_text (opencode, hermes)
    response = stdout.strip() or stderr.strip()
    return response, returncode != 0


# ── The runner (harness_registry contract) ───────────────────────────────


def _presence_hub():
    """Return this installation's in-process event relay, when active."""
    from utils.edition import is_local_edition

    if not is_local_edition():
        return None
    from utils.local_relay import get_local_relay_hub

    return get_local_relay_hub()


async def _emit_status(node: Any, status: str) -> None:
    """Emit in-flight chat status; observability must never fail the turn."""
    try:
        from wss.sender import ChatMessageEvent, send_event

        event = ChatMessageEvent(
            conversation_id=node.chat_routing_id(),
            message=None,
            status=status,
            finished=False,
        )
        if getattr(node, "sio", None) and getattr(node, "sid", None):
            await send_event(node.sio, node.sid, event)
        elif getattr(node, "user_id", None):
            await send_event(node.sio, None, event, user_id=str(node.user_id))
    except Exception:
        logger.debug(f"[LocalHarness] status emit failed: {status}", exc_info=True)


async def run_local_harness_turn(
    node: Any,
    config: Any,
    env_overrides: Dict[str, str],
    user_id: str,
    tool_configs: Dict[str, Dict],
    filesystem_configs: List[Dict],
    *,
    model_type: str,
) -> Dict[str, Any]:
    conversation_key = getattr(config, "conversation_key", None)
    conversation_id = getattr(node, "conversation_id", None) or node.chat_routing_id()
    workflow_id = str(getattr(node, "workflow_id", "") or "no-workflow")
    node_id = str(getattr(node, "node_id", "") or "agent")
    workdir = _workspace_dir(workflow_id, node_id, conversation_key)
    volume_note = _mount_filesystem_volumes(
        workdir, workflow_id, filesystem_configs, conversation_key,
    )

    token: Optional[str] = None
    if tool_configs:
        token = _register_session(_ToolSession(
            node=node, tool_configs=tool_configs, user_id=str(user_id),
            conversation_id=str(conversation_id),
        ))

    model_field = {
        "claude_code": "claude_code_model", "codex": "codex_model",
        "opencode": "opencode_model", "hermes_agent": "hermes_agent_model",
        "openclaw": "openclaw_model",
    }[model_type]
    model_str = getattr(config, model_field, "") or model_type

    await _emit_status(node, "Agent is working…")
    hub = _presence_hub()
    if hub is not None:
        await hub.set_agent_presence(
            workflow_id, node_id, str(conversation_key or ""), str(user_id), busy=True,
        )

    try:
        cmd, parser_kind = _build_command(
            model_type, config, workdir, _mcp_url(token) if token else None,
            extra_note=volume_note,
        )

        env = {**os.environ, **(env_overrides or {})}
        # Per-conversation config/state roots keep harnesses isolated from the
        # operator's own CLI setup (and from each other).
        _apply_subscription_login(model_type, workdir, env)
        if model_type == "hermes_agent":
            env["HERMES_HOME"] = str(workdir / ".hermes")
        elif model_type == "openclaw":
            env["OPENCLAW_HOME"] = str(workdir / ".openclaw")
            env["OPENCLAW_CONFIG_PATH"] = str(workdir / ".openclaw" / "config.json")
        user_env = getattr(node, "_user_env", None)
        if user_env:
            from nodes.agent.user_env import sanitize_user_env
            env = {**sanitize_user_env(user_env), **env}

        logger.info(
            f"[LocalHarness] {model_type} turn: {len(tool_configs)} tool(s), cwd={workdir}"
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=workdir, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=TURN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"Local {model_type} turn timed out after {TURN_TIMEOUT_S:.0f}s"
            )

        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")
        response, is_error = _parse_output(parser_kind, stdout, stderr, proc.returncode)

        # Upstream hermes' `-z` oneshot does not join MCP discovery before its
        # first tool snapshot, so a cold connect can leave the turn toolless
        # before its first tool snapshot. The session tracks whether any tool was
        # fetched and reruns a toolless first turn once. Established CLI
        # connections make the retry uncommon after the first turn.
        if (
            model_type in _DISCOVERY_RACE_HARNESSES
            and token is not None
            and not _session_saw_tools(token)
            and not is_error
        ):
            logger.info(
                f"[LocalHarness] {model_type}: first turn saw no tools "
                "(upstream MCP discovery race) — retrying once"
            )
            await _emit_status(node, "Connecting tools…")
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=workdir, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=TURN_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(
                    f"Local {model_type} turn timed out after {TURN_TIMEOUT_S:.0f}s"
                )
            stdout = stdout_b.decode(errors="replace")
            stderr = stderr_b.decode(errors="replace")
            response, is_error = _parse_output(parser_kind, stdout, stderr, proc.returncode)
        if is_error and not response:
            response = f"{model_type} exited with code {proc.returncode}"

        # Marks the workspace as having history so the next claude turn
        # continues the cwd-keyed session.
        (workdir / ".noclick-turns").touch()

        output: Dict[str, Any] = {
            "type": "agent",
            "status": "failed" if is_error else "completed",
            "response": response,
            "model": model_str,
            "conversation_key": conversation_key,
        }
        if is_error:
            output["error"] = response
            logger.warning(f"[LocalHarness] {model_type} turn failed: {response[:300]}")

        await node._persist_llm_assistant_turn(
            output,
            conversation_id=conversation_id,
            model=model_str,
            raw_text=response,
            agent_errored=is_error,
        )
        return output
    finally:
        if token:
            _sessions.pop(token, None)
        if hub is not None:
            await hub.clear_agent_presence(
                workflow_id, node_id, str(conversation_key or ""),
            )
