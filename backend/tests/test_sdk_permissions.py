"""SDK permission gate for API-key sessions.

A workflow-scoped key reaches only its own workflow: a request that names no
workflow (or another workflow, directly or through a resource) is refused,
except the SDK's two account-level credential events. A published app's key
lives in a public page, so it is further confined to the events the SDK sends.
"""

import re
import uuid
from pathlib import Path

import pytest

from tests.fixtures.cas_fixtures import codec_pool  # noqa: F401
from tests.utils.base_handler_test import BaseHandlerTest
from utils import sdk_permissions
from utils.sdk_permissions import (
    PUBLISHED_APP,
    _PUBLISHED_APP_EVENTS,
    _SCOPED_ACCOUNT_EVENTS,
    check_sdk_permission,
    resolve_request_workflow_ids,
)
from wss.receiver.event_routing import EVENT_ROUTING

OWN_WF = "11111111-1111-1111-1111-111111111111"
OTHER_WF = "22222222-2222-2222-2222-222222222222"
FULL = ["read", "write", "execute"]
APP_KEY = FULL + [PUBLISHED_APP]
SDK_TRANSPORT = Path(__file__).resolve().parents[2] / "sdk/typescript/src/transports/websocket.ts"


def test_published_app_events_are_exactly_what_the_sdk_sends():
    """The published-app allowlist IS the SDK's WebSocket vocabulary: an SDK
    method added without updating it would break every published app, and an
    extra entry would hand visitors an event the SDK never needed."""
    source = SDK_TRANSPORT.read_text()
    sent = set(re.findall(r"event:\s*'([a-z_:]+)',\s*transform:", source))
    sent |= set(re.findall(r"(?:_emitAndWait|socket\.emit)\(\s*'([a-z_:]+)'", source))
    assert sent == set(_PUBLISHED_APP_EVENTS)


@pytest.mark.parametrize("event", [
    "credential:get", "credential:update", "credential:delete", "workflow:list", "workflow:create",
])
def test_scoped_key_cannot_reach_the_account(event):
    assert check_sdk_permission(event, FULL, sdk_workflow_id=OWN_WF) is not None
    assert check_sdk_permission(event, APP_KEY, sdk_workflow_id=OWN_WF) is not None


@pytest.mark.parametrize("event", sorted(_SCOPED_ACCOUNT_EVENTS))
def test_scoped_key_keeps_the_sdks_account_events(event):
    assert check_sdk_permission(event, APP_KEY, sdk_workflow_id=OWN_WF) is None


def test_scoped_key_refuses_a_request_naming_any_other_workflow():
    """A payload naming its own workflow AND another workflow's resource is
    judged on both — the handler acts on the resource."""
    ok = check_sdk_permission("resource:download_url", APP_KEY, sdk_workflow_id=OWN_WF,
                              request_workflow_ids={OWN_WF})
    assert ok is None
    mixed = check_sdk_permission("resource:download_url", APP_KEY, sdk_workflow_id=OWN_WF,
                                 request_workflow_ids={OWN_WF, OTHER_WF})
    assert mixed is not None


@pytest.mark.parametrize("event", [
    "workflow:update", "workflow:delete", "workflow:save_node_state", "resource:fork", "yjs:sync",
])
def test_published_app_cannot_use_events_the_sdk_never_sends(event):
    assert check_sdk_permission(event, APP_KEY, sdk_workflow_id=OWN_WF,
                                request_workflow_ids={OWN_WF}) is not None
    # The same event on a user's own (unpublished) scoped key is unchanged.
    assert check_sdk_permission(event, FULL, sdk_workflow_id=OWN_WF,
                                request_workflow_ids={OWN_WF}) is None


def test_unscoped_personal_key_is_unchanged():
    assert check_sdk_permission("credential:get", FULL) is None
    assert check_sdk_permission("workflow:list", ["write"]) == "API key missing 'read' permission (has: write)"


