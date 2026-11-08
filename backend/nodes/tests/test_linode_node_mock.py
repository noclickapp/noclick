"""Exercise the native Linode factory against a fixture HTTP transport.

These tests check exact methods, parent paths, bodies, pagination and error
behavior without making provider requests or requiring a real token.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import linode_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "linode_personal_access_token", "access_token": "fixture-linode-token"}
CASES = json.loads((Path(__file__).parent / "fixtures/linode/operations.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.linode.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, payload = reply
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(node_type="automation-linode", operation=operation,
        arguments=config or {}, credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_linode_all_operations(transport, case):
    requests, replies = transport
    replies.append((200, case["response"]))
    result = await run(case["operation"], case["config"])
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case["method"] and request.url.path == "/v4" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    if case["operation"].startswith("list_"):
        assert result["data"] == case["response"]["data"]
        assert result["next_page"] is None
    if case["operation"] in {"boot_instance", "shutdown_instance", "reboot_instance"}:
        assert result["accepted"] is True and result["completed"] is False
    if case["method"] == "DELETE":
        assert result["deletion_acknowledged"] is True


async def test_linode_continuation_and_last_page(transport):
    requests, replies = transport
    replies.append((200, {"data": [{"id": 123}], "page": 2, "pages": 3, "results": 51}))
    result = await run("list_instances", {"page": 2, "page_size": 25})
    assert result["next_page"] == 3
    assert dict(requests[0].url.params) == {"page": "2", "page_size": "25"}
    replies.append((200, {"data": [], "page": 1, "pages": 0, "results": 0}))
    assert (await run("list_instances"))["next_page"] is None


@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
async def test_linode_provider_error_is_not_success_and_no_retry(transport, code):
    requests, replies = transport
    replies.append((code, {"errors": [{"reason": "Rejected fixture-linode-token", "field": "token"}]}))
    result = await run("get_profile")
    assert result["success"] is False and result["http_status"] == code
    assert result["message"] == "Rejected [redacted]"
    assert len(requests) == 1


async def test_linode_200_error_envelope(transport):
    _, replies = transport
    replies.append((200, {"errors": [{"reason": "Not allowed"}]}))
    assert (await run("get_profile"))["status"] == "error"


async def test_linode_transport_failure_write_is_unknown(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("fixture"))
    result = await run("create_instance", {"region": "us-east", "type": "g6-standard-2"})
    assert result["status"] == "unknown" and result["success"] is False
    assert len(requests) == 1


async def test_linode_redacts_password_and_token_from_provider_output(transport):
    _, replies = transport
    replies.append((200, {"id": 123, "root_pass": "not-shown", "nested": {"value": "fixture-root-password", "token": "fixture-linode-token"}}))
    result = await run("create_instance", {"region": "us-east", "type": "g6-standard-2", "image": "linode/debian9", "root_pass": "fixture-root-password"})
    assert "fixture-root-password" not in json.dumps(result)
    assert "fixture-linode-token" not in json.dumps(result)
    assert "root_pass" not in json.dumps(result)


@pytest.mark.parametrize("payload", [[], {"data": {}}, {"data": [], "page": "1", "pages": 1}])
async def test_linode_malformed_list_rejected(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await run("list_instances")


async def test_linode_profile_requires_identity(transport):
    _, replies = transport
    replies.append((200, {}))
    with pytest.raises(ValueError):
        await run("get_profile")


@pytest.mark.parametrize("operation,config", [
    ("get_instance", {"linode_id": -1}),
    ("get_domain", {"domain_id": "../profile"}),
    ("list_instances", {"page_size": 24}),
    ("update_instance", {"linode_id": 123}),
    ("create_instance", {"region": "us-east", "type": "g6-standard-2", "image": "linode/debian9"}),
    ("create_instance", {"region": "us-east", "type": "g6-standard-2", "label": "bad--label"}),
    ("create_record", {"domain_id": 1234, "type": "A", "target": "::1"}),
    ("create_record", {"domain_id": 1234, "type": "CNAME", "target": "example.org"}),
    ("create_record", {"domain_id": 1234, "type": "TXT", "target": "text", "priority": 1}),
    ("update_record", {"domain_id": 1234, "record_id": 123456}),
])
async def test_linode_invalid_inputs_never_reach_network(transport, operation, config):
    requests, _ = transport
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not requests


def test_linode_manual_token_default_and_shaping():
    assert node.LinodeTokenCredential(access_token="  fixture-linode-token  ").access_token == "fixture-linode-token"
    assert node.LinodeTokenCredential.model_fields["credential_type"].default == AUTH["credential_type"]
    for token in ("https://cloud.linode.com", "Bearer token", "<token>", "bad\ntoken"):
        with pytest.raises(ValueError):
            node.LinodeTokenCredential(access_token=token)


async def test_linode_connection_evidence_names_the_current_user(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append((200, {"username": "exampleUser", "email": "example-user@gmail.com"}))
    evidence = await collect_evidence(node_type="automation-linode",
        credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001", pool=None)
    assert evidence.reachable is True
    assert evidence.account_label == "exampleUser"
