"""Exercise Ironclad's actual factory, transport, body mapping and error handling."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ironclad_node as native
from nodes.core.registry import NodeFactory

TOKEN = "ironclad-synthetic-token-123"
CREDENTIAL = {"credential_type": "ironclad_api_token", "api_token": TOKEN, "user_email": "jane.doe@test.com"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="ironclad-test", node_type="automation-ironclad",
        node_data={"config": config, "credentials": {**CREDENTIAL, **credential}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_workflows", "search": "master services agreement", "page": 2, "page_size": 10}, "GET", "/workflows", None),
    ({"operation": "get_workflow", "workflow_id": "IC-1"}, "GET", "/workflows/IC-1", None),
    ({"operation": "create_workflow", "template": "600b296c3e15a234ab88f884", "attributes": {"counterpartyName": "Jane Doe"}}, "POST", "/workflows", {"template": "600b296c3e15a234ab88f884", "attributes": {"counterpartyName": "Jane Doe"}}),
    ({"operation": "list_workflow_approvals", "workflow_id": "IC-1"}, "GET", "/workflows/IC-1/approvals", None),
    ({"operation": "list_workflow_signers", "workflow_id": "IC-1"}, "GET", "/workflows/IC-1/signatures", None),
    ({"operation": "list_workflow_participants", "workflow_id": "IC-1"}, "GET", "/workflows/IC-1/participants", None),
    ({"operation": "list_workflow_comments", "workflow_id": "IC-1"}, "GET", "/workflows/IC-1/comments", None),
    ({"operation": "create_workflow_comment", "workflow_id": "IC-1", "comment": "Please review", "replied_to_comment_id": "comment-1"}, "POST", "/workflows/IC-1/comments", {"comment": "Please review", "repliedToActivityFeedMessageId": "comment-1"}),
    ({"operation": "update_workflow_attributes", "workflow_id": "IC-1", "updates": [{"action": "set", "path": "counterpartyName", "value": "Example Company"}, {"action": "remove", "path": "optionalField"}]}, "PATCH", "/workflows/IC-1/attributes", {"updates": [{"action": "set", "path": "counterpartyName", "value": "Example Company"}, {"action": "remove", "path": "optionalField"}]}),
    *[({"operation": action + "_workflow", "workflow_id": "IC-1", "comment": "Requested by legal"}, "POST", "/workflows/IC-1/" + action, {"comment": {"message": "Requested by legal"}}) for action in ("pause", "resume", "cancel")],
    ({"operation": "list_workflow_schemas"}, "GET", "/workflow-schemas", None),
    ({"operation": "get_workflow_schema", "schema_id": "template-1"}, "GET", "/workflow-schemas/template-1", None),
    ({"operation": "list_records", "types": "consultingAgreement", "last_updated": "2018-05-08T00:00:00Z"}, "GET", "/records", None),
    ({"operation": "get_record", "record_id": "IC-1"}, "GET", "/records/IC-1", None),
    ({"operation": "create_record", "record_type": "consultingAgreement", "name": "Consulting Agreement with Jane Doe", "properties": {"counterpartyName": {"type": "string", "value": "Jane Doe"}}}, "POST", "/records", {"type": "consultingAgreement", "name": "Consulting Agreement with Jane Doe", "properties": {"counterpartyName": {"type": "string", "value": "Jane Doe"}}}),
    ({"operation": "update_record", "record_id": "IC-1", "name": "Updated agreement", "add_properties": {"counterpartyName": {"type": "string", "value": "Jane Doe"}}, "remove_properties": ["counterpartySigner"]}, "PATCH", "/records/IC-1", {"name": "Updated agreement", "addProperties": {"counterpartyName": {"type": "string", "value": "Jane Doe"}}, "removeProperties": ["counterpartySigner"]}),
    ({"operation": "delete_record", "record_id": "IC-1"}, "DELETE", "/records/IC-1", None),
    ({"operation": "get_record_schema"}, "GET", "/records/metadata", None),
    ({"operation": "list_entities", "search": "acme"}, "GET", "/entities", None),
    ({"operation": "get_entity", "entity_id": "ENTITY-1"}, "GET", "/entities/ENTITY-1", None),
    ({"operation": "create_entity", "name": "Ironclad Inc."}, "POST", "/entities", {"name": "Ironclad Inc.", "status": "ACTIVE"}),
    ({"operation": "update_entity", "entity_id": "ENTITY-1", "status": "INACTIVE", "remove_properties": ["entity_externalID"]}, "PATCH", "/entities/ENTITY-1", {"status": "INACTIVE", "removeProperties": ["entity_externalID"]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_ironclad_contract_requests(monkeypatch, config, method, path, body):
    reply = {"list": [{"id": "IC-1", "name": "Agreement"}], "page": config.get("page", 0), "pageSize": config.get("page_size", 20), "count": 35}
    requests = transport(monkeypatch, httpx.Response(204) if method == "DELETE" or config["operation"] in {"pause_workflow", "resume_workflow", "cancel_workflow"} else httpx.Response(200, json=reply))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/public/api/v1" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["x-as-user-email"] == "jane.doe@test.com"
    assert request.url.host == "ironcladapp.com"
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"] == "list_workflows":
        assert dict(request.url.params) == {"page": "2", "pageSize": "10", "status": "active", "search": "master services agreement"}
        assert result["next_page"] == 3 and result["complete"] is False
    if config["operation"] == "list_records":
        assert request.url.params["lastUpdated"] == "2018-05-08T00:00:00Z"
    if config["operation"] in {"list_workflow_schemas", "get_workflow_schema"}:
        assert request.url.params["form"] == "launch"


@pytest.mark.asyncio
async def test_ironclad_pagination_empty_and_terminal(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"list": [], "count": 0, "page": 0, "pageSize": 20}))
    result = await node({"operation": "list_records"}).execute({})
    assert result["items"] == [] and result["next_page"] is None and result["complete"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
async def test_ironclad_error_redaction_and_no_write_retries(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, json={"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as caught:
        await node({"operation": "create_entity", "name": "Acme"}).execute({})
    assert TOKEN not in str(caught.value) and str(code) in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_ironclad_write_timeout_unknown(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("private " + TOKEN, request=request)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="Write outcome unknown"):
        await node({"operation": "create_entity", "name": "Acme"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json={"list": {}})])
async def test_ironclad_rejects_bad_list_response(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_records"}).execute({})


@pytest.mark.asyncio
async def test_ironclad_regions_encoded_ids_and_secret_output(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"id": "example", "name": TOKEN}))
    result = await node({"operation": "get_record", "record_id": "a/b?x#z"}, api_host="eu1.ironcladapp.com").execute({})
    assert requests[0].url.host == "eu1.ironcladapp.com"
    assert requests[0].url.raw_path == b"/public/api/v1/records/a%2Fb%3Fx%23z"
    assert TOKEN not in str(result)


@pytest.mark.parametrize("field,value", [("api_host", "evil.example"), ("user_email", "a@example.com\r\nInjected: yes"), ("api_token", "https://example.com/token")])
def test_ironclad_credential_validation(field, value):
    with pytest.raises(ValidationError):
        native.IroncladAPITokenCredential.model_validate({**CREDENTIAL, field: value})


def test_ironclad_refuses_empty_updates_and_missing_set_value():
    for model, values in [(native.UpdateRecord, {"record_id": "IC-1"}), (native.UpdateEntity, {"entity_id": "ENTITY-1"}), (native.AttributeUpdate, {"path": "counterpartyName"})]:
        with pytest.raises(ValidationError):
            model(**values)


@pytest.mark.asyncio
async def test_ironclad_preserves_provider_authored_amendment_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/ironclad/update_record.json").read_text())
    requests = transport(monkeypatch, httpx.Response(200, json=fixture["body"]))
    result = await node({"operation": "update_record", "record_id": "IC-124", "name": "Amendment #1 - Updated Terms"}).execute({})
    assert len(requests) == 1
    assert result["data"]["parentId"] == "IC-123"
    assert result["data"]["parentLinkType"] == "amendment"
    assert result["data"]["properties"]["contractValue"]["value"] == {"amount": 150000, "currency": "USD"}


@pytest.mark.asyncio
@pytest.mark.parametrize("email", [None, "", "  "])
async def test_ironclad_personal_token_uses_own_identity(monkeypatch, email):
    requests = transport(monkeypatch, httpx.Response(200, json={"list": [], "count": 0}))
    await node({"operation": "list_records"}, user_email=email).execute({})
    assert "x-as-user-email" not in requests[0].headers
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
