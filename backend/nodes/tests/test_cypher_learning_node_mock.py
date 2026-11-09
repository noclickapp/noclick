"""Offline wire regressions against CYPHER's API v3 contract and examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import cypher_learning_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-cypher-key-5291"
CREDENTIAL = {"credential_type": "cypher_learning_api_key", "portal_url": "https://school.neolms.com", "api_key": TOKEN}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/cypher-learning/examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="cypher-test", node_type="automation-cypher-learning",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("list_users", {}, "GET", "/users", None),
    ("get_user", {"user_id": 123}, "GET", "/users/123", None),
    ("create_user", {"first_name": "Sally", "last_name": "Johnson", "roles": ["student"]}, "POST", "/users", {"first_name": "Sally", "last_name": "Johnson", "roles": ["student"]}),
    ("update_user", {"user_id": 123, "archived": False}, "PATCH", "/users/123", {"archived": False}),
    ("list_classes", {}, "GET", "/classes", None),
    ("get_class", {"class_id": 27}, "GET", "/classes/27", None),
    ("list_class_students", {"class_id": 27}, "GET", "/classes/27/students", None),
    ("get_class_student", {"class_id": 27, "user_id": 123}, "GET", "/classes/27/students/123", None),
    ("add_class_student", {"class_id": 27, "user_id": 123}, "POST", "/classes/27/students", {"user_id": 123}),
    ("update_class_student", {"class_id": 27, "user_id": 123, "completed": False, "override_percent": 0}, "PATCH", "/classes/27/students/123", {"completed": False, "override_percent": 0}),
    ("remove_class_student", {"class_id": 27, "user_id": 123}, "DELETE", "/classes/27/students/123", None),
    ("list_groups", {}, "GET", "/groups", None),
    ("get_group", {"group_id": 123}, "GET", "/groups/123", None),
    ("create_group", {"name": "AI Enthusiasts"}, "POST", "/groups", {"name": "AI Enthusiasts"}),
    ("update_group", {"group_id": 123, "private": False}, "PATCH", "/groups/123", {"private": False}),
    ("list_group_members", {"group_id": 123}, "GET", "/groups/123/members", None),
    ("add_group_member", {"group_id": 123, "user_id": 123}, "POST", "/groups/123/members", {"user_id": 123}),
    ("remove_group_member", {"group_id": 123, "user_id": 123}, "DELETE", "/groups/123/members/123", None),
    ("list_organizations", {}, "GET", "/organizations", None),
    ("get_organization", {"organization_id": 123}, "GET", "/organizations/123", None),
    ("list_class_assignments", {"class_id": 27}, "GET", "/classes/27/assignments", None),
    ("list_assignment_grades", {"class_id": 27, "assignment_id": 123}, "GET", "/classes/27/assignments/123/grades", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_all_operations_one_contract_request(monkeypatch, operation, config, method, path, body):
    payload = [EXAMPLES["user"]] if operation.startswith("list_") else EXAMPLES["group"] if "group" in operation else EXAMPLES["user"]
    status = 201 if method == "POST" else 204 if method == "DELETE" else 200
    requests = transport(monkeypatch, payload, status)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v3" + path
    assert request.url.host == "school.neolms.com" and request.headers["x-api-key"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    assert (json.loads(request.content) if request.content else None) == body
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"$limit": "10", "$offset": "0"}
        assert result["data"] == payload and result["next_offset"] is None
    elif operation == "create_user":
        assert json.loads(request.url.params["$options"]) == {"send_login_instructions": False}
    elif operation == "add_class_student":
        assert json.loads(request.url.params["$options"]) == {"send_notification": False, "reenroll": "never", "increment_seats": False}
    else:
        assert not request.url.params
    if operation == "update_class_student":
        assert result["status_change_pending"]


@pytest.mark.asyncio
async def test_explicit_page_and_notification_options(monkeypatch):
    requests = transport(monkeypatch, [EXAMPLES["user"]])
    result = await node({"operation": "list_users", "offset": 50, "limit": 1}).execute({})
    assert result["next_offset"] == 51 and result["may_have_more"]
    assert dict(requests[0].url.params) == {"$limit": "1", "$offset": "50"}
    requests = transport(monkeypatch, EXAMPLES["user"], 201)
    await node({"operation": "add_class_student", "class_id": 27, "user_id": 123,
        "send_notification": True, "reenroll": "only_completed", "increment_seats": True}).execute({})
    assert json.loads(requests[0].url.params["$options"]) == {"send_notification": True, "reenroll": "only_completed", "increment_seats": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_and_redirects_do_not_complete_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Provider says: " + TOKEN}, status)
    result = await node({"operation": "list_classes"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Provider says: [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"message": "rejected"}, [1], None])
async def test_bad_list_response_is_not_connection_evidence(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_classes"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [("update_user", {"user_id": 123}), ("update_group", {"group_id": 123}), ("update_class_student", {"class_id": 27, "user_id": 123})])
async def test_empty_update_makes_no_request(monkeypatch, operation, config):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": operation, **config}).execute({})
    assert requests == []


@pytest.mark.parametrize("url", ["http://school.neolms.com", "https://a:b@school.neolms.com", "https://school.neolms.com/api/v3", "https://127.0.0.1", "https://school.neolms.com:443", "https://school.neolms.com?api_key=key", "https://school.neolms.com/#x"])
def test_invalid_portal_origins(url):
    with pytest.raises(ValidationError):
        native.CypherLearningAPIKeyCredential.model_validate({**CREDENTIAL, "portal_url": url})


def test_manual_credential_default_and_normalization():
    data = native.CypherLearningAPIKeyCredential(portal_url=" https://School.neolms.com/ ", api_key=TOKEN)
    assert data.credential_type == "cypher_learning_api_key" and data.portal_url == "https://school.neolms.com"
    assert native.CypherLearningAPIKeyCredential(portal_url="https://academy.example.com", api_key=TOKEN).portal_url == "https://academy.example.com"
    assert len(native.ROUTES) == 22
    with pytest.raises(ValidationError):
        native.CypherLearningAPIKeyCredential(**{**CREDENTIAL, "api_key": "https://school.neolms.com/key"})
    assert native.CypherLearningNode.connection_evidence.operation == "list_classes"


def test_legacy_workflow_credential_metadata_is_not_an_api_input():
    config = {"config": {"operation": "list_users", "credentialIds": {"cypher_learning_api_key": "saved-id"}},
        "credentials": CREDENTIAL}
    assert native.CypherLearningNode.validate_config(config)["valid"]
    parsed = native.CypherLearningNode.parse_config(config)
    assert "credentialIds" not in parsed.config.model_dump()
