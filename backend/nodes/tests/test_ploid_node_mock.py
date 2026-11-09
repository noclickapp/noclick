"""Ploid transport contract regressions. No live provider credentials are used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ploid_node as ploid
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/ploid/requests.json").read_text())
AUTH = {"credential_type": "ploid_api_key", "api_key": "synthetic-ploid-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    def respond(request):
        requests.append(request)
        status, body, headers = replies.pop(0)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ploid, "guarded_async_client", client)
    return requests, replies


def node(config, auth=None):
    return NodeFactory.create_node(node_id="ploid-fixture", node_type="automation-ploid",
        node_data={"config": config, "credentials": AUTH if auth is None else auth})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_ploid_one_request_per_operation_preserves_provider_result(case, transport):
    requests, replies = transport
    # Partial, async, cursor, provenance and usage data must all survive intact.
    response = {"data": {"status": "running", "cells": [{"status": "not_found"}]},
                "meta": {"next_cursor": "next-opaque", "usage": {"billed": [], "not_found": ["phone"]}}}
    replies.append((202 if case["operation"] == "create_dataset" else 200, response, {}))
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.host == "api.ploid.com"
    assert request.url.path == case["path"]
    assert request.headers["x-api-key"] == AUTH["api_key"] and "authorization" not in request.headers
    assert dict(request.url.params) == case.get("query", {})
    if "body" in case:
        assert json.loads(request.content) == case["body"]
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_ploid_paid_post_has_explicit_idempotency_key_and_no_retries(transport):
    requests, replies = transport
    replies.append((429, {"error": {"message": "Rate limit exceeded"}}, {"Retry-After": "5"}))
    with pytest.raises(ValueError, match="Rate limit exceeded"):
        await node({"operation": "detect_technologies", "domain": "example.com", "idempotency_key": "job-1"}).execute({})
    assert len(requests) == 1 and requests[0].headers["Idempotency-Key"] == "job-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,headers", [
    (401, {"error": "synthetic-ploid-key rejected"}, {}),
    (302, {}, {"Location": "https://foreign.test"}),
    (200, {"error": "refused"}, {}),
    (200, [], {}),
    (200, {}, {"Content-Type": "text/html"}),
])
async def test_ploid_errors_never_become_connection_success(status, body, headers, transport):
    requests, replies = transport
    replies.append((status, body, headers))
    with pytest.raises(ValueError) as caught:
        await node({"operation": "get_account_profile"}).execute({})
    assert AUTH["api_key"] not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_monitor", "monitor_id": "../account/profile"},
    {"operation": "get_person_run", "run_id": "a/b"},
    {"operation": "get_dataset", "dataset_id": "https://foreign.test"},
    {"operation": "update_monitor", "monitor_id": "mon_1"},
    {"operation": "resolve_person", "name": "Ada"},
    {"operation": "enrich_person", "email": "ada@example.com", "person_id": "person_1", "fields": ["phone"]},
    {"operation": "search_people", "query": "engineers", "offset": 5, "type": "deep"},
    {"operation": "get_account_profile", "url": "https://foreign.test"},
])
def test_ploid_invalid_inputs_refused_before_transport(config, transport):
    with pytest.raises((ValueError, ValidationError)):
        node(config)
    assert transport[0] == []


def test_ploid_manual_credential_default_and_foreign_type_refusal():
    assert ploid.PloidAPIKeyCredential(api_key="synthetic-ploid-key").credential_type == "ploid_api_key"
    with pytest.raises((ValueError, ValidationError)):
        node({"operation": "get_account_profile"}, {**AUTH, "credential_type": "other_api_key"})
    assert len(CASES) == len(ploid.ROUTES) == 25


@pytest.mark.asyncio
async def test_ploid_documented_empty_delete_acknowledgement(monkeypatch):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kwargs)
    monkeypatch.setattr(ploid, "guarded_async_client", client)
    result = await node({"operation": "delete_monitor", "monitor_id": "mon_1"}).execute({})
    assert result == {"http_status": 200}
