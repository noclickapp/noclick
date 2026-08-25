"""
Mock tests for the Calendly node (no live API calls).

Exercises URL construction (URI-as-ID coercion, default user/org resolution),
pagination params, the generic passthrough, webhook register/unregister + Stripe-
style signature verification, and the trigger passthrough. The HTTP layer
(_calendly_request) is patched so the node's request-shaping is what's under test.
"""

import hashlib
import hmac
import json

import pytest
from unittest.mock import Mock, patch

from nodes.calendly_node import (
    CalendlyNode, CalendlyNodeConfig, CalendlyOAuthCredential, CalendlyPATCredential,
    CalendlyGetCurrentUserConfig, CalendlyGetUserConfig,
    CalendlyListEventTypesConfig, CalendlyGetEventTypeConfig,
    CalendlyListScheduledEventsConfig, CalendlyGetScheduledEventConfig,
    CalendlyCancelScheduledEventConfig, CalendlyListEventInviteesConfig, CalendlyGetEventInviteeConfig,
    CalendlyCreateNoShowConfig, CalendlyDeleteNoShowConfig,
    CalendlyGetOrganizationConfig, CalendlyListMembershipsConfig, CalendlyRemoveMembershipConfig,
    CalendlyListInvitationsConfig, CalendlyCreateInvitationConfig, CalendlyRevokeInvitationConfig,
    CalendlyCreateSchedulingLinkConfig, CalendlyListBusyTimesConfig,
    CalendlyListRoutingFormsConfig, CalendlyListGroupsConfig,
    CalendlyDeleteInviteeDataConfig, CalendlyDeleteEventDataConfig,
    CalendlyCustomRequestConfig, CalendlyOnInviteeCreatedConfig,
    _as_uri, _uuid_tail,
)

USER_URI = "https://api.calendly.com/users/U1"
ORG_URI = "https://api.calendly.com/organizations/O1"


@pytest.fixture
def oauth_cred():
    return CalendlyOAuthCredential(
        access_token="cal_token", refresh_token="r", expires_at="2999-01-01T00:00:00+00:00",
        owner=USER_URI, organization=ORG_URI,
    )


@pytest.fixture
def pat_cred():
    return CalendlyPATCredential(personal_access_token="pat_token")


