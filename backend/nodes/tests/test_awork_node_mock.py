"""HTTP contracts and the provider's published project_added delivery.

Event fixture: https://developers.awork.com/webhooks (JSON trailing comma removed).
Synthetic keys never contact awork.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.awork_node import AworkNode, AworkNodeConfig, AworkAPIKeyCredential, AUTH_HEADER, BASE_URL

ID = "123e4567-e89b-12d3-a456-426614174000"
CREDENTIAL = {"credential_type": "awork_api_key", "api_key": "synthetic-awork-key"}
EVENT = json.loads((Path(__file__).parent / "fixtures/awork/project_added.json").read_text())


def node(config):
    return AworkNode(node_id="awork-test", node_type="automation-awork", node_data={},
        config=AworkNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL}),
        sio=AsyncMock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", [
    ({"operation": "list_projects", "page": 2, "pageSize": 5}, "GET", "/projects", None),
    ({"operation": "list_tasks"}, "GET", "/me/allavailabletasks", None),
    ({"operation": "list_project_tasks", "projectId": ID}, "GET", f"/projects/{ID}/projecttasks", None),
    ({"operation": "get_task", "taskId": ID}, "GET", f"/tasks/{ID}", None),
    ({"operation": "create_task", "name": "Create logo concept", "baseType": "projecttask", "entityId": ID},
     "POST", "/tasks", {"name": "Create logo concept", "baseType": "projecttask", "entityId": ID}),
    ({"operation": "update_task", "taskId": ID, "name": "Create logo concept", "isPrio": False},
     "PUT", f"/tasks/{ID}", {"name": "Create logo concept", "isPrio": False}),
    ({"operation": "create_project", "name": "Website Design"}, "POST", "/projects", {"name": "Website Design"}),
    ({"operation": "update_project", "projectId": ID, "name": "Website Design"},
     "PUT", f"/projects/{ID}", {"name": "Website Design"}),
    ({"operation": "create_company", "name": "NCNSTN Brand Design"},
     "POST", "/companies", {"name": "NCNSTN Brand Design"}),
    ({"operation": "create_task_comment", "taskId": ID, "message": "Hey team, the customer loved the latest designs!"},
     "POST", f"/tasks/{ID}/comments", {"message": "Hey team, the customer loved the latest designs!"}),
    ({"operation": "get_time_entry", "timeEntryId": ID}, "GET", f"/timeentries/{ID}", None),
    ({"operation": "create_time_entry", "timezone": "Europe/Berlin", "typeOfWorkId": ID, "userId": ID,
      "startDateUtc": "2022-03-01T00:00:00Z", "startTimeUtc": "09:21:00", "duration": 8635},
     "POST", "/timeentries", {"timezone": "Europe/Berlin", "typeOfWorkId": ID, "userId": ID,
      "startDateUtc": "2022-03-01T00:00:00Z", "startTimeUtc": "09:21:00", "duration": 8635}),
    ({"operation": "list_users"}, "GET", "/users", None),
])
async def test_request_mapping(config, method, path, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, BASE_URL + path).mock(return_value=httpx.Response(200, json={"id": ID}))
        result = await node(config).execute({})
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer synthetic-awork-key"
    assert (json.loads(request.content) if request.content else None) == body
    assert result["data"] == {"id": ID}
    if config["operation"] == "list_projects":
        assert dict(request.url.params) == {"page": "2", "pageSize": "5"}


@pytest.mark.asyncio
async def test_pagination_is_explicit_and_does_not_claim_all_pages():
    with respx.mock:
        respx.get(BASE_URL + "/projects").mock(return_value=httpx.Response(200, json=[{"id": ID}]))
        result = await node({"operation": "list_projects", "page": 3, "pageSize": 1}).execute({})
    assert result["pagination"] == {"page": 3, "page_size": 1, "next_page": 4}


@pytest.mark.asyncio
async def test_provider_rejection_redacts_key_and_never_follows_redirect():
    with respx.mock:
        respx.get(BASE_URL + "/projects").mock(return_value=httpx.Response(401, text="Rejected synthetic-awork-key"))
        with pytest.raises(ValueError, match=r"awork API 401: Rejected \[redacted\]"):
            await node({"operation": "list_projects"}).execute({})
        respx.get(BASE_URL + "/projects").mock(return_value=httpx.Response(302, headers={"Location": "https://elsewhere.invalid"}))
        with pytest.raises(ValueError, match="awork API 302"):
            await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_task", "taskId": "../../users"},
    {"operation": "create_task", "name": "Task", "baseType": "projecttask"},
    {"operation": "list_projects", "page": 0},
    {"operation": "create_project", "name": "x", "unexpected": True},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises(ValidationError):
        node(config)


def test_credential_connect_default_and_shaping():
    assert AworkAPIKeyCredential(api_key="  synthetic-awork-key  ").api_key == CREDENTIAL["api_key"]
    assert AworkAPIKeyCredential(api_key=CREDENTIAL["api_key"]).credential_type == "awork_api_key"


@pytest.mark.asyncio
async def test_webhook_registration_authentication_and_cleanup():
    with respx.mock(assert_all_called=True) as router:
        create = router.post(BASE_URL + "/webhooks").mock(return_value=httpx.Response(200, json={"id": ID}))
        delete = router.delete(BASE_URL + "/webhooks/" + ID).mock(return_value=httpx.Response(204))
        state = await AworkNode._register_external_webhook(webhook_url="https://example.com/webhook", credential=CREDENTIAL,
            config={"operation": "on_project_created"}, node_id="awork-test")
        body = json.loads(create.calls[0].request.content)
        assert body == {"name": "NoClick awork-test", "uri": "https://example.com/webhook", "events": "project_added",
            "isActive": True, "authenticationType": "header", "authentication": AUTH_HEADER + "=" + state["signing_secret"]}
        assert AworkNode.verify_webhook_signature(b"{}", {AUTH_HEADER.lower(): state["signing_secret"]}, state)
        assert not AworkNode.verify_webhook_signature(b"{}", {AUTH_HEADER: "wrong"}, state)
        assert not AworkNode.verify_webhook_signature(b"{}", {AUTH_HEADER: "é"}, state)
        assert not AworkNode.verify_webhook_signature(b"{}", {}, state)
        assert not AworkNode.verify_webhook_signature(b"{}", {AUTH_HEADER: "x"}, {})
        await AworkNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="awork-test")
        assert delete.called


def test_documented_event_reaches_agent_with_actor_project_url_and_action_id():
    config = {"operation": "on_project_created"}
    assert AworkNode.filter_trigger_payload(EVENT, config)
    assert not AworkNode.filter_trigger_payload({"eventType": "project_deleted"}, config)
    output = AworkNode.resolve_trigger_payload(EVENT, config)
    event = AworkNode.resolve_agent_event(output)
    assert event["conversation_key"] == ID
    assert all(s in event["text"] for s in ["Website Design", "Carla Creative", EVENT["entityLink"], "projectId=" + ID])


@pytest.mark.asyncio
async def test_manual_trigger_does_not_invent_an_event():
    assert (await node({"operation": "on_project_created"}).execute({}))["status"] == "no_event"


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture,config,path", [
    ("task", {"operation": "get_task", "taskId": ID}, "/tasks/" + ID),
    ("time_entry", {"operation": "get_time_entry", "timeEntryId": ID}, "/timeentries/" + ID),
    ("users", {"operation": "list_users"}, "/users"),
])
async def test_provider_examples_preserved_including_documented_date_strings(fixture, config, path):
    # awork's examples have invalid/naive date strings that its OpenAPI validator
    # rejects. The node preserves the published JSON for downstream consumers.
    documented = json.loads((Path(__file__).parent / "fixtures/awork" / (fixture + ".json")).read_text())
    with respx.mock:
        respx.get(BASE_URL + path).mock(return_value=httpx.Response(200, json=documented["body"]))
        result = await node(config).execute({})
    assert result["data"] == documented["body"]
