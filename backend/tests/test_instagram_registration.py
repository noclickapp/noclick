"""A Meta outage reads as one, and a step it left "Not registered" is judged again.

A live comment trigger's next registration met an HTTP 500 from Meta and the step kept
"Not registered: ... check account access" for good, though its subscription stood and
comments kept arriving: the reconciler took its matching rows as converged and never
looked again.
"""

import fakeredis
import httpx
import pytest
import respx

from nodes.core import webhook_subscriptions
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from nodes.instagram_node import INSTAGRAM_API_BASE, InstagramNode
from utils import meta_subscriptions
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

    async def save_rows(cls, pool, **kwargs):
        saved.append(kwargs["operation"])
        return f"Registered {kwargs['operation']}"

    monkeypatch.setattr(InstagramNode, "freshen_credential", classmethod(freshen))
    monkeypatch.setattr(webhook_subscriptions, "list_subscriptions_for_tenant", no_other_triggers)
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
])
async def test_a_refusal_names_metas_code_never_its_words(status, body, said):
    def answer(request):
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        with pytest.raises(ValueError) as refused:
            await meta_subscriptions.graph_request(client, "GET", "me", base="https://graph.example", label="Instagram")

    assert str(refused.value) == said


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

    assert await _reconcile(config) == {"state": "registered"}
    assert registered == ["ig-comments"] and config["trigger_error"] is None


@pytest.mark.asyncio
async def test_a_converged_step_is_left_alone(monkeypatch):
    config = _comment_trigger(trigger_registered=True, subscription_status="Registered", trigger_error=None)
    registered = _stub_reconcile(monkeypatch, rows=[ROW], config=config)

    assert await _reconcile(config) == {"state": "live"}
    assert registered == []
