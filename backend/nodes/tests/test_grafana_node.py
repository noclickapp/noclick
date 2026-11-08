"""Contract tests for Grafana route selection and request/response handling.

These tests do not count as live NoClick FlowCanvas verification.
"""

import json
from unittest.mock import patch

import httpx
import pytest

from nodes.grafana_node import OPERATIONS
from nodes.grafana_node import GrafanaNode, GrafanaNodeConfig, _MODELS, _origin


def _node(operation, **fields):
    config = GrafanaNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": {
                "url": "https://example.grafana.net",
                "token": "grafana-qa-token",
            },
        }
    )
    return GrafanaNode(
        node_id="grafana-test",
        node_type="automation-grafana",
        node_data={},
        config=config,
    )


def _fields_for(spec):
    result = {}
    for parameter in spec["parameters"]:
        if parameter["location"] == "path" or parameter["required"]:
            result[parameter["field"]] = (
                42 if parameter["type"] == "integer" else "resource uid"
            )
    if spec["name"] == "move_folder":
        result["parent_uid"] = "d80b18c0-266a-4aa4-ad5d-5537a00cb8e8"
    elif spec["body_required"]:
        result["body"] = '{"title":"QA","uid":"qa"}'
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", OPERATIONS, ids=lambda spec: spec["name"])
async def test_every_grafana_operation_uses_expected_method_route_and_auth(spec):
    calls = []

    def capture(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node(spec["name"], **_fields_for(spec))
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == spec["name"]
    assert result["data"] == {"ok": True}
    request = calls[0]
    assert request.method == spec["method"]
    assert request.url.host == "example.grafana.net"
    assert request.url.path.startswith("/api/")
    assert "{" not in request.url.path
    assert request.headers["Authorization"] == "Bearer grafana-qa-token"
    if spec["name"] == "move_folder":
        assert json.loads(request.content) == {"parentUid": "d80b18c0-266a-4aa4-ad5d-5537a00cb8e8"}
    elif spec["body_required"]:
        assert json.loads(request.content) == {"title": "QA", "uid": "qa"}
    else:
        assert not request.content


def test_catalog_and_schema_have_one_config_per_operation():
    assert len(OPERATIONS) == 62
    assert len(_MODELS) == len(OPERATIONS)
    assert len({spec["name"] for spec in OPERATIONS}) == len(OPERATIONS)
    schema = GrafanaNode.get_config_schema()
    assert schema["properties"]["credentials"]
    assert len(schema["properties"]["config"]["oneOf"]) == len(OPERATIONS)


@pytest.mark.asyncio
async def test_path_is_encoded_and_query_array_repeats():
    captured = []

    def capture(request):
        captured.append(request)
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node("get_dashboard", uid="folder/secret")
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        await node.execute({})
    assert captured[0].url.raw_path == b"/api/dashboards/uid/folder%2Fsecret"

    captured.clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node("search_dashboards", tag="prod, api", limit=10)
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await node.execute({})
    assert captured[0].url.params.get_list("tag") == ["prod", "api"]
    assert captured[0].url.params["limit"] == "10"
    assert result["data"] == {"items": [], "count": 0}


@pytest.mark.asyncio
async def test_bad_json_does_not_send_request():
    node = _node("save_dashboard", body="{bad")
    with pytest.raises(ValueError, match="valid JSON"):
        await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("code,message", [(401, "Unauthorized"), (403, "Forbidden"), (404, "Not found")])
async def test_provider_errors_are_visible(code, message):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(code, json={"message": message})
        )
    )
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await _node("list_folders").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == code
    assert result["error"] == message


@pytest.mark.asyncio
async def test_empty_delete_response():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(204))
    )
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await _node("delete_folder", folder_uid="qa").execute({})
    assert result["status"] == "success"
    assert result["status_code"] == 204
    assert result["data"] == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal",
        "https://example.grafana.net/evil",
        "https://example.grafana.net?token=bad",
        "https://user:pass@example.grafana.net",
    ],
)
def test_credential_origin_rejects_unsafe_forms(url):
    with pytest.raises(ValueError):
        _origin(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{}, {"parent_uid": ""}])
async def test_move_folder_can_move_under_root(fields):
    captured = []

    def capture(request):
        captured.append(request)
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node("move_folder", folder_uid="a5393ec3-5568-4e88-8809-b866968ae8a6", **fields)
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert captured[0].url.path == "/api/folders/a5393ec3-5568-4e88-8809-b866968ae8a6/move"
    assert json.loads(captured[0].content) == {"parentUid": ""}


def test_move_folder_parent_uid_rejects_non_string():
    with pytest.raises(ValueError, match="parent_uid"):
        _node("move_folder", folder_uid="a5393ec3-5568-4e88-8809-b866968ae8a6", parent_uid={"invalid": True})
