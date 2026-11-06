"""Regression coverage for Jira requests rejected by the provider contract."""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes import jira_node as jira


@pytest.mark.asyncio
@pytest.mark.parametrize('config,path,params', [
    (jira.JiraGetWorkflowConfig(workflow_name='Software'), '/workflow/search', {'workflowName': 'Software'}),
    (jira.JiraGetIssueTypeSchemeConfig(scheme_id=10000), '/issuetypescheme', {'id': '10000'}),
    (jira.JiraValidateJQLConfig(jql='project = HSP'), '/jql/parse', {'validation': 'strict'}),
])
async def test_contract_routes_and_required_parameters(config, path, params):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'values': []})
    await execute(config, respond)
    assert requests[0].url.path == '/rest/api/3' + path
    for key, value in params.items():
        assert requests[0].url.params[key] == value


async def execute(config, respond):
    credential = jira.JiraAPITokenCredential(email='test@example.com', api_token='fake', domain='test.atlassian.net')
    node = jira.JiraNode('test', 'automation-jira', {}, jira.JiraNodeFullConfig(config=config, credentials=credential), None)
    node.emit = AsyncMock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch.object(jira, 'guarded_async_client', return_value=client):
        return await node.execute({})


@pytest.mark.asyncio
async def test_preference_is_json_string_and_key_is_encoded():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(204)
    await execute(jira.JiraSetMyPreferenceConfig(preference_key='a&b', value='1'), respond)
    assert json.loads(requests[0].content) == '1'
    assert dict(requests[0].url.params) == {'key': 'a&b'}


@pytest.mark.asyncio
async def test_dashboard_creation_supplies_private_permissions():
    def respond(request):
        body = json.loads(request.content)
        assert body['editPermissions'] == []
        assert body['sharePermissions'] == []
        return httpx.Response(200, json={'id': '10000'})
    await execute(jira.JiraCreateDashboardConfig(name='Private'), respond)


@pytest.mark.asyncio
async def test_dashboard_update_preserves_name_and_sharing():
    current = {'name': 'Existing', 'sharePermissions': [{'type': 'global'}], 'editPermissions': []}
    def respond(request):
        if request.method == 'GET':
            return httpx.Response(200, json=current)
        assert json.loads(request.content) == {**current, 'description': 'Updated'}
        return httpx.Response(200, json=current)
    await execute(jira.JiraUpdateDashboardConfig(dashboard_id='10000', description='Updated'), respond)


@pytest.mark.asyncio
async def test_priority_deletion_accepts_task_redirect_without_following_it():
    def respond(request):
        return httpx.Response(303, headers={'Location': 'https://test.atlassian.net/rest/api/3/task/123'})
    result = await execute(jira.JiraDeletePriorityConfig(priority_id='1'), respond)
    assert result['success'] is True
    assert result['deleted'] is False
    assert result['task'].endswith('/task/123')


def test_dashboard_permissions_drop_read_only_expansions():
    permission = {'id': 10, 'type': 'group', 'group': {'groupId': 'abc', 'name': 'Team', 'self': 'https://example.com'}}
    assert jira.JiraNode._dashboard_permission_for_write(permission) == {
        'type': 'group', 'group': {'groupId': 'abc', 'name': 'Team'}
    }
    assert jira.JiraNode._dashboard_permission_for_write({'type': 'loggedin'}) == {'type': 'authenticated'}
