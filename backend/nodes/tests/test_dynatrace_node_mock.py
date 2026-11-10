"""Exercise Dynatrace routes, wire formats and the audit trigger's state transitions.

The audit fixture is copied from the provider docs; ordinary HTTP mocks are local
unit-test examples, while the external conformance suite checks the pinned API.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import dynatrace_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

REAL_CLIENT = httpx.AsyncClient
TOKEN = "dynatrace-unit-test-bearer"
ACCOUNT = "6b929f34-bf86-47c6-8a67-4de81011affc"
GROUP = "fc2adb60-5291-43bb-b759-03985ef9a5b0"
POLICY = "af1f98c9-c611-4056-841b-d039b1af3f98"
EMAIL = "someone+automation@example.com"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/dynatrace/account_audits.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="dynatrace-test", node_type="automation-dynatrace",
        node_data={"config": config, "credentials": {"access_token": TOKEN, "account_uuid": ACCOUNT}})


def transport(monkeypatch, *, status=200, payload=None, content=None):
    requests = []
    def respond(request):
        requests.append(request)
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return REAL_CLIENT(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,method,suffix", [
    ("list_users", {}, "GET", "/users"),
    ("create_user", {"email": EMAIL}, "POST", "/users"),
    ("get_user_groups", {"email": EMAIL}, "GET", "/users/someone+automation@example.com"),
    ("add_user_to_groups", {"email": EMAIL, "group_ids_json": json.dumps([GROUP])}, "POST", "/users/someone+automation@example.com"),
    ("remove_user", {"email": EMAIL}, "DELETE", "/users/someone+automation@example.com"),
    ("replace_user_groups", {"email": EMAIL, "group_ids_json": "[]"}, "PUT", "/users/someone+automation@example.com/groups"),
    ("remove_user_from_groups", {"email": EMAIL, "group_ids_json": json.dumps([GROUP, POLICY])}, "DELETE", "/users/someone+automation@example.com/groups"),
    ("list_groups", {}, "GET", "/groups"),
    ("create_group", {"name": "Automation"}, "POST", "/groups"),
    ("update_group", {"group_uuid": GROUP, "name": "Automation"}, "PUT", "/groups/" + GROUP),
    ("delete_group", {"group_uuid": GROUP}, "DELETE", "/groups/" + GROUP),
    ("list_group_members", {"group_uuid": GROUP}, "GET", "/groups/" + GROUP + "/users"),
])
async def test_user_group_routes_and_wire_shapes(monkeypatch, operation, extra, method, suffix):
    requests = transport(monkeypatch, payload={"count": 0, "items": []})
    result = await node({"operation": operation, **extra}).execute({})
    request = requests[0]
    assert len(requests) == 1
    assert request.method == method
    assert request.url.host == "api.dynatrace.com"
    assert request.url.path == "/iam/v1/accounts/" + ACCOUNT + suffix
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert result["http_status"] == 200
    if operation == "create_user":
        assert json.loads(request.content) == {"email": EMAIL}
    if operation == "create_group":
        assert json.loads(request.content) == [{"name": "Automation"}]
    if operation == "update_group":
        assert json.loads(request.content) == {"name": "Automation"}
    if operation == "add_user_to_groups":
        assert json.loads(request.content) == [GROUP]
    if operation == "replace_user_groups":
        assert json.loads(request.content) == []
    if operation == "remove_user_from_groups":
        assert request.url.params.get_list("group-uuid") == [GROUP, POLICY]
        assert not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method", [("list_policies", "GET"), ("get_policy", "GET"), ("create_policy", "POST"), ("update_policy", "PUT"), ("delete_policy", "DELETE")])
async def test_account_policy_bodies_and_required_false_query(monkeypatch, operation, method):
    extra = {}
    if operation in {"get_policy", "update_policy", "delete_policy"}:
        extra["policy_uuid"] = POLICY
    if operation in {"create_policy", "update_policy"}:
        extra.update(name="Log reader", policy_description="Read logs", statement_query="ALLOW storage:logs:read;", tags_json='["automation"]')
    requests = transport(monkeypatch, status=204, content=b"")
    result = await node({"operation": operation, **extra}).execute({})
    request = requests[0]
    assert request.method == method
    assert request.url.path == f"/iam/v1/repo/account/{ACCOUNT}/policies" + ("/" + POLICY if "policy_uuid" in extra else "")
    if operation == "delete_policy":
        assert request.url.params["force"] == "false"
    if extra.get("name"):
        assert json.loads(request.content) == {"name": "Log reader", "description": "Read logs", "statementQuery": "ALLOW storage:logs:read;", "tags": ["automation"]}
    assert result["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,path,params", [
    ("list_environments", {}, f"/env/v2/accounts/{ACCOUNT}/environments", {}),
    ("list_subscriptions", {}, f"/sub/v2/accounts/{ACCOUNT}/subscriptions", {}),
    ("get_subscription", {"subscription_uuid": GROUP}, f"/sub/v2/accounts/{ACCOUNT}/subscriptions/{GROUP}", {}),
    ("list_audit_logs", {"start_time": "now()-2d", "end_time": "now()", "audit_filter": "resource = 'POLICY'"}, f"/audit/v1/accounts/{ACCOUNT}", {"startTime": "now()-2d", "endTime": "now()", "filter": "resource = 'POLICY'", "limit": "50"}),
    ("list_users", {"include_service_users": False}, f"/iam/v1/accounts/{ACCOUNT}/users", {"service-users": "false"}),
])
async def test_account_reads_and_query_names(monkeypatch, operation, extra, path, params):
    requests = transport(monkeypatch, payload={"data": []})
    await node({"operation": operation, **extra}).execute({})
    assert requests[0].method == "GET"
    assert requests[0].url.path == path
    assert dict(requests[0].url.params) == params


@pytest.mark.parametrize("field,value", [("account_uuid", "../other"), ("access_token", "Bearer abc"), ("access_token", "https://example.com/key")])
def test_manual_credential_fields_are_shaped(field, value):
    with pytest.raises(ValueError):
        native.DynatraceOAuthCredential.model_validate({"access_token": TOKEN, "account_uuid": ACCOUNT, field: value})
    credential = native.DynatraceOAuthCredential.model_validate({"access_token": TOKEN, "account_uuid": ACCOUNT})
    assert credential.credential_type == "dynatrace_oauth"


@pytest.mark.parametrize("operation,extra", [
    ("remove_user_from_groups", {"email": EMAIL, "group_ids_json": json.dumps([GROUP] * 21)}),
    ("add_user_to_groups", {"email": EMAIL, "group_ids_json": "[]"}),
    ("replace_user_groups", {"email": EMAIL, "group_ids_json": "[1]"}),
    ("update_group", {"group_uuid": "../groups", "name": "No"}),
    ("create_policy", {"name": "No", "statement_query": "ALLOW storage:logs:read;"}),
])
def test_invalid_requests_fail_before_network(operation, extra):
    with pytest.raises(ValueError):
        node({"operation": operation, **extra})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"message": "Unauthorized"}), (403, {"message": "Forbidden"}), (302, {"message": "redirect"}), (200, {"error": True, "message": "Token " + TOKEN})])
async def test_provider_errors_and_success_error_envelopes(monkeypatch, status, payload):
    transport(monkeypatch, status=status, payload=payload)
    with pytest.raises(native.DynatraceAPIError) as exc:
        await node({"operation": "list_groups"}).execute({})
    assert TOKEN not in str(exc.value)
    if status in {401, 403}:
        assert payload["message"] in str(exc.value)


@pytest.mark.asyncio
async def test_redacts_audit_authentication_material(monkeypatch):
    transport(monkeypatch, payload=FIXTURE["body"])
    result = await node({"operation": "list_audit_logs"}).execute({})
    assert "authenticationToken" not in str(result)
    assert result["data"]["audits"][0]["eventId"] == FIXTURE["body"]["audits"][0]["eventId"]


@pytest.mark.asyncio
async def test_poll_baseline_new_event_replay_scope_and_human_event(monkeypatch):
    payload = {"audits": FIXTURE["body"]["audits"], "warnings": []}
    requests = transport(monkeypatch, payload=payload)
    instance = node({"operation": "on_new_audit_event", "lookback_hours": 24, "audit_filter": "resource = 'POLICY'"})
    state = {}
    async def update(mutator, **kwargs):
        next_state, result = mutator(dict(state))
        if next_state is not None:
            state.clear()
            state.update(next_state)
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))["audits"] == []
    assert instance.trigger_produced_no_event({})
    state["seen_ids"] = []
    result = await instance.execute({})
    assert result["new_event_count"] == 1
    assert instance.trigger_emitted_event(result)
    assert (await instance.execute({}))["new_event_count"] == 0
    turn = native.DynatraceNode.resolve_agent_event(result)
    for value in ["Dynatrace", "user@company.com", "CREATE", "POLICY", "Standard User", payload["audits"][0]["eventId"]]:
        assert value in turn["text"]
    assert "authenticationToken" not in turn["text"]
    assert dict(requests[0].url.params) == {"startTime": "now()-24h", "endTime": "now()", "limit": "1000", "filter": "resource = 'POLICY'"}
    original = {"operation": "on_new_audit_event", "audit_filter": "resource = 'POLICY'"}
    assert poll_scope(native.DynatraceNode, original) != poll_scope(native.DynatraceNode, {**original, "audit_filter": "resource = 'GROUP'"})
    assert poll_scope(native.DynatraceNode, original) == poll_scope(native.DynatraceNode, {**original, "irrelevant": "other-account"})


@pytest.mark.asyncio
async def test_documented_truncated_audit_response_does_not_consume_state(monkeypatch):
    transport(monkeypatch, payload=FIXTURE["body"])
    instance = node({"operation": "on_new_audit_event"})
    async def unexpected(*args, **kwargs):
        pytest.fail("Truncated audit data must not consume seen state")
    instance._filter_unseen = unexpected
    with pytest.raises(ValueError, match="truncated"):
        await instance.execute({})


@pytest.mark.asyncio
async def test_explicit_partial_mode_emits_documented_events_with_warning(monkeypatch):
    transport(monkeypatch, payload=FIXTURE["body"])
    instance = node({"operation": "on_new_audit_event", "allow_partial_results": True})
    state = {"seen_ids": []}
    async def update(mutator, **kwargs):
        next_state, result = mutator(dict(state))
        if next_state is not None:
            state.update(next_state)
        return result
    instance._update_node_state = update
    result = await instance.execute({})
    assert result["new_event_count"] == 1
    assert result["window_may_be_incomplete"] is True
    assert result["warnings"] == FIXTURE["body"]["warnings"]
    assert "incomplete" in instance.resolve_agent_event(result)["text"]
    assert (await instance.execute({}))["new_event_count"] == 0


@pytest.mark.asyncio
async def test_invalid_read_json_is_not_successful_connection_evidence(monkeypatch):
    transport(monkeypatch, content=b"<html>Login required</html>")
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_groups"}).execute({})


@pytest.mark.asyncio
async def test_declared_oauth_pkce_identity_context_and_nonrotating_refresh(monkeypatch):
    import respx
    from urllib.parse import parse_qs
    from nodes.oauth.dynatrace_oauth import OAUTH_PROVIDER
    monkeypatch.setenv("DYNATRACE_CLIENT_ID", "test-client")
    monkeypatch.setenv("DYNATRACE_CLIENT_SECRET", "test-client-secret")
    callback = "https://noclick.com/api/auth/oauth/dynatrace/callback"
    monkeypatch.setenv("DYNATRACE_REDIRECT_URI", callback)
    scopes = " ".join(sorted(native.DYNATRACE_SCOPES.declared_scopes()))
    with respx.mock(assert_all_called=True) as router:
        endpoint = router.post("https://sso.dynatrace.com/sso/oauth2/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "issued-access", "refresh_token": "original-refresh", "expires_in": 600, "scope": scopes, "token_type": "Bearer"}),
            httpx.Response(200, json={"access_token": "refreshed-access", "expires_in": 600, "token_type": "Bearer"}),
        ])
        identity = router.get("https://sso.dynatrace.com/sso/oauth2/userinfo").mock(return_value=httpx.Response(200, json={"name": "Dora Engineer", "sub": "user-1"}))
        first, name = await OAUTH_PROVIDER.exchange("test-code", callback, "a" * 43, context={"account_uuid": ACCOUNT})
        second = await OAUTH_PROVIDER.bind_refresh(first.model_dump())(first.refresh_token)
    assert name == "Dora Engineer"
    assert first.account_uuid == second.account_uuid == ACCOUNT
    assert second.access_token == "refreshed-access" and second.refresh_token is None
    code = parse_qs(endpoint.calls[0].request.content.decode())
    assert code["grant_type"] == ["authorization_code"]
    assert code["code_verifier"] == ["a" * 43]
    assert code["redirect_uri"] == [callback]
    assert code["client_secret"] == ["test-client-secret"]
    refresh = parse_qs(endpoint.calls[1].request.content.decode())
    assert refresh["grant_type"] == ["refresh_token"] and refresh["refresh_token"] == ["original-refresh"]
    assert identity.calls[0].request.headers["Authorization"] == "Bearer issued-access"


@pytest.mark.asyncio
async def test_declared_oauth_rejects_missing_pkce_or_account_context():
    from nodes.oauth.dynatrace_oauth import OAUTH_PROVIDER
    with pytest.raises(ValueError, match="context|account_uuid"):
        await OAUTH_PROVIDER.exchange("test-code", "https://noclick.com/callback", "a" * 43)
    with pytest.raises(ValueError, match="PKCE"):
        await OAUTH_PROVIDER.exchange("test-code", "https://noclick.com/callback", context={"account_uuid": ACCOUNT})


@pytest.mark.asyncio
async def test_expired_execution_refreshes_through_shared_seam_and_retains_refresh_token(monkeypatch):
    import respx
    monkeypatch.setenv("DYNATRACE_CLIENT_ID", "test-client")
    monkeypatch.setenv("DYNATRACE_CLIENT_SECRET", "test-client-secret")
    instance = node({"operation": "list_groups"})
    instance.config.credentials.refresh_token = "original-refresh"
    instance.config.credentials.expires_at = "2000-01-01T00:00:00Z"
    with respx.mock(assert_all_called=True) as router:
        router.post("https://sso.dynatrace.com/sso/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "refreshed-access", "expires_in": 600}))
        groups = router.get(f"https://api.dynatrace.com/iam/v1/accounts/{ACCOUNT}/groups").mock(return_value=httpx.Response(200, json={"count": 0, "items": []}))
        result = await instance.execute({})
    assert groups.calls[0].request.headers["Authorization"] == "Bearer refreshed-access"
    assert instance.config.credentials.refresh_token == "original-refresh"
    assert instance.config.credentials.account_uuid == ACCOUNT
    assert result["data"]["items"] == []
