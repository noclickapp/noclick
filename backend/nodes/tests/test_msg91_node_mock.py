"""Offline MSG91 response regressions; pagination tokens in fixtures are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import msg91_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-msg91-authkey-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/msg91/documented_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credentials=None):
    return NodeFactory.create_node(node_id="msg91-fixture", node_type="automation-msg91",
        node_data={"config": config, "credentials": credentials or {"credential_type": "msg91_api_key", "authkey": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_msg91_account_evidence_reads_owned_sms_templates(monkeypatch):
    body = {"msg_type": "Success", "data": [{"flow_id": "abc123", "flow_name": "Order updates"}]}
    requests = transport(monkeypatch, body)
    result = await make_node({"operation": "list_sms_templates"}).execute({})
    assert result["data"] == body and result["status"] == "success"
    assert result["items"] == body["data"]
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url == "https://control.msg91.com/api/v5/flows"
    assert requests[0].headers["authkey"] == TOKEN
    assert native.Msg91Node.connection_evidence.operation == "list_sms_templates"


@pytest.mark.asyncio
async def test_msg91_sms_send_exact_json_no_delivery_claim(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["POST /api/v5/flow"]["body"])
    config = {"operation": "send_sms", "template_id": "abc123", "recipients": [{"mobiles": "919876543210", "VAR1": "order42"}]}
    result = await make_node(config).execute({})
    assert result["status"] == "success" and result["delivery_verified"] is False
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("op,params,path", [
    ("send_otp", {"template_id": "abc123", "mobile": "919876543210", "Param1": "Alice"}, "/api/v5/otp"),
    ("verify_otp", {"mobile": "919876543210", "otp": "123456"}, "/api/v5/otp/verify"),
    ("resend_otp", {"mobile": "919876543210", "retrytype": "text"}, "/api/v5/otp/retry"),
])
async def test_msg91_otp_documented_success_auth_placement(monkeypatch, op, params, path):
    method = "POST" if op == "send_otp" else "GET"
    requests = transport(monkeypatch, FIXTURES[method + " " + path]["body"])
    result = await make_node({"operation": op, **params}).execute({})
    assert result["status"] == "success"
    req = requests[0]
    assert req.method == method and req.url.path == path
    if op == "resend_otp":
        assert "authkey" not in req.headers and req.url.params["authkey"] == TOKEN
    else:
        assert req.headers["authkey"] == TOKEN and "authkey" not in req.url.params
    if op == "send_otp":
        assert json.loads(req.content) == {"Param1": "Alice"}
        assert dict(req.url.params) == {k: v for k, v in params.items() if k != "Param1"}
    else:
        assert all(req.url.params[k] == v for k, v in params.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"type": "error", "message": "OTP expired"},
    {"hasError": True, "errors": ["Unauthorized"]},
    {"status": "error", "errors": "Invalid template"},
    {"error": "Duration exceeds, allowed limit is 3 days"},
])
async def test_msg91_http200_rejections_are_errors(monkeypatch, body):
    transport(monkeypatch, body)
    result = await make_node({"operation": "verify_otp", "mobile": "919876543210", "otp": "123456"}).execute({})
    assert result["status"] == "error" and "delivery_verified" not in result


@pytest.mark.asyncio
async def test_msg91_redacts_credential_in_provider_rejection(monkeypatch):
    transport(monkeypatch, {"error": "Rejected " + TOKEN, "authkey": TOKEN}, 401)
    result = await make_node({"operation": "list_sms_templates"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_msg91_multipart_sms_template(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["POST /api/v5/sms/addTemplate"]["body"])
    await make_node({"operation": "create_sms_template", "template": "Hi ##name##", "sender_id": "MSGIND", "template_name": "Welcome"}).execute({})
    assert requests[0].headers["content-type"].startswith("multipart/form-data;")
    assert b'name="template"' in requests[0].content and b"Hi ##name##" in requests[0].content


@pytest.mark.asyncio
async def test_msg91_email_alias_and_paginated_list(monkeypatch):
    requests = transport(monkeypatch, FIXTURES["POST /api/v5/email/send"]["body"])
    await make_node({"operation": "send_email", "recipients": [{"to": [{"email": "a@example.com"}]}],
        "from": {"email": "b@example.com"}, "domain": "example.com", "template_id": "welcome"}).execute({})
    assert json.loads(requests[0].content)["from"] == {"email": "b@example.com"}
    requests = transport(monkeypatch, {"data": [], "current_page": 2})
    await make_node({"operation": "list_email_templates", "page": "2", "with": "versions"}).execute({})
    assert dict(requests[0].url.params) == {"page": "2", "per_page": "25", "with": "versions"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_msg91_contact_search_posts_exact_page(monkeypatch):
    requests = transport(monkeypatch, {"status": "success", "hasError": False, "data": {"data": []}})
    await make_node({"operation": "search_contacts", "phonebook_id": "abc123", "pageNo": 2, "search": "Alice"}).execute({})
    assert requests[0].url.path == "/api/v5/segmento/api/v1/phonebooks/abc123/contacts/filters"
    assert json.loads(requests[0].content) == {"pageNo": 2, "itemsPerPage": 100, "search": "Alice"}


@pytest.mark.asyncio
async def test_msg91_no_redirect_follow_or_false_connection(monkeypatch):
    requests = transport(monkeypatch, {"message": "Redirect"}, 302)
    assert (await make_node({"operation": "list_sms_templates"}).execute({}))["status"] == "error"
    assert len(requests) == 1
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="response could not be read"):
        await make_node({"operation": "list_sms_templates"}).execute({})


@pytest.mark.asyncio
async def test_msg91_rejects_path_escape_before_network(monkeypatch):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="resource ID"):
        await make_node({"operation": "get_email_template", "template_version_id": "../other"}).execute({})
    assert not requests


def test_msg91_wrong_family_and_blank_key_rejected():
    with pytest.raises(ValidationError):
        native.Msg91APIKeyCredential(credential_type="other", authkey=TOKEN)
    with pytest.raises(ValidationError):
        native.Msg91APIKeyCredential(authkey=" ")


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,kind,method,path", [
    ("sms", "logs", "POST", "/api/v5/report/logs/p/sms"),
    ("sms", "analytics", "GET", "/api/v5/report/analytics/p/sms"),
    ("otp", "logs", "GET", "/api/v5/report/logs/p/otp"),
    ("otp", "analytics", "GET", "/api/v5/report/analytics/p/otp"),
    ("email", "logs", "GET", "/api/v5/report/logs/mail"),
    ("email", "analytics", "GET", "/api/v5/report/analytics/p/mail"),
])
async def test_msg91_report_dates_and_documented_response(monkeypatch, channel, kind, method, path):
    body = FIXTURES[method + " " + path]["body"]
    requests = transport(monkeypatch, body)
    result = await make_node({"operation": f"get_{channel}_{kind}", "startDate": "2024-07-22", "endDate": "2024-07-23"}).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert requests[0].method == method and requests[0].url.path == path
    assert dict(requests[0].url.params) == {"startDate": "2024-07-22", "endDate": "2024-07-23"}
    assert not requests[0].content


@pytest.mark.asyncio
async def test_msg91_create_email_template_accepts_documented_nullable_fields(monkeypatch):
    # The provider's published success includes null fields which its OpenAPI
    # string-only response schema cannot validate. Exercise the real example too.
    body = FIXTURES["POST /api/v5/email/templates"]["body"]
    requests = transport(monkeypatch, body)
    result = await make_node({"operation": "create_email_template", "name": "Welcome Template",
        "subject": "Welcome", "body": "<p>Hello</p>"}).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert result["data"]["data"]["versions"][0]["files"] is None
    assert json.loads(requests[0].content) == {"name": "Welcome Template", "subject": "Welcome", "body": "<p>Hello</p>"}
