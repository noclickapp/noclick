"""Public HTTP surface for builder input bridge links (/api/builder-bridge).

Anyone holding a link id can read a parked builder run's questions and submit
answers — no NoClick account. The link id is the capability (same model as
credential_requests, which the credential-kind inputs delegate to); answering
resumes the parked run AS THE WORKFLOW OWNER via the headless input_response
seam, and the link is consumed exactly once.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.database_pool import get_native_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/builder-bridge", tags=["builder-bridge"])

_MAX_ANSWER_CHARS = 4000


class BridgeSubmitBody(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class BridgeReconnectBody(BaseModel):
    input_id: str


async def _credential_state(request_id: str) -> Optional[Dict[str, Any]]:
    """Fulfillment state of a bridge-minted credential request: the provide
    page runs its own flow; the bridge only needs (status, credential_id)."""
    row = await get_native_pool().fetchrow(
        "SELECT status, credential_id FROM credential_requests WHERE id = $1::uuid",
        request_id,
    )
    return dict(row) if row else None


async def _create_env_credential(
    raw: Any, *, owner_id: str, workflow_name: Optional[str],
) -> Optional[str]:
    """Mint an ``agent_env`` credential from a bridge visitor's ``{NAME: value}``
    bundle, owned by the workflow owner. Returns its id, or None for an empty/
    invalid bundle (a skipped input). Values are validated + encrypted here and
    never leave the credentials table — the resume only carries the id.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    from nodes.agent.config import AGENT_ENV_CREDENTIAL_TYPE
    from nodes.agent.user_env import sanitize_user_env

    try:
        env = sanitize_user_env(raw)
    except ValueError as e:
        logger.warning("[BuilderBridge] rejected env bundle: %s", e)
        return None
    if not env:
        return None

    pool = get_native_pool()
    from billing.plan_limits import get_user_tier_from_db
    from repositories.credentials import create_credential_with_limit_check
    from utils.encryption import get_encryption

    encrypted = get_encryption().encrypt_credential({"env": env})
    async with pool.acquire() as conn:
        tier = await get_user_tier_from_db(conn, owner_id)
        row, error = await create_credential_with_limit_check(
            conn, owner_id, tier, AGENT_ENV_CREDENTIAL_TYPE,
            f"Env vars — {workflow_name or 'workflow'}", encrypted,
            {"var_names": list(env.keys())},
        )
    if error or not row:
        logger.warning("[BuilderBridge] env credential create failed: %s", error)
        return None
    return str(row["id"])


@router.get("/{link_id}")
async def get_bridge_link(link_id: str) -> Dict[str, Any]:
    """The parked ask's questions. Public — no auth; the id is the capability."""
    from repositories.builder_bridge import BuilderBridgeRepo

    pool = get_native_pool()
    link = await BuilderBridgeRepo(pool).load_pending(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="This link is invalid, answered, or expired")

    # Self-heal deficient snapshots (pre-fix links: empty credential types /
    # missing provide tokens) before serving — see heal_link_inputs.
    from utils.builder_bridge import heal_link_inputs

    healed = await heal_link_inputs(pool, link)

    inputs = []
    for inp in healed:
        entry = dict(inp)
        # Never expose the internal credential_request id; surface only the
        # provide URL + live fulfillment state.
        req_id = entry.pop("credential_request_id", None)
        if req_id:
            state = await _credential_state(req_id)
            entry["credential_fulfilled"] = bool(state and state["status"] == "fulfilled")
        inputs.append(entry)

    return {
        "workflow_name": link.get("workflow_name") or "a workflow",
        "created_at": link["created_at"].isoformat(),
        "expires_at": link["expires_at"].isoformat(),
        "inputs": inputs,
    }


