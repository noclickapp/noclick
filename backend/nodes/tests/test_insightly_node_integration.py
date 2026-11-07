"""Insightly HTTP contract tests. These use MockTransport, not a live account."""

import asyncio
import base64
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.insightly_node import (
    InsightlyApiKeyCredential,
    InsightlyNode,
    InsightlyNodeConfig,
    _SPECS,
)


def _run(operation, expected_request, response_json=None, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        expected_request(request)
        return httpx.Response(status, json=response_json if response_json is not None else {})

    cfg = InsightlyNodeConfig(
        config=operation,
        credentials=InsightlyApiKeyCredential(pod="na1", api_key="test-key"),
    )
    node = InsightlyNode(
        node_id="test-insightly", node_type="automation-insightly", node_data={},
        config=cfg, sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )
    with patch(
        "nodes.insightly_node.guarded_async_client",
        side_effect=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ):
        result = asyncio.run(node.execute({}))
    assert len(requests) == 1
    return result


def _auth(request):
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"test-key:").decode()
    assert request.url.host == "api.na1.insightly.com"


def test_contact_create_uses_collection_post_and_unwrapped_body():
    def check(request):
        _auth(request)
        assert request.method == "POST"
        assert request.url.path == "/v3.1/Contacts"
        assert json.loads(request.content) == {"FIRST_NAME": "Ada", "LAST_NAME": "Lovelace"}

    result = _run(
        {"operation": "create_contact", "record_json": '{"FIRST_NAME":"Ada","LAST_NAME":"Lovelace"}'},
        check, {"CONTACT_ID": 42, "FIRST_NAME": "Ada"}, status=201,
    )
    assert result["data"]["CONTACT_ID"] == 42


def test_update_uses_collection_put_with_record_id_in_body():
    def check(request):
        _auth(request)
        assert request.method == "PUT"
        assert request.url.path == "/v3.1/Opportunities"
        assert json.loads(request.content)["OPPORTUNITY_ID"] == 17

    result = _run(
        {"operation": "update_opportunity", "record_json": '{"OPPORTUNITY_ID":17,"OPPORTUNITY_NAME":"Won"}'},
        check, {"OPPORTUNITY_ID": 17},
    )
    assert result["status"] == "success"


def test_search_and_pagination_use_documented_query_parameters():
    def check(request):
        _auth(request)
        assert request.url.path == "/v3.1/Leads/Search"
        assert dict(request.url.params) == {
            "top": "25", "skip": "50", "field_name": "EMAIL",
            "field_value": "ada@example.com",
        }

    result = _run(
        {"operation": "search_lead", "top": 25, "skip": 50,
         "field_name": "EMAIL", "field_value": "ada@example.com"},
        check, [{"LEAD_ID": 8}],
    )
    assert result["data"] == [{"LEAD_ID": 8}]


def test_tag_search_get_delete_and_metadata_paths():
    cases = [
        ({"operation": "search_by_tag_contact", "tag_name": "Important"}, "GET", "/v3.1/Contacts/SearchByTag"),
        ({"operation": "get_project", "record_id": 12}, "GET", "/v3.1/Projects/12"),
        ({"operation": "delete_task", "record_id": 13}, "DELETE", "/v3.1/Tasks/13"),
        ({"operation": "list_pipeline_stage"}, "GET", "/v3.1/PipelineStages"),
    ]
    for config, method, path in cases:
        def check(request):
            _auth(request)
            assert request.method == method
            assert request.url.path == path
            if config["operation"] == "search_by_tag_contact":
                assert request.url.params["tagName"] == "Important"

        result = _run(config, check)
        assert result["status"] == "success"


def test_invalid_pod_and_body_cannot_escape_fixed_provider_host():
    for pod in ("na1.evil.com", "https://api.na1.insightly.com", "na1/path", "localhost"):
        if pod == "localhost":  # syntactically valid pod, but still fixed under insightly.com
            assert InsightlyApiKeyCredential(pod=pod, api_key="x").pod == pod
        else:
            with pytest.raises(ValidationError):
                InsightlyApiKeyCredential(pod=pod, api_key="x")
    with pytest.raises(ValueError, match="must include CONTACT_ID"):
        _run({"operation": "update_contact", "record_json": '{"FIRST_NAME":"Ada"}'}, lambda _: None)
    with pytest.raises(ValueError, match="must be an object"):
        _run({"operation": "create_contact", "record_json": "[]"}, lambda _: None)


def test_error_response_is_not_reported_as_success():
    result = _run(
        {"operation": "list_contact"}, lambda request: _auth(request),
        {"Message": "Invalid API key"}, status=401,
    )
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert "Invalid API key" in result["error"]


def test_every_declared_operation_uses_a_fixed_api_path():
    assert len(_SPECS) == 52
    for method, path, _, _ in _SPECS.values():
        assert method in ("GET", "POST", "PUT", "DELETE")
        assert path.startswith("/") and "//" not in path
        assert "?" not in path and "http" not in path
