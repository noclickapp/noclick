"""Exercise Upload Post requests without credentials or external side effects.

These tests pin publishing encodings, pagination, account evidence, validation,
and provider refusals independently of the offline conformance harness.
"""
import json
from contextlib import asynccontextmanager
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory
from nodes.upload_post_node import UploadPostNode, UploadPostAPIKeyCredential, OPERATIONS

TOKEN = "test-upload-post-key"


def node(config):
    return NodeFactory.create_node(node_id="upload-post-test", node_type="automation-upload-post",
        node_data={"config": config, "credentials": {"credential_type": "upload_post_api_key", "api_key": TOKEN}})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as instance:
            yield instance
    monkeypatch.setattr("nodes.upload_post_node.guarded_async_client", client)


def parts(request):
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.content)
    result = {}
    for part in message.iter_parts():
        assert part.get_filename() is None
        result.setdefault(part.get_param("name", header="content-disposition"), []).append(part.get_content())
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,media", [("upload_video", {"video": "https://example.com/video.mp4"}),
    ("upload_document", {"document": "https://example.com/report.pdf"}), ("upload_text", {})])
async def test_publish_multipart_repeated_platforms_and_async_ack(monkeypatch, operation, media):
    platforms = ["linkedin"] if operation == "upload_document" else ["linkedin", "x"]
    expected_path = {"upload_video": "/api/upload", "upload_document": "/api/upload_document", "upload_text": "/api/upload_text"}[operation]
    acknowledgement = {"success": True, "request_id": "request-123", "message": "Upload initiated"}
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "POST" and request.url.path == expected_path
        assert request.headers["authorization"] == "Apikey " + TOKEN
        parsed = parts(request)
        assert parsed["platform[]"] == platforms
        assert parsed["title"] == ["A social post"]
        assert parsed["user"] == ["acme"]
        for key, value in media.items(): assert parsed[key] == [value]
        if operation != "upload_document":
            assert parsed["async_upload"] == ["true"]
            assert parsed["add_to_queue"] == ["false"]
        return httpx.Response(200, json=acknowledgement)
    transport(monkeypatch, handler)
    config = {"operation": operation, "user": "acme", "platforms": platforms, "title": "A social post", **media}
    if operation != "upload_document": config.update(async_upload=True, add_to_queue=False)
    assert await node(config).execute({}) == acknowledgement
    assert len(requests) == 1  # A publish never retries or silently follows with another action.


@pytest.mark.asyncio
async def test_media_cursor_and_history_pagination_preserved(monkeypatch):
    response = {"success": True, "media": [{"id": "post-1"}], "pagination": {"has_more": True, "next_cursor": "cursor+/="}}
    def handler(request):
        assert request.method == "GET"
        assert dict(request.url.params) == {"user": "acme", "platform": "instagram", "limit": "20", "cursor": "cursor+/="}
        return httpx.Response(200, json=response)
    transport(monkeypatch, handler)
    assert await node({"operation": "get_media", "user": "acme", "platform": "instagram", "limit": 20, "cursor": "cursor+/="}).execute({}) == response


@pytest.mark.asyncio
@pytest.mark.parametrize("display_name", [None, "Acme Corp"])
async def test_rename_preserves_explicit_null_and_escapes_path(monkeypatch, display_name):
    def handler(request):
        assert request.method == "PATCH"
        assert request.url.raw_path == b"/api/uploadposts/users/acme%2Fteam"
        assert json.loads(request.content) == {"display_name": display_name}
        return httpx.Response(200, json={"success": True})
    transport(monkeypatch, handler)
    await node({"operation": "rename_profile", "username": "acme/team", "display_name": display_name}).execute({})


@pytest.mark.asyncio
async def test_queue_json_and_nested_slots(monkeypatch):
    body = {"profile_username": "acme", "timezone": "Europe/London", "slots": [{"hour": 9, "minute": 30}], "days_of_week": [0, 2, 4]}
    def handler(request):
        assert request.method == "POST" and request.url.path == "/api/uploadposts/queue/settings"
        assert json.loads(request.content) == body
        return httpx.Response(200, json={"success": True, **body})
    transport(monkeypatch, handler)
    assert (await node({"operation": "update_queue_settings", **body}).execute({}))["slots"] == body["slots"]


