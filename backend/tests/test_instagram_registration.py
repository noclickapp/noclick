"""A Meta outage reads as one, and a step it left "Not registered" is judged again.

A live comment trigger's next registration met an HTTP 500 from Meta and the step kept
"Not registered: ... check account access" for good, though its subscription stood and
comments kept arriving: the reconciler took its matching rows as converged and never
looked again.

A registered DM trigger's panel then re-POSTed the account subscription on every open
until Meta rate-limited it (code 613), and each refusal told the user a working trigger
was "Not registered". A registered trigger is re-checked with a read, never re-posted,
and an attempt that reaches no verdict leaves it registered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import httpx
import pytest
import respx

from nodes.core import webhook_subscriptions
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from nodes.instagram_node import INSTAGRAM_API_BASE, InstagramNode
from utils import meta_subscriptions
from utils.registration_verdict import RegistrationUnverified
from utils.webhook_manager import WebhookManager

ACCOUNT = "17841400000000001"
CREDENTIAL = {"credential_type": "instagram_login", "instagram_user_id": ACCOUNT, "access_token": "synthetic-token"}
CREDENTIAL_ID = "33333333-3333-3333-3333-333333333333"
OUTAGE = {"error": {"message": "An unexpected error has occurred. Please retry your request later.",
                    "type": "OAuthException", "code": 2, "is_transient": True}}


@pytest.fixture
def instagram(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_APP_SECRET", "synthetic-app-secret")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "synthetic-verification-token")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_APP_ID", "123456789")
    monkeypatch.setenv("APP_WEBHOOK_BASE_URL", "https://api.example.test")
    redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    saved = []

    async def freshen(cls, credential, **kwargs):
        return credential

    async def no_other_triggers(pool, provider, tenant):
        return []

    async def no_rows(pool, workflow_id, node_id):
        return []

    async def save_rows(cls, pool, **kwargs):
        saved.append(kwargs["operation"])
        return f"Registered {kwargs['operation']}"

    monkeypatch.setattr(InstagramNode, "freshen_credential", classmethod(freshen))
    monkeypatch.setattr(webhook_subscriptions, "list_subscriptions_for_tenant", no_other_triggers)
    monkeypatch.setattr(webhook_subscriptions, "get_node_subscriptions", no_rows)
    monkeypatch.setattr(AppEventTriggerMixin, "register_node_subscriptions", classmethod(save_rows))
    with respx.mock(assert_all_called=False) as graph:
        graph.get(f"{INSTAGRAM_API_BASE}/me").respond(json={"user_id": ACCOUNT})
        yield graph, saved


async def _register():
    return await InstagramNode.register_node_subscriptions(
        None, user_id="owner", workflow_id="wf-1", node_id="ig-comments", operation="on_comment",
        credential_id="cred-1", credential=dict(CREDENTIAL),
    )


@pytest.mark.asyncio
async def test_a_meta_outage_on_the_write_says_it_is_temporary(instagram):
    graph, saved = instagram
    graph.post(f"{INSTAGRAM_API_BASE}/{ACCOUNT}/subscribed_apps").respond(500, json=OUTAGE)

    with pytest.raises(ValueError) as refused:
        await _register()

    assert str(refused.value) == (
        "Instagram had a temporary error on the subscription request (HTTP 500 (code 2)); retry later."
    )
    assert saved == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status, body, said", [
    (400, {"error": {"message": "about @someone", "code": 100}},
     "Instagram subscription request returned HTTP 400 (code 100); check account access."),
    (502, "<html>Bad gateway</html>",
     "Instagram had a temporary error on the subscription request (HTTP 502); retry later."),
    (400, {"error": {"message": "about @someone", "code": 4, "is_transient": True}},
     "Instagram had a temporary error on the subscription request (HTTP 400 (code 4)); retry later."),
    # Meta's rate limits arrive without is_transient; they are no verdict on the account either.
    (400, {"error": {"message": "Calls to this api have exceeded the rate limit.", "code": 613}},
     "Instagram had a temporary error on the subscription request (HTTP 400 (code 613)); retry later."),
    (429, {"error": {"message": "about @someone", "code": 80002}},
     "Instagram had a temporary error on the subscription request (HTTP 429 (code 80002)); retry later."),
])
async def test_a_refusal_names_metas_code_never_its_words(status, body, said):
    def answer(request):
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        with pytest.raises(ValueError) as refused:
            await meta_subscriptions.graph_request(client, "GET", "me", base="https://graph.example", label="Instagram")

    assert str(refused.value) == said
    # Only Meta's outage or rate limit is "no verdict"; a refusal is one.
    assert isinstance(refused.value, RegistrationUnverified) == said.endswith("retry later.")


def _stub_reconcile(monkeypatch, *, rows, config):
    registered = []

    async def node_rows(pool, workflow_id, node_id):
        return rows

    async def credential(cls, pool, owner, ids):
        return CREDENTIAL_ID, dict(CREDENTIAL)

    async def ready(pool, workflow_id, node_id):
        return None

    async def describe(cls, pool, **kwargs):
        registered.append(kwargs["node_id"])
        return {"trigger_registered": True, "trigger_error": None,
                "subscription_status": "Registered", "trigger_action": None}

    async def patch(pool, wf_uuid, node_id, mirrors):
        config.update(mirrors)

    monkeypatch.setattr(webhook_subscriptions, "get_node_subscriptions", node_rows)
    monkeypatch.setattr(InstagramNode, "_resolve_trigger_credential", classmethod(credential))
    monkeypatch.setattr("utils.workflow_readiness.require_activation_ready", ready)
    monkeypatch.setattr(InstagramNode, "register_and_describe", classmethod(describe))
    monkeypatch.setattr(WebhookManager, "merge_node_config_patch", staticmethod(patch))
    return registered


ROW = {"provider": "instagram", "tenant_id": ACCOUNT, "event_type": "comments",
       "credential_id": CREDENTIAL_ID, "user_id": "owner"}


def _comment_trigger(**mirrors):
    return {"operation": "on_comment", "credentialIds": {"instagram_login": CREDENTIAL_ID}, **mirrors}


async def _reconcile(config):
    return await WebhookManager._reconcile_app_event_node(
        None, "wf-1", "ig-comments", owner_id="owner", node={"id": "ig-comments", "config": config},
        node_class=InstagramNode, node_config=config, current_op="on_comment",
    )


@pytest.mark.asyncio
async def test_a_step_still_recording_a_failed_registration_is_judged_again(monkeypatch):
    config = _comment_trigger(trigger_registered=True, subscription_status="Registered",
                              trigger_error="Not registered: Instagram subscription request returned HTTP 500")
    registered = _stub_reconcile(monkeypatch, rows=[ROW], config=config)

    assert (await _reconcile(config))["state"] == "registered"
    assert registered == ["ig-comments"] and config["trigger_error"] is None


@pytest.mark.asyncio
async def test_a_converged_step_is_left_alone(monkeypatch):
    config = _comment_trigger(trigger_registered=True, subscription_status="Registered", trigger_error=None)
    registered = _stub_reconcile(monkeypatch, rows=[ROW], config=config)

    assert (await _reconcile(config))["state"] == "live"
    assert registered == []


OWNER = "owner"
WORKFLOW = "44444444-4444-4444-4444-444444444444"
NODE = "ig-dms"
SUBSCRIBED = f"{INSTAGRAM_API_BASE}/{ACCOUNT}/subscribed_apps"
DM_ROW = {"provider": "instagram", "tenant_id": ACCOUNT, "event_type": "messages",
          "credential_id": CREDENTIAL_ID, "user_id": OWNER, "workflow_id": WORKFLOW, "node_id": NODE}
THROTTLED = {"error": {"message": "Calls to this api have exceeded the rate limit.", "type": "OAuthException", "code": 613}}


@pytest.fixture
def account(monkeypatch):
    """An Instagram Login account at Meta, the DM trigger's local rows, and its panel."""
    for name, value in {"INSTAGRAM_WEBHOOK_APP_SECRET": "synthetic-app-secret",
                        "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "synthetic-verification-token",
                        "INSTAGRAM_WEBHOOK_APP_ID": "123456789",
                        "APP_WEBHOOK_BASE_URL": "https://api.example.test"}.items():
        monkeypatch.setenv(name, value)
    redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    rows = {}

    async def node_rows(pool, workflow_id, node_id):
        return [dict(row) for row in rows.get(node_id, [])]

    async def tenant_rows(pool, provider, tenant):
        return [dict(row) for node in rows.values() for row in node if row["tenant_id"] == tenant]

    async def save(pool, **kwargs):
        rows[kwargs["node_id"]] = [dict(DM_ROW, event_type=event) for event in kwargs["event_types"]]

    async def credential(pool, user_id, credential_id, **kwargs):
        return dict(CREDENTIAL)

    async def freshen(cls, credential, **kwargs):
        return credential

    async def owner(pool, workflow_id, include_nodes=True):
        return OWNER, []

    saved, deleted = AsyncMock(side_effect=save), AsyncMock()
    monkeypatch.setattr(webhook_subscriptions, "get_node_subscriptions", node_rows)
    monkeypatch.setattr(webhook_subscriptions, "list_subscriptions_for_tenant", tenant_rows)
    monkeypatch.setattr(webhook_subscriptions, "save_subscriptions", saved)
    monkeypatch.setattr(webhook_subscriptions, "delete_subscriptions", deleted)
    monkeypatch.setattr("utils.credential_loader.load_credential", credential)
    monkeypatch.setattr(InstagramNode, "freshen_credential", classmethod(freshen))
    monkeypatch.setattr("utils.webhook_manager._load_workflow_owner_and_nodes", owner)
    with respx.mock(assert_all_called=False) as graph:
        graph.get(f"{INSTAGRAM_API_BASE}/me").respond(json={"user_id": ACCOUNT})
        yield SimpleNamespace(rows=rows, saved=saved, deleted=deleted,
                              read=graph.get(SUBSCRIBED), write=graph.post(SUBSCRIBED))