class TestResolveRequestWorkflowIds:
    @pytest.mark.asyncio
    async def test_resource_resolves_to_its_owning_workflow(self, codec_pool, postgres_db, monkeypatch):
        monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: codec_pool)
        owner = "00000000-0000-0000-0000-000000000001"
        workflow_id = str(uuid.uuid4())
        resource_id = str(uuid.uuid4())
        async with codec_pool.acquire() as conn:
            await conn.execute("INSERT INTO workflows (id, owner_id, name) VALUES ($1, $2, 'r')", workflow_id, owner)
            await conn.execute(
                "INSERT INTO workflow_resources (id, owner_id, workflow_id, resource_type, name) "
                "VALUES ($1, $2, $3, 'dataset', 'd')",
                resource_id, owner, workflow_id,
            )
        try:
            assert await resolve_request_workflow_ids({"resource_id": resource_id}) == {workflow_id}
            assert await resolve_request_workflow_ids(
                {"workflow_id": OWN_WF, "resource_id": resource_id}) == {OWN_WF, workflow_id}
        finally:
            async with codec_pool.acquire() as conn:
                await conn.execute("DELETE FROM workflows WHERE id = $1", workflow_id)

    @pytest.mark.asyncio
    async def test_unknown_or_malformed_resource_matches_no_key(self, codec_pool, postgres_db, monkeypatch):
        monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: codec_pool)
        for resource_id in (str(uuid.uuid4()), "not-a-uuid"):
            ids = await resolve_request_workflow_ids({"resource_id": resource_id})
            assert check_sdk_permission("resource:download_url", APP_KEY, sdk_workflow_id=OWN_WF,
                                        request_workflow_ids=ids) is not None

    @pytest.mark.asyncio
    async def test_payload_without_ids_names_nothing(self):
        assert await resolve_request_workflow_ids({"request_id": "x"}) == set()


class TestPublishedAppSessionGate(BaseHandlerTest):
    """The receiver applies the gate to a published-app session, across the
    whole routing table."""

    def get_session_data(self, sid):
        return {
            "sid": sid,
            "user_id": "00000000-0000-0000-0000-000000000001",
            "sdk_permissions": APP_KEY,
            "sdk_workflow_id": OWN_WF,
        }

    @pytest.mark.asyncio
    async def test_only_the_sdks_events_on_its_own_workflow_pass(self, frontend_sio, sid):
        leaked = []
        for event in EVENT_ROUTING["API"]:
            for payload in ({"request_id": "g"}, {"request_id": "g", "workflow_id": OWN_WF}):
                result = await self.proxy._route_event_impl(event, sid, payload)
                denied = isinstance(result, dict) and result.get("error") == "permission_denied"
                allowed = event in _PUBLISHED_APP_EVENTS and (
                    "workflow_id" in payload or event in _SCOPED_ACCOUNT_EVENTS)
                if denied == allowed:
                    leaked.append((event, payload.get("workflow_id"), "denied" if denied else "passed"))
        assert not leaked, leaked

    @pytest.mark.asyncio
    async def test_credential_read_is_refused(self, frontend_sio, sid):
        result = await self.proxy._route_event_impl(
            "credential:get", sid, {"request_id": "c", "credential_id": str(uuid.uuid4())})
        assert result["error"] == "permission_denied"

    @pytest.mark.asyncio
    async def test_another_workflow_is_refused(self, frontend_sio, sid):
        result = await self.proxy._route_event_impl(
            "workflow:get", sid, {"request_id": "w", "workflow_id": OTHER_WF})
        assert result["error"] == "permission_denied"


def test_marker_constant_matches_the_migration():
    """The migration stamps existing published-app keys with this literal."""
    migrations = Path(__file__).resolve().parents[2] / "infra/supabase/migrations"
    [migration] = migrations.glob("*_published_app_key_marker.sql")
    assert f"'{sdk_permissions.PUBLISHED_APP}'" in migration.read_text()
