"""Per-credential restrictions and single-use grants in the existing approval queue.

The credential row serializes policy changes and admission. Exact-call grants
are consumed before external I/O; retries never silently reuse an approval.
"""

import hashlib
import json
from uuid import UUID

from repositories.credentials import credential_access_predicate


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class CredentialApprovalRepo:
    def __init__(self, pool):
        self.pool = pool

    async def policy(self, credential_id, user_id, organization_id=None):
        row = await self.pool.fetchrow(
            f"SELECT c.id,c.name,c.credential_type,c.owner_id,c.approval_operations,c.approval_revision "
            f"FROM credentials c WHERE c.id=$1::uuid AND {credential_access_predicate()}",
            credential_id, user_id, organization_id,
        )
        if not row:
            raise PermissionError("Credential not found or not accessible.")
        return dict(row)

    async def tighten(self, credential_id, user_id, operations):
        """AI-facing primitive: union only, owner only. No replace/remove flag."""
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT approval_operations FROM credentials WHERE id=$1::uuid AND owner_id=$2::uuid FOR UPDATE",
                credential_id, user_id,
            )
            if row is None:
                raise PermissionError("Only the credential owner can change its restrictions.")
            merged = sorted(set(row["approval_operations"]) | set(operations))
            if merged != sorted(row["approval_operations"]):
                await conn.execute(
                    "UPDATE credentials SET approval_operations=$3,approval_revision=approval_revision+1 "
                    "WHERE id=$1::uuid AND owner_id=$2::uuid", credential_id, user_id, merged,
                )
        return merged

    async def replace_from_human(self, credential_id, user_id, operations, expected_revision):
        """Only the authenticated browser route exposes this compare-and-swap."""
        row = await self.pool.fetchrow(
            "UPDATE credentials SET approval_operations=$3,approval_revision=approval_revision+1 "
            "WHERE id=$1::uuid AND owner_id=$2::uuid AND approval_revision=$4 RETURNING approval_revision",
            credential_id, user_id, sorted(set(operations)), expected_revision,
        )
        if row is None:
            raise ValueError("The policy changed or you are not its owner. Refresh before saving.")
        return row["approval_revision"]

    async def has_restrictions(self, credential_id):
        return await self.pool.fetchval(
            "SELECT cardinality(approval_operations)>0 FROM credentials WHERE id=$1::uuid", credential_id,
        )

    async def admit(self, *, credential_id, user_id, node_type, operation, arguments,
                    organization_id=None, workflow_id=None, execution_id=None, node_id=None,
                    conversation_id=None, continuation=None):
        """None admits a call. Otherwise return its durable approval record."""
        async with self.pool.acquire() as conn, conn.transaction():
            credential = await conn.fetchrow(
                "SELECT name,owner_id,approval_operations,approval_revision,revoked_at FROM credentials "
                "WHERE id=$1::uuid FOR UPDATE", credential_id,
            )
            if credential is None or credential["revoked_at"]:
                raise PermissionError("Credential no longer available.")
            restrictions = credential["approval_operations"]
            key = f"{node_type}.{operation}"
            if "*" not in restrictions and key not in restrictions and not (operation == "__lookup__" and restrictions):
                return None
            payload = {
                "credential_id": str(UUID(credential_id)), "caller_user_id": str(UUID(user_id)),
                "organization_id": str(organization_id) if organization_id else None,
                "node_type": node_type, "operation": operation, "arguments": arguments,
                "workflow_id": str(workflow_id) if workflow_id else None,
                "execution_id": str(execution_id) if execution_id else None,
                "node_id": node_id, "conversation_id": conversation_id,
                "policy_revision": credential["approval_revision"],
            }
            encoded = canonical_json(payload)
            if len(encoded.encode()) > 256_000:
                raise ValueError("This action is too large to review. Reduce its arguments before requesting approval.")
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            # Pending calls deduplicate, decisions cannot change arguments, and
            # each approved grant admits one retry of precisely the same call.
            existing = await conn.fetchrow(
                "SELECT id,status,consumed_at,expires_at FROM approval_requests "
                "WHERE credential_id=$1::uuid AND action_fingerprint=$2 AND expires_at>now() "
                "AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
                credential_id, fingerprint,
            )
            if existing:
                if existing["status"] == "approved":
                    await conn.execute("UPDATE approval_requests SET consumed_at=now() WHERE id=$1", existing["id"])
                    return None
                return dict(existing)
            count = await conn.fetchval(
                "SELECT count(*) FROM approval_requests WHERE credential_id=$1::uuid "
                "AND status='pending' AND expires_at>now()", credential_id,
            )
            if count >= 100:
                raise ValueError("This credential already has 100 pending approvals. Review them before requesting more.")
            payload["continuation"] = continuation
            content = {"credential_action": True, "credential_name": credential["name"],
                       "node_type": node_type, "operation": operation, "arguments": arguments,
                       "fields": [], "values": {}}
            row = await conn.fetchrow(
                "INSERT INTO approval_requests (workflow_id,execution_id,node_id,user_id,organization_id,"
                "title,content,credential_id,action_fingerprint,action_payload,expires_at) "
                "VALUES ($1::uuid,$2::uuid,$3,$4::uuid,NULL,$5,$6,$7::uuid,$8,$9,now()+interval '24 hours') "
                "RETURNING id,status,consumed_at,expires_at",
                workflow_id, execution_id, node_id or "__credential__", str(credential["owner_id"]),
                f"{operation.replace('_', ' ')} · {credential['name']}", json.dumps(content),
                credential_id, fingerprint, payload,
            )
            if execution_id:
                await conn.execute(
                    "UPDATE workflow_executions SET status='awaiting_approval',finished_at=now() WHERE id=$1::uuid",
                    execution_id,
                )
            return {**dict(row), "new_request": True, "owner_id": str(credential["owner_id"]),
                    "title": f"{operation.replace('_', ' ')} · {credential['name']}"}

    async def resumable_workflows(self, execution_id=None):
        """The approval queue is also the recovery outbox; no second job store.

        Wait for this suspended batch's decisions, then resume its roots together
        so shared downstream nodes execute once. Claiming the execution below
        serializes an immediate browser dispatch with the recovery worker.
        """
        return await self.pool.fetch(
            "SELECT DISTINCT a.execution_id FROM approval_requests a "
            "JOIN workflow_executions e ON e.id=a.execution_id "
            "WHERE a.credential_id IS NOT NULL AND a.status='approved' AND a.consumed_at IS NULL "
            "AND a.expires_at>now() AND e.status='awaiting_approval' "
            "AND ($1::uuid IS NULL OR e.id=$1::uuid) "
            "AND ($1::uuid IS NOT NULL OR a.dispatch_after<=now()) "
            "AND NOT EXISTS (SELECT 1 FROM approval_requests p WHERE p.execution_id=e.id "
            "AND p.credential_id IS NOT NULL AND p.consumed_at IS NULL "
            "AND (p.status<>'approved' OR p.expires_at<=now())) LIMIT 25", execution_id,
        )

    async def defer_dispatch(self, execution_id):
        # Bounded recovery scans rotate past unavailable checkpoints instead of
        # letting their first batch starve all later workflow approvals.
        await self.pool.execute(
            "UPDATE approval_requests SET dispatch_after=now()+interval '2 minutes' "
            "WHERE execution_id=$1::uuid AND credential_id IS NOT NULL "
            "AND status='approved' AND consumed_at IS NULL", execution_id,
        )

    async def scheduled_request(self, approval_id, caller_id):
        row = await self.pool.fetchrow(
            "SELECT * FROM approval_requests WHERE id=$1::uuid AND credential_id IS NOT NULL "
            "AND action_payload->>'caller_user_id'=$2", approval_id, caller_id,
        )
        return dict(row) if row else None

    async def workflow_grants(self, execution_id):
        return await self.pool.fetch(
            "SELECT a.* FROM approval_requests a JOIN credentials c ON c.id=a.credential_id "
            "WHERE a.execution_id=$1::uuid AND a.status='approved' AND a.consumed_at IS NULL "
            "AND a.expires_at>now() AND c.revoked_at IS NULL "
            "AND (a.action_payload->>'policy_revision')::bigint=c.approval_revision "
            "ORDER BY a.created_at,a.id", execution_id,
        )

    async def claim_workflow_resume(self, execution_id, approval_ids):
        return await self.pool.fetchval(
            "UPDATE workflow_executions e SET status='running',finished_at=NULL "
            "WHERE e.id=$1::uuid AND e.status='awaiting_approval' "
            "AND NOT EXISTS (SELECT 1 FROM approval_requests a WHERE a.execution_id=e.id "
            "AND a.credential_id IS NOT NULL AND a.consumed_at IS NULL "
            "AND (a.status<>'approved' OR a.expires_at<=now() OR NOT (a.id=ANY($2::uuid[])))) "
            "RETURNING e.id", execution_id, approval_ids,
        ) is not None

    async def restore_unstarted_resume(self, execution_id):
        # A relay/persistence failure before consumption is retryable. Never
        # replay a grant whose provider may already have received the call.
        await self.pool.execute(
            "UPDATE workflow_executions e SET status='awaiting_approval',finished_at=now() "
            "WHERE e.id=$1::uuid AND e.status='running' AND EXISTS "
            "(SELECT 1 FROM approval_requests a WHERE a.execution_id=e.id "
            "AND a.credential_id IS NOT NULL AND a.status='approved' AND a.consumed_at IS NULL)", execution_id,
        )

    async def request(self, approval_id, owner_id):
        row = await self.pool.fetchrow(
            "SELECT a.*,c.name AS credential_name,c.approval_revision,c.revoked_at "
            "FROM approval_requests a JOIN credentials c ON c.id=a.credential_id "
            "WHERE a.id=$1::uuid AND c.owner_id=$2::uuid", approval_id, owner_id,
        )
        if row is None:
            raise PermissionError("Approval not found or not owned by this account.")
        return dict(row)

    async def decide_from_human(self, approval_id, owner_id, decision):
        """Immutable decision; an owner browser session is checked by the route."""
        if decision not in ("approved", "rejected"):
            raise ValueError("Invalid decision.")
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "UPDATE approval_requests a SET status=$3,decided_by=$2::uuid,decided_at=now(),"
                "expires_at=LEAST(a.expires_at,now()+interval '30 minutes') "
                "FROM credentials c WHERE a.id=$1::uuid AND a.credential_id=c.id AND c.owner_id=$2::uuid "
                "AND a.status='pending' AND a.expires_at>now() AND c.revoked_at IS NULL "
                "AND (a.action_payload->>'policy_revision')::bigint=c.approval_revision RETURNING a.*",
                approval_id, owner_id, decision,
            )
            if row is None:
                raise ValueError("This request was already decided, expired, or its credential policy changed.")
            payload = row["action_payload"]
            if row["execution_id"] and decision == "rejected":
                await conn.execute(
                    "UPDATE workflow_executions SET status='error',error='Credential action declined by owner',finished_at=now() "
                    "WHERE id=$1 AND status='awaiting_approval'", row["execution_id"],
                )
            context = payload.get("continuation")
            if context and payload.get("conversation_id") == f"coordinator:{payload['caller_user_id']}":
                # Commit decision and follow-up together. Scheduler reconciliation
                # repairs a crash before the route dispatches this outbox event.
                await conn.execute(
                    "INSERT INTO coordinator_wakeups(user_id,source,source_id,context,payload,send_to_phone) "
                    "VALUES ($1::uuid,'credential_approval',$2,$3,$4,$5) ON CONFLICT(source,source_id) DO NOTHING",
                    payload["caller_user_id"], row["id"], context,
                    {"approval_id": str(row["id"]), "status": decision,
                     "credential_id": str(row["credential_id"]), "node_type": payload["node_type"],
                     "operation": payload["operation"], "arguments": payload["arguments"]},
                    context.get("channel", "web") != "web",
                )
            return dict(row)
