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


def poll_node(monkeypatch, *, config=None):
    instance = node({'operation': 'on_new_or_updated_recording', **(config or {})}, credential())
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    monkeypatch.setattr(instance, '_update_node_state', update)
    return instance, state


@pytest.mark.asyncio
async def test_plaud_poll_baseline_updates_and_agent_context(monkeypatch):
    from copy import deepcopy
    response = deepcopy(CASES['list_file_changes']['response'])
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=response))
    instance, state = poll_node(monkeypatch)
    first = await instance.execute({})
    assert first['recordings'] == []
    assert state['seen_ids']
    assert instance.trigger_produced_no_event(first)
    assert native.PlaudNode.resolve_agent_event(first) is None
    recording = response['data']['files'][0]
    recording['version'] += 1
    updated = await instance.execute({})
    assert updated['recordings'] == [recording]
    assert instance.trigger_emitted_event(updated)
    event = native.PlaudNode.resolve_agent_event(updated)
    for value in [recording['id'], recording['title'], recording['workspace_id'], recording['created_by_member_id']]:
        assert value in event['text']
    assert str(recording['version']) in event['text']
    assert native.PlaudNode.should_propagate_output(updated, {'operation': 'on_new_or_updated_recording'})
    assert (await instance.execute({}))['recording_count'] == 0
    new = {**recording, 'id': '<new_file_id>'}
    response['data']['files'].extend([new, new])
    assert (await instance.execute({}))['recordings'] == [new]
    assert all(dict(call.url.params) == {'limit': '1000'} for call in calls)


@pytest.mark.asyncio
async def test_plaud_poll_paginates_before_dedup_and_scopes_checkpoint(monkeypatch):
    from copy import deepcopy
    response = deepcopy(CASES['list_file_changes']['response'])
    second = {**response['data']['files'][0], 'id': '<second_file_id>'}

    def reply(request):
        page = deepcopy(response)
        if request.url.params.get('cursor'):
            page['data']['files'].append(second)
        else:
            page['data'].update(has_more=True, next_cursor='next+/=')
        return httpx.Response(200, json=page)

    calls = transport(monkeypatch, reply)
    instance, state = poll_node(monkeypatch, config={'checkpoint': '<checkpoint>'})
    state['seen_ids'] = []
    output = await instance.execute({})
    assert output['recordings'] == [response['data']['files'][0], second]
    assert [dict(call.url.params) for call in calls] == [
        {'limit': '1000', 'checkpoint': '<checkpoint>'},
        {'limit': '1000', 'cursor': 'next+/=', 'checkpoint': '<checkpoint>'}]
    from nodes.core.poll_trigger import poll_scope
    base = {'operation': 'on_new_or_updated_recording', 'checkpoint': '<checkpoint>'}
    scope = poll_scope(native.PlaudNode, base)
    assert scope == poll_scope(native.PlaudNode, {**base, 'goal': 'cosmetic edit', 'label': 'My recordings'})
    assert scope != poll_scope(native.PlaudNode, {**base, 'checkpoint': '<other_checkpoint>'})


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['http', 'cursor', 'missing_version', 'too_many'])
async def test_plaud_poll_incomplete_feed_never_marks_seen(monkeypatch, failure):
    from copy import deepcopy
    response = deepcopy(CASES['list_file_changes']['response'])
    if failure == 'cursor':
        response['data'].update(has_more=True, next_cursor=None)
    elif failure == 'missing_version':
        del response['data']['files'][0]['version']
    elif failure == 'too_many':
        row = response['data']['files'][0]
        response['data']['files'] = [{**row, 'id': str(index)} for index in range(10001)]
    transport(monkeypatch, (lambda _: httpx.Response(401, json={'msg': 'expired'})) if failure == 'http' else response)
    instance, state = poll_node(monkeypatch)
    if failure == 'http':
        assert (await instance.execute({}))['status'] == 'error'
    else:
        with pytest.raises(ValueError):
            await instance.execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_plaud_poll_wrong_token_and_lost_state_write(monkeypatch):
    calls = transport(monkeypatch, CASES['list_file_changes']['response'])
    with pytest.raises(ValueError, match='requires a Plaud workspace token'):
        await node({'operation': 'on_new_or_updated_recording'}, credential(native.EMBEDDED)).execute({})
    assert not calls
    instance, _ = poll_node(monkeypatch)

    async def unavailable(mutator, *, skip_result):
        return skip_result

    monkeypatch.setattr(instance, '_update_node_state', unavailable)
    output = await instance.execute({})
    assert output['recordings'] == []
    assert instance.trigger_produced_no_event(output)


def test_plaud_trigger_schema_uses_poll_family():
    from nodes.core.poll_trigger import PollTriggerConfigBase
    config = native.OnNewOrUpdatedRecording()
    assert isinstance(config, PollTriggerConfigBase)
    operation = config.model_json_schema()['properties']['operation']
    assert operation['x-is-trigger'] is True
    assert operation['x-category'] == 'Triggers'
