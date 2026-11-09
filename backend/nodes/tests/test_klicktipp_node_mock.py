"""Exercise KlickTipp's actual factory and session transport with contract examples.

These tests use synthetic credentials and local HTTP mocks; they never sign in.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import klicktipp_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/klicktipp/management_examples.json").read_text())
CASES = FIXTURE["cases"]
AUTH = {"credential_type": "klicktipp_api_user", "username": "fixture-apiuser", "password": "fixture-password-123"}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="klicktipp-fixture", node_type="automation-klicktipp",
        node_data={"config": config, "credentials": AUTH})


def transport(monkeypatch, response, *, status=200, login=None):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == "api.klicktipp.com"
        if request.url.path == "/account/login":
            assert request.method == "POST"
            assert json.loads(request.content) == {"username": AUTH["username"], "password": AUTH["password"]}
            return httpx.Response(200, json=login if login is not None else {"session_name": "SSESSabc", "sessid": "xyz123"})
        assert request.headers["Cookie"] == "SSESSabc=xyz123"
        assert AUTH["password"] not in request.content.decode()
        if request.url.path == "/account/logout":
            return httpx.Response(200, json=True)
        return httpx.Response(status, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_contract_examples_and_session_cleanup(monkeypatch, case):
    calls = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["data"] == case["response"]
    assert len(calls) == 3
    request = calls[1]
    assert (request.method, request.url.path) == (case["method"], case["path"])
    # The platform normalizes an empty optional cursor to an omitted value.
    assert dict(request.url.params) == {k: v for k, v in case["query"].items() if v != ""}
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert calls[-1].url.path == "/account/logout"
    assert "xyz123" not in str(result) and AUTH["password"] not in str(result)


@pytest.mark.asyncio
async def test_evidence_uses_account_tags(monkeypatch):
    transport(monkeypatch, {"21": "mytag", "23": "example"})
    result = await node({"operation": "list_tags"}).execute({})
    assert result["items"] == [{"id": "21", "name": "mytag"}, {"id": "23", "name": "example"}]


@pytest.mark.asyncio
async def test_rejection_is_verbatim_and_still_logs_out(monkeypatch):
    calls = transport(monkeypatch, {"error": "Access denied"}, status=403)
    with pytest.raises(ValueError, match="Access denied"):
        await node({"operation": "list_tags"}).execute({})
    assert calls[-1].url.path == "/account/logout"


@pytest.mark.asyncio
async def test_malformed_login_cannot_send_operation(monkeypatch):
    calls = transport(monkeypatch, {}, login={"session_name": "SSESSabc\r\nX", "sessid": "xyz123"})
    with pytest.raises(ValueError, match="valid session cookie"):
        await node({"operation": "list_tags"}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "subscriberid": "../tag"},
    {"operation": "create_or_update_contact"},
    {"operation": "tag_contact", "email": "wrong", "tagids": [19]},
    {"operation": "get_contacts", "subscriberids": "123,../../tag"},
    {"operation": "list_tags", "url": "https://other.example"},
])
def test_invalid_input_refused_before_transport(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_credential_can_be_filled_by_hand():
    credential = native.KlickTippCredential(username=AUTH["username"], password=AUTH["password"])
    assert credential.credential_type == "klicktipp_api_user"
    assert set(native.KlickTippCredential.model_json_schema()["required"]) == {"username", "password"}
