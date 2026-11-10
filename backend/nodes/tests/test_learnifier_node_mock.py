"""Learnifier's key/secret, wire requests, and poll lifecycle regressions.

Synthetic values instantiate only fields from the provider's pinned 1.3.1 schemas;
the fixture retains the original provider schemas and example values verbatim.
"""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import learnifier_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


CREDENTIAL = {"credential_type": "learnifier_api_key", "instance": "https://example.learnifier.com", "api_key": "fixture-key", "api_secret": "fixture-secret"}


def node(config):
    return NodeFactory.create_node(node_id="learnifier-test", node_type="automation-learnifier", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_basic_key_secret_and_connection_proof(monkeypatch):
    requests = transport(monkeypatch, {"orgUnits": [{"id": 1234, "type": "client", "displayName": "My Client"}]})
    out = await native.LearnifierNode.load_field_options("orgid", CREDENTIAL)
    assert out == {"options": [{"value": "1234", "label": "My Client"}]}
    assert requests[0].url.path == "/api/v1/orgunits"
    assert requests[0].headers["authorization"] == "Basic " + base64.b64encode(b"fixture-key:fixture-secret").decode()
    assert requests[0].headers["content-type"] == "application/json"
    assert "fixture-secret" not in str(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("create_user", {"primaryEmail": "jane.doe@example.com", "firstName": "Jane", "homeOrg": 1234}, "POST", "/users", {"primaryEmail": "jane.doe@example.com", "firstName": "Jane", "homeOrg": 1234}),
    ("update_user", {"userid": "81590981-1e05-4fd5-aa15-15bc4b06cf7f", "hardLock": False}, "PATCH", "/users/81590981-1e05-4fd5-aa15-15bc4b06cf7f", {"hardLock": False}),
    ("create_participant", {"orgid": 1234, "projectid": 20, "email": "user@example.com", "activate": True}, "POST", "/orgunits/1234/projects/20/createParticipant", {"email": "user@example.com", "activate": True}),
    ("activate_participant", {"orgid": 1234, "projectid": 20, "participantId": 30}, "POST", "/orgunits/1234/projects/20/participants/30/activate", None),
    ("delete_group_member", {"orgid": 1234, "groupid": 1010, "uuid": "81590981-1e05-4fd5-aa15-15bc4b06cf7f"}, "DELETE", "/orgunits/1234/usergroups/1010/members/81590981-1e05-4fd5-aa15-15bc4b06cf7f", None),
    ("create_user_award", {"awardId": "award-1", "userId": "81590981-1e05-4fd5-aa15-15bc4b06cf7f"}, "POST", "/userawards", {"awardId": "award-1", "userId": "81590981-1e05-4fd5-aa15-15bc4b06cf7f"}),
])
async def test_mutation_wire_contract(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, None, 204)
    out = await node({"operation": operation, **config}).execute({})
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert (json.loads(request.content) if request.content else None) == body
    assert out["data"] == {"ok": True}


@pytest.mark.asyncio
async def test_list_parameters_and_page_controls(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_users", "orgid": 1234, "offset": 100, "limit": 50}).execute({})
    assert dict(requests[0].url.params) == {"limit": "50", "offset": "100"}
    await node({"operation": "list_participants", "orgid": 1234, "projectid": 20, "first_completed_since": "2021-12-20T12:30:00Z", "completionStatus": "completed"}).execute({})
    assert dict(requests[1].url.params) == {"filter[firstCompleted][gte]": "2021-12-20T12:30:00Z", "completionStatus": "completed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,date_field", [("on_course_completed", "firstCompleted"), ("on_participant_activated", "firstActivation")])
async def test_poll_baseline_dedup_and_agent_event(monkeypatch, operation, date_field):
    # The provider's Participation schema supplies every field read here.
    schema = json.loads((Path(__file__).parent / "fixtures/learnifier/contract.json").read_text())["Participation"]
    row = {"id": 30, "userId": "81590981-1e05-4fd5-aa15-15bc4b06cf7f", "projectId": 20, "completionStatus": "completed", date_field: "2021-12-20T12:30:00Z"}
    assert set(row) <= set(schema["properties"])
    requests = transport(monkeypatch, [row])
    current = node({"operation": operation, "orgid": 1234, "projectid": 20})
    state = {}
    async def update(mutator, **kwargs):
        next_state, result = mutator(state.copy())
        if next_state is not None:
            state.clear(); state.update(next_state)
        return result
    monkeypatch.setattr(current, "_update_node_state", update)
    assert (await current.execute({}))["participations"] == []
    row2 = {**row, "id": 31}
    transport(monkeypatch, [row, row2])
    result = await current.execute({})
    assert result["participations"] == [row2]
    assert native.LearnifierNode.should_propagate_output(result, {"operation": operation})
    event = native.LearnifierNode.resolve_agent_event(result)
    assert "81590981" in event["text"] and "31" in event["text"] and "1234" in event["text"]
    assert (await current.execute({}))["participations"] == []
    if operation == "on_course_completed":
        assert requests[0].url.params["completionStatus"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_api_failure_redacts_credentials(monkeypatch, status):
    transport(monkeypatch, {"message": "rejected fixture-key fixture-secret"}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_organizations"}).execute({})
    assert str(status) in str(error.value)
    assert "fixture-key" not in str(error.value) and "fixture-secret" not in str(error.value)


@pytest.mark.parametrize("change", [{"instance": "http://company.learnifier.com"}, {"instance": "https://user:pass@company.learnifier.com"}, {"api_key": "bad:key"}, {"api_secret": "bad\nsecret"}])
def test_credential_validation(change):
    with pytest.raises(ValidationError):
        native.LearnifierAPIKeyCredential.model_validate({**CREDENTIAL, **change})


def test_manual_credential_default_and_origin_paste():
    credential = native.LearnifierAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert credential.credential_type == "learnifier_api_key"
    assert native.LearnifierAPIKeyCredential.model_validate({**CREDENTIAL, "instance": "example.learnifier.com/path"}).instance == "https://example.learnifier.com"


@pytest.mark.parametrize("config", [{"operation": "update_user", "userid": "abc"}, {"operation": "get_user", "userid": "../bad"}, {"operation": "list_users", "orgid": 1, "offset": -1}, {"operation": "on_course_completed", "orgid": 1, "projectid": 2, "first_completed_since": "bad"}])
def test_invalid_configs(config):
    with pytest.raises(ValueError):
        native.LearnifierNode.parse_config({"config": config, "credentials": CREDENTIAL})
