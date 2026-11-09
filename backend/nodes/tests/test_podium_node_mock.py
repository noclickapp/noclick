"""Replay provider-authored Postman responses through real HTTP construction."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.podium_node import PodiumNode, PodiumNodeConfig, PodiumOAuthCredential
from nodes.podium_operations import OPERATIONS
from nodes.scopes.podium import PODIUM_SCOPES

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/podium/postman_examples.json").read_text()
)
REAL_CLIENT = httpx.AsyncClient
CREDENTIAL = {"credential_type": "podium_oauth", "access_token": "test-access"}


def config_for(operation):
    req = EXAMPLES[operation]["request"]
    config = {"operation": operation}
    if "body" in req:
        config.update(json.loads(req["body"]["raw"]))
    if "{uid}" in OPERATIONS[operation]["path"]:
        config["uid"] = req["url"]["variable"][0]["value"]
    if operation == "get_invoice":
        config["locationUid"] = "00000000-0000-0000-0000-000000000000"
    if operation == "create_appointment":
        config.pop("durationMin")  # The saved synthetic duration is negative.
    return config


def node_for(operation, **overrides):
    config = PodiumNodeConfig.model_validate(
        {"config": {**config_for(operation), **overrides}, "credentials": CREDENTIAL}
    )
    return PodiumNode(
        node_id="podium-test",
        node_type="automation-podium",
        node_data={},
        config=config,
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("example_index", [0, 1])
async def test_podium_saved_examples(monkeypatch, operation, example_index):
    saved = EXAMPLES[operation]["response"][example_index]
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            saved["code"],
            content=saved["body"],
            headers=[(h["key"], h["value"]) for h in saved["header"]],
        )

    monkeypatch.setattr(
        "nodes.podium_node.httpx.AsyncClient",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handle), **kw),
    )
    result = await node_for(operation).execute({})
    assert len(seen) == 1
    request = seen[0]
    expected = EXAMPLES[operation]["request"]
    url = expected["url"]
    raw = url if isinstance(url, str) else url["raw"]
    if isinstance(url, dict):
        for v in url.get("variable", []):
            raw = raw.replace(":" + v["key"], v["value"])
    assert request.method == expected["method"]
    assert (
        str(request.url).split("?")[0]
        == raw.replace("{{baseUrl}}", "https://api.podium.com").split("?")[0]
    )
    assert request.headers["authorization"] == "Bearer test-access"
    assert request.headers["accept"] == "application/json"
    if "body" in expected:
        body = json.loads(expected["body"]["raw"])
        if operation == "create_appointment":
            body.pop("durationMin")
        assert json.loads(request.content) == body
    else:
        assert request.content == b""
    if saved["code"] < 300:
        payload = json.loads(saved["body"])
        assert result["status"] == "success"
        assert result["data"] == payload["data"]
        assert result["metadata"] == payload["metadata"]
    else:
        assert result["status"] == "error"
        assert result["http_status"] == saved["code"]
        assert result["error"] == saved["body"]


@pytest.mark.asyncio
async def test_podium_cursor_preserves_page(monkeypatch):
    saved = EXAMPLES["list_locations"]["response"][0]
    payload = json.loads(saved["body"])
    cursor = payload["metadata"]["nextCursor"]

    def handle(request):
        assert dict(request.url.params) == {"cursor": cursor}
        return httpx.Response(saved["code"], content=saved["body"])

    monkeypatch.setattr(
        "nodes.podium_node.httpx.AsyncClient",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handle), **kw),
    )
    result = await node_for(
        "list_locations", cursor=cursor, search="Podium", limit=10
    ).execute({})
    assert result["metadata"] == payload["metadata"]


@pytest.mark.asyncio
async def test_podium_timeout_never_retries_write(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    monkeypatch.setattr(
        "nodes.podium_node.httpx.AsyncClient",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handle), **kw),
    )
    with pytest.raises(httpx.ReadTimeout):
        await node_for("send_message").execute({})
    assert len(calls) == 1


def test_podium_manual_credential_and_scope_coverage():
    assert (
        PodiumOAuthCredential(access_token="test-access").credential_type
        == "podium_oauth"
    )
    assert set(PODIUM_SCOPES) == set(OPERATIONS)
    assert "read_locations" in PODIUM_SCOPES.declared_scopes()
    assert PodiumNode.connection_evidence.operation == "list_locations"


@pytest.mark.parametrize(
    "operation,override",
    [
        ("send_message", {"channel": {"identifier": "x", "type": "fax"}}),
        ("create_invoice", {"lineItems": []}),
        ("get_invoice", {"uid": "../users"}),
        ("update_conversation", {"assignedUserUid": None, "closed": None}),
        ("create_review_invite", {"email": None, "phoneNumber": None}),
        ("create_appointment", {"durationMin": -1}),
    ],
)
def test_podium_invalid_inputs(operation, override):
    with pytest.raises(ValidationError):
        node_for(operation, **override)


@pytest.mark.asyncio
async def test_podium_refresh_uses_shared_seam(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes.oauth.podium_oauth import refresh_access_token

    calls = []

    async def freshen(data, **kwargs):
        calls.append(kwargs)
        return data

    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    result = await PodiumNode.freshen_credential(
        CREDENTIAL.copy(), user_id="user", credential_id="credential"
    )
    assert result == CREDENTIAL
    assert calls[0]["provider"] == "podium"
    assert calls[0]["refresh"] is refresh_access_token
    assert calls[0]["credential_id"] == "credential"
    assert calls[0]["is_expired"](None) is True
    assert calls[0]["is_expired"]("2099-01-01T00:00:00+00:00") is False
