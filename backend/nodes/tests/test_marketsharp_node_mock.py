"""Offline request-contract and connection regressions for MarketSharp 1.0."""
import json

import httpx
import pytest
from pydantic import ValidationError
from nodes import marketsharp_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-marketsharp-access-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='marketsharp-fixture', node_type='automation-marketsharp',
        node_data={'config': config, 'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_token': TOKEN}})


def mock(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs == {'timeout': 30.0, 'follow_redirects': False, 'trust_env': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


CASES = [
    ({'operation': 'list_companies'}, 'GET', '/companies', None),
    ({'operation': 'get_company', 'company_id': 'company-1'}, 'GET', '/companies/company-1', None),
    ({'operation': 'get_contact', 'company_id': 'company-1', 'contact_id': 'contact-1'}, 'GET', '/companies/company-1/contacts/contact-1', None),
    ({'operation': 'search_contacts', 'company_id': 'company-1', 'last_name': 'Jones'}, 'POST', '/companies/company-1/contacts/search', {'numberOfRecords': 100, 'last_name': 'Jones'}),
    ({'operation': 'filter_contacts', 'company_id': 'company-1', 'pageNumber': 2, 'rowsPerPage': 20}, 'POST', '/companies/company-1/contacts/filter', {'pageNumber': 2, 'rowsPerPage': 20}),
    ({'operation': 'get_inquiry', 'company_id': 'company-1', 'inquiry_id': 'lead-1'}, 'GET', '/companies/company-1/inquiries/lead-1', None),
    ({'operation': 'get_opportunity', 'company_id': 'company-1', 'inquiry_id': 'lead-1', 'job_id': 'job-1'}, 'GET', '/companies/company-1/opportunities/lead-1', None),
    ({'operation': 'list_opportunity_notes', 'company_id': 'company-1', 'inquiry_id': 'lead-1', 'note_type': 'Job'}, 'GET', '/companies/company-1/opportunities/lead-1/notes/Job', None),
    ({'operation': 'save_opportunity_note', 'company_id': 'company-1', 'inquiry_id': 'lead-1', 'note': 'Follow up', 'note_id': 12}, 'POST', '/companies/company-1/opportunities/notes', {'inquiryId': 'lead-1', 'note': 'Follow up', 'opportunityNoteType': 'Inquiry', 'id': 12}),
    ({'operation': 'delete_opportunity_note', 'company_id': 'company-1', 'inquiry_id': 'lead-1', 'note_id': 12}, 'DELETE', '/companies/company-1/opportunities/lead-1/notes/12', None),
    ({'operation': 'qualify_opportunity', 'company_id': 'company-1', 'inquiry_id': 'lead-1'}, 'PUT', '/companies/company-1/opportunities/qualification/lead-1', None),
    ({'operation': 'get_appointment', 'company_id': 'company-1', 'appointment_id': 'appt-1'}, 'GET', '/companies/company-1/appointments/appt-1', None),
    ({'operation': 'filter_appointments', 'company_id': 'company-1'}, 'POST', '/companies/company-1/appointments/filter', {'pageNumber': 1, 'rowsPerPage': 100}),
    ({'operation': 'result_appointment', 'company_id': 'company-1', 'appointment_id': 'appt-1', 'result_id': 'result-1', 'employee_id': 'employee-1', 'notes': 'Interested'}, 'POST', '/companies/company-1/appointments/appt-1/result', {'appt_id': 'appt-1', 'result_id': 'result-1', 'employee_id': 'employee-1', 'notes': 'Interested'}),
    ({'operation': 'create_estimate', 'company_id': 'company-1', 'appointmentId': 'appt-1', 'name': 'Windows', 'lineItems': [{'sku': 'window', 'quantity': 2, 'retailPrice': 250.5}]}, 'POST', '/companies/company-1/estimates', {'appointmentId': 'appt-1', 'name': 'Windows', 'lineItems': [{'sku': 'window', 'quantity': 2, 'retailPrice': 250.5}]}),
    ({'operation': 'update_estimate', 'company_id': 'company-1', 'appointmentId': 'appt-1', 'name': 'Windows', 'estimate_id': 'est-1'}, 'PUT', '/companies/company-1/estimates/est-1', {'appointmentId': 'appt-1', 'name': 'Windows'}),
    ({'operation': 'list_pricebook', 'company_id': 'company-1'}, 'GET', '/companies/company-1/pricebook', None),
    ({'operation': 'list_primary_lead_sources', 'company_id': 'company-1'}, 'GET', '/companies/company-1/primaryleadsources/active', None),
    ({'operation': 'list_secondary_lead_sources', 'company_id': 'company-1', 'primary_lead_source_id': 'source-1'}, 'GET', '/companies/company-1/primaryleadsources/source-1/secondaryleadsources/active', None),
    ({'operation': 'list_appointment_results', 'company_id': 'company-1'}, 'GET', '/companies/company-1/appointments/results/active', None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES)
async def test_marketsharp_exact_contract_requests(monkeypatch, config, method, path, body):
    calls = mock(monkeypatch, {'provider': 'original-shape'})
    result = await node(config).execute({})
    assert result['data'] == {'provider': 'original-shape'}
    assert result['status'] == 'success'
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == 'restapi.marketsharpm.com'
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    assert dict(req.url.params) == {'api-version': '1.0', **({'jobId': 'job-1'} if config['operation'] == 'get_opportunity' else {})}
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize('reply', [{'companyName': 'Example company', 'oid': 'company-1'}, [{'companyName': 'Example company', 'oid': 'company-1'}]])
async def test_marketsharp_connection_preserves_provider_shapes(monkeypatch, reply):
    mock(monkeypatch, reply)
    from nodes.core.connection_evidence import _rows_from_operation, _label_from
    result = await node({'operation': 'list_companies'}).execute({})
    assert result['data'] == reply
    rows = _rows_from_operation(result)
    assert _label_from(rows[0], native.MarketSharpNode.connection_evidence.label_keys) == 'Example company'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'message': 'Token expired'}), (403, {'error': 'Access denied'}), (200, {'errors': ['Bad input']}), (200, {'success': False})])
