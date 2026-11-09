"""Exercise the native node against Glide's published v2 request/response shapes."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import glide_apps_node as glide
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "glide_apps_api_token", "api_token": "fixture-glide-token"}
ROW = {"fullName": "Alex Bard", "invoiceDate": "2024-07-29T14:04:15.561Z", "totalAmount": 34.5, "amountPaid": 0}
ROWS = json.dumps([ROW])
TABLE = "2a1bad8b-cf7c-44437-b8c1-e3782df6"
RID = "zcJWnyI8Tbam21V34K8MNA"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.glideapps.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body, *headers = reply
        return httpx.Response(status, json=body, headers=headers[0] if headers else {})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(glide, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **config):
    node = NodeFactory.create_node(node_id="glide-test", node_type="automation-glide-apps",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})
    return await node.execute({})


CASES = [
    ("list_tables", {}, "GET", "/tables", None, 200, {"data": [{"id": TABLE, "name": "Invoices"}]}),
    ("list_rows", {"table_id": TABLE}, "GET", f"/tables/{TABLE}/rows", None, 200, {"data": [ROW], "continuation": "next-page"}),
    ("get_row", {"table_id": TABLE, "row_id": RID}, "GET", f"/tables/{TABLE}/rows/{RID}", None, 200, {"data": ROW}),
    ("create_table", {"name": "Invoices", "rows_json": ROWS}, "POST", "/tables", {"name": "Invoices", "rows": [ROW]}, 201, {"data": {"tableID": TABLE, "rowIDs": [RID]}}),
    ("import_table", {"from_url": "https://example.com/invoices.csv"}, "POST", "/tables/import", {"fromUrl": "https://example.com/invoices.csv"}, 201, {"data": [{"tableID": TABLE, "rowIDs": [RID]}]}),
    ("replace_table", {"table_id": TABLE, "rows_json": ROWS}, "PUT", f"/tables/{TABLE}", {"rows": [ROW]}, 200, {"data": {"rowIDs": [RID]}}),
    ("add_rows", {"table_id": TABLE, "rows_json": ROWS}, "POST", f"/tables/{TABLE}/rows", [ROW], 201, {"data": {"rowIDs": [RID]}}),
    ("update_row", {"table_id": TABLE, "row_id": RID, "values_json": json.dumps(ROW)}, "PATCH", f"/tables/{TABLE}/rows/{RID}", ROW, 200, {}),
    ("delete_row", {"table_id": TABLE, "row_id": RID}, "DELETE", f"/tables/{TABLE}/rows/{RID}", None, 200, {}),
    ("get_job", {"job_id": "job-123"}, "GET", "/jobs/job-123", None, 200, {"data": {"status": "running"}}),
    ("set_stash_chunk", {"stash_id": "20240215-job32", "serial": "1", "rows_json": ROWS}, "PUT", "/stashes/20240215-job32/1", [ROW], 200, {}),
    ("delete_stash", {"stash_id": "20240215-job32"}, "DELETE", "/stashes/20240215-job32", None, 200, {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body,status,response", CASES, ids=[c[0] for c in CASES])
async def test_glide_apps_contract(transport, operation, config, method, path, body, status, response):
    requests, replies = transport
    replies.append((status, response))
    result = await run(operation, **config)
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "list_rows":
        assert result["continuation"] == "next-page"
        assert request.url.params["limit"] == "100"
    if operation in {"create_table", "import_table", "replace_table", "add_rows", "update_row"}:
        assert request.url.params["onSchemaError"] == "abort"


@pytest.mark.asyncio
async def test_glide_apps_optional_parameters_and_version(transport):
    requests, replies = transport
    replies.append((200, {}, {"etag": '"24"'}))
    result = await run("update_row", table_id=TABLE, row_id=RID, values_json='{"amountPaid":34.5}',
        if_match='"23"', on_schema_error="updateSchema")
    assert result["etag"] == '"24"'
    assert requests[0].headers["if-match"] == '"23"'
    assert requests[0].url.params["onSchemaError"] == "updateSchema"
    assert json.loads(requests[0].content) == {"amountPaid": 34.5}
    replies.append((200, {"data": []}))
    await run("list_rows", table_id=TABLE, limit=25, continuation="opaque+/=&token")
    assert dict(requests[1].url.params) == {"limit": "25", "continuation": "opaque+/=&token"}


@pytest.mark.asyncio
async def test_glide_apps_async_job_and_columns(transport):
    requests, replies = transport
    replies.append((202, {"data": {"tableID": TABLE, "jobID": "job-123"}}))
    result = await run("create_table", name="Invoices", rows_json=ROWS, asynchronous=True,
        apps_to_link=["mT91fPcZCWigkZXgSZGJ"], columns=[{"id": "fullName", "type": "string", "displayName": "Full Name"}])
    assert result["completed"] is False
    assert result["status"] == "pending"
    assert requests[0].headers["x-glide-asynchronous"] == "true"
    body = json.loads(requests[0].content)
    assert body["schema"] == {"columns": [{"id": "fullName", "type": "string", "displayName": "Full Name"}]}
    assert body["appsToLink"] == ["mT91fPcZCWigkZXgSZGJ"]
    replies.append((200, {"data": {"status": "failed", "error": {"message": "Invalid data"}}}))
    result = await run("get_job", job_id="job-123")
    assert result["status"] == "error" and result["completed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 412, 429, 500])
async def test_glide_apps_rejection_never_retried(transport, code):
    requests, replies = transport
    replies.append((code, {"error": {"type": "rejected", "message": "Provider rejection " + AUTH["api_token"]}}))
    result = await run("delete_row", table_id=TABLE, row_id=RID)
    assert result["status"] == "error" and result["http_status"] == code
    assert result["message"] == "Provider rejection [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_glide_apps_ambiguous_write(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("not confirmed"))
    result = await run("add_rows", table_id=TABLE, rows_json=ROWS)
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified"
    assert len(requests) == 1
    replies.append((200, {"unexpected": "shape"}))
    assert (await run("get_row", table_id=TABLE, row_id=RID))["status"] == "error"


@pytest.mark.parametrize("model,config", [
    (glide.AddRows, {"table_id": TABLE, "rows_json": '{}'}),
    (glide.AddRows, {"table_id": "../../other", "rows_json": '[]'}),
    (glide.AddRows, {"table_id": TABLE, "rows_json": '[NaN]'}),
    (glide.UpdateRow, {"table_id": TABLE, "row_id": RID, "values_json": '[]'}),
    (glide.ReplaceTable, {"table_id": TABLE, "rows_json": '[]', "if_match": "23"}),
    (glide.SetStashChunk, {"stash_id": "a/b", "serial": "1", "rows_json": '[]'}),
])
def test_glide_apps_invalid_config(model, config):
    with pytest.raises(ValueError):
        model.model_validate(config)


def test_glide_apps_manual_credential():
    credential = glide.GlideAPITokenCredential.model_validate({"api_token": " valid-token "})
    assert credential.credential_type == "glide_apps_api_token"
    assert credential.api_token == "valid-token"
    for token in ["Bearer secret", "https://example.com/token", "<token>", "line\nbreak"]:
        with pytest.raises(ValueError):
            glide.GlideAPITokenCredential(api_token=token)
