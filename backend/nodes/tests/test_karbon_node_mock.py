"""Exercise Karbon requests through the real factory with an offline transport.
Published examples and explicit errors cover wire names, manual auth and parsing.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import karbon_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "karbon_api_key", "authorization_token": "synthetic-auth", "access_key": "synthetic-access"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="karbon-test", node_type="automation-karbon",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_manual_auth_and_account_evidence_list(monkeypatch):
    body = {"value": [{"Name": "Joe Min", "EmailAddress": "joe@samplecompany.com"}],
        "@odata.count": 101, "@odata.nextLink": "https://api.karbonhq.com/v3/Users?$skip=100"}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_users", "top": 10, "skip": 50,
        "filter": "EmailAddress eq 'joe@samplecompany.com'"}).execute({})
    assert result["items"] == body["value"] and result["data"] == body
    assert result["next_page_url"] == body["@odata.nextLink"] and len(requests) == 1
    request = requests[0]
    assert request.headers["Authorization"] == "Bearer synthetic-auth"
    assert request.headers["AccessKey"] == "synthetic-access"
    assert dict(request.url.params) == {"$top": "10", "$skip": "50", "$filter": "EmailAddress eq 'joe@samplecompany.com'"}
    assert native.KarbonCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"}).credential_type == "karbon_api_key"
    assert native.KarbonNode.connection_evidence.label_keys[0] == "Name"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,expected", [
    ({"operation": "create_contact", "first_name": "William", "last_name": "Connor"}, "POST", "/v3/Contacts", {"FirstName": "William", "LastName": "Connor"}),
    ({"operation": "update_contact", "key": "4t8LbR1QcbGS", "preferred_name": "Bill"}, "PATCH", "/v3/Contacts/4t8LbR1QcbGS", {"PreferredName": "Bill"}),
    ({"operation": "create_organization", "full_name": "Sample Company"}, "POST", "/v3/Organizations", {"FullName": "Sample Company"}),
    ({"operation": "update_organization", "key": "2Nw8tnxwQCVf", "full_name": "Sample Company Pty. Ltd."}, "PATCH", "/v3/Organizations/2Nw8tnxwQCVf", {"FullName": "Sample Company Pty. Ltd."}),
    ({"operation": "update_work_item", "key": "2LPSrkzbYrn4", "primary_status": "Completed"}, "PATCH", "/v3/WorkItems/2LPSrkzbYrn4", {"PrimaryStatus": "Completed"}),
])
async def test_mutations_only_send_selected_properties(monkeypatch, config, method, path, expected):
    requests = transport(monkeypatch, None, 204)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] is None
    assert requests[0].method == method and requests[0].url.path == path
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_work_creation_required_fields_and_dates(monkeypatch):
    requests = transport(monkeypatch, {"WorkItemKey": "2LPSrkzbYrn4"}, 201)
    config = {"operation": "create_work_item", "title": "Payroll 31 Aug - 15 Sep 2022",
        "assignee_email_address": "joe@samplecompany.com", "client_key": "4ncPZ7q96SGc",
        "client_type": "Organization", "start_date": "2021-12-29T00:00:00Z"}
    assert (await node(config).execute({}))["data"]["WorkItemKey"] == "2LPSrkzbYrn4"
    assert json.loads(requests[0].content) == {"Title": config["title"], "AssigneeEmailAddress": config["assignee_email_address"],
        "ClientKey": config["client_key"], "ClientType": "Organization", "StartDate": config["start_date"]}


@pytest.mark.asyncio
async def test_note_documented_response_and_timeline(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/karbon/note.json").read_text())
    requests = transport(monkeypatch, fixture, 201)
    result = await node({"operation": "create_note", "subject": "Regarding New Proposal", "body": fixture["Body"],
        "author_email_address": "jessica@samplecompany.com", "timelines": [{"entity_type": "WorkItem", "entity_key": "2m6pSFxRzcF2"}]}).execute({})
    assert result["data"] == fixture
    assert json.loads(requests[0].content)["Timelines"] == [{"EntityType": "WorkItem", "EntityKey": "2m6pSFxRzcF2"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("get_contact", "Contacts"), ("get_organization", "Organizations"),
    ("get_work_item", "WorkItems"), ("get_user", "Users"), ("get_work_template", "WorkTemplates"),
    ("get_client_group", "ClientGroups"), ("get_note", "Notes")])
async def test_detail_routes(monkeypatch, operation, path):
    requests = transport(monkeypatch, {"Name": "Example"})
    await node({"operation": operation, "key": "record+key"}).execute({})
    assert requests[0].method == "GET"
    assert requests[0].url.raw_path == ("/v3/" + path + "/record%2Bkey").encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status,message", [({"error": {"message": "Access denied"}}, 401, "Access denied"),
    ({"error": {}}, 200, "API error"), ({}, 200, "value array"), ([], 200, "JSON object")])
async def test_rejection_and_malformed_response(monkeypatch, body, status, message):
    transport(monkeypatch, body, status)
    with pytest.raises(ValueError, match=message):
        await node({"operation": "list_users"}).execute({})


@pytest.mark.asyncio
async def test_error_redacts_both_secrets(monkeypatch):
    transport(monkeypatch, {"error": "synthetic-auth synthetic-access"}, 403)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_users"}).execute({})
    assert "synthetic-auth" not in str(exc.value) and "synthetic-access" not in str(exc.value)


@pytest.mark.parametrize("config", [{"operation": "update_contact", "key": "x"},
    {"operation": "update_work_item", "key": "x", "secondary_status": "Send client requests"},
    {"operation": "list_users", "skip": 101}, {"operation": "create_contact", "first_name": "William"}])
def test_invalid_config_fails_before_request(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_editor_credential_metadata_is_not_an_api_field():
    value = node({"operation": "get_contact", "key": "4jgPTtcXxwC2",
        "credentialIds": {"karbon_api_key": "saved-id"}, "key__label": "William Connor"})
    assert value.config.config.key == "4jgPTtcXxwC2"
    assert native._body(value.config.config) == {}