async def test_marketsharp_error_envelopes_are_not_success(monkeypatch, status, body):
    mock(monkeypatch, body, status)
    result = await node({'operation': 'list_companies'}).execute({})
    assert result['status'] == 'error' and result['error'] == body
    if status >= 400:
        assert result['status_code'] == status


@pytest.mark.asyncio
async def test_marketsharp_token_redaction(monkeypatch):
    mock(monkeypatch, {TOKEN: [TOKEN, {'message': 'Rejected ' + TOKEN}]}, 401)
    assert TOKEN not in str(await node({'operation': 'list_companies'}).execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize('reply', [None, '', {}, []])
async def test_marketsharp_empty_rejection_cannot_be_connection_evidence(monkeypatch, reply):
    from nodes.core.connection_evidence import _raise_if_error_envelope, _ProviderRefused
    mock(monkeypatch, reply, 401)
    result = await node({'operation': 'list_companies'}).execute({})
    with pytest.raises(_ProviderRefused, match='401'):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
async def test_marketsharp_non_json_and_redirects_are_not_followed(monkeypatch):
    calls = []
    def client(**kwargs):
        def respond(req):
            calls.append(req)
            return httpx.Response(302, headers={'Location': 'https://example.test/'}, text='Moved')
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError, match='non-JSON'):
        await node({'operation': 'list_companies'}).execute({})
    assert len(calls) == 1


def test_marketsharp_manual_credential_and_required_inputs():
    credential = native.MarketSharpAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert native.MarketSharpAPITokenCredential.model_json_schema()['required'] == ['api_token']
    for invalid in ['Bearer abc', 'bad\ntoken', 'https://example.test/key']:
        with pytest.raises((ValueError, ValidationError)):
            native.MarketSharpAPITokenCredential(api_token=invalid)
    with pytest.raises((ValueError, ValidationError)):
        node({'operation': 'get_contact', 'company_id': 'company-1'})
    with pytest.raises((ValueError, ValidationError)):
        node({'operation': 'get_company', 'company_id': '..'})
    assert len(CASES) == len(native.ROUTES) == 20


@pytest.mark.asyncio
async def test_marketsharp_date_filter_serialization_and_single_page(monkeypatch):
    calls = mock(monkeypatch, {'id': 'contact-1'})
    await node({'operation': 'filter_contacts', 'company_id': 'company-1', 'start_modified_datetime': '2026-11-01T10:00:00Z', 'pageNumber': 3, 'rowsPerPage': 10}).execute({})
    assert json.loads(calls[0].content) == {'start_modified_datetime': '2026-11-01T10:00:00Z', 'pageNumber': 3, 'rowsPerPage': 10}
    assert len(calls) == 1
