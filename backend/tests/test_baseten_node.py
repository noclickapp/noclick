"""Baseten route, payload, and credential-security contracts."""

import json

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from nodes.baseten_node import (
    BasetenAPIKeyCredential,
    BasetenAsyncPredictConfig,
    BasetenChatCompletionConfig,
    BasetenCurrentUserConfig,
    BasetenGetAsyncRequestConfig,
    BasetenGetDeploymentConfig,
    BasetenGetModelConfig,
    BasetenListDeploymentsConfig,
    BasetenListInferenceModelsConfig,
    BasetenListModelAPIsConfig,
    BasetenListModelsConfig,
    BasetenNode,
    BasetenNodeConfig,
    BasetenPredictDeploymentConfig,
    BasetenPredictModelConfig,
    _input_json,
    _request,
    _segment,
)

KEY = "baseten-test-secret"


def make_node(config):
    return BasetenNode(
        node_id="baseten-test", node_type="automation-baseten", node_data={},
        config=BasetenNodeConfig(
            config=config, credentials=BasetenAPIKeyCredential(api_key=KEY),
        ),
        sio=Mock(), sid="sid", workflow_id="wf", user_id="user",
    )


@pytest.mark.parametrize(
    "config,url,key",
    [
        (BasetenCurrentUserConfig(), "https://api.baseten.co/v1/users/me", None),
        (BasetenListModelsConfig(name="demo"), "https://api.baseten.co/v1/models", "models"),
        (BasetenGetModelConfig(model_id="m123"), "https://api.baseten.co/v1/models/m123", None),
        (BasetenListDeploymentsConfig(model_id="m123"),
         "https://api.baseten.co/v1/models/m123/deployments", "deployments"),
        (BasetenGetDeploymentConfig(model_id="m123", deployment_id="d456"),
         "https://api.baseten.co/v1/models/m123/deployments/d456", None),
        (BasetenListModelAPIsConfig(limit=10, cursor="next"),
         "https://api.baseten.co/v1/model_apis", "items"),
        (BasetenListInferenceModelsConfig(), "https://inference.baseten.co/v1/models", "data"),
        (BasetenGetAsyncRequestConfig(model_id="m123", request_id="r789"),
         "https://model-m123.api.baseten.co/async_request/r789", None),
    ],
)
@pytest.mark.asyncio
async def test_read_routes(config, url, key):
    payload = {key: [{"id": "one"}]} if key else {"user_id": "u1", "workspace_name": "Team"}
    with patch("nodes.baseten_node._request", new=AsyncMock(return_value={
        "status": "success", "data": payload, "action": config.operation,
    })) as request:
        result = await make_node(config).execute({})
    assert result["status"] == "success"
    assert request.await_args.args == (KEY, "GET", url)
    assert request.await_args.kwargs["action"] == config.operation


@pytest.mark.asyncio
async def test_lists_are_bounded_and_preserve_cursor():
    config = BasetenListModelAPIsConfig(limit=2, cursor="next", added_only=True)
    payload = {"items": [{"name": str(i)} for i in range(3)],
               "pagination": {"cursor": "after", "has_more": True}}
    with patch("nodes.baseten_node._request", new=AsyncMock(return_value={
        "status": "success", "data": payload,
    })) as request:
        result = await make_node(config).execute({})
    assert request.await_args.kwargs["params"] == {
        "limit": 2, "added_only": "true", "cursor": "next",
    }
    assert [row["name"] for row in result["data"]["items"]] == ["0", "1"]
    assert result["data"]["count"] == 3
    assert result["data"]["pagination"]["cursor"] == "after"