@pytest.mark.asyncio
async def test_account_evidence_is_an_authenticated_read(monkeypatch):
    account = {"success": True, "email": "user@example.com", "plan": "Professional"}
    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/uploadposts/me"
        assert request.headers["authorization"] == "Apikey " + TOKEN
        assert not request.content
        return httpx.Response(200, json=account)
    transport(monkeypatch, handler)
    assert UploadPostNode.connection_evidence.identity_operation == "get_current_user"
    assert await node({"operation": "get_current_user"}).execute({}) == account


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "Invalid API key"}), (409, {"error": "Post is being published"}),
    (200, {"success": False, "message": "Rejected"}), (302, {"error": "Redirect"})])
async def test_refusal_is_not_a_success_and_secret_is_redacted(monkeypatch, status, body):
    transport(monkeypatch, lambda request: httpx.Response(status, json={**body, "debug": TOKEN}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_current_user"}).execute({})
    assert TOKEN not in str(error.value)
    assert (body.get("error") or body["message"]) in str(error.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_profile", "username": ".."},
    {"operation": "update_queue_settings", "profile_username": "acme", "days_of_week": [7]},
    {"operation": "update_queue_settings", "profile_username": "acme", "slots": [{"hour": 24, "minute": 0}]},
    {"operation": "upload_video", "user": "acme", "platforms": ["x"], "title": "title", "video": "http://example.com/a.mp4"},
    {"operation": "upload_text", "user": "acme", "platforms": ["instagram"], "title": "title"},
    {"operation": "upload_text", "user": "acme", "platforms": ["x"], "title": "title", "scheduled_date": "2099-01-01T12:00:00Z", "add_to_queue": True},
    {"operation": "get_media", "platform": "linkedin", "user": "acme", "cursor": "cursor"},
    {"operation": "get_analytics", "profile_username": "acme", "platforms": "facebook"},
])
def test_invalid_inputs_are_rejected_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_key_defaults_and_family_validation():
    assert UploadPostAPIKeyCredential(api_key=TOKEN).credential_type == "upload_post_api_key"
    assert UploadPostAPIKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    with pytest.raises(ValidationError): UploadPostAPIKeyCredential(api_key="Apikey " + TOKEN)
    with pytest.raises(ValidationError): UploadPostAPIKeyCredential(credential_type="other", api_key=TOKEN)


def test_operations_have_unique_published_contract_mappings():
    operations = json.loads((Path(__file__).parent / "fixtures/upload-post/operations.json").read_text())
    assert len(operations) == 25
    assert set(OPERATIONS) == {row["operation"] for row in operations}
    assert len({(row["method"], row["path"]) for row in operations}) == 25


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_upload_status", "retry_post"])
async def test_scheduled_job_can_be_tracked_and_retried_without_request_id(monkeypatch, operation):
    def handler(request):
        if operation == "get_upload_status":
            assert dict(request.url.params) == {"job_id": "scheduled-123"}
        else:
            assert json.loads(request.content) == {"job_id": "scheduled-123"}
        return httpx.Response(200, json={"success": True})
    transport(monkeypatch, handler)
    await node({"operation": operation, "job_id": "scheduled-123"}).execute({})


DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/upload-post/witnesses.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("selector,fixture", list(DOCUMENTED.items()))
async def test_provider_authored_successes_are_preserved(monkeypatch, selector, fixture):
    method, path = selector.split(" ", 1)
    path = path.split("?", 1)[0]
    operation = next(name for name, route in OPERATIONS.items() if route["method"] == method and route["path"] == path)
    configs = json.loads((Path(__file__).parent / "fixtures/upload-post/inputs.json").read_text())
    config = configs.get(operation, {}).get("config") or {"operation": operation, **{
        "get_scheduled_post": {"job_id": "job-1"}, "retry_post": {"request_id": "request-1"}
    }.get(operation, {})}
    transport(monkeypatch, lambda request: httpx.Response(200, json=fixture["body"]))
    assert await node(config).execute({}) == fixture["body"]
