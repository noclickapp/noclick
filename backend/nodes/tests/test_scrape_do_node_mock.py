"""Async contract requests through the real factory, using a synthetic token."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import scrape_do_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

JOB = "497f6eca-6276-4993-bfeb-53cbbbba6f08"
TOKEN = "synthetic-scrape-do-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="scrape-do-test", node_type="automation-scrape-do",
        node_data={"config": config, "credentials": {"credential_type": "scrape_do_api_token", "api_token": TOKEN}})


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
@pytest.mark.parametrize("config,method,path,response", [
    ({"operation": "create_job", "targets": ["https://httpbin.co/anything"]}, "POST", "/api/v1/jobs", {"JobID": JOB, "TaskIDs": ["task"]}),
    ({"operation": "list_jobs"}, "GET", "/api/v1/jobs", {"Jobs": [], "TotalCount": 0}),
    ({"operation": "get_job", "job_id": JOB}, "GET", "/api/v1/jobs/" + JOB, {"JobID": JOB, "Status": "pending"}),
    ({"operation": "cancel_job", "job_id": JOB}, "DELETE", "/api/v1/jobs/" + JOB, {"JobID": JOB, "Canceled": True}),
    ({"operation": "get_task", "job_id": JOB, "task_id": "task"}, "GET", "/api/v1/jobs/" + JOB + "/task", {"Content": "hello", "Base64EncodedContent": False}),
    ({"operation": "get_me"}, "GET", "/api/v1/me", {"TotalConcurrency": 5, "AvaliableCredits": 1000}),
])
async def test_all_contract_routes(monkeypatch, config, method, path, response):
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == response
    request = requests[0]
    assert len(requests) == 1 and request.method == method and request.url.path == path
    assert request.url.host == "q.scrape.do" and request.headers["X-Token"] == TOKEN
    if method == "POST":
        assert json.loads(request.content) == {"Targets": config["targets"], "Method": "GET"}
    if config["operation"] == "list_jobs":
        assert dict(request.url.params) == {"page_size": "10", "page": "1"}
        assert result["items"] == []


@pytest.mark.asyncio
async def test_all_create_fields_and_false_values(monkeypatch):
    requests = transport(monkeypatch, {"JobID": JOB})
    config = {"operation": "create_job", "targets": ["https://httpbin.co/anything"],
        "method": "POST", "body": "some sample post data", "geo_code": "us", "super_proxy": True,
        "headers": {"Content-Type": "application/json"}, "forward_headers": False,
        "render": {"CustomWait": 1000, "Screenshot": False}, "output": "markdown"}
    await node(config).execute({})
    body = json.loads(requests[0].content)
    assert body == {"Targets": config["targets"], "Method": "POST", "Body": config["body"],
        "GeoCode": "us", "Super": True, "Headers": config["headers"], "ForwardHeaders": False,
        "Render": {"CustomWait": 1000, "Screenshot": False}, "Output": "markdown"}


@pytest.mark.asyncio
async def test_list_filters_one_page_and_preserved_metadata(monkeypatch):
    requests = transport(monkeypatch, {"Jobs": [{"JobID": JOB}], "PageNumber": 2, "TotalPages": 15})
    result = await node({"operation": "list_jobs", "page": 2, "page_size": 25, "status": "success",
        "start_from": "2025-01-01T00:00:00Z", "sort": "start_time_asc"}).execute({})
    assert len(requests) == 1 and requests[0].url.params["start_from"] == "2025-01-01T00:00:00Z"
    assert result["data"]["TotalPages"] == 15 and result["items"][0]["JobID"] == JOB


@pytest.mark.asyncio
async def test_encoded_task_becomes_binary_file(monkeypatch):
    transport(monkeypatch, {"Base64EncodedContent": True, "Content": "aGVsbG8=", "ResponseHeaders": {"Content-Type": "text/plain"}})
    result = await node({"operation": "get_task", "job_id": JOB, "task_id": "task"}).execute({})
    assert "Content" not in result["data"]
    file = result["data"]["file"]
    assert isinstance(file, BinaryOutput) and file.data == b"hello" and file.content_type == "text/plain"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 404, 406, 429, 500])
async def test_errors_never_retried_or_reported_success(monkeypatch, status):
    requests = transport(monkeypatch, {"Error": "Rejected " + TOKEN, "Code": status}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "cancel_job", "job_id": JOB}).execute({})
    assert TOKEN not in str(error.value) and "Rejected" in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "create_job", "targets": []}, {"operation": "create_job", "targets": ["file:///etc/passwd"]},
    {"operation": "get_job", "job_id": "../me"}, {"operation": "get_task", "job_id": JOB, "task_id": "../me"},
    {"operation": "list_jobs", "page_size": 101}, {"operation": "list_jobs", "start_from": "2025-01-01"},
])
def test_invalid_config_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_has_default_type_and_password_field():
    credential = native.ScrapeDoTokenCredential(api_token=TOKEN)
    assert credential.credential_type == "scrape_do_api_token"
    assert native.ScrapeDoTokenCredential.model_json_schema()["properties"]["api_token"]["ui:widget"] == "password"


@pytest.mark.asyncio
async def test_provider_documented_response_fixtures(monkeypatch):
    from pathlib import Path
    fixtures = json.loads((Path(__file__).parent / "fixtures/scrape-do/documented_responses.json").read_text())
    cases = [
        ("POST /api/v1/jobs", {"operation": "create_job", "targets": ["https://httpbin.co/anything"]}),
        ("GET /api/v1/jobs", {"operation": "list_jobs"}),
        ("GET /api/v1/jobs/{jobID}", {"operation": "get_job", "job_id": JOB}),
        ("DELETE /api/v1/jobs/{jobID}", {"operation": "cancel_job", "job_id": JOB}),
        ("GET /api/v1/me", {"operation": "get_me"}),
    ]
    for key, config in cases:
        transport(monkeypatch, fixtures[key]["body"])
        result = await node(config).execute({})
        assert result["data"] == fixtures[key]["body"]
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_documented_unpadded_encoded_task_content(monkeypatch):
    from pathlib import Path
    fixtures = json.loads((Path(__file__).parent / "fixtures/scrape-do/documented_responses.json").read_text())
    transport(monkeypatch, fixtures["GET /api/v1/jobs/{jobID}/{taskID}"]["body"])
    result = await node({"operation": "get_task", "job_id": JOB, "task_id": "string"}).execute({})
    assert "Content" not in result["data"]
    assert isinstance(result["data"]["file"], BinaryOutput)
    assert result["data"]["file"].data == b"\xb2\xda\xe2\x9e"