@pytest.mark.asyncio
async def test_chat_payload_and_output():
    config = BasetenChatCompletionConfig(
        model="zai-org/GLM-5.3", prompt="Say hello", system_prompt="Be short",
        max_tokens=32, temperature=0.2,
    )
    with patch("nodes.baseten_node._request", new=AsyncMock(return_value={
        "status": "success", "data": {
            "id": "gen1", "model": "zai-org/GLM-5.3",
            "choices": [{"message": {"content": "Hello"}}],
            "usage": {"total_tokens": 8},
        },
    })) as request:
        result = await make_node(config).execute({})
    assert request.await_args.args == (
        KEY, "POST", "https://inference.baseten.co/v1/chat/completions",
    )
    assert request.await_args.kwargs["body"] == {
        "model": "zai-org/GLM-5.3", "messages": [
            {"role": "system", "content": "Be short"},
            {"role": "user", "content": "Say hello"},
        ], "stream": False, "max_tokens": 32, "temperature": 0.2,
    }
    assert result["data"]["content"] == "Hello"
    assert result["data"]["usage"]["total_tokens"] == 8


@pytest.mark.parametrize(
    "config,url,body",
    [
        (BasetenPredictModelConfig(model_id="abc123", input_json='{"prompt":"Hello, world!"}'),
         "https://model-abc123.api.baseten.co/environments/production/predict",
         {"prompt": "Hello, world!"}),
        (BasetenPredictDeploymentConfig(model_id="abc123", deployment_id="def456",
                                       input_json='{"prompt":"Hello, world!"}'),
         "https://model-abc123.api.baseten.co/deployment/def456/predict",
         {"prompt": "Hello, world!"}),
        (BasetenAsyncPredictConfig(model_id="abc123", input_json='{"prompt":"Hello, world!"}'),
         "https://model-abc123.api.baseten.co/environments/production/async_predict",
         {"model_input": {"prompt": "Hello, world!"}}),
    ],
)
@pytest.mark.asyncio
async def test_dedicated_inference_routes(config, url, body):
    # Identity-model input and IDs: https://docs.baseten.co/inference/async.md
    async_prediction = config.operation == "submit_async_prediction"
    response_body = {"request_id": "YOUR_REQUEST_ID"} if async_prediction else body
    response_status = 201 if async_prediction else 200
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(response_status, json=response_body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("nodes.baseten_node.httpx.AsyncClient", return_value=client):
        result = await make_node(config).execute({})
    assert result["status"] == "success"
    assert result["status_code"] == response_status
    assert result["data"] == response_body
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == url
    assert requests[0].headers["Authorization"] == f"Bearer {KEY}"
    assert json.loads(requests[0].content) == body


@pytest.mark.asyncio
async def test_async_prediction_rejects_array_before_request():
    config = BasetenAsyncPredictConfig(model_id="abc123", input_json='[]')
    with patch("nodes.baseten_node.httpx.AsyncClient") as client:
        with pytest.raises(ValueError, match="Async model input must be a JSON object"):
            await make_node(config).execute({})
    client.assert_not_called()


@pytest.mark.parametrize("bad", ["bad.example.com", "../m", "x/y", "", "a b"])
def test_model_id_cannot_change_request_host_or_path(bad):
    with pytest.raises(ValueError):
        _segment(bad, "Model ID")


@pytest.mark.parametrize("bad", ["not json", '"string"', "1", "x" * 100001])
def test_prediction_requires_bounded_json_body(bad):
    with pytest.raises(ValueError):
        _input_json(bad)


@pytest.mark.asyncio
async def test_http_disables_redirects_and_redacts_provider_error():
    client = AsyncMock()
    client.request.return_value = httpx.Response(
        401, json={"error": f"invalid key {KEY}"},
    )
    client.__aenter__.return_value = client
    with patch("nodes.baseten_node.httpx.AsyncClient", return_value=client) as factory:
        result = await _request(KEY, "GET", "https://api.baseten.co/v1/users/me",
                                action="get_current_user")
    assert result["status"] == "error"
    assert KEY not in str(result)
    assert client.request.await_args.kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    assert factory.call_args.kwargs["follow_redirects"] is False


def test_connection_evidence_is_account_specific():
    evidence = BasetenNode.connection_evidence
    assert evidence.identity_operation == "get_current_user"
    assert "workspace_name" in evidence.identity_keys
    assert BasetenAPIKeyCredential.model_fields["api_key"].json_schema_extra["ui:widget"] == "password"