async def _open_panel():
    result = await InstagramNode.load_field_value(
        "subscription_status", OWNER, WORKFLOW, NODE, None,
        context={"operation": "on_message"}, credential_ids={"instagram_login": CREDENTIAL_ID},
    )
    return result["values"]


@pytest.mark.asyncio
async def test_reopening_a_registered_trigger_reads_the_account_and_never_reposts(account):
    account.rows[NODE] = [dict(DM_ROW)]
    account.read.respond(json={"data": [{"subscribed_fields": ["messages"]}]})

    for _ in range(10):
        values = await _open_panel()
        assert values["trigger_registered"] is True and values["trigger_error"] is None
        assert values["subscription_status"] == "Registered — listening for Instagram messages on the connected account"

    assert account.write.call_count == 0 and account.read.call_count == 10
    account.saved.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("blip", [
    httpx.Response(500, json=THROTTLED),
    httpx.Response(400, json=THROTTLED),
    httpx.Response(429, json={"error": {"code": 4}}),
    httpx.ConnectError("unreachable"),
], ids=["613-as-500", "613-as-400", "429", "transport"])
async def test_a_recheck_meta_cannot_answer_keeps_the_trigger_registered(account, blip):
    account.rows[NODE] = [dict(DM_ROW)]
    if isinstance(blip, Exception):
        account.read.mock(side_effect=blip)
    else:
        account.read.mock(return_value=blip)

    values = await _open_panel()

    assert values["trigger_registered"] is True and values["trigger_error"] is None
    assert values["subscription_status"] == (
        "Registered — listening for Instagram messages on the connected account (couldn't re-check just now)"
    )
    assert account.write.call_count == 0 and account.rows[NODE] == [DM_ROW]
    account.saved.assert_not_awaited()
    account.deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_revoked_account_on_recheck_is_not_softened(account):
    account.rows[NODE] = [dict(DM_ROW)]
    account.read.respond(400, json={"error": {"code": 190}})

    values = await _open_panel()

    assert values["trigger_registered"] is False
    assert values["trigger_error"] == (
        "Not registered: Instagram account authorization is unavailable; reconnect with the required Page permissions."
    )
    assert account.rows[NODE] == [DM_ROW]
    account.deleted.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, said", [
    ("write", "Instagram had a temporary error on the subscription request (HTTP 500 (code 613)); retry later."),
    ("readback", "Instagram accepted the subscription update but its readback could not be verified; "
                 "remote fields may have changed and no workflow subscription was saved."),
])
async def test_without_a_registration_on_record_the_same_failure_still_surfaces(account, failure, said):
    if failure == "write":
        account.write.respond(500, json=THROTTLED)
    else:
        account.write.respond(json={"success": True})
        account.read.respond(500, json=THROTTLED)

    values = await _open_panel()

    assert values["trigger_registered"] is False
    assert values["subscription_status"] == f"⚠ Not registered: {said}"
    assert NODE not in account.rows
    account.saved.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "readback"])
