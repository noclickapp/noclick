"""Stored socket pickers admit exact calls before refresh or provider lookup.

The real receiver dispatcher, handler, canonical credential loader, approval
helper/repository and Linear loader run. Storage, encryption, notifications and
provider boundaries are synthetic; SQL ACLs and transaction durability are not
executed by this suite. Raw unsaved connection evidence stays a separate path.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from repositories.credential_approvals import CredentialApprovalRepo
from repositories.credentials import credential_access_predicate
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest

NODE = "automation-linear"
EVENT = "workflow:node:load_options"
CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
UPDATED = datetime(2026, 10, 5, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    """This synthetic boundary does not initialize the suite's native pool."""
    yield


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Storage:
    """Answers native repository SQL with controlled rows, not an ACL engine."""
    def __init__(self):
        self.row = {
            "credential": b"synthetic-encrypted-row", "credential_type": "linear_pat",
            "revoked_at": None, "token_version": 7, "updated_at": UPDATED,
        }
        self.policy = {
            "name": "Fixture account", "owner_id": OWNER,
            "approval_operations": ["automation-linear.create_issue"],
            "approval_revision": 1, "revoked_at": None,
        }
        self.allowed_contexts = {(USER, ORG), (USER, None)}
        self.grants = {}
        self.calls = []
        self.timeline = []
        self.transactions = 0
        self.pending_count = None
        self.policy_error = None
        self.load_error = None

    def acquire(self):
        return _Context(self)

    def transaction(self):
        self.transactions += 1
        return _Context(self)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "SELECT c.credential" in sql:
            self.timeline.append("load")
            if self.load_error:
                raise self.load_error
            cid, user, org = args
            return self.row if cid == CID and (user, org) in self.allowed_contexts else None
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            self.timeline.append("admit")
            if self.policy_error:
                raise self.policy_error
            return self.policy
        if "SELECT id,status,consumed_at,expires_at" in sql:
            assert args[0] == CID
            grant = self.grants.get(args[1])
            return grant if grant and not grant["consumed_at"] and not grant["expired"] else None
        if "INSERT INTO approval_requests" in sql:
            fingerprint, payload = args[-2:]
            grant = {
                "id": UUID(int=len(self.grants) + 100), "status": "pending",
                "consumed_at": None, "expires_at": UPDATED,
                "expired": False, "payload": deepcopy(payload),
            }
            self.grants[fingerprint] = grant
            self.timeline.append("request")
            return grant
        raise AssertionError(f"Unexpected storage query: {sql}")

    async def fetchval(self, sql, *args):
        assert "SELECT count(*) FROM approval_requests" in sql and args == (CID,)
        if self.pending_count is not None:
            return self.pending_count
        return sum(g["status"] == "pending" and not g["expired"] for g in self.grants.values())

    async def execute(self, sql, approval_id):
        assert sql == "UPDATE approval_requests SET consumed_at=now() WHERE id=$1"
        self.timeline.append("consume")
        for grant in self.grants.values():
            if grant["id"] == approval_id:
                grant["consumed_at"] = UPDATED
                return "UPDATE 1"
        raise AssertionError("Missing exact grant")


def _arguments(**updates):
    return {"field_name": "team_id", "context": None, "page_token": None, "search": None, **updates}


