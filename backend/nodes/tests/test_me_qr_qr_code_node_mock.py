"""Synthetic request tests for all ME-QR operations; no provider account used."""
import json
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import me_qr_qr_code_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-meqr-token"
CREDS = {"credential_type": "me_qr_qr_code_api_token", "api_token": TOKEN}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="test", node_type="automation-me-qr-qr-code", node_data={"config": config, "credentials": CREDS})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(r):
        requests.append(r)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

DATA = {"link": {"link": "https://example.com"}, "text": {"text": "Hello"},
    "email": {"emailTo": "person@example.com", "subject": "Hi", "body": "Contact us"},
    "wifi": {"ssid": "Guest", "encryption": "wpa/wpa2", "password": "guest-pass"}}

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", DATA)
@pytest.mark.parametrize("action,method", [("create", "POST"), ("update", "PUT"), ("get", "GET")])
async def test_qr_requests(monkeypatch, kind, action, method):
    config = {"operation": f"{action}_{kind}_qr"}
    if action != "get":
        config.update(qr_fields_data=DATA[kind], title="Campaign", folder_options={"folderName": "Sales"})
    if action != "create":
        config["entry_uid"] = "some-unique-key"
    requests = transport(monkeypatch, {"id": 123})
    assert (await node(config).execute({}))["data"]["id"] == 123
    r = requests[0]
    suffix = "create" if action == "create" else "update/some-unique-key" if action == "update" else "some-unique-key"
    assert r.method == method and r.url.path == f"/api/v2/qr/{kind}/{suffix}"
    assert r.url.host == "me-qr.com" and r.headers["X-AUTH-TOKEN"] == TOKEN and len(requests) == 1
    if action != "get":
        assert json.loads(r.content) == {"qrFieldsData": DATA[kind], "title": "Campaign", "format": "json", "qrFolderOptions": {"folderName": "Sales"}}
    else:
        assert not r.content and not r.url.params

@pytest.mark.asyncio
@pytest.mark.parametrize("action,method", [("create", "POST"), ("update", "PUT"), ("get", "GET")])
async def test_short_links(monkeypatch, action, method):
    config = {"operation": action + "_short_link"}
    if action != "get":
        config.update(link="https://example.com", folder_options={"folderName": "Sales"})
    if action != "create":
        config["entry_uid"] = "123"
    requests = transport(monkeypatch, {"id": 123, "url": "https://me-qr.com/l/abc"})
    assert (await node(config).execute({}))["status"] == "success"
    suffix = "create" if action == "create" else "update/123" if action == "update" else "123"
    assert requests[0].method == method and requests[0].url.path == "/api/v2/short-link/" + suffix
    if action != "get":
        assert json.loads(requests[0].content) == {"link": "https://example.com", "title": "Qr Code", "folderOptions": {"folderName": "Sales"}}

@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body", [
    ({"operation": "list_qr_codes", "page": 2, "limit": 20}, "/api/qr/list/", None),
    ({"operation": "list_scan_events", "qr_uid": "123", "date_from": "2026-01-01", "date_to": "2027-01-01", "return_shared_qrs": False}, "/api/v2/qr/statistic", None),
    ({"operation": "list_folders"}, "/api/v2/user/folders", None),
    ({"operation": "create_folder", "folder_name": "Sales", "subfolder_name": "Leads"}, "/api/v2/user/folder/create", {"folderName": "Sales", "subfolderName": "Leads"}),
    ({"operation": "get_analytics", "entry_uid": "123"}, "/api/v2/qr/123/analytics", None),
    ({"operation": "delete_entries", "ids": ["123", "some-unique-key"]}, "/api/v2/qr/delete", {"ids": ["123", "some-unique-key"]}),
])
async def test_account_operations(monkeypatch, config, path, body):
    requests = transport(monkeypatch, [] if config["operation"] == "list_folders" else {"items": []})
    assert (await node(config).execute({}))["status"] == "success"
    r = requests[0]
    assert len(requests) == 1 and r.url.path == path and r.method == ("POST" if body else "GET")
    if body:
        assert json.loads(r.content) == body
    if config["operation"] == "list_scan_events":
        assert dict(r.url.params) == {"qrUID": "123", "dateFrom": "2026-01-01", "dateTo": "2027-01-01", "returnSharedQrs": "false", "page": "1", "limit": "50"}
    if config["operation"] == "list_qr_codes":
        assert dict(r.url.params) == {"page": "2", "limit": "20"}

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_error_status_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"message": TOKEN}, status)
    result = await node({"operation": "list_folders"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1

@pytest.mark.asyncio
async def test_error_envelope_and_evidence_shape(monkeypatch):
    transport(monkeypatch, {"error": "Denied"})
    assert (await node({"operation": "list_folders"}).execute({}))["status"] == "error"
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="folder array"):
        await node({"operation": "list_folders"}).execute({})


def test_validation_and_connect_default():
    assert native.MEQRCredential(api_token="a-real-token").credential_type == "me_qr_qr_code_api_token"
    for config in [{"operation": "get_link_qr", "entry_uid": "../folders"}, {"operation": "delete_entries", "ids": []}, {"operation": "list_scan_events", "limit": 1001}]:
        with pytest.raises(ConfigValidationError):
            native.MEQRQRCodeNode.parse_config({"config": config, "credentials": CREDS})
