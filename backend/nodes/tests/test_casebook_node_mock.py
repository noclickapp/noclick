"""Replay the pinned collection's verbatim responses for every exposed operation."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import casebook_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/casebook/postman_examples.json").read_text())
TOKEN = "casebook-test-access-token"
RECORD_ID = "d5196910-134f-493f-9687-2c75118b0454"
ORIGINAL_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def config_for(operation):
    config = {"operation": operation}
    _, _, _, action = native.OPERATIONS[operation]
    if action in {"get", "update"}:
        config["record_id"] = RECORD_ID
    if action in {"create", "update"}:
        for field in native.WRITE_FIELDS[operation]["attributes"]:
            config[field] = (RECORD_ID if field.endswith("_id") else
                             "2026-01-02" if field in {"started_at", "ended_at", "date_of_birth"} else
                             False if field == "ended" else "Example record")
        for field in native.WRITE_FIELDS[operation]["relationships"]:
            config[field] = RECORD_ID
    return config


def node(config):
    return NodeFactory.create_node(node_id="casebook-test", node_type="automation-casebook",
        node_data={"config": config, "credentials": {"credential_type": "casebook_bearer_token", "access_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return ORIGINAL_CLIENT(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


CASES = [(operation, index) for operation, item in FIXTURE["items"].items()
         for index in range(len(item["response"]))]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,index", CASES)
async def test_every_saved_postman_response(monkeypatch, operation, index):
    example = FIXTURE["items"][operation]["response"][index]
    requests = transport(monkeypatch, lambda r: httpx.Response(example["code"],
        content=(example.get("body") or "").encode(),
        headers=[(h["key"], h["value"]) for h in example.get("header", [])]))
    config = config_for(operation)
    result = await node(config).execute({})
    method, template, resource_type, action = native.OPERATIONS[operation]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url) == native.BASE_URL + template.format(**config)
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["accept"] == native.MEDIA_TYPE
    assert request.headers["content-type"] == native.MEDIA_TYPE
    assert not request.url.query
    assert TOKEN not in str(result)
    if method == "GET":
        assert not request.content
    else:
        fields = native.WRITE_FIELDS[operation]
        assert json.loads(request.content) == {"data": {"type": resource_type,
            "attributes": {f: config[f] for f in fields["attributes"]},
            **({"relationships": {relation: {"data": {"type": typ, "id": config[field]}}
                for field, (relation, typ) in fields["relationships"].items()}}
               if fields["relationships"] else {})}}
    if 200 <= example["code"] < 300:
        expected = {**json.loads(example["body"]), "status": "success"}
        if operation == "list_cases":
            expected["options"] = [{"label": r["attributes"].get("name") or r["id"], "value": r["id"]}
                                   for r in expected["data"]]
        assert result == expected
    else:
        assert result["status"] == "error"
        assert result["http_status"] == example["code"]
        assert result["error"] == example["body"][:2000]


def test_manual_credential_defaults_and_evidence():
    credential = native.CasebookBearerTokenCredential(access_token="  " + TOKEN + "\n")
    assert credential.access_token == TOKEN
    assert credential.credential_type == "casebook_bearer_token"
    assert native.CasebookNode.connection_evidence.operation == "list_cases"
    assert set(native.OPERATIONS) == set(FIXTURE["items"])


@pytest.mark.parametrize("token", ["", "Bearer abc", "<token>", "https://casebook.net/key", "abc\r\nx: 1", "nonasciié"])
def test_bad_token_refused(token):
    with pytest.raises((ValueError, ValidationError)):
        native.CasebookBearerTokenCredential(access_token=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_case", "record_id": "../people"},
    {"operation": "update_case", "record_id": RECORD_ID},
    {"operation": "create_person", "first_name": "Pat"},
    {"operation": "create_service_enrollment", "person_id": RECORD_ID},
    {"operation": "list_cases", "url": "https://example.com"},
    {"operation": "create_case", "name": "New", "roles": ["admin"]},
])
def test_invalid_config_refused_before_network(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_partial_patch_only_sends_supplied_fields(monkeypatch):
    example = FIXTURE["items"]["update_case"]["response"][0]
    requests = transport(monkeypatch, lambda r: httpx.Response(example["code"], text=example["body"]))
    result = await node({"operation": "update_case", "record_id": RECORD_ID, "description": "Revised"}).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"data": {"type": "cases", "attributes": {"description": "Revised"}}}


@pytest.mark.asyncio
async def test_network_failure_does_not_retry_write(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("timeout", request=request)
    requests = transport(monkeypatch, fail)
    result = await node({"operation": "create_case", "name": "New case"}).execute({})
    assert result["status"] == "error" and len(requests) == 1


@pytest.mark.asyncio
async def test_truncated_saved_response_is_not_success(monkeypatch):
    example = FIXTURE["items"]["get_case"]["response"][0]
    transport(monkeypatch, lambda r: httpx.Response(200, text=example["body"][:40]))
    assert (await node({"operation": "get_case", "record_id": RECORD_ID}).execute({}))["status"] == "error"