def make_node(config):
    return CalendlyNode(
        node_id="cal", node_type="automation-calendly", node_data={},
        config=config, sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


async def _noop_ensure_fresh_token(self, credentials):
    """Stub the OAuth-refresh choke point so mock tests never touch the native DB
    pool (token refresh has its own coverage in test_calendly_oauth.py)."""
    return None


async def run_capture(config, response=None):
    """Execute the node with _calendly_request patched; capture the last call."""
    captured = {}

    async def fake_request(cred, method, url, params=None, json_body=None, action_name="request"):
        captured["cred"] = cred
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        captured["json_body"] = json_body
        captured["action_name"] = action_name
        return response if response is not None else {"status": "success", "action": action_name, "data": {}}

    node = make_node(config)
    with patch("nodes.calendly_node._calendly_request", side_effect=fake_request), \
         patch.object(CalendlyNode, "_ensure_fresh_token", _noop_ensure_fresh_token):
        result = await node.execute({})
    return result, captured


# ------------------------------------------------------------------ helpers


def test_as_uri_coerces_bare_uuid():
    assert _as_uri("users", "abc") == "https://api.calendly.com/users/abc"
    assert _as_uri("users", USER_URI) == USER_URI  # already a URI → passthrough


@pytest.mark.parametrize(
    "uri",
    [
        "http://api.calendly.com/webhook_subscriptions/WH1",
        "https://api.calendly.com.evil.example/webhook_subscriptions/WH1",
        "https://api.calendly.com@evil.example/webhook_subscriptions/WH1",
    ],
)
def test_as_uri_rejects_non_calendly_origins(uri):
    with pytest.raises(ValueError, match="outside"):
        _as_uri("webhook_subscriptions", uri)


def test_uuid_tail():
    assert _uuid_tail(USER_URI) == "U1"
    assert _uuid_tail("bare") == "bare"


# ------------------------------------------------------------------ Users


@pytest.mark.asyncio
async def test_get_current_user(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(config=CalendlyGetCurrentUserConfig(), credentials=oauth_cred))
    assert cap["method"] == "GET"
    assert cap["url"] == "https://api.calendly.com/users/me"


@pytest.mark.asyncio
async def test_get_user_uuid_tail(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(config=CalendlyGetUserConfig(user=USER_URI), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/users/U1"


# ------------------------------------------------------------------ Event types


@pytest.mark.asyncio
async def test_list_event_types_defaults_user_from_credential(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(config=CalendlyListEventTypesConfig(), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/event_types"
    assert cap["params"]["user"] == USER_URI  # defaulted from credential owner


@pytest.mark.asyncio
async def test_list_event_types_org_overrides_user(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyListEventTypesConfig(organization="O9"), credentials=oauth_cred))
    assert cap["params"]["organization"] == "https://api.calendly.com/organizations/O9"
    assert "user" not in cap["params"]


@pytest.mark.asyncio
async def test_get_event_type_uuid_tail(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyGetEventTypeConfig(event_type="https://api.calendly.com/event_types/E1"), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/event_types/E1"


# ------------------------------------------------------------------ Scheduled events


@pytest.mark.asyncio
async def test_list_scheduled_events_defaults_user(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyListScheduledEventsConfig(status="active"), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/scheduled_events"
    assert cap["params"]["user"] == USER_URI
    assert cap["params"]["status"] == "active"


@pytest.mark.asyncio
async def test_cancel_scheduled_event(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyCancelScheduledEventConfig(scheduled_event="https://api.calendly.com/scheduled_events/S1", reason="no longer needed"),
        credentials=oauth_cred))
    assert cap["method"] == "POST"
    assert cap["url"] == "https://api.calendly.com/scheduled_events/S1/cancellation"
    assert cap["json_body"] == {"reason": "no longer needed"}


@pytest.mark.asyncio
async def test_list_event_invitees(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyListEventInviteesConfig(scheduled_event="S1", count="50"), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/scheduled_events/S1/invitees"
    assert cap["params"]["count"] == "50"


@pytest.mark.asyncio
async def test_get_event_invitee(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyGetEventInviteeConfig(scheduled_event="S1", invitee="I1"), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/scheduled_events/S1/invitees/I1"


# ------------------------------------------------------------------ No-shows


@pytest.mark.asyncio
async def test_create_no_show_passes_invitee_uri(oauth_cred):
    inv = "https://api.calendly.com/scheduled_events/S1/invitees/I1"
    _, cap = await run_capture(CalendlyNodeConfig(config=CalendlyCreateNoShowConfig(invitee=inv), credentials=oauth_cred))
    assert cap["method"] == "POST"
    assert cap["url"] == "https://api.calendly.com/invitee_no_shows"
    assert cap["json_body"] == {"invitee": inv}


@pytest.mark.asyncio
async def test_delete_no_show(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyDeleteNoShowConfig(no_show="https://api.calendly.com/invitee_no_shows/N1"), credentials=oauth_cred))
    assert cap["method"] == "DELETE"
    assert cap["url"] == "https://api.calendly.com/invitee_no_shows/N1"


# ------------------------------------------------------------------ Organization


@pytest.mark.asyncio
async def test_get_organization_defaults_from_credential(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(config=CalendlyGetOrganizationConfig(), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/organizations/O1"


@pytest.mark.asyncio
async def test_create_invitation(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyCreateInvitationConfig(email="new@example.com"), credentials=oauth_cred))
    assert cap["method"] == "POST"
    assert cap["url"] == "https://api.calendly.com/organizations/O1/invitations"
    assert cap["json_body"] == {"email": "new@example.com"}


@pytest.mark.asyncio
async def test_revoke_invitation(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyRevokeInvitationConfig(invitation="INV1"), credentials=oauth_cred))
    assert cap["method"] == "DELETE"
    assert cap["url"] == "https://api.calendly.com/organizations/O1/invitations/INV1"


@pytest.mark.asyncio
async def test_remove_membership(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyRemoveMembershipConfig(membership="M1"), credentials=oauth_cred))
    assert cap["method"] == "DELETE"
    assert cap["url"] == "https://api.calendly.com/organization_memberships/M1"


# ------------------------------------------------------------------ Scheduling / availability


@pytest.mark.asyncio
async def test_create_scheduling_link(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyCreateSchedulingLinkConfig(owner="E1"), credentials=oauth_cred))
    assert cap["method"] == "POST"
    assert cap["url"] == "https://api.calendly.com/scheduling_links"
    assert cap["json_body"] == {"max_event_count": 1, "owner": "https://api.calendly.com/event_types/E1", "owner_type": "EventType"}


@pytest.mark.asyncio
async def test_list_busy_times(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyListBusyTimesConfig(start_time="2026-08-01T00:00:00Z", end_time="2026-08-05T00:00:00Z"),
        credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/user_busy_times"
    assert cap["params"]["user"] == USER_URI
    assert cap["params"]["start_time"] == "2026-08-01T00:00:00Z"


# ------------------------------------------------------------------ Enterprise / data compliance


@pytest.mark.asyncio
async def test_delete_invitee_data_splits_emails(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyDeleteInviteeDataConfig(emails="a@x.com, b@x.com"), credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/data_compliance/deletion/invitees"
    assert cap["json_body"] == {"emails": ["a@x.com", "b@x.com"]}


@pytest.mark.asyncio
async def test_delete_event_data_uses_time_range(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyDeleteEventDataConfig(start_time="2026-01-01T00:00:00Z", end_time="2026-02-01T00:00:00Z"),
        credentials=oauth_cred))
    assert cap["url"] == "https://api.calendly.com/data_compliance/deletion/events"
    assert cap["json_body"] == {"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-02-01T00:00:00Z"}


# ------------------------------------------------------------------ Passthrough


@pytest.mark.asyncio
async def test_custom_request_passthrough(oauth_cred):
    _, cap = await run_capture(CalendlyNodeConfig(
        config=CalendlyCustomRequestConfig(method="GET", path="/contacts", query_params="organization=O1&count=100"),
        credentials=oauth_cred))
    assert cap["method"] == "GET"
    assert cap["url"] == "https://api.calendly.com/contacts"
    assert cap["params"] == {"organization": "O1", "count": "100"}


@pytest.mark.asyncio
async def test_custom_request_rejects_absolute_url(oauth_cred):
    node = make_node(CalendlyNodeConfig(
        config=CalendlyCustomRequestConfig(method="GET", path="https://evil.com/x"), credentials=oauth_cred))
    with patch("nodes.calendly_node._calendly_request", side_effect=AssertionError("should not be called")), \
         patch.object(CalendlyNode, "_ensure_fresh_token", _noop_ensure_fresh_token):
        with pytest.raises(ValueError, match="relative"):
            await node.execute({})


# ------------------------------------------------------------------ PAT credential resolves /users/me


@pytest.mark.asyncio
async def test_pat_credential_resolves_me_for_defaults(pat_cred):
    """With a PAT (no owner/org on the credential), the node resolves /users/me
    to default the user param."""
    calls = []

    async def fake_request(cred, method, url, params=None, json_body=None, action_name="request"):
        calls.append(url)
        if url.endswith("/users/me"):
            return {"status": "success", "action": "get_current_user",
                    "data": {"resource": {"uri": USER_URI, "current_organization": ORG_URI}}}
        return {"status": "success", "action": action_name, "data": {}}

    node = make_node(CalendlyNodeConfig(config=CalendlyListScheduledEventsConfig(), credentials=pat_cred))
    with patch("nodes.calendly_node._calendly_request", side_effect=fake_request):
        await node.execute({})
    # /users/me was fetched, then scheduled_events with the resolved user URI.
    assert any(u.endswith("/users/me") for u in calls)


# ------------------------------------------------------------------ Webhook triggers


@pytest.mark.asyncio
async def test_register_webhook_builds_subscription(oauth_cred):
    cred = oauth_cred.model_dump()
    captured = {}

    async def fake_request(credential, method, url, params=None, json_body=None, action_name="request"):
        captured["method"] = method
        captured["url"] = url
        captured["json_body"] = json_body
        return {"status": "success", "action": action_name,
                "data": {"resource": {"uri": "https://api.calendly.com/webhook_subscriptions/WH1"}}}

    with patch("nodes.calendly_node._calendly_request", side_effect=fake_request):
        extra = await CalendlyNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred,
            config={"operation": "on_invitee_created", "scope": "organization"}, node_id="cal")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.calendly.com/webhook_subscriptions"
    body = captured["json_body"]
    assert body["events"] == ["invitee.created"]
    assert body["url"] == "https://abc.hooks.example.test"
    assert body["organization"] == ORG_URI
    assert body["scope"] == "organization"
    assert body["signing_key"]  # a minted secret is sent
    assert extra["external_webhook_id"] == "https://api.calendly.com/webhook_subscriptions/WH1"
    assert extra["signing_secret"] == body["signing_key"]


@pytest.mark.asyncio
async def test_register_webhook_forces_org_scope_for_contact_events(oauth_cred):
    cred = oauth_cred.model_dump()
    captured = {}

    async def fake_request(credential, method, url, params=None, json_body=None, action_name="request"):
        captured["json_body"] = json_body
        return {"status": "success", "data": {"resource": {"uri": "https://api.calendly.com/webhook_subscriptions/WH2"}}}

    with patch("nodes.calendly_node._calendly_request", side_effect=fake_request):
        await CalendlyNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred,
            config={"operation": "on_contact_created", "scope": "user"}, node_id="cal")
    # contact.* is organization-scoped only — the user scope is overridden.
    assert captured["json_body"]["scope"] == "organization"
    assert "user" not in captured["json_body"]


@pytest.mark.asyncio
async def test_unregister_webhook_deletes_subscription(oauth_cred):
    cred = oauth_cred.model_dump()
    captured = {}

    async def fake_request(credential, method, url, params=None, json_body=None, action_name="request"):
        captured["method"] = method
        captured["url"] = url
        return {"status": "success", "data": {}}

    with patch("nodes.calendly_node._calendly_request", side_effect=fake_request):
        await CalendlyNode._unregister_external_webhook(
            credential=cred, config={"external_webhook_id": "https://api.calendly.com/webhook_subscriptions/WH1"}, node_id="cal")
    assert captured["method"] == "DELETE"
    assert captured["url"] == "https://api.calendly.com/webhook_subscriptions/WH1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_id",
    [
        "https://attacker.example/collect",
        "https://api.calendly.com.evil.example/collect",
        "https://api.calendly.com@evil.example/collect",
    ],
)
async def test_unregister_rejects_external_id_before_request(
    oauth_cred, malicious_id
):
    with patch(
        "nodes.calendly_node._calendly_request",
        side_effect=AssertionError("credentialed request must not start"),
    ) as request:
        with pytest.raises(ValueError, match="outside"):
            await CalendlyNode._unregister_external_webhook(
                credential=oauth_cred.model_dump(),
                config={"external_webhook_id": malicious_id},
                node_id="cal",
            )
    request.assert_not_called()


@pytest.mark.asyncio
async def test_register_rejects_stale_external_id_before_request(oauth_cred):
    with patch(
        "nodes.calendly_node._calendly_request",
        side_effect=AssertionError("credentialed request must not start"),
    ) as request:
        with pytest.raises(ValueError, match="outside"):
            await CalendlyNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential=oauth_cred.model_dump(),
                config={
                    "operation": "on_invitee_created",
                    "external_webhook_id": "https://attacker.example/collect",
                },
                node_id="cal",
            )
    request.assert_not_called()


def test_verify_webhook_signature_valid():
    secret = "signing-key-abc"
    body = b'{"event":"invitee.created"}'
    ts = "1700000000"
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={expected}"
    assert CalendlyNode.verify_webhook_signature(body, {"calendly-webhook-signature": header}, {"signing_secret": secret})


def test_verify_webhook_signature_rejects_tampered():
    secret = "signing-key-abc"
    body = b'{"event":"invitee.created"}'
    ts = "1700000000"
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={expected}"
    assert not CalendlyNode.verify_webhook_signature(body + b" ", {"calendly-webhook-signature": header}, {"signing_secret": secret})


def test_verify_webhook_signature_missing_secret():
    assert not CalendlyNode.verify_webhook_signature(b"{}", {"calendly-webhook-signature": "t=1,v1=x"}, {})


@pytest.mark.asyncio
async def test_trigger_passthrough_in_execute(oauth_cred):
    """A fired webhook delivery is passed through as the trigger output."""
    node = make_node(CalendlyNodeConfig(config=CalendlyOnInviteeCreatedConfig(), credentials=oauth_cred))
    payload = {"event": "invitee.created", "payload": {"email": "a@x.com"}}
    result = await node.execute(payload)
    assert result["status"] == "success"
    assert result["action"] == "on_invitee_created"
    assert result["data"] == payload


def test_credential_union_pat_and_oauth():
    from nodes.calendly_node import CalendlyCredential
    import typing
    members = typing.get_args(CalendlyCredential)
    types = {m.model_fields["credential_type"].default for m in members}
    assert types == {"calendly_oauth", "calendly_pat"}
