"""Offline Temporal Cloud Ops regressions. All identities and tokens are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import temporal_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/temporal/operations.json").read_text()
)
TOKEN = "synthetic-temporal-key-123"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="temporal-fixture",
        node_type="automation-temporal",
        node_data={
            "config": config,
            "credentials": {"credential_type": "temporal_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, payload, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def response(operation):
    if operation == "get_current_identity":
        return {"user": {"id": "user-123", "spec": {"email": "person@example.com"}}}
    if operation in native.LIST_KEYS:
        return {
            native.LIST_KEYS[operation]: [{"id": "resource-123"}],
            "nextPageToken": "next + token",
        }
    if operation in native.DETAIL_KEYS:
        return {
            native.DETAIL_KEYS[operation]: {
                "id": "resource-123",
                "resourceVersion": "version-1",
            }
        }
    return {"asyncOperation": {"id": "operation-123", "state": "STATE_PENDING"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_temporal_exact_provider_wire_and_async_acceptance(
    monkeypatch, operation
):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, response(operation))
    result = await node(fixture["config"]).execute({})
    assert result["status"] == "success" and len(requests) == 1
    req = requests[0]
    assert req.method == fixture["method"] and req.url.path == fixture["path"]
    assert req.url.host == "saas-api.tmprl.cloud"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert req.headers["temporal-cloud-api-version"] == "v0.26.0"
    assert TOKEN not in str(result)
    if req.method == "POST":
        body = json.loads(req.content)
        assert (
            body["spec"] == fixture["config"]["spec"] or operation == "create_namespace"
        )
        if operation.startswith("update_"):
            assert body["resourceVersion"] == "version-1"
        assert result["async_operation"]["state"] == "STATE_PENDING"
        assert "completed" not in result and "deleted" not in result
    if req.method == "DELETE":
        assert req.url.params["resourceVersion"] == "version-1" and not req.content
    if operation == "list_namespaces":
        assert dict(req.url.params) == {
            "pageSize": "25",
            "pageToken": "next + token",
            "name": "payments",
            "projectId": "project-123",
        }
        assert result["has_more"] and result["next_page_token"] == "next + token"
    if operation == "create_namespace":
        assert json.loads(req.content)["spec"] == {
            **fixture["config"]["spec"],
            "apiKeyAuth": {"enabled": True},
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.LIST_KEYS)
async def test_temporal_protobuf_empty_page_and_plural_service_account_key(
    monkeypatch, operation
):
    transport(monkeypatch, {})
    result = await node(FIXTURES[operation]["config"]).execute({})
    assert result["items"] == [] and result["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
async def test_temporal_http_errors_keep_provider_message_redact_token(
    monkeypatch, status
):
    requests = transport(monkeypatch, {"message": "provider denied " + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_current_identity"}).execute({})
    assert str(status) in str(exc.value) and "provider denied" in str(exc.value)
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,payload",
    [
        ("get_current_identity", {}),
        ("get_current_identity", {"user": {}}),
        ("get_account", {}),
        ("list_users", {"users": {}}),
        ("list_users", {"users": [1]}),
        ("list_users", {"nextPageToken": 1}),
        ("create_user", {}),
        ("create_user", {"asyncOperation": {}}),
        ("get_account", {"code": 7, "message": "denied"}),
    ],
)
async def test_temporal_incomplete_or_error_responses_fail(
    monkeypatch, operation, payload
):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node(FIXTURES[operation]["config"]).execute({})


@pytest.mark.asyncio
async def test_temporal_identity_supports_service_account_and_redacts_all_outputs(
    monkeypatch,
):
    transport(
        monkeypatch, {"serviceAccount": {"id": "service-123", "spec": {"name": TOKEN}}}
    )
    result = await node({"operation": "get_current_identity"}).execute({})
    assert result["items"] == [{"id": "service-123", "name": "[redacted]"}]
    assert TOKEN not in str(result)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_namespace", "namespace": "../bad"},
        {"operation": "get_user", "user_id": "https://example.com"},
        {"operation": "list_users", "page_size": 1001},
        {"operation": "delete_namespace", "namespace": "payments"},
        {"operation": "update_user", "user_id": "user-123"},
        {"operation": "create_service_account", "spec": {"name": "automation"}},
        {"operation": "start_workflow"},
    ],
)
def test_temporal_invalid_config_and_stale_write_guards(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_temporal_manual_credential_has_default_type_and_one_secret():
    credential = native.TemporalAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "temporal_api_key"
    for value in ["https://example.com/key", "Bearer token", "<token>"]:
        with pytest.raises(ValueError):
            native.TemporalAPIKeyCredential(api_key=value)


def test_temporal_documented_cli_role_spelling_maps_to_http_enum():
    access = native.AccountAccess(role="finance-admin")
    assert access.model_dump(exclude_none=True) == {"role": "ROLE_FINANCE_ADMIN"}
    assert native.AccountAccess(role="read").role == "ROLE_READ"


AUDIT = json.loads(
    (Path(__file__).parent / "fixtures/temporal/audit_logs.json").read_text()
)["body"]["logs"]


def poll_state(instance):
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update
    return state


@pytest.mark.asyncio
async def test_temporal_documented_audit_logs_baseline_fresh_dedup_and_agent(
    monkeypatch,
):
    # These are the provider's verbatim example records, including protobuf timestamps.
    instance = node({"operation": "on_new_audit_log"})
    state = poll_state(instance)
    requests = transport(monkeypatch, {"logs": AUDIT[:1]})
    baseline = await instance.execute({})
    assert baseline["audit_logs"] == []
    assert instance.trigger_produced_no_event(baseline)
    assert native.TemporalNode.resolve_agent_event(baseline) is None
    assert state["seen_ids"] == [AUDIT[0]["logId"]]
    request = requests[0]
    assert request.url.path == "/cloud/audit-logs" and request.method == "GET"
    assert request.headers["temporal-cloud-api-version"] == native.API_VERSION
    start = native.datetime.fromisoformat(request.url.params["startTimeInclusive"])
    end = native.datetime.fromisoformat(request.url.params["endTimeExclusive"])
    assert end - start == native.timedelta(minutes=60)
    transport(monkeypatch, {"logs": AUDIT})
    output = await instance.execute({})
    assert output["audit_logs"] == AUDIT[1:]
    assert instance.trigger_emitted_event(output)
    event = native.TemporalNode.resolve_agent_event(output)
    for text in ["user@email.com", "UserLogin", AUDIT[1]["logId"], "OK", "acceptance"]:
        assert text in event["text"]
    duplicate = await instance.execute({})
    assert duplicate["audit_logs"] == []
    assert instance.trigger_produced_no_event(duplicate)


@pytest.mark.asyncio
async def test_temporal_audit_pagination_uses_fixed_time_bounds_before_dedup(
    monkeypatch,
):
    requests = []

    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200, json={"logs": AUDIT[:1], "nextPageToken": "next + token"}
            )
        return httpx.Response(200, json={"logs": AUDIT[1:]})

    monkeypatch.setattr(
        native,
        "guarded_async_client",
        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw),
    )
    instance = node({"operation": "on_new_audit_log", "operation_filter": "UserLogin"})
    state = poll_state(instance)
    await instance.execute({})
    assert state["seen_ids"] == [row["logId"] for row in AUDIT]
    assert requests[1].url.params["pageToken"] == "next + token"
    for key in ["startTimeInclusive", "endTimeExclusive"]:
        assert requests[0].url.params[key] == requests[1].url.params[key]
    assert "operation_filter" not in requests[0].url.params


@pytest.mark.asyncio
async def test_temporal_audit_filter_and_scope_rebaseline(monkeypatch):
    from nodes.core.poll_trigger import poll_scope

    instance = node(
        {"operation": "on_new_audit_log", "operation_filter": "CreateNamespace"}
    )
    state = poll_state(instance)
    transport(monkeypatch, {"logs": AUDIT})
    await instance.execute({})
    assert state["seen_ids"] == []
    original = {"operation": "on_new_audit_log", "operation_filter": "UserLogin"}
    assert poll_scope(native.TemporalNode, original) == poll_scope(
        native.TemporalNode, {**original, "label": "New label", "webhook_id": "new-id"}
    )
    changed = {**original, "operation_filter": "CreateNamespace"}
    assert poll_scope(native.TemporalNode, original) != poll_scope(
        native.TemporalNode, changed
    )
    # A different parsed watch scope establishes its own baseline without replaying history.
    instance = node(original)

    async def update(mutator, **kwargs):
        replacement, result = mutator(dict(state))
        if replacement is not None:
            state.update(replacement)
        return result

    instance._update_node_state = update
    output = await instance.execute({})
    assert output["audit_logs"] == []
    assert state["seen_ids"] == [row["logId"] for row in AUDIT]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"logs": {}},
        {"logs": [1]},
        {"logs": [{}]},
        {"logs": [{"logId": 1}]},
        {"logs": [{"logId": ""}]},
        {"nextPageToken": 1},
    ],
)
async def test_temporal_invalid_audit_page_never_consumes_state(monkeypatch, payload):
    transport(monkeypatch, payload)
    instance = node({"operation": "on_new_audit_log"})
    state = poll_state(instance)
    with pytest.raises(ValueError, match="invalid audit log page"):
        await instance.execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_temporal_incomplete_audit_scan_never_consumes_state(monkeypatch):
    instance = node({"operation": "on_new_audit_log"})
    state = poll_state(instance)
    transport(monkeypatch, {"logs": AUDIT, "nextPageToken": "repeated"})
    with pytest.raises(ValueError, match="repeated"):
        await instance.execute({})
    assert state == {}
    counter = 0

    def reply(request):
        nonlocal counter
        counter += 1
        return httpx.Response(200, json={"logs": [], "nextPageToken": str(counter)})

    monkeypatch.setattr(
        native,
        "guarded_async_client",
        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw),
    )
    with pytest.raises(ValueError, match="20 pages"):
        await instance.execute({})
    assert counter == 20 and state == {}


def test_temporal_audit_schema_and_config():
    from nodes.core.poll_trigger import PollTriggerConfigBase

    config = native.OnNewAuditLogConfig()
    assert isinstance(config, PollTriggerConfigBase)
    assert config.schedule.frequency == "minutes"
    field = config.model_fields["operation"].json_schema_extra
    assert field["x-is-trigger"] is True
    for values in [
        {"lookback_minutes": 0},
        {"lookback_minutes": 43201},
        {"operation_filter": ""},
    ]:
        with pytest.raises(ValidationError):
            native.OnNewAuditLogConfig(**values)
