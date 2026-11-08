"""eTermin native operations with synthetic transport; no provider account used."""
import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import etermin_node as module
from nodes.core.run_op import run_node_operation
from nodes.core.base import ConfigValidationError

AUTH = {'credential_type': 'etermin_api_key', 'public_key': 'fixture-public-key', 'private_key': 'fixture-private-key'}
CASES = json.loads((Path(__file__).parent / 'fixtures/etermin/operations.json').read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == 'www.etermin.net'
        assert request.headers['publickey'] == AUTH['public_key']
        expected = base64.b64encode(hmac.new(AUTH['private_key'].encode(), request.headers['salt'].encode(), hashlib.sha256).digest()).decode()
        assert request.headers['signature'] == expected
        assert AUTH['private_key'] not in str(request.url)
        return replies.pop(0)
    original = httpx.AsyncClient
    def client(**kw):
        assert kw['follow_redirects'] is False and kw['trust_env'] is False
        return original(**kw, transport=httpx.MockTransport(send))
    monkeypatch.setattr(module.httpx, 'AsyncClient', client)
    return requests, replies


async def run(operation, **config):
    return await run_node_operation(node_type='automation-etermin', operation=operation,
        arguments=config, credential_data=AUTH.copy(), user_id='00000000-0000-4000-8000-000000000001')


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
@pytest.mark.asyncio
async def test_every_operation_has_exact_route_query_and_no_body(transport, case):
    requests, replies = transport
    read = case['method'] == 'GET'
    body = [{'CalendarName': 'Team calendar', 'CalendarID': 1234}] if read else {'Status': 200, 'StatusMsg': '1 record(s) updated!'}
    replies.append(httpx.Response(200, json=body))
    result = await run(case['operation'], **case['config'])
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert dict(request.url.params) == {k: str(v) for k, v in case['config'].items()}
    assert request.content == b''
    assert result == ({'items': body} if read else {'data': body, 'acknowledged': True, 'http_status': 200})


@pytest.mark.asyncio
async def test_salts_are_unique_and_false_zero_unicode_and_commas_survive(transport):
    requests, replies = transport
    replies.extend([httpx.Response(200, json={'Status': 200}) for _ in range(2)])
    for _ in range(2):
        await run('create_appointment', start='2017-10-24 18:00', end='2017-10-24 19:00', calendarid=1234,
            services='45345,45346', lastname='Müller + Co', capacity=0, sendemail=False)
    assert requests[0].headers['salt'] != requests[1].headers['salt']
    assert requests[0].url.params['lastname'] == 'Müller + Co'
    assert requests[0].url.params['sendemail'] == 'false'
    assert requests[0].url.params['capacity'] == '0'
    assert requests[0].url.params['services'] == '45345,45346'


@pytest.mark.asyncio
async def test_account_calendars_and_empty_read(transport):
    _, replies = transport
    replies.append(httpx.Response(200, json=[{'CalendarName': 'Consultations', 'CalendarID': 120034}]))
    assert (await run('list_calendars'))['items'][0]['CalendarName'] == 'Consultations'
    replies.append(httpx.Response(200, json=[]))
    assert await run('list_contacts') == {'items': []}


@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500])
@pytest.mark.asyncio
async def test_http_failure_and_redirect_are_refused_and_secrets_redacted(transport, status):
    requests, replies = transport
    replies.append(httpx.Response(status, text='Rejected ' + AUTH['private_key'], headers={'Location': 'https://example.test/'}))
    with pytest.raises(ValueError) as exc:
        await run('list_calendars')
    assert str(status) in str(exc.value) and AUTH['private_key'] not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize('body', [{'Status': 401, 'StatusMsg': 'Invalid publickey'}, {'status': '400', 'statusmsg': 'Bad input'}, {'error': 'Rejected'}, {}, 'unexpected', [1]])
@pytest.mark.asyncio
async def test_error_envelopes_and_wrong_read_shape_are_refused(transport, body):
    _, replies = transport
    replies.append(httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await run('list_calendars')


@pytest.mark.parametrize('operation,config', [('update_appointment', {'id': 'fixture-id'}), ('update_service', {'id': 123}), ('update_absence', {'id': 123}), ('delete_appointment', {}), ('delete_contact', {})])
def test_no_unbounded_delete_or_empty_update(operation, config):
    with pytest.raises(ConfigValidationError):
        module.EterminNode.parse_config({'config': {'operation': operation, **config}, 'credentials': AUTH.copy()})


@pytest.mark.asyncio
async def test_empty_mutation_is_acknowledgement_and_never_verified_effect(transport):
    _, replies = transport
    replies.append(httpx.Response(200))
    assert await run('delete_absence', id=1234) == {'acknowledged': True, 'http_status': 200}
    replies.append(httpx.Response(200))
    with pytest.raises(ValueError):
        await run('list_calendars')


@pytest.mark.asyncio
async def test_html_is_never_accepted_as_a_success(transport):
    _, replies = transport
    replies.append(httpx.Response(200, text='<html>Sign in</html>'))
    with pytest.raises(ValueError):
        await run('delete_absence', id=1234)


def test_credentials_require_two_hidden_keys_and_reject_urls():
    schema = module.EterminAPIKeyCredential.model_json_schema()
    assert schema['title'] == 'Etermin API Keys'
    for name in ('public_key', 'private_key'):
        assert schema['properties'][name]['ui:widget'] == 'password'
        assert name in schema['required']
        with pytest.raises(ValidationError):
            module.EterminAPIKeyCredential.model_validate({**AUTH, name: 'https://example.test/key'})


@pytest.mark.asyncio
async def test_plain_error_text_is_never_acknowledged(transport):
    _, replies = transport
    replies.append(httpx.Response(200, text='Invalid publickey'))
    with pytest.raises(ValueError):
        await run('delete_absence', id=1234)
    replies.append(httpx.Response(200, text='1 record(s) deleted'))
    assert (await run('delete_absence', id=1234))['acknowledged'] is True


@pytest.mark.asyncio
async def test_creation_with_documented_body_cannot_succeed_empty(transport):
    _, replies = transport
    replies.append(httpx.Response(200))
    with pytest.raises(ValueError):
        await run('create_contact', email='email@example.com')


@pytest.mark.asyncio
async def test_connection_evidence_shows_the_providers_calendar_name(transport):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append(httpx.Response(200, json=[{'CalendarID': 34611, 'CalendarName': 'Employee A'}]))
    evidence = await collect_evidence(node_type='automation-etermin', credential_data=AUTH.copy(),
        user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ['Employee A']
    assert requests[0].url.path == '/api/calendar' and not requests[0].url.params
