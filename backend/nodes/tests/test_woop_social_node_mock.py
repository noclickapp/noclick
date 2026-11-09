"""Synthetic transport tests; no WoopSocial account or live writes are used."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import woop_social_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.woop_social_operations import ROUTES, CreatePostConfig

TOKEN = "synthetic-woop-secret-42"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/woop-social/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="woop-test", node_type="automation-woop-social",
        node_data={"config": config, "credentials": {"credential_type": "woop_social_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


def test_woop_social_registration_and_manual_credential():
    assert NODE_REGISTRY["automation-woop-social"] is native.WoopSocialNode
    credential = native.WoopSocialAPIKey(api_key="  " + TOKEN + " ")
    assert credential.credential_type == "woop_social_api_key" and credential.api_key == TOKEN
    assert native.WoopSocialNode.connection_evidence.operation == "list_projects"
    with pytest.raises(ValidationError):
        native.WoopSocialAPIKey(api_key="Bearer " + TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(ROUTES))
async def test_woop_social_each_operation_exact_request(monkeypatch, operation):
    config = FIXTURE[operation]
    method, path, query, body_model, status = ROUTES[operation]
    response = {"id": "resource-1"}
    if operation in {"list_projects", "list_social_accounts", "list_webhooks"}:
        response = [{"id": "project-1", "name": "My project"}]
    elif operation == "list_media":
        response = {"media": [], "nextCursor": "opaque+next"}
    elif operation == "list_social_account_posts":
        response = {"socialAccountPosts": [], "nextCursor": "opaque+next"}
    elif operation == "validate_post":
        response = {"isValid": False, "errors": [{"path": "content", "message": "Needs media"}], "warnings": []}
    elif operation == "get_social_account_platform_inputs":
        response = {"socialAccountId": "account-1", "platformSpecificInputs": {}}
    calls = transport(monkeypatch, response, status)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.host == "api.woopsocial.com"
    for key, value in config.items():
        path = path.replace("{" + key + "}", str(value))
    assert request.url.path == "/v1" + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    if body_model:
        expected = node(config).config.config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        assert json.loads(request.content) == expected
    else:
        assert not request.content
    if operation in {"list_media", "list_social_account_posts"}:
        assert result["next_cursor"] == "opaque+next" and result["has_more"] is True
    if status == 204:
        assert result["deletion_acknowledged"] is True and "data" not in result


@pytest.mark.asyncio
async def test_woop_social_csv_filters_and_cursor_are_preserved(monkeypatch):
    calls = transport(monkeypatch, {"socialAccountPosts": []})
    result = await node({"operation": "list_social_account_posts", "projectId": ["a", "b"],
        "platform": ["BLUESKY", "X"], "deliveryStatus": ["FAILED"], "limit": 2, "cursor": "opaque+/="}).execute({})
    assert dict(calls[0].url.params) == {"projectId": "a,b", "platform": "BLUESKY,X", "deliveryStatus": "FAILED", "limit": "2", "cursor": "opaque+/="}
    assert result["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_woop_social_errors_redact_key_and_never_retry(monkeypatch, status):
    calls = transport(monkeypatch, {"message": "Provider rejection " + TOKEN}, status)
    result = await node({"operation": "create_project", "name": "Project"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and "Provider rejection" in result["message"] and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "failed"}, {"data": []}, "html"])
async def test_woop_social_invalid_success_envelope_is_error(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_projects"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "x/y", "x?y", "x#y", "x\\y"])
async def test_woop_social_path_injection_makes_no_request(monkeypatch, identifier):
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({"operation": "get_post", "postId": identifier}).execute({})
    assert calls == []


def test_woop_social_platform_specific_required_fields_and_content_bounds():
    base = FIXTURE["create_post"]
    for override in ({"content": []}, {"content": [{}, {}]}, {"socialAccounts": []},
                     {"socialAccounts": [{"platform": "PINTEREST", "socialAccountId": "a"}]},
                     {"socialAccounts": base["socialAccounts"] * 2}):
        with pytest.raises(ValidationError):
            CreatePostConfig.model_validate({**base, **override})


@pytest.mark.asyncio
async def test_woop_social_intended_post_response_preserves_child_platform(monkeypatch):
    # Provider documents SocialAccountPost's platform discriminator, despite the
    # base additionalProperties:false accidentally forbidding it in OpenAPI.
    body = {"id": "post-1", "socialAccountPosts": [{"platform": "BLUESKY", "socialAccountPostId": "child-1", "analytics": {}}]}
    transport(monkeypatch, body)
    result = await node({"operation": "get_post", "postId": "post-1"}).execute({})
    assert result["data"] == body