@router.post("/{link_id}/reconnect")
async def reconnect_bridge_credential(link_id: str, body: BridgeReconnectBody) -> Dict[str, Any]:
    """Re-open a credential input so the visitor can connect a DIFFERENT
    account (a test token isn't an ending). Re-upserting the request rotates
    its token and resets it to pending — the already-created credential stays
    untouched in the owner's account (an anonymous surface never deletes) —
    and the snapshot is refreshed so the connect UI renders again."""
    from repositories.builder_bridge import BuilderBridgeRepo
    from repositories.credentials import CredentialsRepo
    from utils.builder_bridge import heal_link_inputs
    from utils.email import credential_provide_url

    pool = get_native_pool()
    repo = BuilderBridgeRepo(pool)
    link = await repo.load_pending(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="This link is invalid, answered, or expired")

    inputs = await heal_link_inputs(pool, link)
    entry = next(
        (e for e in inputs if e.get("id") == body.input_id and e.get("type") == "credential"),
        None,
    )
    if not entry or not entry.get("credential_type"):
        raise HTTPException(status_code=404, detail="No such credential input")

    row = await CredentialsRepo(pool).upsert_credential_request(
        requester_id=str(link["user_id"]),
        target_email="",
        credential_type=entry["credential_type"],
        message=(
            f"Requested by the workflow builder for "
            f"'{link.get('workflow_name') or 'a workflow'}'"
        ),
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to re-open the credential request")
    entry["credential_request_id"] = str(row.id)
    entry["credential_provide_token"] = row.token
    entry["credential_provide_url"] = credential_provide_url(row.token)
    await repo.update_inputs(link_id, inputs)
    return {"success": True}


@router.post("/{link_id}")
async def submit_bridge_answers(link_id: str, body: BridgeSubmitBody) -> Dict[str, Any]:
    """Submit answers and resume the parked run as the workflow owner.

    Credential-kind inputs are resolved server-side from their fulfilled
    credential_requests rows (the visitor connected via the public provide
    page) — the visitor never supplies a credential id. The resume runs in the
    background; the link is consumed first so a double-submit can't fire two
    builder turns.
    """
    from repositories.builder_bridge import BuilderBridgeRepo

    pool = get_native_pool()
    repo = BuilderBridgeRepo(pool)
    link = await repo.load_pending(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="This link is invalid, answered, or expired")

    from utils.builder_bridge import heal_link_inputs

    healed_inputs = await heal_link_inputs(pool, link)

    # Skipped inputs (including unconnected credentials) are simply OMITTED —
    # the drawer's partial-submit semantics: the brain sees what WAS answered
    # and re-asks or proceeds. Only a fully-empty submit is refused.
    values: Dict[str, Any] = {}
    for inp in healed_inputs:
        input_id = inp.get("id")
        if not input_id:
            continue
        if inp.get("type") == "credential":
            req_id = inp.get("credential_request_id")
            state = await _credential_state(req_id) if req_id else None
            if state and state["status"] == "fulfilled" and state["credential_id"]:
                values[input_id] = str(state["credential_id"])
            continue
        if inp.get("type") == "env":
            # The visitor supplies {NAME: value}. Never store raw values — mint an
            # agent_env credential as the OWNER (link identity) and answer with its
            # id, so the resume attaches it via <set_credentials> exactly like a
            # connected credential. A blank/omitted bundle is a skipped input.
            raw = body.values.get(input_id)
            cred_id = await _create_env_credential(
                raw, owner_id=str(link["user_id"]), workflow_name=link.get("workflow_name"),
            )
            if cred_id:
                values[input_id] = cred_id
            continue
        raw = body.values.get(input_id)
        if raw is None or raw == "":
            continue
        values[input_id] = str(raw)[:_MAX_ANSWER_CHARS]

    if not values:
        raise HTTPException(status_code=422, detail="No answers provided")

    # Consume the link BEFORE resuming — exactly-once even under a double POST.
    if not await repo.mark_answered(link_id):
        raise HTTPException(status_code=409, detail="This link was already answered")

    from utils.async_helpers import spawn
    from utils.socket_singleton import get_sio
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(get_sio())
    spawn(
        handler.handle_input_response(
            "",
            {
                "conversation_id": link["builder_conversation_id"],
                "ask_id": link["ask_id"],
                "values": values,
            },
            caller_user_id=str(link["user_id"]),
        ),
        name=f"builder-bridge-resume:{link_id}",
    )
    logger.info(
        "[BuilderBridge] link %s answered (%d values) — resuming conv %s",
        link_id, len(values), link["builder_conversation_id"],
    )
    return {"success": True}
