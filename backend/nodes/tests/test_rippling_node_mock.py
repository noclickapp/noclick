"""Rippling's documented responses, one HTTP serialization/parsing check per operation.

Sources: https://developer.rippling.com/documentation/rest-api/guides/leave
https://developer.rippling.com/documentation/rest-api/guides/departments
https://developer.rippling.com/documentation/rest-api/guides/supergroup-members
https://developer.rippling.com/documentation/rest-api/reference/list-workers
Source URLs are also stored alongside every verbatim provider body in
fixtures/rippling_responses.json (official reference and guide pages).
Examples with trailing commas are normalized as JSON; no values are invented.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError
from nodes.rippling_node import (
    RipplingAPITokenCredential, RipplingNode, RipplingNodeConfig,
    RipplingCreateLeaveRequestConfig, RipplingUpdateInclusionMembersConfig,
)

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/rippling_responses.json').read_text())
TOKEN = 'test-rippling-token'


def node(config):
    return RipplingNode(node_id='rippling', node_type='automation-rippling', node_data={},
                        config=RipplingNodeConfig(config=config, credentials=RipplingAPITokenCredential(api_token=TOKEN)),
                        sio=Mock(), sid='sid', workflow_id='workflow', user_id='user')


async def run(config, body=None, status=200, error=None):
    requests = []
    original_client = httpx.AsyncClient
    def transport(request):
        requests.append(request)
        if error:
            raise error
        return httpx.Response(status, json=body)
    with patch('nodes.rippling_node.httpx.AsyncClient', side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs)):
        result = await node(config).execute({})
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_documented_operation(operation):
    fixture = FIXTURES[operation]
    config = {'operation': operation, **fixture['config']}
    result, requests = await run(config, fixture['body'])
    assert result['status'] == 'success', result
    assert result['data'] == fixture['body']
    assert result['timing_ms']['total'] >= 0
    request, = requests
    assert request.method == fixture['method']
    path = fixture['path']
    for key in ('id', 'group_id'):
        if key in config:
            path = path.replace('{' + key + '}', config[key])
    assert request.url.host == 'rest.ripplingapis.com'
    assert request.url.path == path
    assert request.headers['Authorization'] == f'Bearer {TOKEN}'
    assert request.headers['Rippling-Api-Version'] == '2024-08-01'
    if request.method == 'GET':
        assert not request.content
        assert 'operation' not in request.url.params
        if operation.startswith('list_'):
            assert request.url.params['limit'] == '50'
    elif operation == 'update_inclusion_members':
        assert json.loads(request.content) == {'Operations': [{'op': 'add', 'value': [
            {'id': '65699292fb7bc7c3510f4781'}, {'id': '6569929efb7bc7c3510f48f3'}]}]}
    else:
        assert json.loads(request.content) == {k: v for k, v in fixture['config'].items() if k != 'id'}


@pytest.mark.asyncio
async def test_pagination_filters_and_expansion():
    body = {'results': [], 'next_link': 'https://rest.ripplingapis.com/workers/?cursor=page2'}
    config = {'operation': 'list_workers', 'limit': 100, 'cursor': 'page1',
              'filter': 'status eq "ACTIVE"', 'expand': 'user', 'order_by': 'created_at'}
    result, requests = await run(config, body)
    request, = requests  # Never follows a returned link with the bearer token.
    assert dict(request.url.params) == {k: str(v) for k, v in config.items() if k != 'operation'}
    assert result['data'] == body


@pytest.mark.asyncio
async def test_remove_members_preserves_protocol_casing():
    result, requests = await run({'operation': 'update_inclusion_members', 'group_id': 'group',
                                 'member_action': 'remove', 'member_ids': '["worker"]'}, {'ok': True})
    assert result['status'] == 'success'
    assert json.loads(requests[0].content) == {'Operations': [{'op': 'remove', 'value': [{'id': 'worker'}]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_provider_error_is_reported_and_not_retried(status):
    result, requests = await run({'operation': 'list_companies'}, {'detail': 'Provider rejected access'}, status)
    assert len(requests) == 1
    assert result['status'] == 'error'
    assert result['status_code'] == status
    assert 'Provider rejected access' in result['error']


@pytest.mark.asyncio
async def test_token_is_redacted_from_error():
    result, _ = await run({'operation': 'list_companies'}, {'detail': TOKEN}, 401)
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_timeout_on_create_leave_is_not_retried():
    fixture = FIXTURES['create_leave_request']
    result, requests = await run({'operation': 'create_leave_request', **fixture['config']}, error=httpx.ReadTimeout('timeout'))
    assert len(requests) == 1
    assert result['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {}, {'results': ['primitive']}, {'results': None}])
async def test_malformed_list_is_not_connection_evidence(body):
    result, _ = await run({'operation': 'list_companies'}, body)
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_false_membership_result_is_error():
    result, _ = await run({'operation': 'update_inclusion_members', 'group_id': 'group', 'member_ids': '["worker"]'}, {'ok': False})
    assert result['status'] == 'error'


def test_leave_requires_policy_or_type():
    with pytest.raises(ValidationError, match='leave_type_id or leave_policy_id'):
        RipplingCreateLeaveRequestConfig(worker_id='worker', status='PENDING', start_date='2026-06-01', end_date='2026-06-05')


@pytest.mark.parametrize('ids', ['[]', '{}', '[null]', '[""]', 'worker', '[123]'])
def test_member_ids_require_nonempty_worker_array(ids):
    with pytest.raises(ValidationError):
        RipplingUpdateInclusionMembersConfig(group_id='group', member_ids=ids)
