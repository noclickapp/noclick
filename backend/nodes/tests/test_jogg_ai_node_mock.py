"""Exercise native Jogg Ai factory requests without a provider account."""
import json
from pathlib import Path

import httpx
import pytest
from nodes.core.base import ConfigValidationError

from nodes import jogg_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-jogg-ai-key-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/jogg-ai/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="jogg-fixture", node_type="automation-jogg-ai", node_data={
        "config": config, "credentials": {"credential_type": "jogg_ai_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["operation"])
async def test_each_operation_makes_one_documented_request(monkeypatch, fixture):
    data = {"task_id": "task_123456789", "status": "processing"}
    requests = transport(monkeypatch, {"code": 0, "msg": "Success", "data": data})
    result = await node(fixture["config"]).execute({})
    if fixture["operation"] == "update_product":
        assert result == {"status": "success", "code": 0, "message": "Success"}
    else:
        assert result == {"status": "success", "data": data}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"] and request.url.host == "api.jogg.ai"
    path = fixture["path"]
    config = node(fixture["config"]).config.config.model_dump(exclude_none=True, exclude={"operation"})
    for name in tuple(config):
        if "{" + name + "}" in path:
            path = path.replace("{" + name + "}", str(config.pop(name)))
    for name in native.JSON_FIELDS.get(fixture["operation"], ()):
        if name in config:
            config[name] = json.loads(config[name])
    assert request.url.path == path
    assert request.headers["x-api-key"] == TOKEN
    if request.method == "GET":
        assert dict(request.url.params) == {k: str(v) for k, v in config.items()}
        assert request.content == b""
    else:
        assert json.loads(request.content) == config
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [10104, 10105, 18020, 18025, 40000, 50000])
async def test_business_error_is_not_a_success(monkeypatch, code):
    transport(monkeypatch, {"code": code, "msg": "Invalid API key", "data": {}})
    with pytest.raises(ValueError, match=f"Jogg Ai {code}: Invalid API key"):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_account_identity_and_pagination_are_preserved(monkeypatch):
    data = {"email": "user@example.com", "username": "johndoe"}
    transport(monkeypatch, {"code": 0, "msg": "Success", "data": data})
    assert (await node({"operation": "get_current_user"}).execute({}))["data"] == data
    page = {"avatars": [], "pagination": {"page": 2, "page_size": 10, "total": 25}}
    requests = transport(monkeypatch, {"code": 0, "msg": "Success", "data": page})
    assert (await node({"operation": "list_custom_avatars", "page": 2}).execute({}))["data"] == page
    assert requests[0].url.params["page"] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"code": True, "msg": "Success", "data": {}}, {"code": 0, "msg": "Success"}])
async def test_malformed_envelopes_fail(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_http_failures_and_redirects_are_not_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"code": 0, "msg": "Success", "data": {}}, status)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await node({"operation": "get_current_user"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "a/b", "a?x=1", "a#x"])
async def test_resource_ids_cannot_change_routes(monkeypatch, identifier):
    requests = transport(monkeypatch, {"code": 0, "msg": "Success", "data": {}})
    with pytest.raises(ValueError, match="single Jogg Ai resource ID"):
        await node({"operation": "get_avatar_video", "id": identifier}).execute({})
    assert not requests


def test_json_editor_input_and_documented_conditional_requirements():
    fixture = next(f for f in FIXTURES if f["operation"] == "create_avatar_video")
    config = {**fixture["config"], "avatar": json.dumps(fixture["config"]["avatar"])}
    assert json.loads(node(config).config.config.avatar)["avatar_id"] == 81
    config["voice"] = {"type": "audio", "voice_id": "en-US-ChristopherNeural"}
    with pytest.raises(ConfigValidationError, match="documented field structure"):
        node(config)
    with pytest.raises(ConfigValidationError, match="product URL or name"):
        node({"operation": "create_product"})
    assert native.JoggAiAPIKeyCredential(api_key=TOKEN).credential_type == "jogg_ai_api_key"


@pytest.mark.asyncio
async def test_update_product_accepts_documented_body_without_data(monkeypatch):
    transport(monkeypatch, {"code": 0, "msg": "Success"})
    result = await node({"operation": "update_product", "product_id": "NTQ0MTkzNjg", "name": "Updated"}).execute({})
    assert result == {"status": "success", "code": 0, "message": "Success"}
