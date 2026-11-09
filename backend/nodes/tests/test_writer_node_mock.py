"""Writer contract wiring, pagination, response and credential boundaries."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import writer_node as native
from nodes.core.registry import NodeFactory

TOKEN = "writer_synthetic_test_key_123"
ID = "50daa3d0-e7d9-44a4-be42-b53e2379ebf7"
FILE = "7c36a365-392f-43ba-840d-8f3103b42572"
INPUTS = [{"id": "Topic", "value": ["Knowledge Graphs"]}]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="writer-fixture", node_type="automation-writer",
        node_data={"config": config, "credentials": {"credential_type": "writer_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("chat", {"messages": [{"role": "user", "content": "Summarize"}]}, {}, {"model": "palmyra-x5", "messages": [{"role": "user", "content": "Summarize"}], "stream": False}),
    ("generate_text", {"prompt": "Write an article"}, {}, {"model": "palmyra-x5", "prompt": "Write an article", "stream": False}),
    ("list_models", {}, {}, None),
    ("list_graphs", {"after": ID, "team_ids": [42, 43]}, {"limit": "50", "order": "desc", "after": ID, "team_ids": ["42", "43"]}, None),
    ("create_graph", {"name": "Example Knowledge Graph"}, {}, {"name": "Example Knowledge Graph"}),
    ("get_graph", {"graph_id": ID}, {}, None),
    ("update_graph", {"graph_id": ID, "description": "New description", "team_ids": []}, {}, {"description": "New description", "team_ids": []}),
    ("delete_graph", {"graph_id": ID}, {}, None),
    ("ask_graph", {"graph_ids": [ID], "question": "What is Bavencio?"}, {}, {"graph_ids": [ID], "question": "What is Bavencio?", "subqueries": False, "stream": False}),
    ("add_file_to_graph", {"graph_id": ID, "file_id": FILE}, {}, {"file_id": FILE}),
    ("remove_file_from_graph", {"graph_id": ID, "file_id": FILE}, {}, None),
    ("list_files", {"status": "completed", "graph_id": ID, "file_types": "pdf,docx", "before": FILE}, {"limit": "50", "order": "desc", "status": "completed", "graph_id": ID, "file_types": "pdf,docx", "before": FILE}, None),
    ("get_file", {"file_id": FILE}, {}, None),
    ("delete_file", {"file_id": FILE}, {}, None),
    ("retry_files", {"file_ids": [FILE]}, {}, {"file_ids": [FILE]}),
    ("list_applications", {"after": ID}, {"limit": "50", "order": "desc", "after": ID, "type": "generation"}, None),
    ("get_application", {"application_id": ID}, {}, None),
    ("generate_application", {"application_id": ID, "inputs": INPUTS}, {}, {"inputs": INPUTS, "stream": False}),
    ("list_jobs", {"application_id": ID, "offset": 50, "status": "in_progress"}, {"offset": "50", "limit": "50", "status": "in_progress"}, None),
    ("create_job", {"application_id": ID, "inputs": INPUTS}, {}, {"inputs": INPUTS}),
    ("get_job", {"job_id": ID}, {}, None),
    ("retry_job", {"job_id": ID}, {}, None),
    ("list_application_graphs", {"application_id": ID}, {}, None),
    ("associate_application_graphs", {"application_id": ID, "graph_ids": []}, {}, {"graph_ids": []}),
    ("parse_pdf", {"file_id": FILE}, {}, {"format": "markdown"}),
]
ROUTES = json.loads((Path(__file__).parent / "fixtures/writer/routes.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,params,body", CASES, ids=[c[0] for c in CASES])
async def test_all_writer_operations(monkeypatch, operation, arguments, params, body):
    response = {"data": [{"id": ID, "name": "Example Knowledge Graph"}], "has_more": True, "last_id": ID}
    requests = transport(monkeypatch, response, 202 if operation in {"create_job", "retry_job"} else 200)
    assert await node({"operation": operation, **arguments}).execute({}) == ({"job": response} if operation == "get_job" else response)
    assert len(requests) == 1
    request = requests[0]
    route = ROUTES[operation]
    path = route["path"]
    for key in ("application_id", "graph_id", "file_id", "job_id"):
        path = path.replace("{" + key + "}", arguments.get(key, ""))
    assert request.method == route["method"] and request.url.path == path
    assert request.url.host == "api.writer.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    actual = dict(request.url.params)
    if "team_ids" in params:
        actual["team_ids"] = request.url.params.get_list("team_ids")
    assert actual == params
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_writer_provider_errors_are_redacted_and_not_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError, match=f"Writer HTTP {status}") as exc:
        await node({"operation": "create_graph", "name": "Example"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error": "invalid_key"}, {}, {"data": {}}])
async def test_writer_connection_evidence_rejects_malformed_lists(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_graphs"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "list_graphs", "limit": 101},
    {"operation": "list_files", "after": FILE, "before": FILE},
    {"operation": "get_graph", "graph_id": "not-a-uuid"},
    {"operation": "get_file", "file_id": "../files"},
    {"operation": "update_graph", "graph_id": ID},
    {"operation": "ask_graph", "graph_ids": [], "question": "q"},
    {"operation": "generate_application", "application_id": ID, "inputs": [{"id": "Topic", "value": "wrong type"}]},
    {"operation": "parse_pdf", "file_id": FILE, "format": "html"},
    {"operation": "list_graphs", "base_url": "https://evil.example"},
])
def test_writer_invalid_config(config):
    with pytest.raises(ValidationError):
        native.WriterFullConfig.model_validate({"config": config})


def test_writer_manual_credential_and_evidence_contract():
    cred = native.WriterAPIKeyCredential(api_key=TOKEN)
    assert cred.credential_type == "writer_api_key"
    assert native.WriterAPIKeyCredential.model_json_schema()["required"] == ["api_key"]
    assert native.WriterNode.connection_evidence.operation == "list_graphs"
    assert {c[0] for c in CASES} == set(ROUTES) == set(native.ROUTES)


@pytest.mark.parametrize("token", ["Bearer abc", "https://app.writer.com", "<token>"])
def test_writer_invalid_key(token):
    with pytest.raises(ValidationError):
        native.WriterAPIKeyCredential(api_key=token)


@pytest.mark.asyncio
async def test_writer_failed_job_is_a_pollable_job_result(monkeypatch):
    body = {"id": ID, "application_id": ID, "status": "failed", "created_at": "2024-07-10T12:00:00Z", "error": "Generation failed"}
    transport(monkeypatch, body)
    assert await node({"operation": "get_job", "job_id": ID}).execute({}) == {"job": body}
