"""Builder input bridge: public capability links for answering a parked
builder run's <ask/> without a NoClick account.

When an agent-initiated (headless) builder run pauses on questions, a link is
minted here and relayed to the agent's conversation — the agent shares it
through its channels (Telegram, Slack, …) and whoever holds it answers the
questions / connects credentials on the public /b/{id} page, which resumes the
run as the workflow owner. Same capability trust model as credential_requests
(which this reuses verbatim for credential-kind inputs) and shared agent links.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Carrier message for builder wake turns. Agent config models require a
# non-empty message (min_length=1), so an empty-string override fails config
# validation before the pre-dispatch relay can compose pending events. The
# agent node strips this sentinel: relay note present → the note is the whole
# turn; nothing pending (raced by a concurrent turn) → the run no-ops instead
# of dispatching a ghost turn.
WAKE_TURN_MESSAGE = "__builder_wake_turn__"


def bridge_url(link_id: str) -> str:
    from mcp_adapter.auth.endpoints import get_frontend_url

    return f"{get_frontend_url()}/b/{link_id}"


def _sanitize_input(inp: Dict[str, Any]) -> Dict[str, Any]:
    """The public projection of one ask input — labels and choices only, never
    node configs or credential id maps (those stay server-side)."""
    out: Dict[str, Any] = {
        "id": inp.get("id"),
        "label": inp.get("label") or "",
        "description": inp.get("description") or "",
        "required": bool(inp.get("required", True)),
        "type": inp.get("type") or "text",
    }
    if inp.get("options"):
        out["options"] = inp["options"]
        if inp.get("multiple"):
            out["multiple"] = True
    if inp.get("defaultValue") is not None:
        out["defaultValue"] = inp["defaultValue"]
    if inp.get("type") == "credential":
        out["credential_type"] = inp.get("credentialType") or ""
    if inp.get("type") == "env":
        # NAMES the visitor must provide (+ optional descriptions). No values —
        # the /b page collects them and the submit turns them into an agent_env
        # credential. Safe to expose: names only, same as the config-panel chips.
        out["env_keys"] = inp.get("envKeys") or []
    return out


async def create_bridge_link_for_ask(
    pool,
    *,
    user_id: str,
    workflow_id: str,
    builder_conversation_id: str,
    ask_id: str,
    inputs: List[Dict[str, Any]],
    agent_conversation_id: Optional[str],
    agent_node_id: Optional[str],
    workflow_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Mint the capability link for a parked ask. Credential-kind inputs each
    get a credential_requests row (requester = owner, link mode) whose EXISTING
    public provide page handles the actual connect; the bridge page just links
    to it and the submit resolves the fulfilled credential id server-side.
    Returns {link_id, url, questions} or None on failure (best-effort — a
    minting failure must never fail the builder run)."""
    try:
        from repositories.builder_bridge import BuilderBridgeRepo
        from repositories.credentials import CredentialsRepo
        from utils.email import credential_provide_url

        sanitized: List[Dict[str, Any]] = []
        for inp in inputs or []:
            entry = _sanitize_input(inp)
            if entry["type"] == "credential" and entry.get("credential_type"):
                row = await CredentialsRepo(pool).upsert_credential_request(
                    requester_id=user_id,
                    target_email="",
                    credential_type=entry["credential_type"],
                    message=(
                        f"Requested by the workflow builder for "
                        f"'{workflow_name or 'a workflow'}'"
                    ),
                )
                if row:
                    entry["credential_request_id"] = str(row.id)
                    entry["credential_provide_url"] = credential_provide_url(row.token)
                    # The bridge page embeds the REAL provide flow inline
                    # (CredentialProvideFlow keys on this token) — same trust
                    # envelope as the link itself.
                    entry["credential_provide_token"] = row.token
            sanitized.append(entry)

        link_id = await BuilderBridgeRepo(pool).create_link(
            user_id=user_id,
            workflow_id=workflow_id,
            builder_conversation_id=builder_conversation_id,
            ask_id=ask_id,
            agent_conversation_id=agent_conversation_id,
            agent_node_id=agent_node_id,
            inputs=sanitized,
            workflow_name=workflow_name,
        )
        return {
            "link_id": link_id,
            "url": bridge_url(link_id),
            "questions": [e["label"] for e in sanitized if e.get("label")],
            # Compact input specs for the agent-facing note (ids let
            # builder_respond answer precisely). Provide fields stay out.
            "inputs": [
                {k: e[k] for k in ("id", "label", "description", "type", "required", "options", "multiple", "env_keys")
                 if k in e and e[k] not in (None, "")}
                for e in sanitized
            ],
        }
    except Exception:
        logger.error("[BuilderBridge] link minting failed", exc_info=True)
        return None