async def test_an_account_that_lost_the_trigger_is_resubscribed(account, failure):
    """Meta's read said the fields are gone, so the re-subscribe write is the verdict: a
    write Meta won't take is "Not registered", while one it accepted but couldn't read
    back reaches no verdict and the rows' registration stands."""
    account.rows[NODE] = [dict(DM_ROW)]
    if failure == "write":
        account.read.respond(json={"data": []})
        account.write.respond(500, json=THROTTLED)
    else:
        account.read.mock(side_effect=[httpx.Response(200, json={"data": []}), httpx.Response(500, json=THROTTLED)])
        account.write.respond(json={"success": True})

    values = await _open_panel()

    assert account.write.call_count == 1
    assert values["trigger_registered"] is (failure == "readback")
    if failure == "write":
        assert values["trigger_error"].startswith("Not registered: Instagram had a temporary error")
    else:
        assert values["subscription_status"].endswith("(couldn't re-check just now)")
    assert account.rows[NODE] == [DM_ROW]
    account.deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_step_left_not_registered_by_a_blip_heals_on_reconcile_without_a_post(account, monkeypatch):
    account.rows[NODE] = [dict(DM_ROW)]
    account.read.respond(json={"data": [{"subscribed_fields": ["messages"]}]})
    config = {"operation": "on_message", "credentialIds": {"instagram_login": CREDENTIAL_ID},
              "trigger_registered": False, "subscription_status": "⚠ Not registered: Instagram had a temporary error",
              "trigger_error": "Not registered: Instagram had a temporary error"}

    async def ready(pool, workflow_id, node_id):
        return None

    async def patch(pool, wf_uuid, node_id, mirrors):
        config.update(mirrors)

    monkeypatch.setattr("utils.workflow_readiness.require_activation_ready", ready)
    monkeypatch.setattr(WebhookManager, "merge_node_config_patch", staticmethod(patch))

    state = await WebhookManager._reconcile_app_event_node(
        None, WORKFLOW, NODE, owner_id=OWNER, node={"id": NODE, "config": config},
        node_class=InstagramNode, node_config=config, current_op="on_message",
    )

    assert state == {"state": "registered"} and account.write.call_count == 0
    assert config["trigger_registered"] is True and config["trigger_error"] is None
