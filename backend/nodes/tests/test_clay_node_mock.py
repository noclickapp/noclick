"""Contract tests for Clay's documented Public API request shapes."""

import json
from unittest.mock import Mock

import httpx
import pytest
from nodes.clay_node import (
    ClayApiKeyCredential,
    ClayCreateSearchConfig,
    ClayGetCreditBalanceConfig,
    ClayGetMeConfig,
    ClayGetRoutineResultsConfig,
    ClayGetSearchResultsConfig,
    ClayNode,
    ClayNodeConfig,
    ClayQueryTablesConfig,
    ClayRunRoutineConfig,
)


def _node(config):
    return ClayNode(
        node_id="clay-test",
        node_type="automation-clay",
        node_data={},
        config=ClayNodeConfig(
            config=config, credentials=ClayApiKeyCredential(api_key="test-secret")
        ),
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,method,path,body,response_status",
    [
        (ClayGetMeConfig(), "GET", "/me", None, 200),
        (ClayGetCreditBalanceConfig(), "GET", "/credits/balance", None, 200),
        (
            ClayCreateSearchConfig(query="companies where headcount > 10"),
            "POST",
            "/search/query-mode",
            {"query": "companies where headcount > 10"},
            200,
        ),
        (
            ClayGetSearchResultsConfig(search_id="search/one", limit=25),
            "POST",
            "/search/query-mode/search%2Fone/run",
            {"limit": 25},
            200,
        ),
        (
            ClayRunRoutineConfig(
                routine_id="routine/one",
                items_json='[{"id":"lead-1","inputs":{"domain":"example.com"}}]',
            ),
            "POST",
            "/routines/routine%2Fone/run",
            {"items": [{"id": "lead-1", "inputs": {"domain": "example.com"}}]},
            202,
        ),
        (
            ClayGetRoutineResultsConfig(
                routine_run_id="run/one", cursor="next", limit=12
            ),
            "GET",
            "/routines/run/run%2Fone/results",
            None,
            200,
        ),
        (
            ClayQueryTablesConfig(
                query_json='{"tables":[{"id":"table-1"}]}', limit=10, cursor="page-2"
            ),
            "POST",
            "/tables/query",
            {"query": {"tables": [{"id": "table-1"}]}, "limit": 10, "cursor": "page-2"},
            200,
        ),
    ],
)
async def test_public_api_contract(
    monkeypatch, config, method, path, body, response_status
):
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(
            response_status, json={"data": [{"id": "record-1"}], "cursor": "next"}
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.clay_node.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(reply), **kwargs
        ),
    )

    result = await _node(config).execute({})
    assert result["status"] == "success"
    assert result["status_code"] == response_status
    assert result["data"]["data"][0]["id"] == "record-1"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == method
    assert request.url.raw_path.decode().split("?", 1)[0] == f"/public/v0{path}"
    assert request.headers["clay-api-key"] == "test-secret"
    assert (json.loads(request.content) if request.content else None) == body
    if isinstance(config, ClayGetRoutineResultsConfig):
        assert dict(request.url.params) == {"limit": "12", "cursor": "next"}


@pytest.mark.asyncio
async def test_api_error_preserves_status_and_provider_message(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.clay_node.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, json={"message": "Rate limit exceeded"})
            ),
            **kwargs,
        ),
    )
    result = await _node(ClayGetMeConfig()).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 429
    assert result["error"] == "Rate limit exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("items_json", ["{}", "[]", '[{"id":"x"}]', "not-json"])
async def test_routine_items_are_validated_before_network(items_json):
    with pytest.raises(ValueError, match="Items|Each item"):
        await _node(
            ClayRunRoutineConfig(routine_id="routine-1", items_json=items_json)
        ).execute({})


@pytest.mark.asyncio
async def test_table_query_requires_tables_before_network():
    with pytest.raises(ValueError, match="tables"):
        await _node(ClayQueryTablesConfig(query_json="{}")).execute({})