@pytest.fixture
def picker(monkeypatch):
    from nodes import linear_node
    from nodes.core import oauth_refresh
    from nodes.core.oauth_audit import current_caller_path
    from utils import credentials
    from wss.handlers import workflow_handler
    from wss.receiver.chunk_reassembly import ChunkReassemblyManager
    from wss.receiver.event_routing import EVENT_ROUTING, Handler
    from wss.receiver.receiver import SocketIOProxy
    from wss.receiver.rate_limiter import RateLimiter
    from wss.receiver.rate_limits import get_rate_limit_config

    storage = _Storage()
    blob = {"api_key": "synthetic-pat", "credential_type": "stale-blob-type"}
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _value: deepcopy(blob)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    org = AsyncMock(return_value=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", org)
    responses, notifications = [], []

    async def capture(_sio, sid, event, **kwargs):
        if kwargs.get("user_id"):
            notifications.append((kwargs["user_id"], event.model_dump()))
        else:
            assert sid == "fixture-sid"
            responses.append(event.model_dump())

    monkeypatch.setattr(workflow_handler, "send_event", capture)
    monkeypatch.setattr("wss.sender.send_event", capture)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: sio)
    monkeypatch.setattr("utils.user_presence.touch_user_presence", lambda _user: None)
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = sio
    handler.get_pool = AsyncMock(return_value=storage)
    proxy = SocketIOProxy.__new__(SocketIOProxy)
    proxy.sio, proxy.SOCKET_PROXY_ENV = sio, "API"
    proxy.chunk_manager = ChunkReassemblyManager()
    proxy.rate_limiter = RateLimiter(get_rate_limit_config())
    assert EVENT_ROUTING["API"][EVENT] == Handler.WORKFLOW
    proxy.config = SimpleNamespace(event_handlers={"API": {EVENT: [handler]}})
    proxy.frontend_request_pydantic_models = {EVENT: WorkflowNodeLoadOptionsRequest}
    proxy._last_heavy_completion = {}

    async def refresh_boundary(data, **kwargs):
        assert current_caller_path() == "dropdown"
        storage.timeline.append("refresh")
        return data

    refresh = AsyncMock(side_effect=refresh_boundary)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", refresh)
    freshen = AsyncMock(wraps=linear_node.LinearNode.freshen_credential)
    loader = AsyncMock(wraps=linear_node.LinearNode.load_field_options)
    monkeypatch.setattr(linear_node.LinearNode, "freshen_credential", freshen)
    monkeypatch.setattr(linear_node.LinearNode, "load_field_options", loader)

    async def provider_boundary(*args, **kwargs):
        storage.timeline.append("provider")
        return {"teams": {"nodes": [{"id": "fixture-team", "name": "Fixture", "key": "FIX"}]}}

    provider = AsyncMock(side_effect=provider_boundary)
    monkeypatch.setattr(linear_node, "_linear_graphql_call", provider)
    return SimpleNamespace(
        storage=storage, blob=blob, crypto=crypto, org=org, proxy=proxy,
        handler=handler, sio=sio, freshen=freshen, loader=loader, refresh=refresh,
        provider=provider, responses=responses, notifications=notifications,
    )


async def _load(picker, **updates):
    request = {"request_id": "fixture-request", "node_type": NODE, "credential_id": CID,
               **_arguments(), **updates}
    count = len(picker.responses)
    await picker.proxy._route_event_impl(EVENT, "fixture-sid", request)
    assert len(picker.responses) == count + 1
    event = picker.responses[-1]
    assert event["request_id"] == "fixture-request" and event["error"] is None
    return event["data"]


async def _seed(picker, status, *, arguments=None, expired=False):
    await CredentialApprovalRepo(picker.storage).admit(
        credential_id=CID, user_id=USER, node_type=NODE, operation="__lookup__",
        arguments=_arguments() if arguments is None else arguments,
    )
    grant = next(reversed(picker.storage.grants.values()))
    grant["status"], grant["expired"] = status, expired
    picker.storage.timeline.clear()
    picker.storage.calls.clear()
    return grant


def _no_provider(picker):
    picker.freshen.assert_not_awaited()
    picker.refresh.assert_not_awaited()
    picker.loader.assert_not_awaited()
    picker.provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("restrictions", [["*"], ["automation-linear.__lookup__"], ["automation-linear.create_issue"]])
async def test_new_pending_lookup_stops_real_routed_handler_before_refresh_and_notifies_owner(picker, restrictions):
    picker.storage.policy["approval_operations"] = restrictions
    result = await _load(picker)
    _no_provider(picker)
    assert result["success"] is False and result["options"] == [] and result["next_page_token"] is None
    assert "must review this exact call" in result["message"]
    grant = next(iter(picker.storage.grants.values()))
    assert result["message"].endswith(f"/credential/approval/{grant['id']}")
    assert grant["payload"]["caller_user_id"] == USER
    assert grant["payload"]["operation"] == "__lookup__"
    assert grant["payload"]["arguments"] == _arguments()
    assert picker.storage.timeline == ["load", "admit", "request"]
    assert picker.storage.transactions == 1
    assert len(picker.notifications) == 1 and picker.notifications[0][0] == OWNER


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending", "rejected"])
async def test_existing_pending_or_rejected_grant_returns_empty_failure_without_reopening(picker, decision):
    await _seed(picker, decision)
    result = await _load(picker)
    assert result["success"] is False and result["options"] == []
    if decision == "rejected":
        assert result["message"] == "The credential owner rejected this options lookup."
    else:
        assert "must review this exact call" in result["message"]
    assert len(picker.storage.grants) == 1 and picker.notifications == []
    _no_provider(picker)


