"""Real-DB coverage for ``filter_accessible_credential_ids`` — the guard that stops
AI write paths (the agentic builder + external MCP ``set_credentials``) from
attaching a bogus or inaccessible credential id.

The guard rejects credential ids absent from ``credentials`` or inaccessible to
the caller. Otherwise ``authorize_credentials`` can violate the
``workflow_authorized_credentials`` foreign key and abort generation instead of
surfacing a graceful "pick another" message. This
validator filters such ids out so both chokepoints can degrade gracefully.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio  # noqa: F401  (registers async fixtures)

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.credentials import (
    filter_accessible_credential_ids,
    resolve_accessible_credential_types,
)
from coder.workflow.workflow_ops import merge_credentials
from coder.workflow.operation_catalog import (
    get_credential_info,
    node_accepted_credential_types,
)

OWNER = "00000000-0000-4000-8000-0000000000aa"
OTHER = "00000000-0000-4000-8000-0000000000bb"


async def _user(db, uid, email):
    await db.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        uid, email,
    )


async def _cred(db, cid, owner, revoked=False, credential_type="slack_oauth"):
    await db.execute(
        "INSERT INTO credentials (id, owner_id, name, credential_type, credential, revoked_at) "
        "VALUES ($1, $2, 'c', $3, 'enc', $4)",
        cid, owner, credential_type,
        datetime.now(timezone.utc) if revoked else None,
    )


async def _share_to_user(db, cid, target_user, shared_by):
    await db.execute(
        "INSERT INTO resource_shares "
        "(resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('credential', $1, 'user', $2, 'view', $3)",
        cid, target_user, shared_by,
    )


@pytest.mark.asyncio
async def test_empty_and_malformed_input_returns_empty_without_db():
    """Short-circuits before touching the DB; non-UUID / falsy ids never qualify."""
    assert await filter_accessible_credential_ids([], OWNER) == set()
    assert await filter_accessible_credential_ids([None, "", "not-a-uuid"], OWNER) == set()


@pytest.mark.asyncio
async def test_filters_to_existing_accessible_unrevoked(real_database):
    pool = real_database.pool
    await _user(real_database, OWNER, "owner@example.com")
    await _user(real_database, OTHER, "other@example.com")

    owned = str(uuid.uuid4())     # owner's own                       → accessible
    shared = str(uuid.uuid4())    # OTHER's, shared to OWNER           → accessible
    revoked = str(uuid.uuid4())   # owner's but revoked                → dropped
    foreign = str(uuid.uuid4())   # OTHER's, not shared                → dropped
    bogus = str(uuid.uuid4())     # never inserted (the phantom bug)   → dropped

    await _cred(real_database, owned, OWNER)
    await _cred(real_database, revoked, OWNER, revoked=True)
    await _cred(real_database, foreign, OTHER)
    await _cred(real_database, shared, OTHER)
    await _share_to_user(real_database, shared, OWNER, OTHER)

    result = await filter_accessible_credential_ids(
        [owned, shared, revoked, foreign, bogus, "not-a-uuid", "", None], OWNER, pool=pool,
    )
    # Only the existing, accessible, un-revoked credentials survive — the bogus
    # phantom id (the actual failure trigger) is dropped instead of FK-crashing.
    assert result == {owned, shared}


@pytest.mark.asyncio
async def test_org_share_requires_matching_org(real_database):
    """An org-shared credential is accessible only when the matching org_id is
    passed — the builder (no org context) must not silently authorize it."""
    pool = real_database.pool
    org_id = "00000000-0000-4000-8000-0000000000cc"
    await _user(real_database, OWNER, "owner@example.com")
    await _user(real_database, OTHER, "other@example.com")
    await real_database.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org', $2) ON CONFLICT (id) DO NOTHING",
        org_id, f"org-{org_id[:8]}",
    )
    org_cred = str(uuid.uuid4())
    await _cred(real_database, org_cred, OTHER)
    await real_database.execute(
        "INSERT INTO resource_shares "
        "(resource_type, resource_id, target_type, target_org_id, permission, shared_by) "
        "VALUES ('credential', $1, 'organization', $2, 'view', $3)",
        org_cred, org_id, OTHER,
    )

    # No org context → not accessible.
    assert await filter_accessible_credential_ids([org_cred], OWNER, pool=pool) == set()
    # Matching org context → accessible.
    assert await filter_accessible_credential_ids([org_cred], OWNER, pool=pool, org_id=org_id) == {org_cred}


# ---------------------------------------------------------------------------
# Credential-type RESOLUTION — the <set_credentials> simplified form must file a
# credential under the slot it ACTUALLY belongs to (its DB credential_type), not
# the node schema's first union member. Slack lists slack_oauth BEFORE
# slack_bot_token, so the old schema-inference path misfiled every bot token
# under "slack_oauth" — invisible to the FE (which keys credentialIds by
# credential_type). Guards builder.py + mcp_server.py set_credentials re-keying.
# ---------------------------------------------------------------------------


def test_node_accepted_credential_types_returns_all_union_members():
    """The fix's validation helper sees BOTH Slack credential types, while the old
    get_credential_info returns only the first — that gap WAS the bug."""
    accepted = node_accepted_credential_types("automation-slack")
    assert accepted == {"slack_oauth", "slack_bot_token"}
    # The schema-first inference the fix replaces only ever yielded slack_oauth.
    assert get_credential_info("automation-slack").credential_type == "slack_oauth"


@pytest.mark.asyncio
async def test_resolve_returns_actual_credential_type(real_database):
    """resolve_accessible_credential_types returns each id's REAL DB type — a
    bot token resolves to slack_bot_token, not the schema-first slack_oauth."""
    pool = real_database.pool
    await _user(real_database, OWNER, "owner@example.com")

    bot = str(uuid.uuid4())
    oauth = str(uuid.uuid4())
    revoked = str(uuid.uuid4())
    bogus = str(uuid.uuid4())  # never inserted
    await _cred(real_database, bot, OWNER, credential_type="slack_bot_token")
    await _cred(real_database, oauth, OWNER, credential_type="slack_oauth")
    await _cred(real_database, revoked, OWNER, revoked=True, credential_type="slack_bot_token")

    result = await resolve_accessible_credential_types(
        [bot, oauth, revoked, bogus, "not-a-uuid", "", None], OWNER, pool=pool,
    )
    # Only accessible, un-revoked ids resolve — each to its OWN stored type.
    assert result == {bot: "slack_bot_token", oauth: "slack_oauth"}


@pytest.mark.asyncio
async def test_set_credentials_keys_bot_token_under_real_type(real_database):
    """The regression: a slack_bot_token credential placed via the simplified
    <set_credentials node="slack" id=... /> form must land under the
    "slack_bot_token" key, NOT "slack_oauth" (which the FE would show unselected).
    This composes the exact steps builder.py performs."""
    pool = real_database.pool
    await _user(real_database, OWNER, "owner@example.com")
    bot = str(uuid.uuid4())
    await _cred(real_database, bot, OWNER, credential_type="slack_bot_token")

    real_types = await resolve_accessible_credential_types([bot], OWNER, pool=pool)
    accepted = node_accepted_credential_types("automation-slack")
    assert real_types[bot] in accepted  # passes the wrong-provider gate

    config: dict = {}
    merge_credentials(config, {real_types[bot]: bot})
    # Keyed by the credential's real type — the bug stored it under "slack_oauth".
    assert config["credentialIds"] == {"slack_bot_token": bot}


@pytest.mark.asyncio
async def test_wrong_provider_credential_is_rejected(real_database):
    """A credential of a type the node does NOT accept (e.g. a GitHub credential
    on a Slack node) resolves to a real type that fails the accepted-types gate,
    so the write path drops it with a graceful error instead of misfiling it."""
    pool = real_database.pool
    await _user(real_database, OWNER, "owner@example.com")
    gh = str(uuid.uuid4())
    await _cred(real_database, gh, OWNER, credential_type="github_oauth")

    real_types = await resolve_accessible_credential_types([gh], OWNER, pool=pool)
    assert real_types[gh] == "github_oauth"
    # github_oauth is not among Slack's accepted credential types → rejected.
    assert real_types[gh] not in node_accepted_credential_types("automation-slack")
