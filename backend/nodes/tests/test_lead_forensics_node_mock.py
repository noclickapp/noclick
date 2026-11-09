"""Wire-contract regressions using the provider's published example responses.

No provider account or live API calls are used.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lead_forensics_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'lead-forensics'
RESPONSES = json.loads((FIXTURES / 'responses.json').read_text())
INPUTS = json.loads((FIXTURES / 'inputs.json').read_text())
CREDENTIAL = {'credential_type': 'lead_forensics_api_key', 'client_id': '45656', 'api_key': 'synthetic-lf-key-42'}
# This list is independent of the node's routing table.
ROUTES = {
    'list_businesses': '/Business/GetAllBusinesses', 'get_business': '/Business/GetBusiness',
    'list_businesses_by_category': '/Business/GetBusinessesByCategory',
    'list_businesses_by_assignee': '/Business/GetBusinessesByAssignedTo',
    'list_visits': '/Visit/GetAllVisits', 'get_visit': '/Visit/GetVisit',
    'get_visit_details': '/Visit/GetVisitDetails', 'list_visits_by_business': '/Visit/GetVisitsByBusiness',
    'list_visits_by_conversion': '/Visit/GetVisitsByConversion',
    'list_visits_by_trigger_report': '/Visit/GetVisitsByTriggerReport',
    'list_recent_visits': '/Visit/Get10MostRecent', 'list_pages': '/Page/GetPages',
    'list_pages_by_visit': '/Page/GetPagesByVisit', 'list_industries': '/Reference/GetIndustryList',
    'list_countries': '/Reference/GetCountryList', 'list_employee_bands': '/Reference/GetEmployeeBandList',
    'list_categories': '/Reference/GetCategoryList', 'list_assignees': '/Reference/GetAssignedToList',
    'list_conversions': '/Reference/GetConversionList', 'list_trigger_reports': '/Reference/GetTriggerReportList',
    'list_date_ranges': '/Reference/GetDateList', 'get_new_leads': '/KPI/NewLeads',
    'get_lead_funnel': '/KPI/LeadFunnel', 'get_most_active_companies': '/KPI/MostActiveCompanies',
    'get_visit_kpi': '/KPI/Visits',
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation='list_assignees', config=None, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id='lf-fixture', node_type='automation-lead-forensics',
        node_data={'config': copy.deepcopy(config or INPUTS[operation]), 'credentials': credential})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ROUTES)
async def test_lead_forensics_documented_operations_exact_wire_and_parser(monkeypatch, operation):
    requests = transport(monkeypatch, RESPONSES[operation])
    result = await node(operation).execute({})
    assert result['success'] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET'
    assert request.url.scheme == 'https' and request.url.host == 'interact.leadforensics.com'
    assert request.url.path == '/WebApi_v2' + ROUTES[operation]
    assert request.headers['ClientID'] == CREDENTIAL['client_id']
    assert request.headers['Authorization-Token'] == CREDENTIAL['api_key']
    assert 'Authorization' not in request.headers and not request.content
    cfg = node(operation).config.config.model_dump(mode='json', exclude={'operation'}, exclude_none=True)
    assert dict(request.url.params) == {k: str(v) for k,v in cfg.items()}
    assert CREDENTIAL['api_key'] not in json.dumps(result)
    assert result['data']


@pytest.mark.asyncio
async def test_lead_forensics_account_evidence_empty_and_multiple_pages(monkeypatch):
    body = {'List': [], 'PageSize': 5, 'PageCount': 0, 'RecordCount': 0, 'CurrentPage': 1}
    requests = transport(monkeypatch, body)
    result = await node().execute({})
    assert result['data'] == [] and result['next_page'] is None and not result['has_more']
    assert requests[0].url.path.endswith('/Reference/GetAssignedToList')
    body.update(List=[{'ID': 12, 'Name': 'Owned user'}], PageCount=3, RecordCount=11)
    result = await node().execute({})
    assert result['next_page'] == 2 and result['has_more'] and not result['complete']
    assert len(requests) == 2  # one request per execution; never auto-drains pages
    assert native.LeadForensicsNode.connection_evidence.operation == 'list_assignees'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 429, 500])
async def test_lead_forensics_provider_rejections_and_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={'Message': 'Denied ' + CREDENTIAL['api_key']}))
    result = await node().execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'Denied' in result['message'] and CREDENTIAL['api_key'] not in result['message']
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'List': {}}, {'error': 'bad'}, {'Message': 'bad'},
    {'List': [1]}, {'List': [], 'PageSize': '5', 'PageCount': 1, 'RecordCount': 0, 'CurrentPage': 1}])
async def test_lead_forensics_malformed_or_error_envelopes_fail(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node().execute({})


@pytest.mark.asyncio
async def test_lead_forensics_bad_mime_network_and_wrong_identity(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, text='<html>not the API</html>'))
    with pytest.raises(ValueError, match='bounded JSON'):
        await node().execute({})
    def timeout(r):
        raise httpx.ReadTimeout('private token ' + CREDENTIAL['api_key'])
    transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match='could not be reached') as exc:
        await node().execute({})
    assert CREDENTIAL['api_key'] not in str(exc.value)
    transport(monkeypatch, {**RESPONSES['get_business'], 'BusinessID': 999})
    with pytest.raises(ValueError, match='different resource'):
        await node('get_business').execute({})


@pytest.mark.parametrize('field,value', [('api_key', 'https://example.com/key'), ('api_key', '<token>'),
    ('api_key', 'header\ninjection'), ('api_key', 'nonascii–key'), ('client_id', 'a b')])
def test_lead_forensics_credential_header_validation(field, value):
    with pytest.raises(ValidationError):
        native.LeadForensicsAPIKeyCredential.model_validate({**CREDENTIAL, field: value})


def test_lead_forensics_manual_credential_default_and_paste_cleanup():
    value = native.LeadForensicsAPIKeyCredential(client_id=' 45656 ', api_key=' synthetic-lf-key-42\n')
    assert value.credential_type == 'lead_forensics_api_key'
    assert value.client_id == '45656' and value.api_key == CREDENTIAL['api_key']


@pytest.mark.parametrize('config', [
    {'operation': 'get_business', 'businessid': 0},
    {'operation': 'get_business', 'businessid': '../path'},
    {'operation': 'list_assignees', 'pageno': 0},
    {'operation': 'list_assignees', 'pagesize': 1001},
    {'operation': 'list_assignees', 'url': 'https://attacker.example'},
    {'operation': 'list_visits', 'datefrom': '2016-07-30', 'dateto': '2016-07-01'},
    {'operation': 'list_visits', 'datefrom': '2016-02-30', 'dateto': '2016-03-01'},
    {'operation': 'list_recent_visits', 'datefrom': '2016-03-01'},
])
def test_lead_forensics_invalid_configs_fail_before_network(config):
    with pytest.raises(ValueError):
        node(config=config)


def test_lead_forensics_config_validation_hides_supplied_credential_values():
    private = "invalid synthetic-private-key-value"
    with pytest.raises(ValidationError) as exc:
        native.LeadForensicsConfig.model_validate({
            'config': {'operation': 'list_assignees'},
            'credentials': {**CREDENTIAL, 'api_key': private},
        })
    assert private not in str(exc.value)
