"""All operations use unmodified Atlassian response examples.

Fixture source: https://developer.atlassian.com/cloud/jira/service-desk/swagger.v3.json
Authentication: https://developer.atlassian.com/cloud/jira/service-desk/basic-auth-for-rest-apis/
The official spec encodes JSON responses as strings; fixtures decode those once.
No credentials, sockets, or Jira account are needed.
"""
import base64
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.jiraservicemanagement_node import (
    JiraServiceManagementNode, JiraServiceManagementNodeConfig,
    JiraServiceManagementAPITokenCredential, OPERATIONS,
)

CASES = json.loads((Path(__file__).parent / "fixtures/jiraservicemanagement/documented.json").read_text())
CREDENTIAL = {"site_url": "https://your-domain.atlassian.net", "email": "fred@example.com", "api_token": "test-api-token"}
ACCOUNT = "qm:a713c8ea-1075-4e30-9d96-891a7d181739:5ad6d3581db05e2a66fa80b"
# Independently spell out the wire contract for each write operation.
BODIES = {
    "create_request": {"serviceDeskId": "10", "requestTypeId": "25", "requestFieldValues": {
        "summary": "Request JSD help via REST", "description": "I need a new *mouse* for my Mac"}},
    "add_comment": {"body": "Hello there", "public": True},
    "add_participants": {"accountIds": [ACCOUNT]},
    "transition_request": {"id": "1", "additionalComment": {"body": "I have fixed the problem."}},
    "create_customer": {"email": "fred@example.com", "displayName": "Fred F. User"},
    "add_customers": {"accountIds": [ACCOUNT]},
}


def node(config):
    return JiraServiceManagementNode(node_id="test-jsm", node_type="automation-jiraservicemanagement",
        node_data={}, config=JiraServiceManagementNodeConfig(config=config, credentials=CREDENTIAL),
        sio=Mock(), sid="test", workflow_id="test", user_id="test")


