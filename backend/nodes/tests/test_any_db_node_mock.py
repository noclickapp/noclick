"""AnyDB requests checked against independently specified Ext API wire cases."""
import json
from contextlib import asynccontextmanager
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import any_db_node as native

CREDENTIAL = {"credential_type": "any_db_api_key", "api_key": "anydb-test-secret-value", "email": "user@example.com"}
SCOPE = {"teamid": "team-1", "adbid": "db-1"}
RECORD = {**SCOPE, "adoid": "record-1"}
CASES = [
    ("check_connection", {}, "POST", "checkauth", None),
    ("list_teams", {}, "GET", "listteams", {}),
    ("list_databases", {"teamid": "team-1"}, "GET", "listdbsforteam", {"teamid": "team-1"}),
    ("get_record", RECORD, "GET", "record", RECORD),
    ("list_records", SCOPE, "GET", "list", {**SCOPE, "pagesize": 50}),
    ("search_records", {**SCOPE, "search": "John + Jane"}, "GET", "search", {**SCOPE, "search": "John + Jane", "start": 0, "limit": 50}),
    ("create_record", {**SCOPE, "name": "New Record", "content": [{"key": "firstName", "value": "John"}]}, "POST", "createrecord", {**SCOPE, "name": "New Record", "content": [{"key": "firstName", "value": "John"}]}),
    ("update_record", {"meta": {**RECORD, "icon": "person", "locked": False}, "content": []}, "PUT", "updaterecord", {"meta": {**RECORD, "icon": "person", "locked": False}, "content": []}),
    ("get_upload_url", {**RECORD, "filename": "a + b.pdf", "filesize": 0, "import_media": False}, "GET", "getuploadurl", {**RECORD, "filename": "a + b.pdf", "filesize": 0, "import_media": False}),
    ("complete_upload", {**SCOPE, "filesize": 0}, "PUT", "completeupload", {**SCOPE, "filesize": 0}),
    ("get_download_url", {**RECORD, "cellpos": "A1"}, "GET", "download", {**RECORD, "cellpos": "A1", "preview": False, "redirect": False}),
    ("remove_record", {**RECORD, "removefromids": ["parent-1"]}, "DELETE", "remove", {**RECORD, "removefromids": ["parent-1"]}),
    ("copy_record", RECORD, "POST", "copyrecord", {**RECORD, "attachmentsmode": "noattachments"}),
    ("create_share", {**RECORD, "withattachments": "false"}, "PUT", "share", {**RECORD, "withattachments": "false", "role": "viewer"}),
    ("delete_share", {"teamid": "team-1", "shareid": "share-1"}, "DELETE", "share/share-1", {"teamid": "team-1", "sharetype": "item"}),
    ("register_webhook", {"teamid": "team-1", "url": "https://example.com/anydb-webhook", "name": "My AnyDB Webhook"}, "POST", "register", {"teamid": "team-1", "url": "https://example.com/anydb-webhook", "name": "My AnyDB Webhook"}),
    ("subscribe_webhook", {"webhookId": "hook-1", "event": "RECORD_CREATE"}, "POST", "subscribe", {"webhookId": "hook-1", "event": "RECORD_CREATE"}),
    ("unsubscribe_webhook", {"webhookId": "hook-1", "event": "RECORD_UPDATE"}, "DELETE", "unsubscribe", {"webhookId": "hook-1", "event": "RECORD_UPDATE"}),
    ("update_webhook", {"webhookId": "hook-1", "timeout": 1000}, "PUT", "hook-1", {"timeout": 1000}),
    ("delete_webhook", {"webhookId": "hook-1"}, "DELETE", "hook-1", None),
]


def make_node(operation, config):
    return native.AnyDbNode(node_id="test", node_type="automation-any-db", node_data={}, sio=Mock(),
        config=native.AnyDbConfig.model_validate({"config": {"operation": operation, **config}, "credentials": CREDENTIAL}))


def transport(monkeypatch, body, status=200):
    seen = []
    def reply(request):
        seen.append(request)
        return httpx.Response(status, json=body)
    @asynccontextmanager
    async def guarded(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs) as client:
            yield client
    monkeypatch.setattr(native, "guarded_async_client", guarded)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,fields", CASES)
async def test_any_db_single_published_request(monkeypatch, operation, config, method, path, fields):
    seen = transport(monkeypatch, {"success": True, "result": {"items": [], "hasmore": False}})
    output = await make_node(operation, config).execute({})
    assert output["status"] == "success" and len(seen) == 1
    request = seen[0]
    assert request.method == method and request.url.path == "/api/integrations/ext/" + path
    assert request.url.host == "app.anydb.com"
    assert request.headers["x-anydb-api-key"] == CREDENTIAL["api_key"]
    assert request.headers["x-anydb-email"] == CREDENTIAL["email"]
    if method == "GET" or operation == "delete_share":
        assert dict(request.url.params) == {k: str(v).lower() if type(v) is bool else str(v) for k, v in fields.items()}
        assert not request.content
    else:
        assert not request.url.query
        assert (json.loads(request.content) if request.content else None) == fields
    assert CREDENTIAL["api_key"] not in str(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"reason": "Wrong API key"}), (403, {"error": "Not permitted"}), (429, {"message": "Try later"}), (500, {}), (302, {}), (200, {"success": False, "reason": "Invalid account"}), (200, {"ok": False})])
async def test_any_db_refusals_are_errors_without_retry(monkeypatch, status, body):
    seen = transport(monkeypatch, body, status)
    output = await make_node("list_teams", {}).execute({})
    assert output["status"] == "error" and len(seen) == 1 and output["http_status"] == status
    if "reason" in body:
        assert output["error"] == body["reason"]


@pytest.mark.asyncio
async def test_any_db_preserves_result_continuation_and_redacts_key(monkeypatch):
    body = {"result": {"items": [{"name": "Sample"}], "hasmore": True, "lastmarker": "opaque+marker"}, "message": CREDENTIAL["api_key"]}
    transport(monkeypatch, body, 201)
    output = await make_node("list_records", {**SCOPE, "lastmarker": "previous+marker"}).execute({})
    assert output["data"]["result"] == body["result"] and CREDENTIAL["api_key"] not in str(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["../listteams", "listteams?x=y", "%2e%2e", ".."])
async def test_any_db_path_values_cannot_change_route(monkeypatch, value):
    seen = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await make_node("delete_webhook", {"webhookId": value}).execute({})
    assert seen == []


@pytest.mark.parametrize("credential", [{**CREDENTIAL, "email": "not-email"}, {**CREDENTIAL, "api_key": "https://example.com/key"}, {**CREDENTIAL, "api_key": "key\r\ninjection"}])
def test_any_db_invalid_credentials(credential):
    with pytest.raises(ValidationError):
        native.AnyDbCredential.model_validate(credential)


def test_any_db_required_update_meta_and_icon_are_not_dropped():
    with pytest.raises(ValidationError):
        make_node("update_record", {"meta": RECORD})


def test_any_db_evidence_is_account_specific_and_needs_no_config():
    assert native.AnyDbNode.connection_evidence.operation == "list_teams"
    assert make_node("list_teams", {}).config.config.operation == "list_teams"


@pytest.mark.asyncio
async def test_any_db_rejects_unexpected_response_shape(monkeypatch):
    transport(monkeypatch, ["not a Result wrapper"])
    with pytest.raises(ValueError, match="Result object"):
        await make_node("list_teams", {}).execute({})
