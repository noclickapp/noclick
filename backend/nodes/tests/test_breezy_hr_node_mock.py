"""Offline wire and failure semantics for Breezy HR v3; synthetic data only."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import breezy_hr_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-breezy-token-42"
COMPANY = "abc123def456"
POSITION = "def123abc456"
CANDIDATE = "fed123cba456"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="breezy-fixture", node_type="automation-breezy-hr",
        node_data={"config": config, "credentials": credentials or {"credential_type": native.TYPE, "api_token": TOKEN}})


def transport(monkeypatch, body, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, **({"json": body} if body is not None else {}), headers=headers)
    def client(**kwargs):
        assert kwargs["verify"] is True and kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("get_user", {}, "GET", "/user", {}, None, {"_id": COMPANY, "name": "Test recruiter"}),
    ("list_companies", {}, "GET", "/companies", {}, None, [{"_id": COMPANY, "name": "Test company"}]),
    ("get_company", {}, "GET", f"/company/{COMPANY}", {}, None, {"_id": COMPANY}),
    ("list_departments", {}, "GET", f"/company/{COMPANY}/departments", {}, None, [{"id": "sales", "name": "Sales"}]),
    ("list_pipelines", {}, "GET", f"/company/{COMPANY}/pipelines", {}, None, {"default": {"stages": [{"id": "applied"}]}}),
    ("get_pipeline", {"pipeline_id": "default"}, "GET", f"/company/{COMPANY}/pipeline/default", {}, None, [{"id": "applied", "name": "Applied"}]),
    ("list_positions", {"state": "draft", "page_size": 1, "page": 2}, "GET", f"/company/{COMPANY}/positions", {"state": "draft", "page_size": "1", "page": "2"}, None, [{"_id": POSITION}]),
    ("get_position", {}, "GET", f"/company/{COMPANY}/position/{POSITION}", {}, None, {"_id": POSITION}),
    ("create_position", {"name": "Engineer", "description": "Build products", "type": "fullTime", "location": {"country": "US", "state": "CA"}}, "POST", f"/company/{COMPANY}/positions", {}, {"name": "Engineer", "description": "Build products", "type": "fullTime", "location": {"country": "US", "state": "CA"}}, {"_id": POSITION}),
    ("update_position", {"name": "Engineer II", "tags": []}, "PUT", f"/company/{COMPANY}/position/{POSITION}", {}, {"name": "Engineer II", "tags": []}, {"_id": POSITION}),
    ("set_position_state", {"state": "published"}, "PUT", f"/company/{COMPANY}/position/{POSITION}/state", {}, {"state": "published"}, None),
    ("get_position_team", {}, "GET", f"/company/{COMPANY}/position/{POSITION}/team", {}, None, []),
    ("search_candidates", {"email_address": "test+recruit@example.com"}, "GET", f"/company/{COMPANY}/candidates/search", {"email_address": "test+recruit@example.com"}, None, []),
    ("list_candidates", {"stage_id": "applied", "page_size": 50, "page": 1}, "GET", f"/company/{COMPANY}/position/{POSITION}/candidates", {"stage_id": "applied", "page_size": "50", "page": "1"}, None, []),
    ("add_candidate", {"name": "Test Person", "email_address": "person@example.com"}, "POST", f"/company/{COMPANY}/position/{POSITION}/candidates", {"stage_actions_enabled": "false"}, {"name": "Test Person", "email_address": "person@example.com", "origin": "sourced"}, {"_id": CANDIDATE}),
    ("get_candidate", {}, "GET", f"/company/{COMPANY}/position/{POSITION}/candidate/{CANDIDATE}", {}, None, {"_id": CANDIDATE}),
    ("update_candidate", {"tags": [], "summary": "Interview complete"}, "PUT", f"/company/{COMPANY}/position/{POSITION}/candidate/{CANDIDATE}", {}, {"tags": [], "summary": "Interview complete"}, {"_id": CANDIDATE}),
    ("set_candidate_stage", {"stage_id": "hired"}, "PUT", f"/company/{COMPANY}/position/{POSITION}/candidate/{CANDIDATE}/stage", {}, {"stage_id": "hired"}, None),
    ("get_candidate_stream", {"skip": 50}, "GET", f"/company/{COMPANY}/position/{POSITION}/candidate/{CANDIDATE}/stream", {"skip": "50"}, None, [{"type": "companyNotePosted", "first_activity": True}]),
    ("post_candidate_note", {"body": "Schedule interview"}, "POST", f"/company/{COMPANY}/position/{POSITION}/candidate/{CANDIDATE}/stream", {}, {"body": "Schedule interview"}, {"type": "companyNotePosted"}),
]


def config_for(operation, extra):
    config = {"operation": operation, "company_id": COMPANY, "position_id": POSITION, "candidate_id": CANDIDATE}
    # Select only actual path fields from the explicitly pinned route fixture.
    route = json.loads((Path(__file__).parent / "fixtures/breezy-hr/routes.json").read_text())[operation]
    return {**{k: v for k, v in config.items() if k == "operation" or "{" + k + "}" in route["path"]}, **extra}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,method,path,query,body,response", CASES, ids=["breezy-hr-" + c[0] for c in CASES])
async def test_wire_contract(monkeypatch, operation, extra, method, path, query, body, response):
    requests = transport(monkeypatch, response, 204 if response is None else 200)
    result = await node(config_for(operation, extra)).run({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url).startswith(native.BASE)
    assert request.url.path == "/v3" + path and dict(request.url.params) == query
    assert request.headers["Authorization"] == TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in str(result)
    if operation == "list_positions":
        assert result["next_page"] == 3 and result["complete"] is False
    if operation == "get_candidate_stream":
        assert result["complete"] and result["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 401, 403, 409, 429, 500])
async def test_failed_or_partial_write_never_retries_or_reports_completed(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"type": "failure", "message": "Denied " + TOKEN}}, status, {"Retry-After": "60"})
    result = await node({"operation": "add_candidate", "company_id": COMPANY, "position_id": POSITION, "name": "Test"}).run({})
    assert result["status"] != "success" and result["success"] is False and result["http_status"] == status and len(requests) == 1
    assert TOKEN not in str(result)
    if status == 202:
        assert result["write_outcome"] == "partial"
    if status == 429:
        assert result["retry_after"] == "60"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": {"message": TOKEN}}, {}, "bad"])
async def test_evidence_refuses_malformed_or_error_list(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_companies"}).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_evidence_account_labels(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, [{"_id": COMPANY, "name": "Recognisable Company"}])
    evidence = await collect_evidence(node_type="automation-breezy-hr", user_id="00000000-0000-0000-0000-000000000001", credential_data={"credential_type": native.TYPE, "api_token": TOKEN})
    assert evidence.reachable is True and evidence.samples[0].label == "Recognisable Company"


@pytest.mark.parametrize("config", [
    {"operation": "get_company", "company_id": "../other"},
    {"operation": "list_positions", "company_id": COMPANY, "page": 2},
    {"operation": "list_candidates", "company_id": COMPANY, "position_id": POSITION, "page_size": 51},
    {"operation": "add_candidate", "company_id": COMPANY, "position_id": POSITION, "name": "Test", "origin": "applied"},
])
def test_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        native.BreezyHRNode.parse_config({"config": config})


def test_token_cleaning_and_hidden_secret_errors():
    assert native.BreezyHRTokenCredential(api_token="  " + TOKEN + "  ").api_token == TOKEN
    with pytest.raises(ValidationError) as error:
        native.BreezyHRTokenCredential(api_token="Bearer " + TOKEN)
    assert TOKEN not in str(error.value)
