"""Folding one account into another, in one transaction: what a phone-only
account built moves to the account its owner proved they also hold (an
email account), and the phone-only account is retired.

Every user-keyed column in the schema carries an explicit decision here —
MOVE to the surviving account, or KEEP with the retired one (billing and
usage history, per-account settings, audit trails). The plan spans both
editions' schemas (hosted and open differ by a few tables); a merge acts on
the tables its database has. The ratchet in tests/test_account_merge_postgres.py
fails any user-keyed column that has no decision, so a new table cannot be
left behind silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

MOVE_COLUMNS = (
    ("agent_email_replies", "user_id"),
    ("api_keys", "user_id"),
    ("apps", "owner_id"),
    ("approval_requests", "user_id"),
    ("builder_input_links", "user_id"),
    ("builder_requests", "user_id"),
    ("builder_sessions", "user_id"),
    ("conversations", "user_id"),
    ("coordinator_agent_tasks", "user_id"),
    ("coordinator_memories", "user_id"),
    ("coordinator_wakeups", "user_id"),     # pending follow-ups and alarms
    ("credential_requests", "requester_id"),
    ("credentials", "owner_id"),
    ("email_reservations", "user_id"),
    ("hosted_mcp_servers", "user_id"),
    ("local_cron_schedules", "user_id"),  # the open edition's scheduler
    ("mcp_server_links", "user_id"),
    ("recurring_charges", "user_id"),
    ("resource_forks", "forked_by"),
    ("resource_shares", "shared_by"),
    ("resource_shares", "target_user_id"),
    ("shared_agent_links", "user_id"),
    ("shared_run_links", "user_id"),
    ("skill_user_mutes", "user_id"),
    ("skills", "owner_id"),
    ("template_votes", "user_id"),
    ("tool_call_events", "user_id"),
    ("user_tables_metadata", "owner_id"),
    ("webhook_channels", "user_id"),
    ("webhook_subscriptions", "user_id"),
    ("webhooks", "user_id"),
    ("workflow_build_requests", "user_id"),
    ("workflow_checkpoints", "user_id"),
    ("workflow_embeddings", "owner_id"),
    ("workflow_executions", "user_id"),
    ("workflow_folders", "owner_id"),
    ("workflow_invite_links", "created_by"),
    ("workflow_resources", "owner_id"),
    ("workflow_saved_output", "owner_id"),
    ("workflows", "owner_id"),
)

# Moved by their own rule below, not the plain UPDATE.
SPECIAL_COLUMNS = (
    ("organization_members", "user_id"),  # memberships beyond the retired personal workspace
    ("user_phones", "user_id"),           # live numbers only; unlinked history stays
)

KEEP_COLUMNS = (
    ("account_link_challenges", "target_user_id"),
    ("account_link_challenges", "user_id"),
    ("activity_logs", "user_id"),
    ("approval_requests", "decided_by"),
    ("credential_refresh_events", "user_id"),
    ("instance_oauth_apps", "updated_by"),
    ("instance_provider_keys", "updated_by"),
    ("invite_redemptions", "inviter_id"),
    ("invite_redemptions", "redeemer_id"),
    ("mcp_feedback", "user_id"),
    ("organization_invites", "invited_by"),
    ("organization_members", "invited_by"),
    ("phone_verification_challenges", "user_id"),
    ("trigger_test_credentials", "updated_by"),
    ("trigger_test_runs", "triggered_by"),
    ("user_billing", "id"),
    ("user_feedback", "user_id"),
    ("user_login_stats", "user_id"),
    ("user_notification_preferences", "user_id"),
    ("user_notifications", "user_id"),
    ("user_onboarding_completion", "user_id"),
    ("user_onboarding_responses", "user_id"),
    ("user_usage_events", "user_id"),
    ("voice_calls", "user_id"),                   # the bill of a call already charged
    ("workflow_authorized_credentials", "authorized_by"),
)

# organization_id: rows that moved out of the retired personal workspace land
# in the surviving account's personal workspace.
ORG_MOVE_TABLES = (
    "approval_requests", "credentials", "skills", "user_tables_metadata", "webhooks",
    "workflow_embeddings", "workflow_folders", "workflow_resources", "workflow_saved_output", "workflows",
)
ORG_KEEP_TABLES = (
    "activity_logs", "organization_invites", "organization_members", "user_billing", "user_usage_events",
)

# Text columns that name the retired account's coordinator conversation.
COORDINATOR_REFERENCES = (
    ("builder_requests", "reply_conversation_id"),
    ("builder_input_links", "agent_conversation_id"),
)


@dataclass(frozen=True)
class MergeResult:
    moved: Dict[str, int]  # "table.column" -> rows


def _coordinator(user_id: str) -> str:
    return f"coordinator:{user_id}"


def _count(status: str) -> int:
    return int(status.rsplit(" ", 1)[-1])


async def personal_workspace(conn, user_id: str) -> Optional[str]:
    value = await conn.fetchval(
        "SELECT o.id FROM organization_members m JOIN organizations o ON o.id = m.organization_id "
        "WHERE m.user_id = $1::uuid AND m.role = 'owner' AND o.is_personal_workspace",
        user_id,
    )
    return str(value) if value else None


async def merge_accounts(conn, *, source: str, target: str) -> MergeResult:
    """Move ``source``'s work to ``target`` inside the caller's transaction and
    retire ``source`` (no phone, marked ``merged_into``). Both accounts must be
    locked by the caller for the duration."""
    if source == target:
        raise ValueError("an account cannot merge into itself")
    moved: Dict[str, int] = {}
    present = {(r["relname"], r["attname"]) for r in await conn.fetch(
        "SELECT c.relname, a.attname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND c.relname = ANY($1::text[])",
        sorted({t for t, _ in MOVE_COLUMNS}))}
    s_org, t_org = await personal_workspace(conn, source), await personal_workspace(conn, target)
    args = (source, target)

    # Collisions the plain UPDATE would trip on, resolved first.
    await conn.execute(
        "UPDATE coordinator_memories s SET name = left(s.name, 91) || '-' || left($1::text, 8) WHERE s.user_id = $1::uuid "
        "AND EXISTS (SELECT 1 FROM coordinator_memories t WHERE t.user_id = $2::uuid AND t.name = s.name)", *args)
    await conn.execute(
        "UPDATE user_tables_metadata s SET virtual_table_name = s.virtual_table_name || '_' || left($1::text, 8) "
        "WHERE s.owner_id = $1::uuid AND EXISTS (SELECT 1 FROM user_tables_metadata t "
        "WHERE t.owner_id = $2::uuid AND t.virtual_table_name = s.virtual_table_name)", *args)
    await conn.execute(
        "UPDATE workflow_folders s SET name = s.name || ' (WhatsApp)' WHERE s.owner_id = $1::uuid "
        "AND s.parent_folder_id IS NULL AND EXISTS (SELECT 1 FROM workflow_folders t WHERE t.owner_id = $2::uuid "
        "AND t.parent_folder_id IS NULL AND t.name = s.name "
        "AND t.organization_id IS NOT DISTINCT FROM (CASE WHEN s.organization_id = $3::uuid THEN $4::uuid ELSE s.organization_id END))",
        source, target, s_org, t_org)
    for table, key in (("template_votes", "template_id"), ("skill_user_mutes", "skill_id")):
        await conn.execute(
            f"DELETE FROM {table} s WHERE s.user_id = $1::uuid AND EXISTS "
            f"(SELECT 1 FROM {table} t WHERE t.user_id = $2::uuid AND t.{key} = s.{key})", *args)
    await conn.execute(
        "DELETE FROM resource_shares s WHERE s.target_user_id = $1::uuid AND EXISTS (SELECT 1 FROM resource_shares t "
        "WHERE t.target_user_id = $2::uuid AND t.resource_type = s.resource_type AND t.resource_id = s.resource_id)", *args)
    await conn.execute(
        "DELETE FROM credential_requests s WHERE s.requester_id = $1::uuid AND EXISTS (SELECT 1 FROM credential_requests t "
        "WHERE t.requester_id = $2::uuid AND t.target_email = s.target_email AND t.credential_type = s.credential_type)", *args)

    # One coordinator thread: the retired account's turns follow the target's.
    s_conv, t_conv = _coordinator(source), _coordinator(target)
    if await conn.fetchval("SELECT 1 FROM conversations WHERE conversation_id = $1", t_conv):
        await conn.execute(
            """
            UPDATE conversations t SET
                events = t.events || s.events,
                metadata = jsonb_set(COALESCE(t.metadata, '{}'), '{sdk_history}',
                    COALESCE(t.metadata->'sdk_history', '[]') || COALESCE(s.metadata->'sdk_history', '[]')),
                last_activity = GREATEST(t.last_activity, s.last_activity)
            FROM conversations s WHERE t.conversation_id = $2 AND s.conversation_id = $1
            """, s_conv, t_conv)
        await conn.execute("DELETE FROM conversations WHERE conversation_id = $1", s_conv)
    else:
        await conn.execute("UPDATE conversations SET conversation_id = $2 WHERE conversation_id = $1", s_conv, t_conv)
    for table, column in COORDINATOR_REFERENCES:
        await conn.execute(f"UPDATE {table} SET {column} = $2 WHERE {column} = $1", s_conv, t_conv)
    await conn.execute(
        "UPDATE builder_requests SET origin = jsonb_set(origin, '{coordinator_conversation_id}', to_jsonb($2::text)) "
        "WHERE origin->>'coordinator_conversation_id' = $1", s_conv, t_conv)

    if s_org and t_org:
        for table in ORG_MOVE_TABLES:
            if (table, "organization_id") not in present:
                continue
            owner = next(c for t, c in MOVE_COLUMNS if t == table)
            status = await conn.execute(
                f"UPDATE {table} SET organization_id = $3::uuid WHERE {owner} = $1::uuid AND organization_id = $2::uuid",
                source, s_org, t_org)
            moved[f"{table}.organization_id"] = _count(status)
    for table, column in MOVE_COLUMNS:
        if (table, column) not in present:
            continue
        # Uncast: most user columns are uuid, a few (local_cron_schedules) text.
        status = await conn.execute(f"UPDATE {table} SET {column} = $2 WHERE {column} = $1", *args)
        moved[f"{table}.{column}"] = _count(status)

    status = await conn.execute(
        "UPDATE organization_members s SET user_id = $2::uuid WHERE s.user_id = $1::uuid "
        "AND s.organization_id IS DISTINCT FROM $3::uuid AND NOT EXISTS (SELECT 1 FROM organization_members t "
        "WHERE t.user_id = $2::uuid AND t.organization_id = s.organization_id)", source, target, s_org)
    moved["organization_members.user_id"] = _count(status)

    live = [r["phone_e164"] for r in await conn.fetch(
        "SELECT phone_e164 FROM user_phones WHERE user_id = $1::uuid AND unlinked_at IS NULL", source)]
    await conn.execute(
        "DELETE FROM user_phones WHERE user_id = $1::uuid AND unlinked_at IS NOT NULL AND phone_e164 = ANY($2::text[])",
        target, live)
    status = await conn.execute(
        "UPDATE user_phones SET user_id = $2::uuid, link_version = link_version + 1 "
        "WHERE user_id = $1::uuid AND unlinked_at IS NULL", *args)
    moved["user_phones.user_id"] = _count(status)

    await conn.execute(
        "UPDATE auth.users SET phone = NULL, phone_confirmed_at = NULL, "
        "raw_user_meta_data = COALESCE(raw_user_meta_data, '{}') || jsonb_build_object('merged_into', $2::text) "
        "WHERE id = $1::uuid", *args)
    return MergeResult(moved={k: v for k, v in moved.items() if v})
