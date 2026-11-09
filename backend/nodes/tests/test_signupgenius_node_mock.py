"""Offline key-based v2 request, envelope and credential regressions.

Fixtures are synthetic, shaped from the provider's published Swagger models.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import signupgenius_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-key+/with=encoding"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/signupgenius/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="signupgenius-test", node_type="automation-signupgenius",
                                   node_data={"config": config, "credentials": {"user_key": KEY}})


def transport(monkeypatch, payload, status=200):
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(status, json=payload)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


CASES = [
    ({"operation": "list_groups", "sort": "desc"}, "GET", "/groups/", "groups"),
    ({"operation": "list_group_members", "group_id": 42, "sort": "asc"}, "GET", "/groups/42/members/", "members"),
    ({"operation": "get_group_member", "group_id": 42, "member_id": 7}, "GET", "/groups/42/members/7/details/", "member"),
    ({"operation": "add_group_member", "group_id": 42, "emailaddress": "ada@example.com", "firstname": "Ada"}, "POST", "/groups/42/members/create/", "write"),
    ({"operation": "list_active_signups"}, "GET", "/signups/created/active/", "signups"),
    ({"operation": "list_all_signups"}, "GET", "/signups/created/all/", "signups"),
    ({"operation": "list_expired_signups"}, "GET", "/signups/created/expired/", "signups"),
    ({"operation": "list_invited_signups"}, "GET", "/signups/invited/active/", "signups"),
    ({"operation": "list_joined_signups"}, "GET", "/signups/signedupfor/active/", "signups"),
    ({"operation": "get_signup_report", "signup_id": 93}, "GET", "/signups/report/all/93/", "report"),
    ({"operation": "get_available_slots_report", "signup_id": 93}, "GET", "/signups/report/available/93/", "report"),
    ({"operation": "get_filled_slots_report", "signup_id": 93}, "GET", "/signups/report/filled/93/", "report"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,fixture", CASES)
async def test_native_requests_match_published_contract(monkeypatch, config, method, path, fixture):
    calls = transport(monkeypatch, FIXTURES[fixture])
    result = await node(config).execute({})
    assert result["success"] is True and result["data"] == FIXTURES[fixture]["data"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.host == "api.signupgenius.com"
    assert request.url.path == "/v2/k" + path
    assert dict(request.url.params) == {"user_key": KEY, **({"sort": config["sort"]} if "sort" in config else {})}
    if method == "POST":
        assert json.loads(request.content) == {"emailaddress": "ada@example.com", "firstname": "Ada"}
        assert request.headers["content-type"] == "application/json"
    else:
        assert not request.content
    assert KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [
    (200, {"success": False, "message": ["Invalid API key"], "data": {}}),
    (403, "Invalid API key"),
    (400, {"message": ["Email address is required"]}),
])
async def test_provider_rejections_cannot_prove_connection(monkeypatch, status, payload):
    transport(monkeypatch, payload, status)
    result = await node({"operation": "list_groups"}).execute({})
    assert result["status"] == "error" and result["success"] is False
    assert result["http_status"] == status
    assert result["message"] in {"Invalid API key", "Email address is required"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"success": True}, {"success": "true", "data": []}, {"success": True, "data": {}}])
async def test_unexpected_envelopes_do_not_report_success(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="unexpected"):
        await node({"operation": "list_groups"}).execute({})


@pytest.mark.asyncio
async def test_key_is_redacted_and_provider_links_are_not_followed(monkeypatch):
    payload = {"success": True, "data": [{"title": KEY, "nested": {"user_key": KEY, "url": "https://example.com/?user_key=" + native.quote(KEY, safe="")}}], "message": [], "links": {"next": "https://evil.example/?user_key=" + KEY}}
    calls = transport(monkeypatch, payload)
    result = await node({"operation": "list_groups"}).execute({})
    assert len(calls) == 1 and "links" not in result
    assert KEY not in str(result) and native.quote(KEY, safe="") not in str(result)
    assert "user_key" not in result["data"][0]["nested"]


@pytest.mark.asyncio
async def test_report_accepts_absent_optional_custom_questions(monkeypatch):
    transport(monkeypatch, FIXTURES["report"])
    result = await node({"operation": "get_signup_report", "signup_id": 93}).execute({})
    assert result["data"]["signups"][0]["myqty"] == 1


def test_manual_credential_default_and_shaping():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential(native.CREDENTIAL_TYPE, {"user_key": " " + KEY + " "})
    assert not errors and resolved is not None
    assert shaped["user_key"] == KEY
    assert native.SignUpGeniusAPIKeyCredential.model_validate(shaped).credential_type == native.CREDENTIAL_TYPE


@pytest.mark.parametrize("config", [
    {"operation": "get_group_member", "group_id": "../users", "member_id": 7},
    {"operation": "list_group_members", "group_id": 0},
    {"operation": "get_signup_report", "signup_id": 2147483648},
    {"operation": "add_group_member", "group_id": 42, "emailaddress": "invalid"},
])
def test_invalid_required_inputs_are_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.asyncio
async def test_plain_text_authentication_rejection_is_preserved(monkeypatch):
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(403, text="API key rejected: " + KEY)

    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs))
    result = await node({"operation": "list_groups"}).execute({})
    assert len(calls) == 1 and result["http_status"] == 403
    assert result["success"] is False and result["message"] == "API key rejected: [redacted]"
