"""Offline boundary tests for the NetHunt CRM v2 contract; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import nethunt_crm_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/nethunt-crm/requests.json").read_text())
TOKEN = "synthetic-nethunt-test-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="nethunt-fixture", node_type="automation-nethunt-crm",
        node_data={"config":config,"credentials":{"credential_type":"nethunt_crm_api_token","api_token":TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native,"guarded_async_client",client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c:c["operation"])
async def test_nethunt_crm_documented_request_and_response(monkeypatch, case):
    response = httpx.Response(204) if case["response"] is None else httpx.Response(201 if case["operation"] in {"create_record","add_comment","log_call"} else 200,json=case["response"])
    requests = transport(monkeypatch,response)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "nethunt.com" and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if case["body"] is not None:
        assert json.loads(request.content) == case["body"]
    else:
        assert not request.content
    if case["response"] is not None:
        assert result["data"] == case["response"]
    else:
        assert result["deleted_id"] == case["config"]["record_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status",[400,401,403,404,409,429,500,302])
async def test_nethunt_crm_rejections_are_not_success(monkeypatch,status):
    transport(monkeypatch,httpx.Response(status,json={"error":"REJECTED","message":"Rejected "+TOKEN}))
    result = await node({"operation":"list_folders"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("response",[httpx.Response(200,text="<html>Sign in</html>"),httpx.Response(200,json={"folders":[]})])
async def test_nethunt_crm_unexpected_response_is_not_evidence(monkeypatch,response):
    transport(monkeypatch,response)
    with pytest.raises(ValueError):
        await node({"operation":"list_folders"}).execute({})


@pytest.mark.parametrize("identifier",["..",".","a/b","a?b","a#b","a\\b"])
def test_nethunt_crm_resource_ids_cannot_change_route(identifier):
    with pytest.raises(ValueError):
        native.request_parts(native.GetFolder(folder_id=identifier))


def test_nethunt_crm_sort_and_page_bounds():
    with pytest.raises(ValidationError):
        native.FilterRecords(folder_id="folder",sort=[{"name":1,"created":-1}])
    with pytest.raises(ValidationError):
        native.SearchRecords(folder_id="folder",text="acme",limit=101)
    with pytest.raises(ValidationError):
        native.ListFolderTimeline(folder_id="folder",limit=0)


def test_nethunt_crm_connection_evidence_is_credential_only_read():
    assert native.NetHuntCrmNode.connection_evidence.operation == "list_folders"
    assert native.request_parts(native.ListFolders()) == ("GET","/api/v2/folders",{},None)


@pytest.mark.parametrize("token",["https://nethunt.com/api/docs","<your-token>","Bearer secret", "curly–token", "   "])
def test_nethunt_crm_invalid_pasted_token(token):
    with pytest.raises(ValidationError):
        native.NetHuntTokenCredential(api_token=token)
