"""Exercise the actual node factory against requests from the pinned Public API contract."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import bitwarden_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/bitwarden/requests.json').read_text())
TOKEN = 'synthetic-access-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region='US'):
    return NodeFactory.create_node(node_id='bitwarden-test', node_type='automation-bitwarden', node_data={
        'config': config, 'credentials': {'credential_type': 'bitwarden_access_token', 'access_token': TOKEN, 'region': region}})


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_contract_requests_and_response_passthrough(monkeypatch, case):
    requests = []
    real = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'object': 'list', 'data': [{'id': 'owned-id', 'name': 'Development Team'}], 'continuationToken': 'next-cursor'})
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    result = await node(case['config']).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method'] and req.url.path == case['path']
    assert req.url.host == 'api.bitwarden.com'
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(req.content) if req.content else None) == case['body']
    assert result == {'data': [{'id': 'owned-id', 'name': 'Development Team'}], 'continuationToken': 'next-cursor'}


@pytest.mark.asyncio
@pytest.mark.parametrize('region,host', [('EU', 'api.bitwarden.eu'), ('Gov', 'api.bitwarden-gov.com')])
async def test_regions_pagination_and_provider_rejection(monkeypatch, region, host):
    real = httpx.AsyncClient
    def reply(request):
        assert request.url.host == host
        assert request.url.params['continuationToken'] == 'cursor+with/slash='
        return httpx.Response(401, json={'message': 'Token expired'})
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    with pytest.raises(ValueError, match='401: Token expired'):
        await node({'operation': 'list_groups', 'continuationToken': 'cursor+with/slash='}, region).execute({})


def test_manual_credential_and_path_validation():
    assert native.BitwardenAccessTokenCredential(access_token=TOKEN).credential_type == 'bitwarden_access_token'
    for config in [{'operation': 'get_member', 'id': '../groups'}, {'operation': 'get_policy', 'policy_type': 1000}, {'operation': 'create_group', 'body': {}}]:
        with pytest.raises(ValidationError):
            native.BitwardenNode.parse_config({'config': config})


def test_custom_permission_null_is_not_a_wire_value():
    with pytest.raises(ValidationError):
        native.MemberCreateRequestModel(type=2, email="jsmith@example.com", permissions=None)
    body = native.MemberCreateRequestModel(type=2, email="jsmith@example.com")
    assert "permissions" not in body.model_dump(mode="json", exclude_unset=True)
