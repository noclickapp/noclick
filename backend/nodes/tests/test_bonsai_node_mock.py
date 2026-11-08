"""Bonsai HTTP-boundary regressions. All credentials and records are synthetic."""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError
from nodes import bonsai_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/bonsai/requests.json").read_text())
TOKEN = "bonsai_at_synthetic_test_key"
CREDENTIAL = {"credential_type": "bonsai_api_key", "api_key": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credentials=None):
    return NodeFactory.create_node(node_id="bonsai-fixture", node_type="automation-bonsai",
        node_data={"config": config, "credentials": credentials or CREDENTIAL})


def envelope(operation, *, has_more=False, page=1):
    data = {"id": 42, "name": "Acme Corp"}
    meta = {"request_id": "b1f0d2c4-7a9e-4c3b-8d5f-1e2a3b4c5d6e"}
    if operation.startswith("list_"):
        data = [data]
        meta["pagination"] = {"page": page, "page_size": 25, "has_more": has_more}
    return {"data": data, "meta": meta}


def mock_http(monkeypatch, body, status=200):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://example.invalid"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CASES))
async def test_each_operation_exact_provider_route_and_wrapper(monkeypatch, operation):
    case = CASES[operation]
    calls = mock_http(monkeypatch, envelope(operation), 201 if case["method"] == "POST" else 200)
    output = await make_node(case["config"]).execute({})
    assert output["status"] == "success"
    request, = calls
    assert request.method == case["method"]
    path = case["path"]
    for name, value in case["config"].items():
        if name.endswith('_id') or name in ('task_uuid', 'time_entry_key'):
            path = path.replace('{id}', str(value)).replace('{uuid}', str(value)).replace('{key}', quote(str(value), safe=''))
    assert request.url.path == path and request.url.host == "app.hellobonsai.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if request.method in {"POST", "PATCH"}:
        wrapper = {'companies':'company', 'contacts':'contact', 'deals':'deal', 'projects':'project', 'tasks':'task', 'invoices':'invoice', 'time_entries':'time_entry'}[path.split('/')[3]]
        body = json.loads(request.content)
        assert list(body) == [wrapper]
        assert "operation" not in body[wrapper]
        assert body[wrapper]
    else:
        assert not request.content
    assert TOKEN not in str(output)


@pytest.mark.asyncio
async def test_pagination_filters_and_empty_account_evidence(monkeypatch):
    calls = mock_http(monkeypatch, envelope('list_companies', page=2, has_more=True))
    output = await make_node({'operation':'list_companies', 'page':2, 'filter_name':'Acme + Co'}).execute({})
    assert dict(calls[0].url.params) == {'page[number]':'2', 'page[size]':'25', 'filter[name]':'Acme + Co'}
    assert output['has_more'] is True and output['next_page'] == 3
    body = envelope('list_companies'); body['data'] = []
    mock_http(monkeypatch, body)
    assert (await make_node({'operation':'list_companies'}).execute({}))['data'] == []
    assert native.BonsaiNode.connection_evidence.operation == 'list_companies'


@pytest.mark.asyncio
async def test_partial_update_preserves_explicit_nullable_clear_and_omits_unset(monkeypatch):
    calls = mock_http(monkeypatch, envelope('update_task'))
    await make_node({'operation':'update_task', 'task_uuid':'ad3fdad8-5072-46df-8800-bb57299179df', 'project_id':None, 'tag_ids':[]}).execute({})
    assert json.loads(calls[0].content) == {'task': {'project_id':None, 'tag_ids':[]}}
    calls = mock_http(monkeypatch, envelope('create_time_entry'))
    await make_node({'operation':'create_time_entry', 'date':'2026-06-17', 'seconds':0, 'non_billable':False}).execute({})
    assert json.loads(calls[0].content) == {'time_entry':{'seconds':0, 'date':'2026-06-17', 'non_billable':False}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [202,204,301,302,400,401,403,404,409,422,429,500])
async def test_refusal_redirect_and_unexpected_success_status(monkeypatch, status):
    calls = mock_http(monkeypatch, {'error': {'message':'Rejected '+TOKEN}}, status)
    result = await make_node({'operation':'list_companies'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data':[]}, {'data':[], 'meta':{}}, {'data':{}, 'meta':{'request_id':'req'}}, {'data':[], 'meta':{'request_id':'req','pagination':{'page':0,'page_size':25,'has_more':False}}}, {'error':{'message':'bad'}, **envelope('list_companies')}])
async def test_malformed_response_is_not_a_success(monkeypatch, body):
    mock_http(monkeypatch, body)
    assert (await make_node({'operation':'list_companies'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation':'get_company','company_id':0},
    {'operation':'get_task','task_uuid':'../companies'},
    {'operation':'create_project','title':'Acme','company_id':42,'billing_type':'retainer'},
    {'operation':'create_task','title':'Task','parent_task_uuid':'ad3fdad8-5072-46df-8800-bb57299179df','project_id':51},
    {'operation':'create_invoice','contact_id':7,'due':'custom'},
    {'operation':'list_companies','page_size':101},
    {'operation':'create_time_entry','seconds':-1,'date':'2026-06-17'},
    {'operation':'create_time_entry','seconds':0,'date':'2026-02-30'},
    {'operation':'create_deal','company_id':42,'title':'Deal','deal_value':'-1'},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises((ValidationError,ValueError)):
        make_node(config)
