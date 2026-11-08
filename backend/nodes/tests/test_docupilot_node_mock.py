"""Offline request-contract, pagination, credential and failure regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import docupilot_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-docupilot-token"
CREDENTIAL = {"credential_type": "docupilot_api_token", "api_token": TOKEN, "workspace_id": "workspace-owned"}
API = "/dashboard/api/v2/"
CASES = [
    ("get_me", {}, "GET", "/dashboard/accounts/v2/users/me/", None),
    ("get_current_organization", {}, "GET", "/dashboard/accounts/v2/organization/current/", None),
    ("list_templates", {"page": 2, "search": "Invoice + receipt", "status": "active"}, "GET", API + "templates/", None),
    ("get_template", {"template_id": 42}, "GET", API + "templates/42/", None),
    ("trash_template", {"template_id": 42}, "DELETE", API + "templates/42/", None),
    ("copy_template", {"template_id": 42, "title": "Copy", "folder": None}, "POST", API + "templates/42/copy/", {"title": "Copy", "folder": None}),
    ("generate_document", {"template_id": 42, "data": {"customer": "Ada"}, "includeUrl": False}, "POST", API + "templates/42/generate/", {"customer": "Ada"}),
    ("publish_latest_template_version", {"template_id": 42}, "POST", API + "templates/42/publish/", None),
    ("restore_template_from_trash", {"template_id": 42}, "PUT", API + "templates/42/restore/", None),
    ("get_template_schema", {"template_id": 42, "version_id": "live"}, "GET", API + "templates/42/schema/", None),
    ("get_test_data", {"template_id": 42}, "GET", API + "templates/42/test_data/", None),
    ("test_document_generation", {"template_id": 42, "data": {"invoice": 101}, "use_data": False}, "POST", API + "templates/42/test/", {"invoice": 101}),
    ("list_template_deliveries", {"template_id": 42}, "GET", API + "templates/42/deliveries/", None),
    ("list_template_versions", {"template_id": 42}, "GET", API + "templates/42/versions/", None),
    ("list_folders", {"permission": "write"}, "GET", API + "folders/", None),
    ("create_folder", {"name": "Invoices"}, "POST", API + "folders/", {"name": "Invoices"}),
    ("update_folder", {"folder_id": 7, "name": "Paid invoices"}, "PUT", API + "folders/7/", {"name": "Paid invoices"}),
    ("delete_folder", {"folder_id": 7}, "DELETE", API + "folders/7/", None),
    ("list_content_blocks", {"search": "Terms"}, "GET", API + "content_blocks/", None),
    ("get_content_block", {"content_block_id": 9}, "GET", API + "content_blocks/9/", None),
    ("delete_content_block", {"content_block_id": 9}, "DELETE", API + "content_blocks/9/", None),
    ("copy_content_block", {"content_block_id": 9, "name": "Terms copy", "key": "terms_copy", "description": "Standard terms"}, "POST", API + "content_blocks/9/copy/", {"name": "Terms copy", "key": "terms_copy", "description": "Standard terms"}),
    ("get_created_documents_history", {}, "GET", API + "history/", None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None):
    return NodeFactory.create_node(node_id="docupilot-fixture", node_type="automation-docupilot",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": CREDENTIAL})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("op,config,method,path,body", CASES)
async def test_each_operation_has_one_exact_contract_request(monkeypatch, op, config, method, path, body):
    fixture = json.loads((Path(__file__).parent / "fixtures/docupilot/responses.json").read_text())
    status = 204 if method == "DELETE" else 201 if op in {"copy_template", "generate_document", "test_document_generation", "create_folder", "copy_content_block"} else 200
    response = fixture[op] if op in fixture else {"id": 42}
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json=response) if status != 204 else httpx.Response(204))
    output = await node(op, config).execute({})
    assert output["status"] == "success" and output["data"] == (None if status == 204 else response)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path and req.url.host == "api-us1.docupilot.app"
    assert req.headers["Authorization"] == "Basic " + TOKEN
    assert req.headers.get("X-Workspace") == (None if op in {"get_me", "get_current_organization"} else "workspace-owned")
    assert (json.loads(req.content) if req.content else None) == body
    if body is not None:
        assert req.headers["content-type"] == "application/json"
    if op == "generate_document":
        assert dict(req.url.params) == {"includeUrl": "false", "download": "false"}
    if op == "test_document_generation":
        assert dict(req.url.params) == {"use_data": "false"}
    if op == "list_templates":
        assert dict(req.url.params) == {"page": "2", "search": "Invoice + receipt", "status": "active"}


@pytest.mark.asyncio
async def test_pagination_reports_page_without_following_provider_url(monkeypatch):
    body = {"count": 2, "next": "https://foreign.test/steal", "previous": None, "results": [{"id": 42, "title": "Invoice"}]}
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    output = await node("list_templates", {"page": 2}).execute({})
    assert len(requests) == 1 and output["next_page"] == 3 and output["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_redact_token_and_never_retry_write(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"detail": "Rejected " + TOKEN}, headers={"Location": "https://foreign.test"}))
    with pytest.raises(ValueError) as error:
        await node("create_folder", {"name": "Invoices"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Login</html>"), httpx.Response(200, json={"error": "Rejected"}), httpx.Response(200, json="wrong shape")])
async def test_invalid_success_is_not_connection_evidence(monkeypatch, response):
    transport(monkeypatch, lambda req: response)
    with pytest.raises(ValueError):
        await node("get_me").execute({})


@pytest.mark.parametrize("cfg", [{"operation": "get_template", "template_id": "../escape"}, {"operation": "get_template", "template_id": 0}, {"operation": "list_templates", "page": 0}, {"operation": "create_folder", "name": "a" * 51}, {"operation": "generate_document", "template_id": 42, "data": []}, {"operation": "unsupported"}])
def test_invalid_configs_rejected_before_http(cfg):
    with pytest.raises(ValueError):
        native.DocupilotNode.parse_config({"config": cfg, "credentials": CREDENTIAL})


def test_credential_schema_and_wrong_family():
    assert native.DocupilotNode.connection_evidence.identity_operation == "get_me"
    assert len(CASES) == len(native.ROUTES) == 23
    with pytest.raises(ValidationError):
        native.DocupilotAPITokenCredential.model_validate({**CREDENTIAL, "api_token": "Basic token"})
    with pytest.raises(ValueError):
        native.DocupilotNode.parse_config({"config": {"operation": "get_me"}, "credentials": {**CREDENTIAL, "credential_type": "other_token"}})
