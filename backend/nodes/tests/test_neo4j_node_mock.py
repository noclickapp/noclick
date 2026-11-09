"""Aura v1 request contracts and provider-published response examples; no live credentials."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import neo4j_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/neo4j/contract_examples.json").read_text())
AUTH = {"credential_type": "neo4j_access_token", "access_token": "synthetic-aura-access-credential"}
CONFIGS = {
    "list_instances": {"tenant_id": "project-1"},
    "create_instance": {
        "version": "5",
        "region": "europe-west1",
        "memory": "1GB",
        "name": "Instance01",
        "type": "free-db",
        "tenant_id": "project-1",
        "cloud_provider": "gcp",
    },
    "estimate_instance_size": {
        "node_count": 1000000,
        "relationship_count": 5000000,
        "instance_type": "professional-ds",
        "algorithm_categories": ["pathfinding", "community-detection"],
    },
    "get_instance": {"instance_id": "db1d1234"},
    "delete_instance": {"instance_id": "db1d1234"},
    "update_instance": {"instance_id": "db1d1234", "name": "Instance02", "vector_optimized": False},
    "overwrite_instance": {
        "instance_id": "db1d1234",
        "source_instance_id": "191b0da2",
        "source_snapshot_id": "3e5e6e27-bf0a-4898-abb8-5f3050cac418",
    },
    "pause_instance": {"instance_id": "db1d1234"},
    "resume_instance": {"instance_id": "db1d1234"},
    "get_snapshot": {"instance_id": "db1d1234", "snapshot_id": "snapshot-1"},
    "restore_snapshot": {"instance_id": "db1d1234", "snapshot_id": "snapshot-1"},
    "list_snapshots": {"instance_id": "db1d1234", "date": "2026-11-09"},
    "create_snapshot": {"instance_id": "db1d1234"},
    "upgrade_instance": {"instance_id": "db1d1234", "memory": "16GB", "storage": "32GB"},
    "list_projects": {},
    "get_project": {"tenant_id": "project-1"},
    "list_customer_managed_keys": {"tenant_id": "project-1"},
    "create_customer_managed_key": {
        "key_id": "arn:aws:kms:us-west-2:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
        "region": "us-west-2",
        "name": "Production Key",
        "instance_type": "enterprise-db",
        "tenant_id": "project-1",
        "cloud_provider": "aws",
    },
    "get_customer_managed_key": {"customer_managed_key_id": "key-1"},
    "delete_customer_managed_key": {"customer_managed_key_id": "key-1"},
    "get_project_metrics": {"tenant_id": "project-1"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, values=None):
    return NodeFactory.create_node(
        node_id="aura-fixture",
        node_type="automation-neo4j",
        node_data={
            "config": {"operation": operation, **(CONFIGS[operation] if values is None else values)},
            "credentials": AUTH,
        },
    )


def transport(monkeypatch, *, body=None, status=200, headers=None):
    requests = []

    def respond(request):
        requests.append(request)
        if status == 204:
            return httpx.Response(status)
        return httpx.Response(status, json=body, headers=headers)

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_neo4j_all_operations_exact_contract_and_published_examples(monkeypatch, operation):
    example = EXAMPLES[operation]
    replies = example["replies"]
    status = (
        int(next(iter(replies))) if replies else 204 if operation == "delete_customer_managed_key" else 202
    )
    body = next(iter(replies.values())) if replies else {"data": {"snapshot_id": "snapshot-1"}}
    requests = transport(monkeypatch, body=body, status=status)
    result = await node(operation).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    expected_path = example["path"]
    placeholders = {
        "instance_id": "instanceId",
        "snapshot_id": "snapshotId",
        "tenant_id": "tenantId",
        "customer_managed_key_id": "customerManagedKeyId",
    }
    for key, placeholder in placeholders.items():
        if key in CONFIGS[operation]:
            expected_path = expected_path.replace("{" + placeholder + "}", CONFIGS[operation][key])
    assert str(request.url.copy_with(query=None)) == native.BASE + expected_path
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert result["http_status"] == status
    assert result["status"] == ("accepted" if status == 202 else "success")
    assert result["data"] == (None if status == 204 else body["data"])
    expected_values = dict(CONFIGS[operation])
    for key in placeholders:
        if "{" + placeholders[key] + "}" in example["path"]:
            expected_values.pop(key)
    if operation in ("list_instances", "list_customer_managed_keys"):
        assert dict(request.url.params) == {"tenantId": "project-1"}
    elif operation == "list_snapshots":
        assert dict(request.url.params) == {"date": "2026-11-09"}
    elif request.method in ("POST", "PATCH"):
        assert json.loads(request.content) == expected_values
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert not request.content and not request.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 308, 400, 401, 403, 404, 409, 429, 500])
async def test_neo4j_errors_preserve_provider_message_redact_token_never_retry(monkeypatch, status):
    requests = transport(
        monkeypatch,
        status=status,
        body={"errors": [{"message": "Rejected " + AUTH["access_token"], "reason": "auth"}]},
    )
    with pytest.raises(ValueError, match=f"HTTP {status}: Rejected \\[redacted\\]") as caught:
        await node("list_projects").execute({})
    assert AUTH["access_token"] not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": None},
        {"data": [], "error": "no"},
        {"data": {}, "errors": []},
        {"data": {"echo": AUTH["access_token"]}},
    ],
)
async def test_neo4j_malformed_or_credential_echo_response_fails(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node("list_projects").execute({})


@pytest.mark.parametrize("bad", ["..", "a/b", "a%2Fb", "a?tenantId=other", "https://example.test", "id\n"])
def test_neo4j_path_injection_fails_before_transport(bad):
    with pytest.raises(ValueError):
        node("get_instance", {"instance_id": bad})


def test_neo4j_manual_credential_default_and_typed_configs():
    assert (
        native.Neo4jTokenCredential(access_token=AUTH["access_token"]).credential_type == "neo4j_access_token"
    )
    for value in ["Bearer abc", "abc\ndef", "https://example.test/key"]:
        with pytest.raises(ValueError):
            native.Neo4jTokenCredential(access_token=value)
    for operation, values in [
        ("update_instance", {"instance_id": "db1d1234"}),
        ("create_instance", {**CONFIGS["create_instance"], "source_snapshot_id": "snap-1"}),
        ("list_projects", {"unexpected": True}),
        ("upgrade_instance", {"instance_id": "db1d1234", "memory": "16GB"}),
        ("update_instance", {"instance_id": "db1d1234", "name": " spaced "}),
        ("estimate_instance_size", {"node_count": 1, "relationship_count": 1, "instance_type": "free-db"}),
        (
            "create_customer_managed_key",
            {**CONFIGS["create_customer_managed_key"], "instance_type": "free-db"},
        ),
        ("list_snapshots", {"instance_id": "db1d1234", "date": "not-a-date"}),
    ]:
        with pytest.raises(ValueError):
            node(operation, values)
    assert set(CONFIGS) == set(native.ROUTES) == set(EXAMPLES)
