"""Formbricks v1 node contract tests with a controlled HTTP transport."""

import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import formbricks_node as fb


def _credential():
    return fb.FormbricksApiKeyCredential(api_key="fb_test_key")


def _node(operation: str, **fields):
    config = fb.FormbricksNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": _credential().model_dump(),
    })
    return fb.FormbricksNode(
        node_id="test-formbricks", node_type="automation-formbricks",
        node_data={}, config=config, sio=Mock(), sid="test-sid",
        workflow_id="test-workflow", user_id="test-user",
    )


def _field_values(operation):
    values = {}
    for field in operation.fields:
        if field == "optional_survey_id":
            values["survey_id"] = "survey_1"
        elif field == "payload_json":
            values[field] = json.dumps({"name": "QA Survey", "data": {"question_1": "yes"}})
        elif field == "triggers":
            values[field] = ["responseCreated"]
        elif field == "webhook_url":
            values[field] = "https://hooks.example.com/formbricks"
        elif field == "allowed_extensions_json":
            values[field] = '["png"]'
        elif field == "limit":
            values[field] = 25
        elif field == "skip":
            values[field] = 5
        else:
            values[field] = field + "_1"
    return values


def test_all_documented_operations_have_validated_configs_and_bounded_paths():
    assert len(fb._OPERATIONS) == 26
    assert len(fb._CONFIG_MODELS) == len(fb._OPERATIONS)
    for operation in fb._OPERATIONS:
        node = _node(operation.name, **_field_values(operation))
        path, params, body = fb._request_parts(node.config.config, operation)
        assert path.startswith(("/api/v1/management/", "/api/v1/webhooks"))
        if operation.name == "get_me":
            assert path == "/api/v1/management/me"
        assert "{" not in path and "}" not in path
        assert operation.method in {"GET", "POST", "PUT", "DELETE"}
        assert (body is not None) == bool(operation.body)
        if operation.name == "list_responses":
            assert params == {"limit": 25, "skip": 5, "surveyId": "survey_1"}


@pytest.mark.asyncio
async def test_execute_uses_api_key_header_and_preserves_resource_data(monkeypatch):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/surveys"):
            return httpx.Response(200, json={"data": [{"id": "survey_1", "name": "QA Survey"}]})
        return httpx.Response(200, json={"data": {"id": "survey_1", "name": "QA Survey"}})

    monkeypatch.setattr(
        fb, "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )
    listed = await _node("list_surveys").execute({})
    assert listed["count"] == 1
    assert listed["data"][0]["name"] == "QA Survey"
    created = await _node(
        "create_survey", workspace_id="workspace_1",
        payload_json='{"name":"QA Survey","workspaceId":"ignored"}',
    ).execute({})
    assert created["data"]["id"] == "survey_1"
    assert requests[0].headers["x-api-key"] == "fb_test_key"
    assert requests[0].url.host == "app.formbricks.com"
    assert json.loads(requests[1].content)["workspaceId"] == "workspace_1"
    assert requests[1].url.path == "/api/v1/management/surveys"


@pytest.mark.asyncio
async def test_picker_search_and_page_token(monkeypatch):
    async def fake_request(*args, **kwargs):
        return {"data": [{"id": str(i), "name": f"Survey {i}"} for i in range(105)]}

    monkeypatch.setattr(fb, "_request", fake_request)
    first = await fb.FormbricksNode.load_field_options(
        "survey_id", _credential().model_dump(), page_token=None,
    )
    assert len(first["options"]) == 100
    assert first["next_page_token"] == "100"
    second = await fb.FormbricksNode.load_field_options(
        "survey_id", _credential().model_dump(), page_token="100",
    )
    assert len(second["options"]) == 5
    assert second["next_page_token"] is None
    searched = await fb.FormbricksNode.load_field_options(
        "survey_id", _credential().model_dump(), search="survey 103",
    )
    assert searched["options"] == [{"value": "103", "label": "Survey 103"}]
    with pytest.raises(ValueError, match="page token"):
        await fb.FormbricksNode.load_field_options(
            "survey_id", _credential().model_dump(), page_token="-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status, hint", [
    (401, "API key"), (403, "workspace access"), (404, "not found"), (429, "Rate limit"),
])
async def test_api_errors_do_not_echo_provider_body_or_key(monkeypatch, status, hint):
    def handler(request: httpx.Request):
        return httpx.Response(status, json={"message": "fb_test_key secret details"})

    monkeypatch.setattr(
        fb, "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ValueError) as exc:
        await fb._request(_credential(), "GET", "/api/v1/management/me")
    assert hint in str(exc.value)
    assert "fb_test_key" not in str(exc.value)


def test_json_path_and_webhook_validation():
    with pytest.raises(ValueError, match="valid JSON"):
        fb._request_parts(_node("update_survey", survey_id="s", payload_json="{" ).config.config,
                          fb._OPERATION_BY_NAME["update_survey"])
    with pytest.raises(ValueError, match="JSON object"):
        fb._request_parts(_node("update_survey", survey_id="s", payload_json="[]").config.config,
                          fb._OPERATION_BY_NAME["update_survey"])
    for url in ("http://example.com/hook", "https://user:pass@example.com/hook", "https://example.com/hook#fragment"):
        with pytest.raises(ValueError, match="Webhook destination"):
            fb._request_parts(_node("create_webhook", webhook_url=url, triggers=["responseCreated"]).config.config,
                              fb._OPERATION_BY_NAME["create_webhook"])
    with pytest.raises(ValidationError):
        _node("create_webhook", webhook_url="https://example.com", triggers=[])
    path, _, _ = fb._request_parts(_node("get_survey", survey_id="a/b").config.config,
                                   fb._OPERATION_BY_NAME["get_survey"])
    assert path.endswith("/a%2Fb")


def test_credential_origin_validation_and_connection_evidence():
    for url in ("http://app.formbricks.com", "https://app.formbricks.com/x", "https://user:pass@app.formbricks.com"):
        with pytest.raises(ValidationError):
            fb.FormbricksApiKeyCredential(api_key="test", base_url=url)
    evidence = fb.FormbricksNode.connection_evidence
    assert evidence.field == "survey_id"
    assert evidence.identity_operation == "get_me"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", fb._OPERATIONS, ids=lambda op: op.name)
async def test_execute_preserves_documented_management_api_response(monkeypatch, operation):
    """Provider v1 examples cover the routes missing from the pinned v2 spec."""
    import re
    from pathlib import Path

    witnesses = json.loads((Path(__file__).parent / "fixtures/formbricks/documented_responses.json").read_text())
    normalize = lambda path: re.sub(r"\{[^}]+\}", "{id}", path)
    key = next(key for key in witnesses if key.split(" ", 1)[0] == operation.method
               and normalize(key.split(" ", 1)[1]) == normalize(operation.path))
    body = witnesses[key]["body"]

    def handler(request):
        assert request.method == operation.method
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        fb, "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )
    configs = json.loads((Path(__file__).parent / "fixtures/formbricks/documented_configs.json").read_text())["configs"]
    result = await _node(**configs[operation.name]).execute({})
    expected = body.get("data", body)
    assert result["data"] == expected
    if isinstance(expected, list):
        assert result["count"] == len(expected)
