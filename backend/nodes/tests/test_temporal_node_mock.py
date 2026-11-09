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