@pytest.mark.asyncio
async def test_exact_approved_retry_consumes_once_before_refresh_and_real_native_loader(picker):
    grant = await _seed(picker, "approved")
    result = await _load(picker)
    assert result == {"success": True, "options": [{"value": "fixture-team", "label": "Fixture (FIX)", "metadata": {"key": "FIX"}}], "message": None, "next_page_token": None}
    assert grant["consumed_at"] is not None
    assert picker.storage.timeline == ["load", "admit", "consume", "refresh", "provider"]
    loaded = picker.freshen.await_args.args[0]
    assert loaded["credential_type"] == "linear_pat"
    assert loaded["token_version"] == 7 and loaded["updated_at"] == UPDATED.isoformat()
    assert picker.refresh.await_args.kwargs["credential_id"] == CID
    assert picker.provider.await_args.args[0] == "synthetic-pat"
    assert (await _load(picker))["success"] is False
    assert picker.freshen.await_count == picker.loader.await_count == picker.provider.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [
    {"field_name": "user_id"}, {"context": {"team_id": "different"}},
    {"page_token": "new-cursor"}, {"search": " new search "},
])
async def test_changed_call_cannot_consume_approved_grant(picker, changed):
    approved = await _seed(picker, "approved")
    assert (await _load(picker, **changed))["success"] is False
    assert approved["consumed_at"] is None and len(picker.storage.grants) == 2
    assert next(reversed(picker.storage.grants.values()))["payload"]["arguments"] == _arguments(**changed)
    _no_provider(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["expired", "policy_revision"])
async def test_expired_or_old_policy_approval_cannot_admit_lookup(picker, stale):
    approved = await _seed(picker, "approved", expired=stale == "expired")
    if stale == "policy_revision":
        picker.storage.policy["approval_revision"] += 1
    assert (await _load(picker))["success"] is False
    assert approved["consumed_at"] is None
    _no_provider(picker)


@pytest.mark.asyncio
async def test_context_cannot_supply_approval_actor_or_scope(picker):
    context = {"_user_id": OWNER, "organization_id": ORG, "workflow_id": CID,
               "approved": True, "approval_id": CID}
    result = await _load(picker, context=context, search=" spaced ", page_token="cursor")
    assert result["success"] is False
    payload = next(iter(picker.storage.grants.values()))["payload"]
    assert payload["caller_user_id"] == USER
    assert payload["organization_id"] is payload["workflow_id"] is payload["conversation_id"] is None
    assert payload["arguments"] == _arguments(context=context, search=" spaced ", page_token="cursor")
    _no_provider(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["missing", "denied", "revoked"])
async def test_unavailable_current_row_never_creates_review_or_calls_provider(picker, unavailable):
    if unavailable == "missing":
        picker.storage.row = None
    elif unavailable == "denied":
        picker.storage.allowed_contexts.clear()
    else:
        picker.storage.row["revoked_at"] = UPDATED
    result = await _load(picker)
    assert result["success"] is False and result["message"] == "Credential not found or access denied"
    assert picker.storage.transactions == 0 and picker.storage.grants == {}
    picker.crypto.decrypt_credential.assert_not_called()
    _no_provider(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["revoked_during_admission", "policy_read", "pending_cap", "invalid_arguments"])
async def test_admission_failure_stops_refresh_and_returns_typed_error(picker, failure):
    updates = {}
    if failure == "revoked_during_admission":
        picker.storage.policy["revoked_at"] = UPDATED
    elif failure == "policy_read":
        picker.storage.policy_error = RuntimeError("synthetic admission storage failure")
    elif failure == "pending_cap":
        picker.storage.pending_count = 100
    else:
        updates["context"] = {"not_finite": float("nan")}
    result = await _load(picker, **updates)
    assert result["success"] is False and result["options"] == [] and result["message"]
    assert picker.storage.grants == {} and picker.notifications == []
    _no_provider(picker)


@pytest.mark.asyncio
async def test_unrestricted_row_keeps_native_options_without_review(picker):
    picker.storage.policy["approval_operations"] = []
    assert (await _load(picker))["success"] is True
    assert picker.storage.grants == {} and picker.notifications == []
    assert picker.storage.timeline == ["load", "admit", "refresh", "provider"]


