"""CircleCI API v2 request contract for every action in the pinned catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.circleci_node import (
    CONFIG_MODELS, OPERATIONS, CircleCINode, CircleCINodeConfig, _catalog, _field_name, _NATIVE_BODY_FIELDS,
)
from tests.utils.sweep import check_each


def _action(op: dict) -> dict:
    values = {"operation": op["name"]}
    for raw in op["path_params"]:
        values[_field_name("path", raw)] = "sample-id"
    for raw in op["required_query"]:
        values[_field_name("query", raw)] = "sample-value"
    for raw in op["required_headers"]:
        values[_field_name("header", raw)] = "sample-value"
    native_examples = {
        "patch_org_claims": {"audience": ["string"]},
        "patch_project_claims": {"audience": ["string"]},
        "create_organization": {"name": "string", "vcs_type": "github"},
        "make_decision": {"input": "string", "metadata": {}},
        "set_decision_settings": {"enabled": True},
        "create_checkout_key": {"type": "deploy-key"},
        "create_env_var": {"name": "foo", "value": "xxxx1234"},
        "create_project": {"name": "api-preview-docs"},
    }
    if op["name"] in native_examples:
        values.update(native_examples[op["name"]])
    elif op["body_json"]:
        values["body_json"] = json.dumps({"sample": "value", **{
            key: "sample-value" for key in op["body_required_fields"]
        }})
    return values


def _node(action: dict, *, token: str = "test-personal-token") -> CircleCINode:
    config = CircleCINodeConfig.model_validate({
        "config": action,
        "credentials": {"credential_type": "circleci_pat", "api_token": token},
    })
    return CircleCINode(
        node_id="circleci-test", node_type="automation-circleci", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


async def _every_openapi_action_uses_documented_method_path_and_bearer_token(op):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    real_client = httpx.AsyncClient
    with patch("nodes.circleci_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node(_action(op)).execute({})
    request = requests[0]
    assert result["status"] == "success"
    assert result["operation"] == op["name"]
    assert result["status_code"] == 200
    assert request.method == op["method"]
    assert request.url.host == "circleci.com"
    assert request.url.path == "/api/v2" + re.sub(r"\{[^{}]+\}", "sample-id", op["path"])
    assert request.headers["authorization"] == "Bearer test-personal-token"
    for raw in op["required_query"]:
        assert request.url.params[raw] == "sample-value"
    for raw in op["required_headers"]:
        assert request.headers[raw] == "sample-value"
    if op["body_json"]:
        if op["name"] in _NATIVE_BODY_FIELDS:
            assert json.loads(request.content) == {
                field: _action(op)[field] for field in _NATIVE_BODY_FIELDS[op["name"]]
                if field in _action(op)
            }
        else:
            assert json.loads(request.content) == json.loads(_action(op)["body_json"])


@pytest.mark.asyncio
async def test_every_openapi_action_uses_documented_method_path_and_bearer_token():
    await check_each(OPERATIONS.values(), _every_openapi_action_uses_documented_method_path_and_bearer_token, name=lambda op: op["name"])


def test_catalog_and_frontend_schema_cover_the_same_official_operations():
    root = Path(__file__).resolve().parents[2]
    catalog = _catalog
    schema = json.loads((root.parent / "frontend" / "app" / "schemas" / "nodes" / "circleci.json").read_text())
    assert catalog["source"] == "https://circleci.com/api/v2/openapi.json"
    assert len(catalog["operations"]) == len(OPERATIONS) == len(CONFIG_MODELS) == 111
    schema_operations = {
        entry["properties"]["operation"]["const"]
        for entry in schema["$defs"].values()
        if isinstance(entry, dict) and "operation" in entry.get("properties", {})
    }
    assert schema_operations == set(OPERATIONS)


def test_pipeline_list_requires_org_slug_despite_upstream_spec_marking_it_optional():
    """The live v2 endpoint rejects a missing org-slug with HTTP 400."""
    assert OPERATIONS["list_pipelines"]["required_query"] == ["org-slug"]
    schema = json.loads((Path(__file__).resolve().parents[3]
                         / "frontend/app/schemas/nodes/circleci.json").read_text())
    assert "query_org_slug" in schema["$defs"]["CircleCIListPipelinesConfig"]["required"]


@pytest.mark.parametrize("op", [op for op in OPERATIONS.values() if op["body_required"]],
                         ids=lambda op: op["name"])
def test_required_request_bodies_are_required_by_the_form(op):
    action = _action(op)
    if op["name"] in _NATIVE_BODY_FIELDS:
        for field in _NATIVE_BODY_FIELDS[op["name"]]:
            action.pop(field, None)
    else:
        del action["body_json"]
    with pytest.raises(ValueError):
        _node(action)


@pytest.mark.asyncio
async def test_body_keys_and_query_json_are_validated_before_request():
    op = next(op for op in OPERATIONS.values() if op["body_required_fields"])
    action = _action(op)
    action["body_json"] = "{}"
    with pytest.raises(ValueError, match="missing required keys"):
        await _node(action).execute({})

    with pytest.raises(ValueError, match="JSON object"):
        await _node({"operation": "get_current_user", "query_json": "[]"}).execute({})


@pytest.mark.asyncio
async def test_project_slug_is_encoded_and_errors_do_not_disclose_token():
    real_client = httpx.AsyncClient
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, json={"message": "Unauthorized"})

    with patch("nodes.circleci_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        with pytest.raises(ValueError, match="CircleCI API error 401: Unauthorized") as error:
            await _node({"operation": "get_project_by_slug", "path_project_slug": "gh/acme/repo"},
                        token="private-token").execute({})
    assert "private-token" not in str(error.value)
    assert "%2F" in str(requests[0].url)


@pytest.mark.parametrize("operation,field,value", [
    ("create_organization", "vcs_type", "unsupported"),
    ("create_checkout_key", "type", "unsupported"),
    ("patch_org_claims", "ttl", "string"),
    ("patch_project_claims", "audience", "string"),
])
def test_native_body_fields_reject_invalid_provider_values(operation, field, value):
    action = _action(OPERATIONS[operation])
    action[field] = value
    with pytest.raises(ValueError):
        _node(action)


@pytest.mark.asyncio
async def test_context_environment_variable_accepts_documented_response():
    example = json.loads((Path(__file__).parent / "fixtures/circleci/context_environment_variable.json").read_text())
    real_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert json.loads(request.content) == {"value": "some-secret-value"}
        return httpx.Response(200, json=example["body"])

    with patch("nodes.circleci_node.httpx.AsyncClient",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await _node({
            "operation": "add_environment_variable_to_context",
            "path_context_id": "be8bb2e3-c3d6-4098-89f4-572ff976ba9a",
            "path_env_var_name": "POSTGRES_USER",
            "body_json": '{"value":"some-secret-value"}',
        }).execute({})
    assert result["data"] == example["body"]
