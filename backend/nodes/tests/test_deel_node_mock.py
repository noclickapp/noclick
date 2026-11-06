"""Test all Deel actions against verbatim provider documentation responses.

Each fixture carries its official source URL. HTTP requests are captured with
MockTransport, so these tests never access an account or open a network socket.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

import httpx
import pytest

from nodes.deel_node import DeelNode, DeelNodeConfig

# Sources are recorded per operation in the fixture, for example:
# https://developer.deel.com/api/stable/hris-endpoints/people/get-people.md
# https://developer.deel.com/api/stable/hris-endpoints/organization-structure/update-person-department.md
FIXTURES = json.loads((Path(__file__).parent / "fixtures/deel/documented_responses.json").read_text())
TOKEN = "deel-test-token"
REAL_CLIENT = httpx.AsyncClient


def make_node(operation, config=None, credentials=True):
    return DeelNode(
        node_id="test-deel", node_type="automation-deel", node_data={},
        config=DeelNodeConfig(
            config={"operation": operation, **(config if config is not None else FIXTURES[operation]["config"])},
            credentials={"api_token": TOKEN} if credentials else None,
        ),
        sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )


def client_for(handler):
    return REAL_CLIENT(transport=httpx.MockTransport(handler))


# Explicit wire bodies are independent of the node's routing/conversion code.
BODIES = {
    "update_personal_information": {"data": {"preferred_name": "John"}},
    "update_department": {"data": {"department_id": "00000000-0000-0000-0000-000000000000"}},
    "update_working_location": {"data": {"working_location_id": 1}},
    "create_organization_structure": {"data": {"name": "Engineering", "external_id": "d290f1ee-6c54-4b01-90e6-d701748f0853"}},
    "update_organization_structure": {"data": {"teams": [{"name": "Engineering"}]}},
    "create_worker_relation": {"data": {
        "parent_hris_profile_id": "642b0547-9d80-4d35-a085-fd977ef209ef",
        "child_hris_profile_ids": ["9b9fc43a-a90c-4615-ac50-baf1e314b53e"],
        "hris_relationship_type_id": "877ccad0-1234-5678-9abc-def012345678",
    }},
    "create_person": {"data": {
        "client": {"team": {"id": "cbb25647-31e0-485d-9d5f-bdd48296aa1e"},
                   "legal_entity": {"id": "cfebc769-abe9-4646-83b9-28cf79f23a0d"}},
        "person": {"email": "email@email.com", "last_name": "Doe", "first_name": "John", "start_date": "2020-01-01"},
    }},
}
QUERIES = {"list_people": {"limit": "50", "offset": "150", "search": "John Doe"},
           "list_organization_structures": {"limit": "100", "offset": "0"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_documented_operation(operation):
    fixture = FIXTURES[operation]
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == fixture["method"]
        path = fixture["path"]
        for key, value in fixture["config"].items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        assert str(request.url).split("?")[0] == "https://api.letsdeel.com/rest" + path
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert dict(request.url.params) == QUERIES.get(operation, {})
        if operation in BODIES:
            assert json.loads(request.content) == BODIES[operation]
        else:
            assert not request.content
        return (httpx.Response(204) if fixture["status_code"] == 204 else
                httpx.Response(fixture["status_code"], json=fixture["response"]))

    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(handle)):
        result = await make_node(operation).execute({})
    assert len(requests) == 1
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == fixture["status_code"]
    assert result["data"] == fixture["response"]
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_provider_errors_preserve_status_and_verbatim_body(status):
    body = '{"errors":[{"message":"Token lacks people:read"}]}'
    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(
        lambda request: httpx.Response(status, text=body)
    )):
        result = await make_node("list_people").execute({})
    assert result["status"] == "error"
    assert result["error"] == body
    assert result["status_code"] == status
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_network_error_does_not_expose_token():
    def handle(request):
        raise httpx.ConnectError(f"private detail {TOKEN}", request=request)
    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(handle)):
        result = await make_node("list_people").execute({})
    assert result["status"] == "error"
    assert result["error"] == "Deel request failed (ConnectError)"
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_credentials():
    with pytest.raises(ValueError, match="Credentials are required"):
        await make_node("list_people", credentials=False).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["{broken", '{"teams":[]}', '["not an object"]'])
async def test_invalid_teams_json_never_sends_request(value):
    with patch("nodes.deel_node.httpx.AsyncClient") as client:
        with pytest.raises(ValueError):
            await make_node("update_organization_structure", {
                "hris_org_structure_id": "example", "teams_json": value,
            }).execute({})
        client.assert_not_called()


@pytest.mark.asyncio
async def test_dates_and_explicit_false_survive_serialization():
    def handle(request):
        assert dict(request.url.params) == {"replace_other_positions": "false"}
        assert json.loads(request.content) == {"data": {"department_id": "department", "effective_date": "2026-01-01"}}
        return httpx.Response(200, json={"data": {"updated": True}})
    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(handle)):
        await make_node("update_department", {"id": "person", "department_id": "department", "effective_date": "2026-01-01", "replace_other_positions": False}).execute({})


@pytest.mark.asyncio
async def test_json_team_string_and_create_field_name():
    def handle(request):
        assert json.loads(request.content) == {"data": {"name": "Engineering", "teams": [{"name": "Platform"}], "is_multiple_select": False}}
        return httpx.Response(200, json={"data": {"id": "structure"}})
    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(handle)):
        await make_node("create_organization_structure", {"name": "Engineering", "teams_json": '[{"name":"Platform"}]', "is_multiple_select": False}).execute({})


@pytest.mark.asyncio
async def test_path_ids_are_encoded():
    def handle(request):
        assert request.url.raw_path == b"/rest/people/a%2Fb%3Fq%3D1"
        return httpx.Response(200, json={"data": {}})
    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(handle)):
        await make_node("get_person", {"hris_profile_id": "a/b?q=1"}).execute({})


@pytest.mark.asyncio
async def test_empty_personal_update_is_refused():
    with pytest.raises(ValueError, match="at least one"):
        await make_node("update_personal_information", {"worker_id": "worker"}).execute({})


@pytest.mark.asyncio
async def test_non_object_response_is_not_success():
    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(
        lambda request: httpx.Response(200, json=["unexpected"])
    )):
        with pytest.raises(ValueError, match="invalid response object"):
            await make_node("list_people").execute({})


@pytest.mark.asyncio
async def test_connection_evidence_shows_documented_person_name():
    from nodes.core.connection_evidence import collect_evidence

    async def run_operation(**kwargs):
        assert kwargs["operation"] == "list_people"
        assert kwargs["arguments"] == {}
        return await make_node("list_people", {}).execute({})

    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(
        lambda request: httpx.Response(200, json=FIXTURES["list_people"]["response"])
    )), patch("nodes.core.run_op.run_node_operation", side_effect=run_operation):
        evidence = await collect_evidence(node_type="automation-deel", user_id="test", credential_data={"api_token": TOKEN})
    assert evidence.reachable is True
    assert evidence.samples[0].label == FIXTURES["list_people"]["response"]["data"][0]["full_name"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,reachable", [(200, {"data": []}, True), (401, {"errors": [{"message": "Invalid API token"}]}, False)])
async def test_connection_evidence_empty_account_and_rejected_token(status, body, reachable):
    from nodes.core.connection_evidence import collect_evidence

    async def run_operation(**kwargs):
        return await make_node("list_people", {}).execute({})

    with patch("nodes.deel_node.httpx.AsyncClient", return_value=client_for(
        lambda request: httpx.Response(status, json=body)
    )), patch("nodes.core.run_op.run_node_operation", side_effect=run_operation):
        evidence = await collect_evidence(node_type="automation-deel", user_id="test", credential_data={"api_token": TOKEN})
    assert evidence.reachable is reachable
    assert evidence.samples == []
