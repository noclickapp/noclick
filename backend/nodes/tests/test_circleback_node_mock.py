"""Exercise native Circleback requests without provider accounts or network."""
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import circleback_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'circleback-unit-secret'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='circleback-test', node_type='automation-circleback',
        node_data={'config': config, 'credentials': {'credential_type': 'circleback_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CONFIGS = [
    {'operation': 'get_account'},
    {'operation': 'list_meetings'},
    {'operation': 'get_meeting', 'meetingId': 'WRweb12iCBimU6Vo8cD7z'},
    {'operation': 'get_meeting_transcript', 'meetingId': 'WRweb12iCBimU6Vo8cD7z'},
    {'operation': 'search_meetings', 'searchTerm': 'venue'},
    {'operation': 'import_meeting', 'name': 'Event Venue Review', 'notes': 'Review venues'},
    {'operation': 'update_meeting', 'meetingId': 'WRweb12iCBimU6Vo8cD7z', 'notes': 'Updated notes', 'tagIds': []},
    {'operation': 'delete_meeting', 'meetingId': 'WRweb12iCBimU6Vo8cD7z'},
    {'operation': 'share_meeting', 'meetingId': 'WRweb12iCBimU6Vo8cD7z', 'targets': [{'email': 'john@initech.com', 'access': 'Viewer'}]},
    {'operation': 'list_action_items'},
    {'operation': 'create_action_item', 'title': 'Contact event venues'},
    {'operation': 'update_action_item', 'actionItemId': 252, 'assigneeProfileId': None, 'status': 'DONE'},
    {'operation': 'delete_action_item', 'actionItemId': 252},
    {'operation': 'list_calendar_events'},
    {'operation': 'update_meeting_for_calendar_event', 'calendarMeetingId': 'google-calendar-event-id', 'tagIds': []},
    {'operation': 'list_companies'},
    {'operation': 'get_company', 'domain': 'initech.com'},
    {'operation': 'list_people'},
    {'operation': 'get_person', 'profileId': 1},
    {'operation': 'list_folders'},
    {'operation': 'get_folder', 'folderId': 'folder-1'},
    {'operation': 'list_tags'},
    {'operation': 'create_tag', 'name': 'Events', 'description': 'Company events and offsites.'},
    {'operation': 'update_tag', 'tagId': 1, 'description': None},
    {'operation': 'delete_tag', 'tagId': 1},
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config', CONFIGS, ids=lambda cfg: cfg['operation'])
async def test_single_contract_request(monkeypatch, config):
    body = {'email': 'john@initech.com'} if config['operation'] == 'get_account' else [] if (config['operation'].startswith(('list_', 'search_')) or config['operation'] == 'get_meeting_transcript') else {'id': 1}
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['data'] == body
    assert len(requests) == 1
    req = requests[0]
    method, path, ids, query, array = native.ROUTES[config['operation']]
    for name in ids:
        path = path.replace('{' + name + '}', str(config[name]))
    assert req.method == method and req.url.path == '/api' + path
    assert req.url.host == 'circleback.ai'
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    if method in {'POST', 'PUT'}:
        import json
        expected = {k: v for k, v in config.items() if k not in {'operation', *ids}}
        assert json.loads(req.content) == (expected['targets'] if array else expected)


@pytest.mark.asyncio
async def test_cursor_filters_repeated_query_and_false(monkeypatch):
    requests = transport(monkeypatch, [], headers={'Link': '</api/meetings?cursor=next-page>; rel="next"'})
    result = await node({'operation': 'list_meetings', 'ownership': 'All', 'tagIds': [1, 2]}).execute({})
    assert result['has_more'] and result['next_cursor'] == 'next-page'
    assert requests[0].url.params.get_list('tagIds') == ['1', '2']
    assert requests[0].url.params['ownership'] == 'All'
    requests = transport(monkeypatch, [])
    await node({'operation': 'list_calendar_events', 'includeOfflineSingleAttendee': False}).execute({})
    assert requests[0].url.params['includeOfflineSingleAttendee'] == 'false'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_failure_redacts_key_and_does_not_follow(monkeypatch, status):
    requests = transport(monkeypatch, {'error': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'get_account'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_foreign_cursor_and_missing_identity_fail(monkeypatch):
    requests = transport(monkeypatch, [], headers={'Link': '<https://evil.test/api/meetings?cursor=x>; rel="next"'})
    assert (await node({'operation': 'list_meetings'}).execute({}))['status'] == 'error'
    assert len(requests) == 1
    transport(monkeypatch, {})
    assert (await node({'operation': 'get_account'}).execute({}))['status'] == 'error'


def test_hand_connect_and_required_inputs():
    assert native.CirclebackAPIKeyCredential(api_key=TOKEN).credential_type == 'circleback_api_key'
    assert set(native.ROUTES) == {c['operation'] for c in CONFIGS}
    for config in [{'operation': 'create_action_item'}, {'operation': 'get_person', 'profileId': 0}]:
        with pytest.raises(ConfigValidationError):
            node(config)


@pytest.mark.asyncio
async def test_documented_import_response_with_nested_attendees(monkeypatch):
    import json
    from pathlib import Path
    body = json.loads((Path(__file__).parent / 'fixtures/circleback/import_meeting.json').read_text())
    transport(monkeypatch, body)
    result = await node({'operation': 'import_meeting', 'name': 'Event Venue Review', 'notes': 'Review venues'}).execute({})
    assert result['status'] == 'success'
    assert result['data']['id'] == 'WRweb12iCBimU6Vo8cD7z'
    assert result['data']['attendees'][1]['email'] == 'samantha@initech.com'
    assert result['data'] == body
