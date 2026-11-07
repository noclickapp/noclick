"""Exercise staging connect, saved-credential execution, access and lookup seams.

Only SQL I/O, decryption, HTTP transport and event delivery are fixtures.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from nodes import staffbase_node as db
from nodes.core import credential_connect as cc
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import credential_access_predicate
from utils import ssrf
from nodes.tests.test_staffbase_node_mock import resource, listing
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

NODE = "automation-staffbase"
USER, ORG, CID = ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000042")
TENANT, KEY = "https://fixture.staffbase.com/api", "Zml4dHVyZTpzeW50aGV0aWMtbm90LWxpdmU="
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


class Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_):
        return False


class Storage:
    def __init__(self):
        self.row = {"id": CID, "name": "Fixture CRM", "credential": b"synthetic-encrypted", "credential_type": db.TYPE, "owner_id": USER, "token_version": 7, "approval_revision": 0, "updated_at": UPDATED, "created_at": UPDATED, "revoked_at": None, "metadata": {}, "approval_operations": []}
        self.blob = {"credential_type": db.TYPE, "api_base_url": TENANT, "api_token": KEY}
        self.allowed, self.calls, self.approval_status = True, [], None

    def acquire(self):
        return Context(self)

    def transaction(self):
        return Context(self)

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        if "organizations" in sql or "org_members" in sql or "organization_members" in sql:
            return ORG
        if "count(*) FROM approval_requests" in sql:
            return 0
        raise AssertionError("Unexpected native fetchval")

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            return deepcopy(self.row)
        if "SELECT id,status,consumed_at,expires_at" in sql:
            return {"id": UUID(int=99), "status": self.approval_status, "consumed_at": None, "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc)} if self.approval_status else None
        if "FROM credentials c" in sql:
            assert credential_access_predicate().strip() in sql and args[0] == CID and args[1] == USER
            if len(args) == 6:
                assert args[3] == USER and "workflow_authorized_credentials" in sql
            assert len(args) in {3, 6}
            return deepcopy(self.row) if self.allowed else None
        raise AssertionError("Unexpected native fetchrow")


@pytest.fixture
def harness(monkeypatch):
    from utils import credentials
    from wss.handlers import credentials_handler, workflow_handler
    state = SimpleNamespace(storage=Storage(), http=[], replies=[], events=[], after_http=None)
    encryption = MagicMock()
    encryption.decrypt_credential.side_effect = lambda _: deepcopy(state.storage.blob)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: encryption)
    monkeypatch.setattr(credentials, "get_encryption", lambda: encryption)
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: encryption)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)

    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        state.http.append(request)
        if state.after_http:
            state.after_http(len(state.http))
        assert request.url.host == "fixture.staffbase.com" and not request.url.userinfo
        assert request.headers["Authorization"] == "Basic " + KEY and KEY not in str(request.url)
        code, payload = state.replies.pop(0)
        return httpx.Response(code, content=payload, headers={"Content-Type": "application/json"}) if isinstance(payload, bytes) else httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(db, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))

    async def capture(sio, sid, response):
        state.events.append(response.model_dump())

    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    sio = AsyncMock()
    sio.get_session.return_value = {"user_id": USER}
    state.access = credentials_handler.CredentialsHandler(sio)
    state.picker = workflow_handler.WorkflowHandler(sio)
    monkeypatch.setattr(state.access, "get_pool", AsyncMock(return_value=state.storage))
    monkeypatch.setattr(state.picker, "get_pool", AsyncMock(return_value=state.storage))
    return state


@pytest.mark.asyncio
async def test_actual_manual_connect_and_empty_access_do_not_invent_identity(harness):
    harness.replies = [(200, listing())]
    verdict = await cc.validate_for_connect(credential_type=db.TYPE, credential_data={"api_base_url": TENANT, "api_token": KEY}, user_id=USER, probe=True)
    assert verdict.field_errors == {} and verdict.credential_data == harness.storage.blob
    assert verdict.evidence.reachable is True and verdict.evidence.account_label is None
    assert verdict.evidence.samples[0].label == "Fixture User" and harness.http[0].url.path == "/api/users"
    harness.replies = [(200, listing(rows=[]))]
    empty = await cc.validate_for_connect(credential_type=db.TYPE, credential_data={"api_base_url": TENANT, "api_token": KEY}, user_id=USER, probe=True)
    assert empty.evidence.reachable is True and empty.evidence.account_label is None and empty.evidence.samples == []
    harness.replies = [(401, {"message": "Unauthorized"})]
    rejected = await cc.validate_for_connect(credential_type=db.TYPE, credential_data={"api_base_url": TENANT, "api_token": KEY}, user_id=USER, probe=True)
    assert rejected.evidence.reachable is False and rejected.rejection


@pytest.mark.asyncio
async def test_actual_saved_factory_and_access_hook_are_positive_without_identity(harness):
    harness.replies = [(200, listing())]
    result = await run_node_operation(node_type=NODE, operation="list_users", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["status"] == "success" and result["identity_verified"] is False
    assert any("FROM credentials c" in sql for sql, _ in harness.storage.calls)
    harness.replies = [(200, listing())]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is True and harness.events[-1]["data"]["identity_verified"] is False


@pytest.mark.asyncio
async def test_actual_handler_definitive_refusal_unknown_and_no_context(harness):
    harness.replies = [(403, {"message": "Denied"})]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is False
    harness.replies = [(202, {"entries": []})]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is None and harness.events[-1]["data"]["identity_verified"] is False


@pytest.mark.asyncio
async def test_actual_stored_lookup_later_page_and_parent_bound_post(harness):
    harness.replies = [(200, listing(following="later")), (200, listing(rows=[{**resource("user", "u2"), "profile": {"firstName": "Later"}}]))]
    result = await run_node_lookup(node_type=NODE, field_name="user_id", context={"search": "Later"}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["options"] == [{"value": "u2", "label": "Later", "metadata": {}}] and result["next_page_token"] is None
    assert harness.http[-1].url.params["cursor"] == "later"
    harness.replies = [(200, resource("channel")), (200, listing("post"))]
    child = await run_node_lookup(node_type=NODE, field_name="post_id", context={"channel_id": "c1"}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert child["options"][0]["metadata"] == {"channelID": "c1"} and harness.http[-1].url.path == "/api/channels/c1/posts"
