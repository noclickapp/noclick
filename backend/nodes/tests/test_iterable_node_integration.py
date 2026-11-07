"""Iterable HTTP contracts using MockTransport; live UI QA is tracked separately."""

import asyncio
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.iterable_node import (
    BASE_URLS,
    CONFIG_MODELS,
    OPERATIONS,
    IterableApiKeyCredential,
    IterableNode,
    IterableNodeConfig,
)


def run_action(config, check_request, *, region="us", status=200, response=None, text=None):
    requests = []

    def handler(request):
        requests.append(request)
        check_request(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=response if response is not None else {"ok": True})

    node = IterableNode(
        node_id="iterable-test", node_type="automation-iterable", node_data={},
        config=IterableNodeConfig(
            config=config,
            credentials=IterableApiKeyCredential(region=region, api_key="private-test-key"),
        ),
        sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )
    with patch(
        "nodes.iterable_node.guarded_async_client",
        side_effect=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ):
        result = asyncio.run(node.execute({}))
    assert len(requests) == 1
    return result


def assert_auth(request, host="api.iterable.com"):
    assert request.url.host == host
    assert request.headers["Api-Key"] == "private-test-key"
    assert "private-test-key" not in str(request.url)


def test_get_lists_uses_project_header_and_us_host():
    def check(request):
        assert_auth(request)
        assert request.method == "GET"
        assert request.url.path == "/api/lists"

    result = run_action({"operation": "list_lists"}, check, response={"lists": []})
    assert result["data"] == {"lists": []}


def test_update_user_sends_unwrapped_json_to_eu_host():
    payload = {"email": "ada@example.com", "dataFields": {"plan": "pro"}}

    def check(request):
        assert_auth(request, "api.eu.iterable.com")
        assert request.method == "POST"
        assert request.url.path == "/api/users/update"
        assert json.loads(request.content) == payload

    result = run_action(
        {"operation": "users_update_user", "payload_json": json.dumps(payload)},
        check, region="eu", response={"code": "Success"},
    )
    assert result["status"] == "success"


def test_lookup_by_email_uses_named_required_query_field():
    def check(request):
        assert_auth(request)
        assert request.url.path == "/api/users/getByEmail"
        assert dict(request.url.params) == {"email": "ada@example.com"}

    run_action(
        {"operation": "users_get_user_get_by_email", "query_email": "ada@example.com"}, check,
    )


def test_catalog_path_segments_are_encoded_and_optional_query_is_forwarded():
    def check(request):
        assert_auth(request)
        assert request.method == "GET"
        assert b"summer%2Fsale" in request.url.raw_path
        assert b"item%3Fone" in request.url.raw_path

    # The catalog endpoint has no optional query parameter, so test encoded
    # segments independently from a campaign operation with filters.
    run_action(
        {"operation": "catalogs_get_catalog_item", "catalogName": "summer/sale", "itemId": "item?one"},
        check,
    )

    def campaign_check(request):
        assert_auth(request)
        assert dict(request.url.params) == {"page": "1", "pageSize": "20"}

    run_action(
        {"operation": "campaigns_campaigns", "query_json": '{"page":1,"pageSize":20}'},
        campaign_check,
    )


def test_required_query_and_invalid_json_are_rejected_before_network():
    with pytest.raises(ValidationError):
        IterableNodeConfig(config={"operation": "users_get_user_get_by_email"})
    with pytest.raises(ValueError, match="must be valid JSON"):
        run_action(
            {"operation": "events_track", "payload_json": "{bad"},
            lambda _: pytest.fail("unexpected network request"),
        )
    with pytest.raises(ValueError, match="must be a JSON object"):
        run_action(
            {"operation": "events_track", "payload_json": "[]"},
            lambda _: pytest.fail("unexpected network request"),
        )


def test_error_response_is_never_reported_as_success():
    with pytest.raises(ValueError, match="Iterable API error 401: Invalid API key"):
        run_action(
            {"operation": "list_lists"}, lambda request: assert_auth(request),
            status=401, response={"msg": "Invalid API key"},
        )


def test_plain_text_success_response_is_preserved():
    result = run_action(
        {"operation": "list_lists"}, lambda request: assert_auth(request),
        text="ready",
    )
    assert result["data"] == {"text": "ready"}


def test_catalog_has_only_fixed_iterable_paths_and_schema_for_every_operation():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 152
    assert BASE_URLS == {"us": "https://api.iterable.com", "eu": "https://api.eu.iterable.com"}
    for key, operation in OPERATIONS.items():
        assert key in CONFIG_MODELS
        assert operation["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert operation["path"].startswith("/api/")
        assert "//" not in operation["path"]
        assert "?" not in operation["path"]
        assert "http" not in operation["path"]
        assert set(operation["required_query_params"]) <= set(operation["query_params"])


def test_region_is_allowlisted():
    with pytest.raises(ValidationError):
        IterableApiKeyCredential(region="https://evil.example", api_key="x")


def test_structured_json_inputs_match_pasted_json_without_changing_the_request():
    payload = {"email": "ada@example.com", "dataFields": {"plan": "pro"}}

    def check_body(request):
        assert_auth(request)
        assert request.url.path == "/api/users/update"
        assert json.loads(request.content) == payload

    run_action({"operation": "users_update_user", "payload_json": payload}, check_body)

    def check_query(request):
        assert dict(request.url.params) == {"page": "1", "pageSize": "20"}

    run_action(
        {"operation": "campaigns_campaigns", "query_json": {"page": 1, "pageSize": 20}},
        check_query,
    )


@pytest.mark.parametrize("value", ["1", "true", "null", "[]"])
def test_json_scalars_and_arrays_still_fail_before_network(value):
    with pytest.raises(ValueError, match="must be a JSON object"):
        run_action(
            {"operation": "users_update_user", "payload_json": value},
            lambda _: pytest.fail("unexpected network request"),
        )
