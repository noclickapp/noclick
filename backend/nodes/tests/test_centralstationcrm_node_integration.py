"""CentralStationCRM HTTP contracts; vendor-live FlowCanvas QA is separate."""

import asyncio
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.centralstationcrm_node import (
    BASE_URL,
    CONFIG_MODELS,
    OPERATIONS,
    CentralStationCRMApiKeyCredential,
    CentralStationCRMNode,
    CentralStationCRMNodeConfig,
)


def run_action(config, check_request, *, status=200, response=None, text=None):
    seen = []

    def handler(request):
        seen.append(request)
        check_request(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=response if response is not None else {"ok": True})

    node = CentralStationCRMNode(
        node_id="cscrm-test", node_type="automation-centralstationcrm", node_data={},
        config=CentralStationCRMNodeConfig(
            config=config,
            credentials=CentralStationCRMApiKeyCredential(api_key="private-test-key"),
        ),
        sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )
    original_client = httpx.AsyncClient
    with patch(
        "nodes.centralstationcrm_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handler)),
    ):
        result = asyncio.run(node.execute({}))
    assert len(seen) == 1
    return result


def assert_auth(request):
    assert str(request.url).startswith(BASE_URL + "/api/")
    assert request.headers["X-apikey"] == "private-test-key"
    assert "private-test-key" not in str(request.url)


def test_connection_check_uses_fixed_host_and_header():
    def check(request):
        assert_auth(request)
        assert request.method == "GET"
        assert request.url.path == "/api/check_connection"

    result = run_action({"operation": "check_connection"}, check, response={})
    assert result == {"status": "success", "operation": "check_connection", "data": {}}


def test_list_contacts_paginates_and_forwards_filters():
    def check(request):
        assert_auth(request)
        assert request.method == "GET"
        assert request.url.path == "/api/people"
        assert dict(request.url.params) == {"page": "2", "perpage": "25", "filter[name]": "Morgan"}

    result = run_action(
        {"operation": "get_people", "page": 2, "perpage": 25,
         "query_json": '{"filter[name]":"Morgan"}'},
        check, response=[{"person": {"id": 8, "name": "Morgan"}}],
    )
    assert result["data"][0]["person"]["id"] == 8


def test_create_contact_sends_wrapped_vendor_json():
    payload = {"person": {"first_name": "Avery", "name": "Morgan"}}

    def check(request):
        assert_auth(request)
        assert request.method == "POST"
        assert request.url.path == "/api/people"
        assert json.loads(request.content) == payload

    result = run_action(
        {"operation": "post_people", "payload_json": json.dumps(payload)},
        check, status=201, response={"person": {"id": 42, **payload["person"]}},
    )
    assert result["data"]["person"]["id"] == 42


def test_update_contact_encodes_path_segment_and_body():
    def check(request):
        assert_auth(request)
        assert request.method == "PUT"
        assert b"%2F" in request.url.raw_path
        assert json.loads(request.content) == {"person": {"background": "qualified"}}

    run_action(
        {"operation": "put_people_by_id", "id": "contact/42",
         "payload_json": '{"person":{"background":"qualified"}}'},
        check,
    )


def test_delete_contact_handles_empty_success_response():
    def check(request):
        assert_auth(request)
        assert request.method == "DELETE"
        assert request.url.path == "/api/people/42"
        assert not request.content

    result = run_action(
        {"operation": "delete_people_by_id", "id": "42"},
        check, status=204, text="",
    )
    assert result["data"] == {"ok": True}


def test_invalid_json_and_page_size_fail_before_network():
    with pytest.raises(ValidationError):
        CentralStationCRMNodeConfig(config={"operation": "get_people", "perpage": 251})
    for payload in ("{bad", "[]"):
        with pytest.raises(ValueError, match="must be (valid JSON|a JSON object)"):
            run_action(
                {"operation": "post_people", "payload_json": payload},
                lambda _: pytest.fail("unexpected network request"),
            )


def test_vendor_errors_are_not_success():
    with pytest.raises(ValueError, match="CentralStationCRM API error 401: Invalid API key"):
        run_action(
            {"operation": "check_connection"}, assert_auth,
            status=401, response={"error": "Invalid API key"},
        )


def test_catalog_has_one_schema_per_fixed_vendor_route():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 199
    assert BASE_URL == "https://api.centralstationcrm.net"
    assert len({(op["category"], op["label"]) for op in OPERATIONS.values()}) == 199
    for key, operation in OPERATIONS.items():
        assert key in CONFIG_MODELS
        assert operation["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert operation["path"].startswith("/api/")
        assert "//" not in operation["path"]
        assert "?" not in operation["path"]
        assert "http" not in operation["path"]
        assert set(operation["required_query_params"]) <= set(operation["query_params"])


def test_vendor_error_redacts_echoed_api_key():
    with pytest.raises(ValueError, match=r"Invalid API key: \[redacted\]") as error:
        run_action(
            {"operation": "check_connection"}, assert_auth,
            status=401, response={"error": "Invalid API key: private-test-key"},
        )
    assert "private-test-key" not in str(error.value)
