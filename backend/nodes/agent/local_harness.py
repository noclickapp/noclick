"""Run installed CLI agents in conversation-scoped local processes.

Native streaming and gateway protocols accept input in their live session.
Independent conversation keys execute concurrently.
Wired tools use the local MCP endpoint and the normal execution/audit path.
"""

import asyncio
import socket
import hashlib
import json
import logging
import os
import secrets
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

LOCAL_HARNESS_MODEL_TYPES = ("claude_code", "codex", "opencode", "hermes_agent", "openclaw")

TURN_TIMEOUT_S = float(os.environ.get("NOCLICK_LOCAL_HARNESS_TIMEOUT", "900"))

router = APIRouter()


# ── Process-scoped tool sessions ────────────────────────────────────────────


@dataclass
class _ToolSession:
    node: Any
    tool_configs: Dict[str, Dict]
    user_id: str
    conversation_id: str
    # Records whether this MCP client fetched the advertised tool list.
    saw_tools: bool = False


_sessions: Dict[str, _ToolSession] = {}
_presence_counts: Dict[tuple, int] = {}


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
    """Stateless MCP Streamable-HTTP endpoint scoped to a local process."""
    session = _sessions.get(token)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown or expired tool session")
    # A concurrent completion may advance the active input while this tool is
    # awaiting I/O. Keep its execution and audit context together.
    session = replace(session)
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
    if (method or "").startswith("notifications/") or req_id is None:
        # JSON-RPC notifications get NO body: Streamable HTTP says 202 with
        # nothing in it. Answering 200 {} broke codex's rmcp client mid-handshake
        # — it re-initialized in a loop and never issued tools/list, so every
        # codex turn ran toolless while the server logged nothing but 200s.
        return Response(status_code=202)
    if method == "ping":
        return result({})
    if method == "tools/list":
        session.saw_tools = True
        if token in _sessions:
            _sessions[token].saw_tools = True
        return result({"tools": _tool_list(session.tool_configs)})
    if method == "tools/call":
        from nodes.agent.tool_execution import execute_tool

        tool_name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        # This endpoint is the CLI harnesses' only tool path, so it is also the
        # chat UI's live mid-turn signal — same id-keyed step frames (shared
        # builders in wss.sender.events) used by the agent chat UI.
        step_id = f"local-{secrets.token_hex(6)}"
        _spawn_step(session, step_id, _step_text(tool_name, arguments), "in_progress")
        try:
            call_result = await execute_tool(session.node, tool_name, arguments, session.tool_configs)
            is_error = isinstance(call_result, dict) and call_result.get("success") is False
        except Exception as e:
            logger.error(f"[LocalHarness] tools/call {tool_name} failed: {e}", exc_info=True)
            # Tool exceptions can contain request details, credentials, or a
            # local stack-derived path. Keep that detail in operator logs and
            # return a stable public error to the CLI client/agent.
            call_result = {"success": False, "error": "Tool execution failed"}
            is_error = True
            # execute_tool audits every call it returns from, with the node's
            # execution context; it never got to this one, so record the masked
            # failure here. A row on the success path too doubled every call.
            from utils.tool_call_log import record_tool_call

            info = session.tool_configs.get(tool_name) or {}
            record_tool_call(
                user_id=session.user_id,
                tool_name=tool_name,
                tool_type=info.get("tool_type", "unknown"),
                result_status="error",
                workflow_id=str(getattr(session.node, "workflow_id", "") or ""),
                conversation_id=session.conversation_id,
                provider_node_id=info.get("node_id"),
                operation=info.get("operation"),
                credential_id=info.get("credential_id"),
                arguments=arguments,
                error="Tool execution failed",
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
    """The turn-scoped tool endpoint, on the BACKEND's own port.

    PORT is the container's public port on every PaaS — in the single-origin
    image that is nginx, which has no route for this path, so a CLI pointed
    there shook hands with an HTML page and ran every turn toolless (Railway,
    2026-08-31; `make local` masked it, PORT unset there). The entrypoint
    exports the backend's real bind as NOCLICK_BACKEND_PORT.
    """
    port = os.environ.get("NOCLICK_BACKEND_PORT") or os.environ.get("PORT", "8000")
    return f"http://127.0.0.1:{port}/local-agent-mcp/{token}"


def _tools_note(tool_configs: Dict[str, Dict]) -> str:
    """One grounding line naming the wired tools. The MCP advertisement alone
    is not always believed: a ChatGPT-backend model asked about "apollo tools"
    matched the name against its own connector catalogue and answered "not
    installed" while the tools sat in its own tool list (2026-08-31)."""
    if not tool_configs:
        return ""
    return (
        "These NoClick tools are connected and callable right now via the "
        "'noclick' MCP server: " + ", ".join(sorted(tool_configs)) + "."
    )


def _join_notes(*notes: Optional[str]) -> str:
    return " ".join(n for n in notes if n)


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
        # The credential vars are transport between the backend and this
        # function — never the CLI's to see (same doctrine as codex below).
        for key in ("CLAUDE_CODE_ACCESS_TOKEN", "CLAUDE_CODE_REFRESH_TOKEN",
                    "CLAUDE_CODE_EXPIRES_AT", "CLAUDE_CODE_EXPIRES_IN"):
            env.pop(key, None)

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
        # codex (0.147) treats CODEX_ACCESS_TOKEN in its environment as an auth
        # override and abandons auth.json for a keyless API mode — every turn
        # died with a bearer-less 401 from api.openai.com while a perfectly
        # good ChatGPT sign-in sat in auth.json (2026-08-31, bisected var by
        # var against the live binary). The credential vars are transport
        # between the backend and this function — never the CLI's to see.
        for key in ("CODEX_ACCESS_TOKEN", "CODEX_ID_TOKEN", "CODEX_REFRESH_TOKEN",
                    "CODEX_EXPIRES_AT", "CODEX_EXPIRES_IN", "CODEX_ACCOUNT_ID"):
            env.pop(key, None)


# Agent model ids are `<provider>/<model>`; hermes takes the provider as its own
# flag and the model WITHOUT the prefix (`--provider openrouter -m openai/gpt-5`
# — passing `openrouter/openai/gpt-5` as the model is "not a valid model ID").
_HERMES_PROVIDERS = {
    "openrouter": "openrouter",
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "google",
    "google": "google",
    "groq": "groq",
    "deepseek": "deepseek",
}


def hermes_provider_and_model(model_id: str) -> Tuple[Optional[str], str]:
    """(hermes provider, model id hermes expects); an unknown prefix is passed
    through whole for hermes to auto-detect."""
    prefix, _, rest = model_id.partition("/")
    provider = _HERMES_PROVIDERS.get(prefix.lower()) if rest else None
    return (provider, rest) if provider else (None, model_id)


def _build_command(
    model_type: str, config: Any, workdir: Path, mcp_url: Optional[str],
    extra_note: str = "",
    *, persistent: bool = False,
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
        if persistent:
            del cmd[2]  # messages arrive on stdin, never as a positional prompt
            cmd += ["--input-format", "stream-json", "--replay-user-messages", "--strict-mcp-config"]
            if not mcp_url:
                cmd += ["--mcp-config", '{"mcpServers":{}}']
        return cmd, "claude_stream_json"

    if model_type == "codex":
        binary = _require_binary("codex", "https://github.com/openai/codex")
        cmd = [binary, "exec", "--json", "--skip-git-repo-check"]
        model = getattr(config, "codex_model", "") or ""
        if model:
            cmd += ["-m", model]
        if mcp_url:
            # codex gates each MCP server's tool calls behind an approval
            # prompt, and a headless exec has no answerer — every call died as
            # "user cancelled MCP tool call" (the same headless-asks audit
            # every harness needs). approval_policy alone does NOT cover it;
            # the per-server approval mode is the knob (bisected against the
            # live binary, 2026-08-31).
            cmd += ["-c", f'mcp_servers.noclick.url="{mcp_url}"',
                    "-c", "experimental_use_rmcp_client=true",
                    "-c", 'mcp_servers.noclick.default_tools_approval_mode="approve"']
        cmd += [_compose_prompt(config, inline_system=True, extra_note=extra_note)]
        if persistent:
            options = []
            if mcp_url:
                options = ["-c", f"mcp_servers.noclick.url={json.dumps(mcp_url)}",
                           "-c", 'mcp_servers.noclick.default_tools_approval_mode="approve"']
            cmd = [binary, "app-server", *options]
        return cmd, "codex_jsonl"

    if model_type == "opencode":
        binary = _require_binary("opencode", "https://opencode.ai")
        model = getattr(config, "opencode_model", "") or ""
        opencode_config = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {"noclick": {"type": "remote", "url": mcp_url, "enabled": True}} if mcp_url else {},
        }
        if model:
            # Session titles otherwise go to opencode's own hosted provider,
            # which fails on accounts without a payment method.
            opencode_config["small_model"] = model
        (workdir / "opencode.json").write_text(json.dumps(opencode_config))
        cmd = [binary, "run", _compose_prompt(config, inline_system=True, extra_note=extra_note)]
        if model:
            cmd += ["-m", model]
        if persistent:
            cmd = [binary, "serve", "--hostname", "127.0.0.1"]
        return cmd, "plain_text"

    if model_type == "hermes_agent":
        binary = _require_binary("hermes", "Use the pinned Hermes installer in backend/tests/fixtures/install_clis.py")
        home = workdir / ".hermes"
        home.mkdir(parents=True, exist_ok=True)
        # Replace the owned configuration even when tools were removed; a
        # retired endpoint must not remain in the next process's tool list.
        (home / "config.yaml").write_text(
            "agent:\n  disabled_toolsets: [messaging, gateway]\n\ntools:\n  tool_search: false\n\n"
            "mcp_discovery_timeout: 20\n" + (
                "mcp_servers:\n  noclick:\n"
                f"    url: {json.dumps(mcp_url)}\n"
                "    timeout: 120\n    connect_timeout: 60\n"
                if mcp_url else "mcp_servers: {}\n")
        )
        cmd = [binary, "-z", _compose_prompt(config, inline_system=True, extra_note=extra_note)]
        provider, model = hermes_provider_and_model(getattr(config, "hermes_agent_model", "") or "")
        if model:
            cmd += ["-m", model]
        if provider:
            cmd += ["--provider", provider]
        if persistent:
            # NoClick owns this process and its isolated HERMES_HOME. Let the
            # CLI return lifecycle control here instead of its system service.
            cmd = [binary, "gateway", "run", "--external-supervisor"]
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
                # openclaw names the transport itself: "http" fails its config
                # validation before the turn starts ("allowed: stdio, sse, streamable-http").
                "servers": {"noclick": {"transport": "streamable-http", "url": mcp_url}}
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
        if persistent:
            oc_config["plugins"] = {"allow": []}
            oc_config["gateway"] = {"mode": "local", "bind": "loopback", "auth": {"mode": "token"}}
            if model:
                oc_config["agents"]["defaults"]["model"] = {"primary": model}
            (home / "config.json").write_text(json.dumps(oc_config, indent=2))
            cmd = [binary, "gateway", "--allow-unconfigured"]
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


_CODEX_NO_API_KEY = "Missing bearer or basic authentication in header"


def explain_codex_failure(
    failure: str, chatgpt_auth: bool, id_token: Optional[str] = None
) -> str:
    """Codex that abandons a ChatGPT sign-in for API-key auth dies with a bare
    401 from api.openai.com. WHY it abandoned the sign-in is read from the id
    token's claims — a missing token must never be reported as a Free plan."""
    from nodes.agent.harness_oauth import CODEX_FREE_PLAN_MESSAGE, chatgpt_plan_type

    if not (chatgpt_auth and _CODEX_NO_API_KEY in failure):
        return failure
    prefix = "Codex fell back to an OpenAI API key, and none is connected."
    plan = chatgpt_plan_type(id_token)
    if plan == "free":
        return f"{prefix} {CODEX_FREE_PLAN_MESSAGE}"
    if plan is None:
        return (
            f"{prefix} The ChatGPT sign-in is missing its identity token, so "
            "Codex could not use the subscription. Reconnect the ChatGPT account."
        )
    return (
        f"{prefix} The ChatGPT sign-in (plan: {plan}) was not accepted by Codex. "
        "Reconnect the ChatGPT account, or connect an OpenAI API key instead."
    )


def _parse_output(
    parser_kind: str, stdout: str, stderr: str, returncode: int, *,
    chatgpt_auth: bool = False, chatgpt_id_token: Optional[str] = None
) -> Tuple[str, bool]:
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
            return explain_codex_failure(failure, chatgpt_auth, chatgpt_id_token), True
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


async def close_local_harness_sessions():
    from nodes.agent.local_process.session import sessions
    await sessions.close()


# The registry is deliberately local to this backend process.
from utils.lifecycle import register_shutdown_hook
register_shutdown_hook(close_local_harness_sessions, phase="drain", timeout=10,
                       name="local-cli-processes")


async def run_local_harness_turn(
    node: Any, config: Any, env_overrides: Dict[str, str], user_id: str,
    tool_configs: Dict[str, Dict], filesystem_configs: List[Dict], *, model_type: str,
) -> Dict[str, Any]:
    from nodes.agent.local_process.session import sessions
    from nodes.agent.local_process.native import ClaudeSession, CodexSession, OpenCodeSession
    from nodes.agent.local_process.hermes import HermesSession
    from nodes.agent.local_process.openclaw import OpenClawSession

    conversation_key = getattr(config, "conversation_key", None)
    conversation_id = getattr(node, "conversation_id", None) or node.chat_routing_id()
    workflow_id = str(getattr(node, "workflow_id", "") or "no-workflow")
    node_id = str(getattr(node, "node_id", "") or "agent")
    # No key means a new conversation, not a shared global 'default' session.
    scope = str(conversation_key) if conversation_key is not None and str(conversation_key) else secrets.token_hex(16)
    workdir = _workspace_dir(workflow_id, node_id, scope)
    key = (str(workdir), workflow_id, node_id, scope)
    model_field = {"claude_code": "claude_code_model", "codex": "codex_model",
                   "opencode": "opencode_model", "hermes_agent": "hermes_agent_model",
                   "openclaw": "openclaw_model"}[model_type]
    model = getattr(config, model_field, "") or ""
    fingerprint = hashlib.sha256(json.dumps({
        "harness": model_type, "model": model, "user": str(user_id),
        "system": getattr(config, "system_prompt", ""), "env": env_overrides,
        "user_env": getattr(node, "_user_env", None),
        "tools": tool_configs, "filesystems": filesystem_configs,
    }, sort_keys=True, default=str).encode()).hexdigest()

    async def factory():
        note = _mount_filesystem_volumes(workdir, workflow_id, filesystem_configs, conversation_key)
        note = _join_notes(note, _tools_note(tool_configs))
        context = _ToolSession(node=node, tool_configs=tool_configs, user_id=str(user_id),
                               conversation_id=str(conversation_id))
        token = _register_session(context) if tool_configs else None
        def cleanup():
            if token:
                _sessions.pop(token, None)
        try:
            kwargs = {"persistent": True} if model_type in LOCAL_HARNESS_MODEL_TYPES else {}
            cmd, parser = _build_command(model_type, config, workdir,
                                         _mcp_url(token) if token else None, extra_note=note, **kwargs)
            env = {**os.environ, **(env_overrides or {})}
            # Some CLIs resolve configuration through PWD rather than getcwd().
            env["PWD"] = str(workdir)
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
            common = dict(workdir=workdir, env=env, command=cmd, cleanup=cleanup)
            if model_type == "claude_code":
                session = ClaudeSession(**common)
            elif model_type == "codex":
                session = CodexSession(model=model, **common)
            elif model_type == "opencode":
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                password = secrets.token_urlsafe(24)
                env["OPENCODE_SERVER_PASSWORD"] = password
                env["XDG_DATA_HOME"] = str(workdir / ".local" / "share")
                env["XDG_STATE_HOME"] = str(workdir / ".local" / "state")
                cmd += ["--port", str(port)]
                session = OpenCodeSession(model=model, base_url=f"http://127.0.0.1:{port}",
                                          password=password, **common)
            elif model_type == "hermes_agent":
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                api_key = secrets.token_urlsafe(24)
                env.update(API_SERVER_ENABLED="true", API_SERVER_KEY=api_key,
                           API_SERVER_HOST="127.0.0.1", API_SERVER_PORT=str(port),
                           HERMES_YOLO_MODE="1")
                provider, hermes_model = hermes_provider_and_model(model)
                session = HermesSession(base_url=f"http://127.0.0.1:{port}", api_key=api_key,
                                        provider=provider, model=hermes_model, **common)
            elif model_type == "openclaw":
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                home = workdir / ".openclaw"
                config_path = home / "config.json"
                oc = json.loads(config_path.read_text())
                # Custom provider endpoints use the same credential env as the
                # other local CLIs; configuration remains inside this workspace.
                provider, _, submodel = model.partition("/")
                base = env.get("ANTHROPIC_BASE_URL") if provider == "anthropic" else env.get("OPENAI_BASE_URL")
                if base:
                    key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
                    base = base.rstrip("/")
                    if not base.endswith("/v1"):
                        base += "/v1"
                    oc["models"] = {"providers": {provider: {"baseUrl": base,
                        "api": "anthropic-messages" if provider == "anthropic" else "openai-completions",
                        "apiKey": env.get(key_name, ""), "models": [{"id": submodel, "name": submodel}]}}}
                config_path.write_text(json.dumps(oc))
                config_path.chmod(0o600)
                env.update(OPENCLAW_STATE_DIR=str(home), OPENCLAW_GATEWAY_TOKEN=secrets.token_urlsafe(24),
                    OPENCLAW_DISABLE_BONJOUR="1", OPENCLAW_NO_RESPAWN="1", OPENCLAW_SKIP_CHANNELS="1",
                    OPENCLAW_EXEC_SHELL_SNAPSHOT="0", NOCLICK_OPENCLAW_URL=f"ws://127.0.0.1:{port}",
                    NOCLICK_OPENCLAW_COMMAND=json.dumps([*cmd, "--port", str(port)]))
                bridge = Path(__file__).with_name("openclaw_bridge.mjs")
                common["command"] = [_require_binary("node", "Install Node.js 22.22.3 or later"), str(bridge)]
                session = OpenClawSession(**common)
            else:
                raise RuntimeError(f"No persistent adapter for {model_type}")
            session.tool_context, session.note = context, note
            return session
        except BaseException:
            cleanup()
            raise

    def activate(session):
        session.tool_context.node = node
        session.tool_context.conversation_id = str(conversation_id)

    await _emit_status(node, "Agent is working…")
    hub = _presence_hub()
    presence_key = (workflow_id, node_id, str(conversation_key or ""))
    if hub is not None:
        _presence_counts[presence_key] = _presence_counts.get(presence_key, 0) + 1
    session = future = None
    try:
        if hub is not None:
            try:
                await hub.set_agent_presence(*presence_key, str(user_id), busy=True)
            except Exception:
                logger.debug("Local agent presence update failed", exc_info=True)
        async with asyncio.timeout(TURN_TIMEOUT_S):
            session, future = await sessions.submit(key, fingerprint, factory,
                lambda session: _compose_prompt(config, inline_system=model_type != "claude_code", extra_note=session.note), activate)
            result = await asyncio.shield(future)
        error = result.pop("error", None)
        if error:
            error = _human_error(error) or str(error)
            if model_type == "codex":
                error = explain_codex_failure(error, bool(env_overrides.get("CODEX_ACCESS_TOKEN")), env_overrides.get("CODEX_ID_TOKEN"))
        output = {"type": "agent", "status": "failed" if error else "completed",
                  "model": model or model_type, "conversation_key": conversation_key, **result}
        if error:
            output["error"] = error
        if not output.get("skipped"):
            await node._persist_llm_assistant_turn(output, conversation_id=conversation_id,
                model=model or model_type, raw_text=output["response"], agent_errored=bool(error))
        return output
    except asyncio.CancelledError:
        if future:
            future.cancel()
        if session and all(f.done() for f in session.pending.values()):
            await session.close("Local agent request cancelled")
        raise
    except Exception as exc:
        error = (f"Local {model_type} turn timed out after {TURN_TIMEOUT_S:.0f}s"
                 if isinstance(exc, TimeoutError) else str(exc))
        if session:
            await session.close(error)
        output = {"type": "agent", "status": "failed", "response": "", "error": error,
                  "model": model or model_type, "conversation_key": conversation_key}
        await node._persist_llm_assistant_turn(output, conversation_id=conversation_id,
            model=model or model_type, raw_text="", agent_errored=True)
        return output
    finally:
        if hub is not None:
            remaining = _presence_counts[presence_key] - 1
            if remaining:
                _presence_counts[presence_key] = remaining
            else:
                _presence_counts.pop(presence_key)
                try:
                    await hub.clear_agent_presence(*presence_key)
                except Exception:
                    logger.debug("Local agent presence cleanup failed", exc_info=True)
