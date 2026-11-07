"""HTTP contract tests for every selected Bunny.net OpenAPI action."""

import json
from urllib.parse import quote
from unittest.mock import patch

import httpx
import pytest

from nodes.bunnycdn_node import (
    BUNNY_API_BASES,
    BUNNY_CONFIGS,
    BUNNY_OPERATIONS,
    BunnyAccountCredential,
    BunnyNode,
    BunnyNodeConfig,
    BunnyStreamCredential,
)
from tests.utils.sweep import check_each


def _node(operation, *, credential=None, **fields):
    spec = BUNNY_OPERATIONS[operation]
    if credential is None:
        credential = (
            BunnyStreamCredential(access_key="stream-key", library_id=123)
            if spec["api"] == "stream"
            else BunnyAccountCredential(access_key="account-key")
        )
    return BunnyNode(
        node_id="test",
        node_type="automation-bunnycdn",
        node_data={},
        config=BunnyNodeConfig(
            config=BUNNY_CONFIGS[operation](**fields), credentials=credential
        ),
    )


async def _execute(node, handler):
    original = httpx.AsyncClient
    with patch(
        "nodes.bunnycdn_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    ):
        return await node.execute({})


async def _every_action_routes_to_fixed_host_with_correct_method_fields_and_key(
    operation,
):
    spec = BUNNY_OPERATIONS[operation]
    fields = {"query_json": '{"extra":"value"}'}
    expected_path = spec["path"]
    for param in spec["path_fields"]:
        value = "123" if param["type"] == "integer" else "a b"
        if param["name"] == "date":
            value = "11-07-2023"
        fields[param["field"]] = value
        expected_path = expected_path.replace(
            "{" + param["name"] + "}", quote(value, safe="")
        )
    required_query = {}
    for param in spec["query_fields"]:
        if param["required"]:
            value = {
                "boolean": True,
                "integer": 3,
                "number": 3.5,
                "array": ["a", "b"],
            }.get(param["type"], "chosen")
            fields[param["field"]] = value
            required_query[param["name"]] = value
    if spec["body_required"]:
        fields["body_json"] = '{"fixture":true}'

    def handler(request):
        assert request.method == spec["method"]
        assert request.url.host == httpx.URL(BUNNY_API_BASES[spec["api"]]).host
        assert request.url.raw_path.split(b"?")[0].decode() == expected_path
        assert request.headers["AccessKey"] == (
            "stream-key" if spec["api"] == "stream" else "account-key"
        )
        assert request.url.params["extra"] == "value"
        for name, value in required_query.items():
            assert name in request.url.params
            if not isinstance(value, list):
                expected = str(value).lower() if isinstance(value, bool) else str(value)
                assert request.url.params[name] == expected
        if spec["body_required"]:
            assert json.loads(request.content) == {"fixture": True}
        return httpx.Response(
            200,
            json=[{"id": 123}],
            headers={"Link": '</pullzone?page=2>; rel="next"'},
        )

    result = await _execute(_node(operation, **fields), handler)
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["data"]["items"] == [{"id": 123}]
    assert "next" in result["pagination_link"]
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
async def test_every_action_routes_to_fixed_host_with_correct_method_fields_and_key():
    await check_each(sorted(name for name in BUNNY_OPERATIONS if name != "list_connection_resources"), _every_action_routes_to_fixed_host_with_correct_method_fields_and_key)


@pytest.mark.asyncio
async def test_stream_library_id_defaults_from_credential_and_credentials_are_scoped():
    operation = next(
        name
        for name, spec in BUNNY_OPERATIONS.items()
        if spec["api"] == "stream"
        and spec["method"] == "GET"
        and {p["name"] for p in spec["path_fields"]} == {"libraryId"}
        and not spec["body_required"]
        and not any(p["required"] for p in spec["query_fields"])
    )

    def handler(request):
        assert "/library/123/" in request.url.path
        return httpx.Response(200, json={"items": []})

    result = await _execute(_node(operation), handler)
    assert result["status"] == "success"
    with pytest.raises(ValueError, match="Stream library API key"):
        await _node(
            operation,
            credential=BunnyAccountCredential(access_key="account-key"),
        ).execute({})


@pytest.mark.asyncio
async def test_connection_evidence_uses_the_right_credential_and_host():
    for credential, host, path in (
        (
            BunnyAccountCredential(access_key="account-key"),
            "api.bunny.net",
            "/pullzone",
        ),
        (
            BunnyStreamCredential(access_key="stream-key", library_id=123),
            "video.bunnycdn.com",
            "/library/123/collections",
        ),
    ):

        def handler(request):
            assert request.url.host == host
            assert request.url.path == path
            assert dict(request.url.params) == (
                {"page": "1", "perPage": "5"}
                if host == "api.bunny.net"
                else {"itemsPerPage": "1"}
            )
            assert request.headers["AccessKey"] == credential.access_key
            return httpx.Response(200, json={"Items": []})

        result = await _execute(
            _node("list_connection_resources", credential=credential), handler
        )
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_errors_invalid_json_and_login_redirect():
    operation = next(
        name
        for name, spec in BUNNY_OPERATIONS.items()
        if spec["api"] == "core"
        and spec["method"] == "GET"
        and not spec["path_fields"]
        and not any(p["required"] for p in spec["query_fields"])
    )
    with pytest.raises(ValueError, match="query must be valid JSON"):
        await _node(operation, query_json="not json").execute({})
    result = await _execute(
        _node(operation),
        lambda request: httpx.Response(401, json={"Message": "bad key"}),
    )
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert result["error"] == {"Message": "bad key"}
    result = await _execute(
        _node(operation),
        lambda request: httpx.Response(302, headers={"Location": "/login"}),
    )
    assert result["status"] == "error"
    assert "redirected" in result["error"]


def test_schema_exposes_all_actions_and_both_key_types():
    schema = BunnyNode.get_config_schema()
    operations = {
        definition.get("properties", {}).get("operation", {}).get("const")
        for definition in schema["$defs"].values()
    }
    assert set(BUNNY_OPERATIONS) <= operations
    assert len(BUNNY_OPERATIONS) == 206
    assert not any(spec["path"].endswith("/pdf") for spec in BUNNY_OPERATIONS.values())
    assert "BunnyAccountCredential" in schema["$defs"]
    assert "BunnyStreamCredential" in schema["$defs"]


@pytest.mark.asyncio
async def test_path_traversal_is_rejected_before_network():
    operation = next(
        name for name, spec in BUNNY_OPERATIONS.items()
        if not spec["body_required"]
        and any(p["type"] == "string" for p in spec["path_fields"])
        and not any(p["name"] == "date" for p in spec["path_fields"])
        and not any(p["required"] for p in spec["query_fields"])
    )
    spec = BUNNY_OPERATIONS[operation]
    fields = {p["field"]: "123" if p["type"] == "integer" else "safe" for p in spec["path_fields"]}
    target = next(p["field"] for p in spec["path_fields"] if p["type"] == "string")
    fields[target] = "a/../b"
    with pytest.raises(ValueError, match="path traversal"):
        await _node(operation, **fields).execute({})


def test_integer_path_ids_are_validated_by_config():
    with pytest.raises(ValueError, match="valid integer"):
        _node("core_get_pull_zone", id="not-an-integer")


@pytest.mark.asyncio
@pytest.mark.parametrize("date", ["11-07-2023", "2023-11-07", "2023-11-07T05:31:56Z"])
async def test_event_log_dates_use_documented_wire_format(date):
    def handler(request):
        assert request.url.path == "/shield/event-logs/123/11-07-2023/page-token"
        return httpx.Response(200, json={"data": []})
    result = await _execute(_node(
        "shield_get_event_logs_for_shield_zone", shield_zone_id=123,
        date=date, continuation_token="page-token",
    ), handler)
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("date", ["1", "02-30-2023", "2023-02-30", "not-a-date"])
async def test_invalid_event_log_dates_fail_before_request(date):
    with pytest.raises(ValueError, match="event log date must be a valid"):
        await _execute(_node(
            "shield_get_event_logs_for_shield_zone", shield_zone_id=123,
            date=date, continuation_token="page-token",
        ), lambda request: pytest.fail("Invalid date reached the provider"))
