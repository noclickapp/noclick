"""A member's own connection on a workflow someone else owns: asked, lent, and no further.

Trigger, schedule and agent runs go as the workflow's owner, so a connection only the member holds failed there
("Failed to resolve credential") while it looked fine on the canvas. Picking it now asks the member whether the
runs may use it; their yes lends it to that workflow alone, while they can still edit it and a step holds it.
The secret never moves: the runs resolve it as the member's.
"""

import uuid

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.credentials import (
    lend_credential_to_workflow,
    member_connection_warnings,
    prune_unused_lends,
    resolve_credential_with_owner_fallback,
    unlent_member_connections,
)
from utils.encryption import get_encryption

OWNER = "00000000-0000-4000-8000-0000000003a1"
MEMBER = "00000000-0000-4000-8000-0000000003b2"
OTHER = "00000000-0000-4000-8000-0000000003c3"


async def _world(db, *, member_permission="edit"):
    for user_id in (OWNER, MEMBER, OTHER):
        await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                         user_id, f"{user_id[-3:]}@example.com")
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Inbox', $3)",
                     workflow_id, OWNER, {"nodes": [], "edges": []})
    if member_permission:
        await _share(db, workflow_id, member_permission)
    return workflow_id


async def _share(db, workflow_id, permission):
    await db.execute(
        "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('workflow', $1::uuid, 'user', $2::uuid, $3, $4::uuid)", workflow_id, MEMBER, permission, OWNER)


async def _credential(db, owner, name="Shop WhatsApp"):
    credential_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO credentials (id, owner_id, name, credential_type, credential) "
        "VALUES ($1::uuid, $2::uuid, $3, 'whatsapp_qr', $4)",
        credential_id, owner, name, get_encryption().encrypt_credential({"connection_id": "conn-1"}))
    return credential_id


async def _on_a_step(db, workflow_id, credential_id):
    await db.execute("UPDATE workflows SET workflow = $2 WHERE id = $1::uuid", workflow_id, {
        "nodes": [{"id": "wa", "type": "automation-whatsapp",
                   "config": {"operation": "receive_message", "credentialIds": {"whatsapp_qr": credential_id}}}],
        "edges": []})


async def _run_as_owner(db, credential_id, workflow_id):
    return await resolve_credential_with_owner_fallback(credential_id, OWNER, db.pool, workflow_id=workflow_id)


CONSENT = ('Automatic runs of this workflow (triggers, schedules and agents) go as its owner. Let them use your '
           '"Shop WhatsApp"? Anyone who can edit this workflow can then make it act as you.')


@pytest.mark.asyncio
async def test_a_member_lends_their_own_connection_and_the_owners_runs_use_it(real_database):  # noqa: F811
    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)
    assert await unlent_member_connections(db.pool, workflow_id, MEMBER, [theirs]) == {theirs: "Shop WhatsApp"}
    assert await _run_as_owner(db, theirs, workflow_id) is None

    assert await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, theirs) is True

    assert (await _run_as_owner(db, theirs, workflow_id))["connection_id"] == "conn-1"
    assert await unlent_member_connections(db.pool, workflow_id, MEMBER, [theirs]) == {}
    assert await member_connection_warnings(db.pool, workflow_id, MEMBER, [theirs]) == {}
    # Lent to that workflow alone.
    elsewhere = await _world(db)
    assert await _run_as_owner(db, theirs, elsewhere) is None


@pytest.mark.asyncio
async def test_the_lend_ends_with_the_members_access_and_when_no_step_holds_it(real_database):  # noqa: F811
    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)
    await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, theirs)
    await _on_a_step(db, workflow_id, theirs)

    await db.execute("UPDATE resource_shares SET permission = 'view' WHERE resource_id = $1::uuid", workflow_id)
    assert await _run_as_owner(db, theirs, workflow_id) is None
    await db.execute("UPDATE resource_shares SET permission = 'edit' WHERE resource_id = $1::uuid", workflow_id)
    assert await _run_as_owner(db, theirs, workflow_id) is not None

    graph = await db.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)
    assert await prune_unused_lends(db.pool, workflow_id, graph) == 0  # still on its step
    assert await prune_unused_lends(db.pool, workflow_id, {"nodes": [], "edges": []}) == 1
    assert await _run_as_owner(db, theirs, workflow_id) is None


