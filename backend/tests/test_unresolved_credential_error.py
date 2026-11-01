"""The error a run gets for a credential it can't use says why.

Automatic runs (triggers, schedules, agents) execute as the workflow owner, so
a credential another member connected on a shared workflow fails resolution
while being perfectly live. The error used to say it "may have been
disconnected or revoked", which sent the owner to reconnect an account that
was fine and wasn't theirs. Over real PostgreSQL, through both places a run
resolves a credential (an agent's tool call and a workflow step), the error
names the actual cause and never the other person. Access itself is
unchanged: the member sharing the credential is what makes it resolve.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from nodes.core.run_op import resolve_operation_credential
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.encryption import get_encryption
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

pytestmark = pytest.mark.asyncio


async def _user(db):
    user = str(uuid.uuid4())
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", user, f"{user}@example.test")
    return user


async def _credential(db, owner, name="WhatsApp (shop)"):
    return str(await db.fetchval(
        "INSERT INTO credentials (owner_id, credential_type, name, credential) "
        "VALUES ($1, 'whatsapp_qr', $2, $3) RETURNING id",
        owner, name, get_encryption().encrypt_credential({"connection_id": "conn-1"})))


async def _shared_workflow(db):
    owner, member = await _user(db), await _user(db)
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, 'Inbox', '{}'::jsonb)",
                     workflow_id, owner)
    return owner, member, workflow_id


async def _tool_error(db, credential_id, runner, workflow_id):
    with pytest.raises(ValueError) as raised:
        await resolve_operation_credential(credential_id, runner, db.pool, workflow_id=workflow_id)
    return str(raised.value)


async def _step_error(db, credential_id, runner, workflow_id):
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=db.pool)
    with pytest.raises(ValueError) as raised:
        await handler._resolve_credentials(
            {"operation": "send_text_message", "credentialIds": {"whatsapp_qr": credential_id}},
            user_id=runner, workflow_id=workflow_id,
        )
    return str(raised.value)


async def test_another_members_credential_says_whose_connections_runs_use(real_database):  # noqa: F811
    db = real_database
    owner, member, workflow_id = await _shared_workflow(db)
    theirs = await _credential(db, member)

    for error in (await _tool_error(db, theirs, owner, workflow_id), await _step_error(db, theirs, owner, workflow_id)):
        assert error.startswith(f"Failed to resolve credential {theirs}")
        assert '"WhatsApp (shop)" is connected, but it belongs to another member of this workflow' in error
        assert "use the workflow owner's connections" in error
        assert "the owner connects their own account" in error and "shares it with them" in error
        assert "revoked" not in error
        assert member not in error and "example.test" not in error
    assert "this tool's provider node" in await _tool_error(db, theirs, owner, workflow_id)
    assert "on this step" in await _step_error(db, theirs, owner, workflow_id)

    # The fix it names is real: shared with the owner, the owner's runs resolve it.
    await db.execute(
        "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('credential', $1, 'user', $2, 'view', $3)", theirs, owner, member)
    assert (await resolve_operation_credential(theirs, owner, db.pool, workflow_id=workflow_id))["connection_id"]


async def test_the_owners_credential_on_a_members_run_says_the_owner_must_pick_it(real_database):  # noqa: F811
    db = real_database
    owner, member, workflow_id = await _shared_workflow(db)
    mine = await _credential(db, owner, name="WhatsApp (owner)")
    error = await _step_error(db, mine, member, workflow_id)
    assert "\"WhatsApp (owner)\" is the workflow owner's connection" in error
    assert "only once the owner selects it on this step" in error


async def test_a_deleted_or_revoked_credential_says_so(real_database):  # noqa: F811
    db = real_database
    owner, _, workflow_id = await _shared_workflow(db)
    gone = str(uuid.uuid4())
    assert "it was deleted" in await _step_error(db, gone, owner, workflow_id)

    revoked = await _credential(db, owner)
    await db.execute("UPDATE credentials SET revoked_at = $2 WHERE id = $1", revoked, datetime.now(timezone.utc))
    assert "it was revoked" in await _tool_error(db, revoked, owner, workflow_id)
