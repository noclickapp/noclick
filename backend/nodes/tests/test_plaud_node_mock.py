"""Exercise real Plaud nodes with provider-authored fixtures, without an account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import plaud_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/plaud/documented.json").read_text())
TOKEN = "synthetic-plaud-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(family=native.WORKSPACE):
    return {"credential_type": family, "access_token": TOKEN,
        **({"device_sn": "8810000000000001", "region": "us"} if family == native.EMBEDDED else {})}


def node(config, creds):
    return NodeFactory.create_node(node_id="plaud-test", node_type="automation-plaud",
        node_data={"config": config, "credentials": creds})


def transport(monkeypatch, response):
    calls = []
    def reply(request):
        calls.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_plaud_documented_request_and_response(monkeypatch, operation):
    case = CASES[operation]
    family = native.ROUTES[operation][2]
    calls = transport(monkeypatch, case["response"])
    out = await node(case["config"], credential(family)).execute({})
    assert len(calls) == 1
    req = calls[0]
    assert req.method == case["method"]
    assert req.headers["authorization"] == "Bearer " + TOKEN
    assert req.headers["content-type"] == "application/json"
    assert str(req.url).split("?")[0] == (native.WORKSPACE_BASE if family == native.WORKSPACE else native.PARTNER_BASES['us']) + case["path"].replace("{id}", "%3Cfile_id_2%3E")
    values = {k: v for k, v in case["config"].items() if k != "operation"}
    if req.method == "POST":
        assert json.loads(req.content) == values
    elif "{id}" not in case["path"]:
        assert dict(req.url.params) == {k: str(v) for k, v in values.items()}
    else:
        assert not req.url.query
    assert out == {"status": "success", "operation": operation, "data": case["response"].get("data", case["response"])}
    assert TOKEN not in str(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_plaud_wrong_credential_never_sent(monkeypatch, operation):
    family = native.EMBEDDED if native.ROUTES[operation][2] == native.WORKSPACE else native.WORKSPACE
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="requires a Plaud"):
        await node(CASES[operation]["config"], credential(family)).execute({})
    assert not calls


@pytest.mark.asyncio
async def test_plaud_japan_and_exact_pagination(monkeypatch):
    calls = transport(monkeypatch, CASES['get_device_binding']['response'])
    creds = {**credential(native.EMBEDDED), 'region': 'jp'}
    await node(CASES['get_device_binding']['config'], creds).execute({})
    assert calls[0].url.host == 'platform-jp.plaud.ai'
    calls = transport(monkeypatch, CASES['list_file_changes']['response'])
    out = await node({'operation': 'list_file_changes', 'limit': 5, 'cursor': 'page+/=', 'checkpoint': 'resume+/='}, credential()).execute({})
    assert dict(calls[0].url.params) == {'limit': '5', 'cursor': 'page+/=', 'checkpoint': 'resume+/='}
    assert out['data']['next_checkpoint'] == '<checkpoint>'
    assert out['data']['has_more'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('family', [native.WORKSPACE, native.EMBEDDED])
async def test_plaud_connection_uses_read_only_provider_operation(monkeypatch, family):
    response = CASES['list_workspaces' if family == native.WORKSPACE else 'get_device_binding']['response']
    calls = transport(monkeypatch, response)
    result = await native.PlaudNode.load_field_options('connection', credential(family))
    assert len(calls) == 1 and calls[0].method == 'GET'
    if family == native.WORKSPACE:
        assert result['options'] == [{'value': '<workspace_id>', 'label': '<workspace_name>'}]
    else:
        assert result['options'] == []  # Published binding read does not prove ownership.


@pytest.mark.asyncio
@pytest.mark.parametrize('http_status,envelope', [(401, {'msg': 'expired token'}), (200, {'status': 401, 'msg': 'expired token', 'type': 'error'})])
async def test_plaud_connection_preserves_provider_rejection(monkeypatch, http_status, envelope):
    transport(monkeypatch, lambda _: httpx.Response(http_status, json=envelope))
    out = await native.PlaudNode.load_field_options('connection', credential())
    assert out['status'] == 'error' and out['http_status'] == 401
    assert out['error'] == 'expired token'


@pytest.mark.asyncio
async def test_plaud_redirect_is_not_followed(monkeypatch):
    calls = transport(monkeypatch, lambda _: httpx.Response(302, headers={'Location': 'https://example.com/steal'}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'list_workspaces'}, credential()).execute({})
    assert len(calls) == 1


def test_plaud_manual_credential_defaults_and_secret_validation():
    assert native.PlaudWorkspaceCredential(access_token=TOKEN).credential_type == native.WORKSPACE
    assert native.PlaudUserCredential(access_token=TOKEN, device_sn='8820000000000001').credential_type == native.EMBEDDED
    for bad in ['https://example.com/token', 'Bearer abc', 'abc\nxyz']:
        with pytest.raises(ValidationError):
            native.PlaudWorkspaceCredential(access_token=bad)


@pytest.mark.parametrize('file_id', ['.', '..', 'id\nnext'])
def test_plaud_file_id_cannot_change_the_route(file_id):
    with pytest.raises(ValidationError):
        native.GetFile(file_id=file_id)


def test_plaud_foreign_credential_tag_is_refused():
    data = {'config': {'operation': 'list_workspaces'}, 'credentials': {**credential(), 'credential_type': 'other_token'}}
    assert native.PlaudNode.validate_config(data)['valid'] is False
    with pytest.raises(ValueError, match='Attach a Plaud credential'):
        native.PlaudNode.parse_config(data)