def transport_patch(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.jiraservicemanagement_node.httpx.AsyncClient",
                        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_documented_operation(monkeypatch, operation):
    case = CASES[operation]
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(case["status"], json=case["body"]) if case["body"] is not None else httpx.Response(case["status"])
    transport_patch(monkeypatch, handler)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == case["status"]
    assert result["data"] == (case["body"] if case["body"] is not None else {"success": True})
    assert result["timing_ms"]["api_request"] >= 0
    assert len(requests) == 1
    request = requests[0]
    path = case["path"]
    for key, value in {"serviceDeskId": "10", "requestTypeId": "25", "issueIdOrKey": "HELPDESK-1", "slaMetricId": "10030", "queueId": "20"}.items():
        path = path.replace("{" + key + "}", value)
    assert request.method == case["method"]
    assert request.url.path == path
    assert request.url.host == "your-domain.atlassian.net"
    expected_auth = base64.b64encode(b"fred@example.com:test-api-token").decode()
    assert request.headers["Authorization"] == "Basic " + expected_auth
    assert request.headers["Accept"] == "application/json"
    if operation in BODIES:
        assert json.loads(request.content) == BODIES[operation]
        assert not request.url.params
    else:
        assert not request.content
        expected_query = {"start": "0", "limit": "50"} if operation.startswith("list_") else {}
        if operation == "list_queues": expected_query["includeCount"] = "false"
        assert dict(request.url.params) == expected_query


def test_all_operations_have_a_documented_case():
    assert set(OPERATIONS) == set(CASES)
    schema = JiraServiceManagementNode.get_config_schema()
    configs = [definition for definition in schema["$defs"].values()
               if "operation" in definition.get("properties", {})]
    assert {definition["properties"]["operation"]["const"] for definition in configs} == set(CASES)


@pytest.mark.asyncio
async def test_filters_pagination_and_false_boolean(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=CASES["list_requests"]["body"])
    transport_patch(monkeypatch, handler)
    result = await node({"operation": "list_requests", "search_term": "laptop repair", "request_status": "OPEN_REQUESTS",
                         "service_desk_id": 10, "start": 50, "limit": 25}).execute({})
    assert result["data"] == CASES["list_requests"]["body"]  # retains provider pagination, links and nested fields
    assert dict(requests[0].url.params) == {"start": "50", "limit": "25", "searchTerm": "laptop repair",
                                          "requestStatus": "OPEN_REQUESTS", "serviceDeskId": "10"}


@pytest.mark.asyncio
async def test_private_comment(monkeypatch):
    def handler(request):
        assert json.loads(request.content) == {"body": "Internal note", "public": False}
        return httpx.Response(201, json=CASES["add_comment"]["body"])
    transport_patch(monkeypatch, handler)
    assert (await node({"operation": "add_comment", "issue_id_or_key": "HELPDESK-1", "body": "Internal note", "public": False}).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_custom_request_fields_and_on_behalf(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["requestFieldValues"] == {"summary": "Summary", "customfield_10000": {"id": "123"}}
        assert body["raiseOnBehalfOf"] == ACCOUNT
        return httpx.Response(201, json=CASES["create_request"]["body"])
    transport_patch(monkeypatch, handler)
    assert (await node({"operation": "create_request", "service_desk_id": "10", "request_type_id": "25", "summary": "Summary",
                       "raise_on_behalf_of": ACCOUNT, "request_field_values": '{"customfield_10000":{"id":"123"},"summary":"ignored"}'}).execute({}))["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_api_errors_do_not_leak_secrets(monkeypatch, status):
    transport_patch(monkeypatch, lambda request: httpx.Response(status, json={"errorMessage": "test-api-token"}))
    result = await node({"operation": "list_service_desks"}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert "test-api-token" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"values": "bad"}, {"values": [None]}, {"values": [{}]}, {"errorMessage": "Failed"}, {"values": [], "errors": {}}])
async def test_connection_probe_rejects_invalid_shapes(monkeypatch, payload):
    transport_patch(monkeypatch, lambda request: httpx.Response(200, json=payload))
    assert (await node({"operation": "list_service_desks"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_connection_evidence_uses_own_service_desks(monkeypatch):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/rest/servicedeskapi/servicedesk"
        return httpx.Response(200, json=CASES["list_service_desks"]["body"])
    transport_patch(monkeypatch, handler)
    options = await JiraServiceManagementNode.load_field_options("service_desk_id", CREDENTIAL)
    assert options["options"] == [{"value": row["id"], "label": row["projectName"]} for row in CASES["list_service_desks"]["body"]["values"]]
    assert JiraServiceManagementNode.connection_evidence.field == "service_desk_id"


@pytest.mark.asyncio
async def test_empty_service_desk_page(monkeypatch):
    transport_patch(monkeypatch, lambda request: httpx.Response(200, json={"values": [], "isLastPage": True, "start": 0, "limit": 50, "size": 0}))
    assert (await JiraServiceManagementNode.load_field_options("service_desk_id", CREDENTIAL))["options"] == []


@pytest.mark.asyncio
async def test_non_json_and_timeout(monkeypatch):
    transport_patch(monkeypatch, lambda request: httpx.Response(200, text="<html>Sign in</html>"))
    assert (await node({"operation": "list_service_desks"}).execute({}))["status"] == "error"
    monkeypatch.undo()
    def timeout(request): raise httpx.ReadTimeout("test-api-token", request=request)
    transport_patch(monkeypatch, timeout)
    result = await node({"operation": "list_service_desks"}).execute({})
    assert result["status_code"] == 408
    assert "test-api-token" not in json.dumps(result)


@pytest.mark.parametrize("site", ["http://your-domain.atlassian.net", "https://evil.test", "https://your-domain.atlassian.net.evil.test", "https://user:pass@your-domain.atlassian.net", "https://your-domain.atlassian.net:444"])
def test_host_validation(site):
    with pytest.raises(ValidationError):
        JiraServiceManagementAPITokenCredential(**{**CREDENTIAL, "site_url": site})


def test_host_normalizes_pasted_url():
    credential = JiraServiceManagementAPITokenCredential(**{**CREDENTIAL, "site_url": "your-domain.atlassian.net/jira/servicedesk/projects/HELPDESK"})
    assert credential.site_url == CREDENTIAL["site_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", ["[]", "null", "invalid-json"])
async def test_bad_custom_fields_make_no_request(monkeypatch, fields):
    transport_patch(monkeypatch, lambda request: pytest.fail("Invalid configuration must not make a request"))
    with pytest.raises(ValueError):
        await node({"operation": "create_request", "service_desk_id": "10", "request_type_id": "25", "summary": "Summary", "request_field_values": fields}).execute({})
