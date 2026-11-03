"""A member who puts their own connection on a workflow someone else owns is told its automatic runs can't use it.

Trigger, schedule and agent runs go as the workflow's owner, so a connection only the member holds fails there
("Failed to resolve credential") while it looks fine on the canvas. Nothing about access changes: the member is
warned when they attach it (the panel's authorize call, the builder's and the workflow MCP's set_credentials),
and the run-time error already says why.
"""

import uuid

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.credentials import member_connection_warnings
from utils.encryption import get_encryption

OWNER = "00000000-0000-4000-8000-0000000003a1"
MEMBER = "00000000-0000-4000-8000-0000000003b2"


async def _world(db):
    for user_id in (OWNER, MEMBER):
        await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                         user_id, f"{user_id[-3:]}@example.com")
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Inbox', $3)",
                     workflow_id, OWNER, {"nodes": [], "edges": []})
    return workflow_id


async def _credential(db, owner, name="Shop WhatsApp"):
    credential_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO credentials (id, owner_id, name, credential_type, credential) "
        "VALUES ($1::uuid, $2::uuid, $3, 'whatsapp_qr', $4)",
        credential_id, owner, name, get_encryption().encrypt_credential({"connection_id": "conn-1"}))
    return credential_id


WARNING = ('Your "Shop WhatsApp" won\'t work in this workflow\'s automatic runs (triggers, schedules and agents): '
           "they use the workflow owner's connections. Share it with the owner, or ask them to connect their own "
           "account on this step.")


@pytest.mark.asyncio
async def test_a_members_own_connection_on_the_owners_workflow_is_named(real_database):  # noqa: F811
    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)

    assert await member_connection_warnings(db.pool, workflow_id, MEMBER, [theirs]) == {theirs: WARNING}


@pytest.mark.asyncio
async def test_nothing_is_said_where_the_owners_runs_can_use_it(real_database):  # noqa: F811
    db = real_database
    workflow_id = await _world(db)
    shared, owners = await _credential(db, MEMBER), await _credential(db, OWNER)
    await db.execute(
        "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('credential', $1::uuid, 'user', $2::uuid, 'view', $3::uuid)", shared, OWNER, MEMBER)

    assert await member_connection_warnings(db.pool, workflow_id, MEMBER, [shared, owners]) == {}
    # The owner's own placement is never questioned.
    assert await member_connection_warnings(db.pool, workflow_id, OWNER, [await _credential(db, MEMBER)]) == {}


@pytest.mark.asyncio
async def test_the_panel_hears_it_when_the_member_picks_it(real_database):  # noqa: F811
    from unittest.mock import AsyncMock, MagicMock

    from wss.handlers.credentials_handler import CredentialsHandler
    from wss.receiver.client_events import CredentialAuthorizeForWorkflowRequest

    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": MEMBER})
    sio.emit = AsyncMock()
    handler = CredentialsHandler(sio=sio)
    handler.get_pool = AsyncMock(return_value=db.pool)

    await handler.authorize_for_workflow("sid", CredentialAuthorizeForWorkflowRequest(
        request_id="r", workflow_id=workflow_id, credential_id=theirs))

    reply = sio.emit.await_args.args[1]
    assert reply["data"] == {"authorized": False, "warning": WARNING}
    assert await db.fetchval("SELECT count(*) FROM workflow_authorized_credentials WHERE workflow_id = $1::uuid",
                             workflow_id) == 0