async def heal_link_inputs(pool, link: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Repair a link's credential entries in place and persist the result.

    Snapshots are baked at mint time, so links minted before a plumbing fix
    (the empty-credential_type era, the pre-inline-token era) served dead
    credential steps forever — and the share button intentionally re-hands out
    the same pending link. The conversation's pending_ask still carries the
    FULL inputs (nodeType + nodeConfig), so a deficient entry can always be
    re-derived: backfill the provide token from an existing request row, else
    mint the credential_request now (as the link owner). Best-effort per
    entry; returns the (possibly healed) inputs list either way."""
    import json

    inputs = link["inputs"]
    if isinstance(inputs, str):
        inputs = json.loads(inputs)
    inputs = list(inputs or [])

    needs_heal = [
        i for i, e in enumerate(inputs)
        if e.get("type") == "credential" and not e.get("credential_provide_token")
    ]
    if not needs_heal:
        return inputs

    from repositories.builder_bridge import BuilderBridgeRepo
    from repositories.credentials import CredentialsRepo
    from utils.email import credential_provide_url

    # Full ask inputs from the conversation, for entries whose snapshot never
    # captured a credential type. Fetched lazily, once.
    full_by_id: Optional[Dict[str, Dict[str, Any]]] = None

    async def full_inputs_by_id() -> Dict[str, Dict[str, Any]]:
        nonlocal full_by_id
        if full_by_id is None:
            full_by_id = {}
            try:
                row = await pool.fetchrow(
                    "SELECT pending_ask FROM conversations WHERE conversation_id = $1",
                    link["builder_conversation_id"],
                )
                pending = row["pending_ask"] if row else None
                if isinstance(pending, str):
                    pending = json.loads(pending)
                for inp in (pending or {}).get("inputs") or []:
                    if isinstance(inp, dict) and inp.get("id"):
                        full_by_id[inp["id"]] = inp
            except Exception:
                logger.warning("[BuilderBridge] pending_ask read failed during heal", exc_info=True)
        return full_by_id

    changed = False
    for i in needs_heal:
        entry = inputs[i]
        try:
            req_id = entry.get("credential_request_id")
            if req_id:
                # Pre-inline-token era: the request exists — backfill its token
                # without re-minting (an upsert would rotate it needlessly).
                row = await pool.fetchrow(
                    "SELECT token, credential_type FROM credential_requests WHERE id = $1::uuid",
                    req_id,
                )
                if row:
                    entry["credential_provide_token"] = row["token"]
                    entry["credential_provide_url"] = credential_provide_url(row["token"])
                    entry.setdefault("credential_type", row["credential_type"])
                    changed = True
                continue

            cred_type = entry.get("credential_type")
            if not cred_type:
                # Empty-type era: re-derive from the conversation's full input.
                full = (await full_inputs_by_id()).get(entry.get("id") or "")
                cred_type = (full or {}).get("credentialType")
                if not cred_type and full and full.get("nodeType"):
                    from coder.workflow.operation_catalog import (
                        derive_credential_type,
                    )

                    cred_type = derive_credential_type(
                        full["nodeType"], None, full.get("nodeConfig"),
                    )
                if not cred_type:
                    continue
                entry["credential_type"] = cred_type

            row = await CredentialsRepo(pool).upsert_credential_request(
                requester_id=str(link["user_id"]),
                target_email="",
                credential_type=cred_type,
                message=(
                    f"Requested by the workflow builder for "
                    f"'{link.get('workflow_name') or 'a workflow'}'"
                ),
            )
            if row:
                entry["credential_request_id"] = str(row.id)
                entry["credential_provide_url"] = credential_provide_url(row.token)
                entry["credential_provide_token"] = row.token
                changed = True
        except Exception:
            logger.warning(
                "[BuilderBridge] heal failed for input %s", entry.get("id"), exc_info=True
            )

    if changed:
        try:
            await BuilderBridgeRepo(pool).update_inputs(str(link["id"]), inputs)
        except Exception:
            logger.warning("[BuilderBridge] healed-inputs persist failed", exc_info=True)
    return inputs


async def fire_agent_wake_turn(
    pool,
    *,
    user_id: str,
    workflow_id: str,
    node_id: Optional[str],
    agent_conversation_id: str,
) -> None:
    """Fire an immediate agent turn so builder updates reach the agent WITHOUT
    waiting for the next user message — the agent answers design asks itself
    (builder_respond) or pushes the bridge link through its channels. The
    turn's user message is empty; the pre-dispatch relay
    (AgentNode._relay_builder_updates) composes the pending events into the
    turn, so push and next-user-message delivery are ONE mechanism and the
    latter stays as the backstop when this fails. Loop safety rides the
    existing gates: every wake turn is credit-gated, and every builder resume
    consumes an AI-builder credit.

    Best-effort; only fires when something is actually undelivered and the
    conversation id is ck-shaped (re-keyable into a run)."""
    try:
        parts = agent_conversation_id.split(":", 3)
        if len(parts) != 4 or parts[0] != "ck" or not node_id:
            return
        conversation_key = parts[3]

        from repositories.conversation import ConversationRepo

        if not await ConversationRepo(pool).fetch_unrelayed_builder_events(agent_conversation_id):
            return  # consumed by a user turn in the meantime — nothing to wake for

        import uuid as _uuid

        from utils.socket_singleton import get_sio
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
        from wss.receiver.client_events import WorkflowExecuteRequest

        request = WorkflowExecuteRequest(
            request_id=f"builder-wake-{_uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            start_node_id=node_id,
            trigger_source="builder_event",
            conversation_id=agent_conversation_id,
            config_overrides={
                node_id: {
                    "message": WAKE_TURN_MESSAGE,
                    "conversation_key": conversation_key,
                    "mockedOutput": None,
                }
            },
        )
        handler = WorkflowExecutionHandler(get_sio())
        await handler.handle_execute(sid="", request=request, caller_user_id=user_id)
        logger.info(
            "[BuilderBridge] wake turn fired for %s (%s)", node_id, agent_conversation_id
        )
    except Exception:
        logger.error("[BuilderBridge] wake turn failed — next-user-message backstop applies", exc_info=True)


async def append_agent_builder_event(
    pool,
    *,
    agent_conversation_id: str,
    user_id: str,
    workflow_id: Optional[str],
    node_id: Optional[str],
    kind: str,
    payload: Dict[str, Any],
) -> None:
    """Append a builder outcome event ({builder_ask} / {builder_result}) to the
    ORIGINATING agent conversation — the next-turn relay note delivers it to
    the model, and the chat mapper can render it. Best-effort."""
    from repositories.conversation import ConversationRepo

    try:
        await ConversationRepo(pool).append_chat_event(
            conversation_id=agent_conversation_id,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            event={
                kind: payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            label=None,
            model=None,
        )
    except Exception:
        logger.error(
            "[BuilderBridge] failed to append %s to %s", kind, agent_conversation_id,
            exc_info=True,
        )
