"""
Live integration tests for the PagerDuty node.

Skipped unless a REST API key is present:
  PAGERDUTY_API_KEY   (a General Access or personal token)
  PAGERDUTY_FROM_EMAIL (optional; a user email — required by account-level
                        keys for write attribution; defaults to the first user)

Exercises the paths mock tests can't prove: a full incident lifecycle
(escalation policy -> service -> incident -> note -> status update -> resolve)
with the From header, plus create/get/delete cycles on the newer families
(Event Orchestrations, Business Services, Teams) and webhook-subscription
enable/disable.
"""

import os
import httpx
import pytest
from unittest.mock import Mock

from nodes.pagerduty_node import (
    PagerDutyNode,
    PagerDutyNodeConfig,
    PagerDutyApiKeyCredential,
)
import nodes.pagerduty_node as P

API_KEY = os.environ.get("PAGERDUTY_API_KEY")

pytestmark = pytest.mark.skipif(not API_KEY, reason="PAGERDUTY_API_KEY not set")


def _from_email():
    if os.environ.get("PAGERDUTY_FROM_EMAIL"):
        return os.environ["PAGERDUTY_FROM_EMAIL"]
    r = httpx.get(
        "https://api.pagerduty.com/users",
        headers={"Authorization": f"Token token={API_KEY}", "Accept": "application/vnd.pagerduty+json;version=2"},
        params={"limit": 1}, timeout=20,
    )
    return r.json()["users"][0]["email"]


def _ops():
    import typing
    return {c.model_fields["operation"].default: c
            for c in typing.get_args(typing.get_args(PagerDutyNodeConfig.model_fields["config"].annotation)[0])}


def _node(op, cred):
    return PagerDutyNode(
        node_id="it", node_type="automation-pagerduty", node_data={},
        config=PagerDutyNodeConfig(config=op, credentials=cred),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


def _id(r, key):
    d = (r or {}).get("data", {})
    return d.get(key, {}).get("id") if isinstance(d.get(key), dict) else None


@pytest.fixture
def cred():
    return PagerDutyApiKeyCredential(api_key=API_KEY, from_email=_from_email(), region="us")


@pytest.mark.asyncio
async def test_incident_lifecycle_live(cred):
    ops = _ops()
    user_email = cred.from_email
    users = httpx.get(
        "https://api.pagerduty.com/users",
        headers={"Authorization": f"Token token={API_KEY}", "Accept": "application/vnd.pagerduty+json;version=2"},
        params={"query": user_email, "limit": 1}, timeout=20,
    ).json()["users"]
    uid = users[0]["id"]

    ep = _id(await _node(ops["create_escalation_policy"](name="IT EP", escalation_target_id=uid, escalation_target_type="user_reference"), cred).execute({}), "escalation_policy")
    svc = _id(await _node(ops["create_service"](name="IT Svc", escalation_policy_id=str(ep)), cred).execute({}), "service")
    try:
        r = await _node(ops["create_incident"](title="[IT] incident", service_id=str(svc)), cred).execute({})
        assert r["status"] == "success", r
        inc = r["data"]["incident"]["id"]
        assert (await _node(ops["get_incident"](incident_id=inc), cred).execute({}))["status"] == "success"
        assert (await _node(ops["create_note"](incident_id=inc, content="note"), cred).execute({}))["status"] == "success"
        assert (await _node(ops["create_status_update"](incident_id=inc, message="working"), cred).execute({}))["status"] == "success"
        assert (await _node(ops["manage_incidents"](incident_ids=inc, status="resolved"), cred).execute({}))["status"] == "success"
    finally:
        httpx.request("DELETE", f"https://api.pagerduty.com/services/{svc}",
                      headers={"Authorization": f"Token token={API_KEY}", "Accept": "application/vnd.pagerduty+json;version=2"}, timeout=20)
        httpx.request("DELETE", f"https://api.pagerduty.com/escalation_policies/{ep}",
                      headers={"Authorization": f"Token token={API_KEY}", "Accept": "application/vnd.pagerduty+json;version=2"}, timeout=20)


@pytest.mark.asyncio
async def test_new_families_lifecycle_live(cred):
    ops = _ops()
    # Event Orchestration
    eo = _id(await _node(ops["create_event_orchestration"](name="IT EO"), cred).execute({}), "orchestration")
    assert eo
    assert (await _node(ops["get_event_orchestration"](orchestration_id=str(eo)), cred).execute({}))["status"] == "success"
    assert (await _node(ops["delete_event_orchestration"](orchestration_id=str(eo)), cred).execute({}))["status"] == "success"
    # Business Service
    bs = _id(await _node(ops["create_business_service"](name="IT BS"), cred).execute({}), "business_service")
    assert bs
    assert (await _node(ops["delete_business_service"](business_service_id=str(bs)), cred).execute({}))["status"] == "success"
    # Webhook subscription enable/disable (disable uses PUT active=false, not a /disable route)
    wh = _id(await _node(ops["create_webhook_subscription"](delivery_url="https://httpbin.org/status/200"), cred).execute({}), "webhook_subscription")
    assert wh
    assert (await _node(ops["disable_webhook_subscription"](webhook_subscription_id=str(wh)), cred).execute({}))["status"] == "success"
    assert (await _node(ops["enable_webhook_subscription"](webhook_subscription_id=str(wh)), cred).execute({}))["status"] == "success"
    assert (await _node(ops["delete_webhook_subscription"](webhook_subscription_id=str(wh)), cred).execute({}))["status"] == "success"


def test_region_routing():
    P._PD_REGION.set("eu")
    assert P._rest_base() == "https://api.eu.pagerduty.com"
    assert P._events_enqueue_url() == "https://events.eu.pagerduty.com/v2/enqueue"
    P._PD_REGION.set("us")
    assert P._rest_base() == "https://api.pagerduty.com"
