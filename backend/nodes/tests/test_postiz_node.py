"""Postiz REST request, authentication, error handling and validation tests."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nodes.postiz_node import PostizNode, PostizNodeConfig, PostizApiKeyCredential, _request

CASES = [({'operation': 'get_analytics', 'integration': 'example', 'date': 'example'}, 'GET', '/analytics/example', {'date': 'example'}, None), ({'operation': 'get_post_analytics', 'postId': 'example', 'date': 'example'}, 'GET', '/analytics/post/example', {'date': 'example'}, None), ({'operation': 'start_clipping', 'url': 'https://example.test/resource', 'clips': 5, 'fit': 'blur'}, 'POST', '/clipping', {}, {'url': 'https://example.test/resource', 'clips': 5, 'fit': 'blur'}), ({'operation': 'get_clipping', 'id': 'example'}, 'GET', '/clipping/example', {}, None), ({'operation': 'list_clippings', 'page': 1}, 'GET', '/clipping', {'page': 1}, None), ({'operation': 'get_integration_url', 'integration': 'example'}, 'GET', '/social/example', {}, None), ({'operation': 'delete_channel', 'id': 'example'}, 'DELETE', '/integrations/example', {}, None), ({'operation': 'find_slot', 'id': 'example'}, 'GET', '/find-slot/example', {}, None), ({'operation': 'list_groups'}, 'GET', '/groups', {}, None), ({'operation': 'is_connected'}, 'GET', '/is-connected', {}, None), ({'operation': 'list_integrations'}, 'GET', '/integrations', {}, None), ({'operation': 'get_me'}, 'GET', '/me', {}, None), ({'operation': 'get_integration_settings', 'id': 'example'}, 'GET', '/integration-settings/example', {}, None), ({'operation': 'trigger_integration_tool', 'id': 'example', 'methodName': 'example'}, 'POST', '/integration-trigger/example', {}, {'methodName': 'example'}), ({'operation': 'list_notifications', 'page': 0}, 'GET', '/notifications', {'page': 0}, None), ({'operation': 'change_post_status', 'id': 'example', 'status': 'draft'}, 'PUT', '/posts/example/status', {}, {'status': 'draft'}), ({'operation': 'create_post', 'type': 'draft', 'date': '2026-10-09T12:00:00Z', 'shortLink': False, 'tags': [{'value': 'example', 'label': 'example'}]}, 'POST', '/posts', {}, {'type': 'draft', 'date': '2026-10-09T12:00:00Z', 'shortLink': False, 'tags': [{'value': 'example', 'label': 'example'}]}), ({'operation': 'delete_post_by_group', 'group': 'example'}, 'DELETE', '/posts/group/example', {}, None), ({'operation': 'delete_post', 'id': 'example'}, 'DELETE', '/posts/example', {}, None), ({'operation': 'list_posts', 'startDate': '2026-10-09T12:00:00Z', 'endDate': '2026-10-09T12:00:00Z'}, 'GET', '/posts', {'startDate': '2026-10-09T12:00:00Z', 'endDate': '2026-10-09T12:00:00Z'}, None), ({'operation': 'get_missing_content', 'id': 'example'}, 'GET', '/posts/example/missing', {}, None), ({'operation': 'update_post_settings', 'id': 'example', 'settings': {}}, 'PUT', '/posts/example/settings', {}, {'settings': {}}), ({'operation': 'update_release_id', 'id': 'example', 'releaseId': 'example'}, 'PUT', '/posts/example/release-id', {}, {'releaseId': 'example'}), ({'operation': 'list_media', 'page': 1}, 'GET', '/media', {'page': 1}, None), ({'operation': 'upload_file', 'file_base64': 'aGVsbG8=', 'filename': 'sample.txt', 'content_type': 'text/plain'}, 'POST', '/upload', {}, {'file_base64': 'aGVsbG8=', 'filename': 'sample.txt', 'content_type': 'text/plain'}), ({'operation': 'upload_from_url', 'url': 'https://example.test/resource'}, 'POST', '/upload-from-url', {}, {'url': 'https://example.test/resource'}), ({'operation': 'video_function', 'functionName': 'example', 'identifier': 'example'}, 'POST', '/video/function', {}, {'functionName': 'example', 'identifier': 'example'}), ({'operation': 'generate_video', 'type': 'image-text-slides', 'output': 'vertical', 'customParams': {}}, 'POST', '/generate-video', {}, {'type': 'image-text-slides', 'output': 'vertical', 'customParams': {}})]

@pytest.mark.asyncio
@pytest.mark.parametrize("args,method,path,params,body", CASES)
async def test_documented_http_contract(args, method, path, params, body):
    credential = PostizApiKeyCredential(api_key="test-key")
    config = PostizNodeConfig(config=args, credentials=credential)
    node = PostizNode("test", "automation-postiz", {}, config=config)
    client = AsyncMock()
    client.request.return_value = httpx.Response(200, json={"items": [{"id": "resource"}]})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("nodes.postiz_node.httpx.AsyncClient", return_value=context):
        result = await node.execute({})
    assert result["status"] == "success"
    positional, kwargs = client.request.call_args
    assert positional == (method, 'https://api.postiz.com/public/v1' + path)
    assert kwargs["headers"]["Authorization"] == 'test-key'
    if args["operation"] == "upload_file":
        assert kwargs["files"] == {"file": ("sample.txt", b"hello", "text/plain")}
        assert "json" not in kwargs
    else:
        assert kwargs["params"] == params
        assert kwargs.get("json") == body
    assert result["data"] == {"items": [{"id": "resource"}]}
    assert "total" in result["timing_ms"]

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_errors_are_not_retried_or_echoed(status):
    client = AsyncMock()
    client.request.return_value = httpx.Response(status, json={"error": "test-key"}, headers={"Retry-After": "60"})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("nodes.postiz_node.httpx.AsyncClient", return_value=context) as constructor:
        result = await _request({"api_key": "test-key"}, "GET", '/me', action="probe")
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert "test-key" not in json.dumps(result)
    client.request.assert_awaited_once()
    assert constructor.call_args.kwargs["follow_redirects"] is False

@pytest.mark.asyncio
async def test_timeout_is_not_retried():
    client = AsyncMock()
    client.request.side_effect = httpx.ReadTimeout("sensitive request details")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    with patch("nodes.postiz_node.httpx.AsyncClient", return_value=context):
        result = await _request({"api_key": "test-key"}, "GET", '/me', action="probe")
    assert result["status"] == "error"
    assert "sensitive" not in json.dumps(result)
    client.request.assert_awaited_once()

def test_oauth_token_is_sent_raw_and_self_hosted_url_is_respected():
    from nodes.postiz_node import _auth
    assert _auth({"access_token": "pos_test", "base_url": "https://postiz.example.test/public/v1/"}) == ("https://postiz.example.test/public/v1", "pos_test")
    with pytest.raises(ValueError):
        _auth({"api_key": "test", "base_url": "https://user:password@example.test/public/v1"})

def test_non_draft_posts_require_content_and_zoned_date():
    from nodes.postiz_node import PostizCreatePostConfig
    with pytest.raises(ValueError):
        PostizCreatePostConfig(type="now", date="2026-10-09T12:00:00Z", shortLink=False, tags=[])
    with pytest.raises(ValueError):
        PostizCreatePostConfig(type="draft", date="2026-10-09T12:00:00", shortLink=False, tags=[])


@pytest.mark.parametrize("file_base64", ["", "1", "%%%", "aGVs\nbG8="])
def test_upload_rejects_invalid_base64_during_configuration(file_base64):
    with pytest.raises(ValueError):
        PostizNodeConfig(
            config={"operation": "upload_file", "file_base64": file_base64, "filename": "photo.jpg"},
            credentials=PostizApiKeyCredential(api_key="test-key"),
        )


@pytest.mark.asyncio
async def test_preserves_documented_upload_response():
    # https://docs.postiz.com/public-api/uploads/upload-file — Example response.
    body = {
        "id": "01HXYZ123ABCDEF",
        "path": "https://uploads.postiz.com/photo.jpg",
        "status": "ready",
    }
    client = AsyncMock()
    client.request.return_value = httpx.Response(200, json=body)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    config = PostizNodeConfig(
        config={"operation": "upload_file", "file_base64": "aGVsbG8=", "filename": "sample.txt", "content_type": "text/plain"},
        credentials=PostizApiKeyCredential(api_key="test-key"),
    )
    node = PostizNode("test", "automation-postiz", {}, config=config)
    with patch("nodes.postiz_node.httpx.AsyncClient", return_value=context):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"] == body
