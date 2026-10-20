"""The engine's side of the activity feed: each action reaches whoever keeps a feed through
``ACTIVITY_SIGNAL`` (``utils.activity.signal_activity``), once, at the choke point every surface of
that action shares, and never fails the action when the feed does."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.activity_fixtures import activity_signals  # noqa: F401
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from tests.mocks.mock_asyncpg import MockNativePool
from tests.utils.base_handler_test import BaseHandlerTest
from utils import capabilities
from utils.activity import signal_activity
from utils.capabilities import ACTIVITY_SIGNAL
from wss.receiver.client_events import WorkflowCreateRequest, WorkflowUpdateRequest
from wss.sender import send_event

USER = "11111111-1111-4111-8111-111111111111"


def test_nothing_happens_where_no_feed_is_kept(monkeypatch):
    monkeypatch.delitem(capabilities._providers, ACTIVITY_SIGNAL, raising=False)

    signal_activity(USER, "chat", {"text": "hi"}, key="chat")  # no provider, no error


def test_a_signal_reaches_the_feed_once(activity_signals):
    signal_activity(USER, "chat", {"text": "hi"}, key="chat")

    assert activity_signals == [(USER, "chat", {"text": "hi"}, "chat")]


def test_a_feed_that_raises_never_reaches_the_action(monkeypatch, caplog):
    def broken(user, action, details=None, *, key=None):
        raise RuntimeError("slack exploded")

    monkeypatch.setitem(capabilities._providers, ACTIVITY_SIGNAL, broken)

    signal_activity(USER, "chat", {"text": "hi"})

    assert "slack exploded" in caplog.text


# ── connecting an account ───────────────────────────────────────────────────

async def _connect(monkeypatch, credential_type, metadata=None, *, allowed=True):
    from repositories.credentials import create_credential_with_limit_check

    monkeypatch.setattr("billing.plan_limits.check_credential_limit", AsyncMock(
        return_value=(allowed, None if allowed else "Plan limit reached: 1 credential")))
    pool = MockNativePool({"INSERT INTO credentials": {"id": "cred-1", "name": "n", "credential_type": credential_type,
                                                       "metadata": metadata or {}, "created_at": None,
                                                       "updated_at": None}})
    async with pool.acquire() as conn:
        return await create_credential_with_limit_check(conn, USER, "free", credential_type, "n", "enc",
                                                        metadata or {})


async def test_connecting_an_account_is_activity_named_by_its_type_alone(activity_signals, monkeypatch):
    await _connect(monkeypatch, "google_gmail_oauth", {"verified_as": "ana@example.com"})

    assert activity_signals == [(USER, "connect", {"credential_type": "google_gmail_oauth"}, None)]


@pytest.mark.parametrize("credential_type, metadata, allowed", [
    ("phone_number", {}, True),  # a number bought: the purchase is the activity
    ("slack_oauth", {"hidden_from_owner": True}, True),  # held for someone else
    ("slack_oauth", {}, False),  # refused at the plan's limit: nothing was connected
])
async def test_what_is_not_the_owner_connecting_an_account(activity_signals, monkeypatch, credential_type, metadata,
                                                          allowed):
    await _connect(monkeypatch, credential_type, metadata, allowed=allowed)

    assert activity_signals == []


async def test_an_account_given_through_a_connect_link_is_its_owners_activity(activity_signals):
    from repositories.credentials import CredentialsRepo

    pool = MockNativePool({"INSERT INTO credentials": "cred-2", "UPDATE credential_requests": "req-1"})
    await CredentialsRepo(pool).store_provided_credential(
        request_id="req-1", request_token="tok", owner_id=USER, requester_id=USER, organization_id=None,
        name="Notion", credential_type="notion_oauth", encrypted="enc", metadata={})

    assert activity_signals == [(USER, "connect", {"credential_type": "notion_oauth", "via": "connect link"}, None)]


# ── creating an automation ──────────────────────────────────────────────────

async def test_an_automation_made_for_a_person_is_their_activity(activity_signals, monkeypatch):
    from wss.handlers import workflow_handler

    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    pool = MockNativePool({"INSERT INTO workflows": str(uuid.uuid4())})

    await workflow_handler.create_workflow_as_user(pool, USER, name="Lead tracker", description="", capped=False,
                                                   by="coordinator")
    await workflow_handler.create_workflow_as_user(pool, USER, name="Agent's own", description="", capped=False)

    assert activity_signals == [(USER, "automation.create", {"name": "Lead tracker", "by": "coordinator"}, None)]


@pytest.mark.parametrize("context, by", [({}, "builder"), ({"source": "coordinator"}, "coordinator"),
                                         ({"source": "platform_api"}, "api"),
                                         ({"source": "platform_api", "by": "coordinator"}, "coordinator"),
                                         ({"source": "agent_prompt_builder"}, "agent")])
def test_a_finished_build_is_an_edit_by_whoever_asked_for_it(activity_signals, context, by):
    from wss.handlers.workflow_builder_handler import signal_build

    signal_build(USER, context, name="Lead tracker", prompt="add Slack", nodes=4, model="claude-sonnet")

    assert activity_signals == [(USER, "automation.edit", {"name": "Lead tracker", "by": by, "prompt": "add Slack",
                                                           "nodes": 4, "model": "claude-sonnet"}, None)]


@pytest.mark.asyncio
class TestCanvas(BaseHandlerTest):
    """The canvas's own create and save, over the socket and a real database."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": USER, "email": "canvas@example.com"}

    async def _user(self, real_database):
        await real_database.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                                    USER, "canvas@example.com")

    async def test_creating_an_automation_in_the_app(self, real_database, frontend_sio, sid, activity_signals):
        await self._user(real_database)

        await send_event(frontend_sio, sid, WorkflowCreateRequest(request_id="c1", name="Lead tracker"))
        await asyncio.sleep(0.2)

        assert activity_signals == [(USER, "automation.create", {"name": "Lead tracker", "by": "app"}, None)]

    async def test_saves_of_one_automation_share_a_burst_and_moves_say_nothing(self, real_database, frontend_sio,
                                                                               sid, activity_signals):
        await self._user(real_database)
        workflow_id = str(uuid.uuid4())
        gmail = {"id": "n1", "type": "automation-gmail", "position": {"x": 0, "y": 0},
                 "config": {"label": "Gmail"}}
        await real_database.execute(
            "INSERT INTO workflows (id, owner_id, name, workflow, permissions) VALUES ($1, $2, 'Lead tracker', $3, $4)",
            workflow_id, USER, {"nodes": [gmail], "edges": []}, {})

        slack_node = {"id": "n2", "type": "automation-slack", "position": {"x": 0, "y": 0},
                      "config": {"label": "Slack"}}
        moved = {**gmail, "position": {"x": 50, "y": 0}}
        for request_id, nodes in (("u1", [gmail, slack_node]), ("u2", [moved, slack_node])):
            await send_event(frontend_sio, sid, WorkflowUpdateRequest(
                request_id=request_id, workflow_id=workflow_id, workflow_data={"nodes": nodes, "edges": []}))
            await asyncio.sleep(0.2)

        assert activity_signals == [(USER, "automation.edit",
                                     {"name": "Lead tracker", "by": "canvas", "added": ["Slack"]},
                                     f"edit:{workflow_id}:canvas")]
