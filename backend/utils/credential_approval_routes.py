"""Human-only credential policy editing and exact-call review.

These routes accept the owner's Supabase browser session, never an MCP token,
shadow-tool credential, or the mere possession of a review URL.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from repositories.credential_approvals import CredentialApprovalRepo
from utils.auth import verify_token
from utils.credential_operations import operation_catalog
from utils.database_pool import get_native_pool

router = APIRouter()


async def human(authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in to review this credential.")
    try:
        claims = await verify_token(token)
        if claims.get("role") != "authenticated" or not claims.get("session_id"):
            raise ValueError("A browser session is required")
        return str(UUID(claims["sub"]))
    except Exception:
        raise HTTPException(401, "Sign in to review this credential.") from None


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[str] = Field(max_length=20000)
    expected_revision: int = Field(ge=0)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str


@router.get("/permissions/{credential_id}")
async def policy(credential_id: UUID, user_id=Depends(human)):
    from wss.handlers.workflow_handler import get_user_org_context
    pool = get_native_pool()
    async with pool.acquire() as conn:
        org_id = await get_user_org_context(conn, user_id)
    try:
        row = await CredentialApprovalRepo(pool).policy(str(credential_id), user_id, org_id)
        from repositories.coordinator_links import CoordinatorLinkRepo
        return {"id": str(row["id"]), "name": row["name"], "credential_type": row["credential_type"],
                "operations": operation_catalog(row["credential_type"]),
                "approval_operations": row["approval_operations"], "revision": row["approval_revision"],
                "can_edit": str(row["owner_id"]) == user_id,
                "review_pending": await CoordinatorLinkRepo(pool).pending("credential_policy", credential_id, user_id)}
    except PermissionError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/permissions/{credential_id}")
async def save_policy(credential_id: UUID, body: PolicyChange, user_id=Depends(human)):
    repo = CredentialApprovalRepo(get_native_pool())
    try:
        row = await repo.policy(str(credential_id), user_id)
        if str(row["owner_id"]) != user_id:
            raise PermissionError("Only the owner can change approval rules.")
        valid = {op["key"] for op in operation_catalog(row["credential_type"])} | {"*"}
        # Preserve unknown historical rules on save; a human may remove them.
        if set(body.operations) - valid - set(row["approval_operations"]):
            raise ValueError("Unknown operation in approval policy.")
        revision = await repo.replace_from_human(str(credential_id), user_id, body.operations, body.expected_revision)
        from utils.coordinator_links import dispatch_link
        dispatch_link(get_native_pool(), "credential_policy", credential_id)
        return {"revision": revision, "approval_operations": sorted(set(body.operations))}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


def review_view(row):
    from datetime import datetime, timezone
    payload = row["action_payload"]
    valid = not row.get("revoked_at") and row["expires_at"] > datetime.now(timezone.utc) and payload["policy_revision"] == row.get("approval_revision", payload["policy_revision"])
    return {"id": str(row["id"]), "credential_id": str(row["credential_id"]),
            "credential_name": row.get("credential_name"), "operation": payload["operation"],
            "node_type": payload["node_type"], "arguments": payload["arguments"],
            "status": row["status"], "consumed": bool(row["consumed_at"]),
            "actionable": valid and row["status"] == "pending", "expires_at": row["expires_at"].isoformat(),
            "coordinator": bool(payload.get("continuation")), "workflow": bool(row["execution_id"])}


@router.get("/approval/{approval_id}")
async def review(approval_id: UUID, user_id=Depends(human)):
    try:
        return review_view(await CredentialApprovalRepo(get_native_pool()).request(str(approval_id), user_id))
    except PermissionError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/approval/{approval_id}")
async def decide(approval_id: UUID, body: Decision, user_id=Depends(human)):
    pool = get_native_pool()
    repo = CredentialApprovalRepo(pool)
    try:
        row = await repo.decide_from_human(str(approval_id), user_id, body.decision)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    from utils.async_helpers import spawn
    from utils.credential_approval_dispatch import dispatch_decision
    spawn(dispatch_decision(pool, row), name=f"credential-approval:{row['id']}")
    return review_view(await repo.request(str(approval_id), user_id))
