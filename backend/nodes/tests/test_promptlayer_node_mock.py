"""Exercise PromptLayer's request boundary without an account or live writes.

Wire fixtures pin body nesting, identifiers, pagination and asynchronous results;
negative cases cover credential shaping, input validation and provider rejection.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.promptlayer_node import PromptLayerAPIKeyCredential, PromptLayerNode, ROUTES

SECRET = "promptlayer-test-secret-123"
CASES = json.loads((Path(__file__).parent / "fixtures/promptlayer/wire_cases.json").read_text())["cases"]


def node(config):
    return NodeFactory.create_node(node_id="promptlayer-test", node_type="automation-promptlayer", node_data={
        "config": config, "credentials": {"credential_type": "promptlayer_api_key", "api_key": SECRET},
    })


def test_promptlayer_cases_cover_operations():
    assert len(CASES) == 25
    assert {case["config"]["operation"] for case in CASES} == set(ROUTES)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_promptlayer_wire(monkeypatch, case):
    calls = []

    async def request(self, method, url, **kwargs):
        calls.append(url)
        assert (method, url) == (case["method"], "https://api.promptlayer.com" + case["path"])
        assert kwargs["headers"]["X-API-KEY"] == SECRET
        assert kwargs["params"] == case["query"]
        assert kwargs.get("json") == case["body"]
        if case["status"] == 204:
            return httpx.Response(204)
        return httpx.Response(case["status"], json=case["response"])

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    result = await node(case["config"]).execute({})
    assert result == {"data": case["response"], "http_status": case["status"]}
    assert len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"operation": "get_prompt", "identifier": "x", "version": 2, "label": "prod"},
    {"operation": "get_prompt", "identifier": ".."},
    {"operation": "track_score", "request_id": 1, "score": 101},
    {"operation": "track_score", "request_id": 0, "score": 10},
    {"operation": "patch_prompt", "identifier": "x"},
    {"operation": "list_workflows", "page": 0},
    {"operation": "list_tables", "limit": 101},
    {"operation": "get_sheet", "table_id": "not-a-uuid", "sheet_id": "not-a-uuid"},
    {"operation": "publish_prompt", "prompt_name": "x", "prompt_template": {}},
])
def test_promptlayer_rejects_invalid_config(changes):
    assert not PromptLayerNode.validate_config({"config": changes})["valid"]


@pytest.mark.parametrize("value", ["https://api.promptlayer.com/key", "<token>", "Bearer key", "key\r\nheader", "   ", 123])
def test_promptlayer_rejects_bad_credential(value):
    with pytest.raises(ValueError):
        PromptLayerAPIKeyCredential(api_key=value)


def test_promptlayer_manual_credential():
    shaped = PromptLayerAPIKeyCredential(api_key="  " + SECRET + "  ")
    assert shaped.credential_type == "promptlayer_api_key"
    assert shaped.api_key == SECRET


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_promptlayer_preserves_rejection_without_secret_or_retry(monkeypatch, status):
    calls = []

    async def request(self, method, url, **kwargs):
        calls.append(url)
        return httpx.Response(status, text="Provider rejected " + SECRET)

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError, match=f"PromptLayer HTTP {status}: Provider rejected \\[redacted\\]"):
        await node({"operation": "list_workflows"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"success": False, "message": "rejected"}, {"error": "invalid"}, [], "invalid"])
async def test_promptlayer_rejects_error_envelopes(monkeypatch, body):
    async def request(self, method, url, **kwargs):
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError):
        await node({"operation": "list_workflows"}).execute({})


@pytest.mark.asyncio
async def test_promptlayer_confirmation_is_returned_without_resubmitting(monkeypatch):
    case = next(c for c in CASES if c["config"]["operation"] == "recalculate_sheet")
    confirmation = {"success": False, "requires_confirmation": True, "confirmation_token": "confirm-1", "affected_cell_count": 10000, "message": "Confirm this operation"}
    calls = []

    async def request(self, method, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json=confirmation)

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    assert (await node(case["config"]).execute({}))["data"] == confirmation
    assert len(calls) == 1
    assert "confirmation_token" not in calls[0]["json"]


@pytest.mark.asyncio
async def test_promptlayer_identifier_encoded_as_one_segment(monkeypatch):
    async def request(self, method, url, **kwargs):
        assert url == "https://api.promptlayer.com/prompt-templates/support%2Fresponse%3Fv%3D1"
        return httpx.Response(200, json={"id": 1})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    await node({"operation": "get_prompt", "identifier": "support/response?v=1"}).execute({})


@pytest.mark.asyncio
async def test_promptlayer_timeout_does_not_retry_write(monkeypatch):
    calls = []

    async def request(self, method, url, **kwargs):
        calls.append(url)
        raise httpx.ReadTimeout("Timeout after sending")

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError, match="Inspect the provider before retrying a write"):
        await node({"operation": "create_table", "title": "Regression suite"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_promptlayer_nested_response_secret_redacted(monkeypatch):
    async def request(self, method, url, **kwargs):
        return httpx.Response(200, json={"items": [{"metadata": {"key": SECRET}}]})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    result = await node({"operation": "list_workflows"}).execute({})
    assert SECRET not in json.dumps(result)
    assert result["data"]["items"][0]["metadata"]["key"] == "[redacted]"


def test_promptlayer_add_rows_count_and_column_ids():
    cfg = copy.deepcopy(next(c["config"] for c in CASES if c["config"]["operation"] == "add_rows"))
    cfg["count"] = 2
    assert not PromptLayerNode.validate_config({"config": cfg})["valid"]
    cfg["count"] = 1
    cfg["values"] = [{"not-a-column-uuid": "text"}]
    assert not PromptLayerNode.validate_config({"config": cfg})["valid"]