@pytest.mark.asyncio
async def test_no_one_lends_what_isnt_theirs_or_without_edit_access(real_database):  # noqa: F811
    db = real_database
    workflow_id = await _world(db, member_permission="view")
    theirs, owners, a_third_partys = (await _credential(db, MEMBER), await _credential(db, OWNER),
                                      await _credential(db, OTHER))

    assert await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, theirs) is False  # can only view it
    await db.execute("UPDATE resource_shares SET permission = 'edit' WHERE resource_id = $1::uuid", workflow_id)
    assert await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, owners) is False
    assert await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, a_third_partys) is False
    assert await _run_as_owner(db, a_third_partys, workflow_id) is None
    assert await db.fetchval("SELECT count(*) FROM workflow_authorized_credentials WHERE workflow_id = $1::uuid",
                             workflow_id) == 0


@pytest.mark.asyncio
async def test_nothing_is_asked_where_the_owners_runs_can_use_it(real_database):  # noqa: F811
    db = real_database
    workflow_id = await _world(db)
    shared, owners = await _credential(db, MEMBER), await _credential(db, OWNER)
    await db.execute(
        "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('credential', $1::uuid, 'user', $2::uuid, 'view', $3::uuid)", shared, OWNER, MEMBER)

    assert await unlent_member_connections(db.pool, workflow_id, MEMBER, [shared, owners]) == {}
    assert await unlent_member_connections(db.pool, workflow_id, OWNER, [await _credential(db, MEMBER)]) == {}


def _handler(db, user_id):
    from unittest.mock import AsyncMock, MagicMock

    from wss.handlers.credentials_handler import CredentialsHandler

    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": user_id})
    sio.emit = AsyncMock()
    handler = CredentialsHandler(sio=sio)
    handler.get_pool = AsyncMock(return_value=db.pool)
    return handler, sio


@pytest.mark.asyncio
async def test_the_panel_asks_the_member_then_records_their_yes(real_database):  # noqa: F811
    from wss.receiver.client_events import CredentialAuthorizeForWorkflowRequest

    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)
    handler, sio = _handler(db, MEMBER)

    await handler.authorize_for_workflow("sid", CredentialAuthorizeForWorkflowRequest(
        request_id="r", workflow_id=workflow_id, credential_id=theirs))
    assert sio.emit.await_args.args[1]["data"] == {"authorized": False, "consent": CONSENT}
    assert await _run_as_owner(db, theirs, workflow_id) is None  # asking lends nothing

    await handler.authorize_for_workflow("sid", CredentialAuthorizeForWorkflowRequest(
        request_id="r", workflow_id=workflow_id, credential_id=theirs, lend=True))
    assert sio.emit.await_args.args[1]["data"] == {"authorized": True, "lent": True}
    assert await _run_as_owner(db, theirs, workflow_id) is not None

    # Picked again, it's lent already: nothing to ask.
    await handler.authorize_for_workflow("sid", CredentialAuthorizeForWorkflowRequest(
        request_id="r", workflow_id=workflow_id, credential_id=theirs))
    assert sio.emit.await_args.args[1]["data"] == {"authorized": False}


@pytest.mark.asyncio
async def test_the_owner_sees_whose_connection_a_step_uses(real_database):  # noqa: F811
    from wss.receiver.client_events import CredentialDisplayInfoRequest

    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)
    await _on_a_step(db, workflow_id, theirs)
    handler, sio = _handler(db, OWNER)

    await handler.display_info("sid", CredentialDisplayInfoRequest(request_id="r", workflow_id=workflow_id))
    assert sio.emit.await_args.args[1]["data"]["credentials"] == []  # not lent: the owner reads no member's name

    await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, theirs)
    await handler.display_info("sid", CredentialDisplayInfoRequest(request_id="r", workflow_id=workflow_id))
    [shown] = sio.emit.await_args.args[1]["data"]["credentials"]
    assert (shown["id"], shown["name"], shown["owned_by_me"]) == (theirs, "Shop WhatsApp", False)
    assert shown["owner_name"]  # the member's name, which the picker shows as "Owned by …"


@pytest.mark.asyncio
async def test_a_save_that_takes_it_off_its_step_ends_the_lend(real_database):  # noqa: F811
    from utils.workflow_reconcile import reconcile_graph_change

    db = real_database
    workflow_id = await _world(db)
    theirs = await _credential(db, MEMBER)
    await _on_a_step(db, workflow_id, theirs)
    await lend_credential_to_workflow(db.pool, workflow_id, MEMBER, theirs)
    before = await db.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)
    after = {"nodes": [{**before["nodes"][0], "config": {"operation": "receive_message", "credentialIds": {}}}],
             "edges": []}
    await db.execute("UPDATE workflows SET workflow = $2 WHERE id = $1::uuid", workflow_id, after)

    await reconcile_graph_change(db.pool, workflow_id, MEMBER, before, after)

    assert await _run_as_owner(db, theirs, workflow_id) is None
