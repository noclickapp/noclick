"""New Relic node contracts. HTTP responses here are mocks, not live UI QA."""

from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.agent.node_op_tools import list_node_operations, node_supports_op_tools
from nodes.new_relic_node import (
    OPERATIONS, NewRelicNode, NewRelicNodeConfig, NewRelicUserKeyCredential,
    _graphql, _graphql_operation, _rest,
)


def _node(action: str, **values):
    return NewRelicNode(
        node_id="newrelic", node_type="automation-new-relic", node_data={},
        config=NewRelicNodeConfig(
            config={"operation": action, **values},
            credentials={"api_key": "private-test-key", "region": "eu"},
        ),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


def _required(action: str):
    samples = {
        "account_id": 123, "application_id": 456, "entity_guid": "abc/def",
        "nrql": "SELECT count(*) FROM Transaction", "search_query": "name LIKE 'app'",
        "dashboard_json": '{"name":"QA","permissions":"PUBLIC_READ_WRITE","pages":[{"name":"Page 1","widgets":[]}]}',
        "policy_name": "QA alerts", "policy_id": "99", "confirm_delete": True,
    }
    return {name: samples[name] for name in OPERATIONS[action].required}


def test_schema_exposes_operations_and_account_proof():
    schema = NewRelicNode.get_config_schema()
    assert len(OPERATIONS) == 19
    assert len(schema["properties"]["config"]["oneOf"]) == 19
    assert NewRelicNode.connection_evidence.field == "account_id"
    assert "api_key" in schema["$defs"]["NewRelicUserKeyCredential"]["properties"]
    assert node_supports_op_tools("automation-new-relic")
    assert len(list_node_operations("automation-new-relic")) == 19


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(OPERATIONS))
async def test_every_action_dispatches_to_new_relic_only(action):
    captured = {}

    async def graph(credential, document, variables=None):
        captured.update(kind="graph", region=credential.region, document=document, variables=variables)
        return {"actor": {"accounts": [{"id": 123, "name": "NoClick"}]}}

    async def rest(credential, path):
        captured.update(kind="rest", region=credential.region, path=path)
        return {"applications": []}

    with patch("nodes.new_relic_node._graphql", side_effect=graph), patch("nodes.new_relic_node._rest", side_effect=rest):
        result = await _node(action, **_required(action)).execute({})
    assert captured["region"] == "eu"
    assert captured["kind"] == ("rest" if action in {
        "list_applications", "get_application", "list_deployments", "list_application_metrics",
    } else "graph")
    assert result["operation"] == action
    assert result["status"] == "success"


def test_nrql_and_dashboard_use_bound_variables():
    document, variables = _graphql_operation("run_nrql", {"account_id": 123, "nrql": 'SELECT count(*) FROM Transaction WHERE appName = "a"'})
    assert "$nrql: Nrql!" in document
    assert variables["nrql"].endswith('"a"')

    document, variables = _graphql_operation("create_dashboard", {
        "account_id": 123, "dashboard_json": '{"name":"A dashboard","pages":[{"name":"Page 1","widgets":[]}]}',
    })
    assert "$dashboard" in document
    assert variables["dashboard"]["name"] == "A dashboard"


@pytest.mark.asyncio
async def test_invalid_dashboard_and_unconfirmed_deletion_fail_before_http():
    with patch("nodes.new_relic_node._graphql") as graph:
        with pytest.raises(ValueError, match="valid JSON"):
            await _node("create_dashboard", account_id=123, dashboard_json="{").execute({})
        with pytest.raises(ValueError, match="Confirm deletion"):
            await _node("delete_dashboard", entity_guid="g", confirm_delete=False).execute({})
    graph.assert_not_called()


@pytest.mark.asyncio
async def test_account_picker_matches_runtime_contract_and_filters_search():
    async def graph(credential, document, variables=None):
        return {"actor": {"accounts": [{"id": 123, "name": "NoClick QA"}, {"id": 456, "name": "Other"}]}}

    with patch("nodes.new_relic_node._graphql", side_effect=graph):
        result = await NewRelicNode.load_field_options(
            "account_id", {"api_key": "key", "region": "us"}, page_token=None, search="noclick",
        )
    assert result == {"options": [{"value": "123", "label": "NoClick QA"}], "next_page_token": None}


@pytest.mark.asyncio
async def test_nerdgraph_uses_region_and_user_key_without_echoing_error_body():
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, url, **kwargs):
            assert url == "https://api.jp.newrelic.com/graphql"
            assert kwargs["headers"]["Api-Key"] == "secret"
            return httpx.Response(401, json={"error": "secret"}, request=httpx.Request("POST", url))

    with patch("nodes.new_relic_node.httpx.AsyncClient", return_value=Client()):
        with pytest.raises(ValueError) as exc:
            await _graphql(NewRelicUserKeyCredential(api_key="secret", region="jp"), "query { actor { user { name } } }")
    assert "HTTP 401" in str(exc.value)
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_graphql_errors_are_not_returned_as_success():
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, url, **kwargs):
            return httpx.Response(200, json={"errors": [{"message": "secret echoed"}]}, request=httpx.Request("POST", url))

    with patch("nodes.new_relic_node.httpx.AsyncClient", return_value=Client()):
        with pytest.raises(ValueError, match="1 GraphQL error") as exc:
            await _graphql(NewRelicUserKeyCredential(api_key="secret"), "query { invalid }")
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_rest_host_is_fixed_and_path_restricted():
    with pytest.raises(ValueError, match="documented v2"):
        await _rest(NewRelicUserKeyCredential(api_key="key"), "https://evil.example.com")


def test_alert_policy_name_is_graphql_escaped():
    document, _ = _graphql_operation("create_alert_policy", {
        "account_id": 123, "policy_name": 'QA" } mutation { deleteSomething',
        "incident_preference": "PER_POLICY",
    })
    assert 'QA\\" } mutation' in document