@pytest.mark.asyncio
async def test_credential_owner_still_requires_exact_approval(picker):
    picker.storage.policy["owner_id"] = USER
    assert (await _load(picker))["success"] is False
    assert picker.notifications[0][0] == USER
    _no_provider(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,permitted", [(ORG, True), (None, True), (OWNER, False)])
async def test_current_user_org_loader_binding_precedes_admission(picker, scope, permitted):
    picker.org.return_value = scope
    result = await _load(picker)
    sql, args = picker.storage.calls[0]
    assert credential_access_predicate() in sql and args == (CID, USER, scope)
    assert result["success"] is False
    assert bool(picker.storage.transactions) is permitted
    _no_provider(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["legacy_list", "paginated_dict"])
async def test_admitted_lookup_preserves_option_shape_context_search_and_cursor(picker, monkeypatch, shape):
    from nodes.core.registry import NODE_REGISTRY

    seen = {}
    class Node:
        freshen_credential = picker.freshen

        @classmethod
        async def load_field_options(cls, **kwargs):
            seen.update(kwargs)
            options = [{"value": "one", "label": "One", "metadata": {"kind": "fixture"}}]
            return options if shape == "legacy_list" else {"options": options, "next_page_token": "next"}

    monkeypatch.setitem(NODE_REGISTRY, "fixture-options", Node)
    picker.storage.policy["approval_operations"] = []
    context = {"_user_id": OWNER, "folder": "fixture-folder"}
    result = await _load(picker, node_type="fixture-options", context=context, search=" spaced ", page_token="cursor")
    assert result["success"] is True and result["options"][0]["value"] == "one"
    assert result["next_page_token"] == (None if shape == "legacy_list" else "next")
    assert seen["context"] == {"_user_id": USER, "folder": "fixture-folder"}
    assert seen["page_token"] == "cursor" and seen["search"] == "spaced"


@pytest.mark.asyncio
async def test_credential_less_picker_skips_storage_and_admission(picker, monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Node:
        @classmethod
        async def load_field_options(cls, **kwargs):
            assert kwargs["credential_data"] == {} and kwargs["context"] == {"_user_id": USER}
            return []

    monkeypatch.setitem(NODE_REGISTRY, "fixture-public-options", Node)
    assert (await _load(picker, node_type="fixture-public-options", credential_id=None))["success"] is True
    picker.handler.get_pool.assert_not_awaited()
    assert picker.storage.calls == [] and picker.storage.transactions == 0
    _no_provider(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending", "rejected", "approved"])
async def test_native_agent_lookup_uses_same_exact_call_admission(picker, decision):
    from nodes.core.run_op import run_node_lookup

    grant = await _seed(picker, decision)
    result = await run_node_lookup(node_type=NODE, credential_id=CID, user_id=USER,
                                   pool=picker.storage, **_arguments())
    if decision == "approved":
        assert result["options"][0]["value"] == "fixture-team" and grant["consumed_at"] is not None
        assert picker.storage.timeline.index("consume") < picker.storage.timeline.index("refresh")
    else:
        assert result["executed"] is False and result["_halt_downstream"] is True
        assert result["status"] == ("pending_approval" if decision == "pending" else "rejected")
        _no_provider(picker)


@pytest.mark.asyncio
async def test_raw_unsaved_connect_evidence_keeps_native_loader_without_stored_admission(picker):
    from nodes.core.connection_evidence import collect_evidence

    result = await collect_evidence(node_type=NODE, user_id=USER, credential_data={"credential_type": "linear_pat", "api_key": "synthetic-pat"})
    assert result.reachable is True and result.samples[0].value == "fixture-team"
    assert picker.storage.calls == [] and picker.storage.transactions == 0
    picker.freshen.assert_not_awaited()
    picker.provider.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unauthenticated", "unknown_node", "missing_pool"])
async def test_routed_preconditions_fail_before_admission(picker, failure):
    updates = {}
    if failure == "unauthenticated":
        picker.sio.get_session.return_value = {}
    elif failure == "unknown_node":
        updates["node_type"] = "automation-does-not-exist"
    else:
        picker.handler.get_pool.return_value = None
    assert (await _load(picker, **updates))["success"] is False
    assert picker.storage.calls == [] and picker.storage.transactions == 0
    _no_provider(picker)
