"""Postmark catalog and HTTP contracts (live FlowCanvas QA is separate)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml

from nodes import postmark_node
from nodes.postmark_node import (
    CONFIG_MODELS,
    OPERATIONS,
    PostmarkAccountTokenCredential,
    PostmarkNode,
    PostmarkNodeConfig,
    PostmarkServerTokenCredential,
)

ORIGINAL_CLIENT = httpx.AsyncClient


def mock_client(monkeypatch, handler):
    monkeypatch.setattr(
        postmark_node.httpx,
        "AsyncClient",
        lambda *args, **kwargs: ORIGINAL_CLIENT(
            *args, transport=httpx.MockTransport(handler), **kwargs
        ),
    )


def server_token():
    return PostmarkServerTokenCredential(server_token="server-secret-token")


def account_token():
    return PostmarkAccountTokenCredential(account_token="account-secret-token")


def test_catalog_is_pinned_to_official_swagger_and_contains_newer_actions():
    root = Path(__file__).parent / "fixtures" / "postmark"
    catalog = json.loads((root / "catalog.json").read_text())
    assert len(catalog["operations"]) == 84
    assert PostmarkNode.integration_type == "automation-postmark"
    assert {op["name"] for op in catalog["operations"]} == set(OPERATIONS) - {"test_connection"}
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 85
    assert PostmarkNode.connection_evidence.operation == "test_connection"
    for scope in ("server", "account"):
        source = (root / f"{scope}.yaml").read_bytes()
        spec = yaml.safe_load(source)
        assert catalog["source_sha256"][scope] == hashlib.sha256(source).hexdigest()
        from_spec = {
            (method.upper(), path)
            for path, methods in spec["paths"].items()
            for method in methods
            if method in {"get", "post", "put", "patch", "delete"}
        }
        from_catalog = {
            (op["method"], op["path"])
            for op in catalog["operations"]
            if op["scope"] == scope and "/swagger/" in op["source"]
        }
        assert from_catalog == from_spec
    assert "server_list_message_streams" in OPERATIONS
    assert "server_create_webhook" in OPERATIONS
    assert "server_list_suppressions" in OPERATIONS
    assert "account_create_data_removal" in OPERATIONS
    schema = PostmarkNode.get_config_schema()
    assert schema["x-agent-tool-provider"] is True
    assert "PostmarkServerTokenCredential" in schema["$defs"]
    assert "PostmarkAccountTokenCredential" in schema["$defs"]


@pytest.mark.asyncio
async def test_server_token_connection_redacts_returned_api_tokens(monkeypatch):
    def handler(request):
        assert request.method == "GET"
        assert request.url == "https://api.postmarkapp.com/server"
        assert request.headers["X-Postmark-Server-Token"] == "server-secret-token"
        assert "X-Postmark-Account-Token" not in request.headers
        return httpx.Response(
            200,
            json={"ID": 42, "ApiTokens": ["server-secret-token", "another-token"]},
        )

    mock_client(monkeypatch, handler)
    config = PostmarkNodeConfig(
        config={"operation": "test_connection"},
        credentials={
            "credential_type": "postmark_server_token",
            "server_token": "server-secret-token",
        },
    )
    node = PostmarkNode(
        node_id="postmark-connection",
        node_type="automation-postmark",
        node_data={},
        config=config,
    )
    result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["ID"] == 42
    assert result["data"]["ApiTokens"] == "[REDACTED]"
    assert "server-secret-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_account_token_connection_and_required_query_defaults(monkeypatch):
    def handler(request):
        assert request.url.path == "/servers"
        assert dict(request.url.params) == {"count": "1", "offset": "0"}
        assert request.headers["X-Postmark-Account-Token"] == "account-secret-token"
        return httpx.Response(200, json={"TotalCount": 0, "Servers": []})

    mock_client(monkeypatch, handler)
    result = await PostmarkNode._request(account_token(), "test_connection", {})
    assert result["data"]["TotalCount"] == 0


@pytest.mark.asyncio
async def test_wrong_token_scope_rejected_before_network(monkeypatch):
    def fail(request):
        raise AssertionError("Unexpected HTTP request")

    mock_client(monkeypatch, fail)
    with pytest.raises(ValueError, match="account token"):
        await PostmarkNode._request(server_token(), "account_list_servers", {})
    with pytest.raises(ValueError, match="server token"):
        await PostmarkNode._request(account_token(), "server_list_templates", {})


@pytest.mark.asyncio
async def test_canvas_uses_attached_account_token_for_account_action(monkeypatch):
    async def resolve(credential_id, user_id, **kwargs):
        assert credential_id == "account-credential-id"
        assert user_id == "local-user"
        return {
            "credential_type": "postmark_account_token",
            "account_token": "account-secret-token",
        }

    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", resolve)

    def handler(request):
        assert request.url.path == "/servers"
        assert request.headers["X-Postmark-Account-Token"] == "account-secret-token"
        assert "X-Postmark-Server-Token" not in request.headers
        return httpx.Response(200, json={"TotalCount": 1, "Servers": [{"ID": 42}]})

    mock_client(monkeypatch, handler)
    node = PostmarkNode(
        node_id="postmark-account",
        node_type="automation-postmark",
        node_data={
            "credentialIds": {
                "postmark_server_token": "server-credential-id",
                "postmark_account_token": "account-credential-id",
            }
        },
        config=PostmarkNodeConfig(
            config={"operation": "account_list_servers"},
            credentials={
                "credential_type": "postmark_server_token",
                "server_token": "server-secret-token",
            },
        ),
        user_id="local-user",
    )
    result = await node.execute({})
    assert result["data"]["Servers"][0]["ID"] == 42


@pytest.mark.asyncio
async def test_list_templates_uses_swagger_query_casing_and_defaults(monkeypatch):
    def handler(request):
        assert request.url.path == "/templates"
        assert dict(request.url.params) == {"Count": "100", "Offset": "0"}
        return httpx.Response(200, json={"Templates": [{"Name": "Receipt"}]})

    mock_client(monkeypatch, handler)
    result = await PostmarkNode._request(server_token(), "server_list_templates", {})
    assert result["data"]["Templates"][0]["Name"] == "Receipt"


@pytest.mark.asyncio
async def test_send_email_body_and_path_encoding(monkeypatch):
    def handler(request):
        assert request.url.path == "/email"
        assert request.method == "POST"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.read()) == {
            "From": "sender@example.com",
            "To": "recipient@example.com",
            "Subject": "Hello",
            "TextBody": "World",
        }
        return httpx.Response(200, json={"ErrorCode": 0, "MessageID": "abc"})

    mock_client(monkeypatch, handler)
    result = await PostmarkNode._request(
        server_token(),
        "server_send_email",
        {
            "body_json": json.dumps(
                {
                    "From": "sender@example.com",
                    "To": "recipient@example.com",
                    "Subject": "Hello",
                    "TextBody": "World",
                }
            )
        },
    )
    assert result["data"]["MessageID"] == "abc"


@pytest.mark.asyncio
async def test_rejects_bad_query_and_body_before_network(monkeypatch):
    mock_client(
        monkeypatch, lambda _: (_ for _ in ()).throw(AssertionError("No request"))
    )
    with pytest.raises(ValueError, match="Unknown query"):
        await PostmarkNode._request(
            server_token(), "server_list_templates", {"query_json": '{"bogus":1}'}
        )
    with pytest.raises(ValueError, match="JSON array"):
        await PostmarkNode._request(
            server_token(), "server_send_email_batch", {"body_json": "{}"}
        )
    with pytest.raises(ValueError, match="Request Body is missing required keys"):
        await PostmarkNode._request(
            server_token(), "server_create_a_template", {"body_json": "{}"}
        )


@pytest.mark.asyncio
async def test_postmark_error_code_and_http_error_are_surfaced_without_token(
    monkeypatch,
):
    mock_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, json={"ErrorCode": 422, "Message": "server-secret-token is invalid"}
        ),
    )
    with pytest.raises(ValueError, match=r"\[REDACTED\]"):
        await PostmarkNode._request(server_token(), "server_get_delivery_stats", {})
    mock_client(
        monkeypatch,
        lambda _: httpx.Response(401, json={"Message": "server-secret-token denied"}),
    )
    with pytest.raises(ValueError, match=r"\[REDACTED\]"):
        await PostmarkNode._request(server_token(), "server_get_delivery_stats", {})


@pytest.mark.asyncio
async def test_stream_path_escapes_id_and_query_is_exact(monkeypatch):
    def handler(request):
        assert request.url.raw_path == b"/message-streams/team%2Fwest"
        return httpx.Response(200, json={"ID": "team/west"})

    mock_client(monkeypatch, handler)
    result = await PostmarkNode._request(
        server_token(), "server_get_message_stream", {"path_stream_id": "team/west"}
    )
    assert result["data"]["ID"] == "team/west"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["server_send_email_with_template", "server_update_template"])
async def test_documented_template_requests(monkeypatch, operation):
    """Official sends use TemplateId alone; edits take their identifier from the path."""
    examples = json.loads(
        (Path(__file__).parent / "fixtures" / "postmark" / "template_requests.json").read_text()
    )
    values = examples[operation]["config"]
    body = json.loads(values["body_json"])

    def handler(request):
        assert json.loads(request.content) == body
        if operation == "server_send_email_with_template":
            assert request.method == "POST"
            assert request.url.path == "/email/withTemplate"
            assert "TemplateAlias" not in body
        else:
            assert request.method == "PUT"
            assert request.url.path == "/templates/1234"
            assert "TemplateId" not in body
        return httpx.Response(200, json={"ErrorCode": 0})

    mock_client(monkeypatch, handler)
    result = await PostmarkNode._request(server_token(), operation, values)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_template_send_still_requires_an_identifier(monkeypatch):
    mock_client(monkeypatch, lambda _: pytest.fail("No request expected"))
    with pytest.raises(ValueError, match="TemplateId or TemplateAlias"):
        await PostmarkNode._request(
            server_token(), "server_send_email_with_template",
            {"body_json": json.dumps({"From": "sender@example.com", "To": "receiver@example.com", "TemplateModel": {}})},
        )


@pytest.mark.asyncio
async def test_structured_json_and_editor_text_make_the_same_request(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"ErrorCode": 0})

    mock_client(monkeypatch, handler)
    body = {"From": "sender@example.com", "To": "receiver@example.com", "TemplateId": 1234, "TemplateModel": {"user_name": "John Smith"}}
    for value in (body, json.dumps(body)):
        model = PostmarkNodeConfig(
            config={"operation": "server_send_email_with_template", "body_json": value},
            credentials=server_token(),
        )
        await PostmarkNode._request(server_token(), model.config.operation, model.config.model_dump())
    assert bodies == [body, body]

    with pytest.raises(ValueError, match="Unknown query parameters"):
        await PostmarkNode._request(server_token(), "server_list_templates", {"query_json": {"bogus": 1}})
    with pytest.raises(ValueError, match="JSON object"):
        await PostmarkNode._request(server_token(), "server_list_templates", {"query_json": [1]})
    with pytest.raises(ValueError, match="missing required keys"):
        await PostmarkNode._request(server_token(), "server_send_email_with_template", {"body_json": {"TemplateId": 1234}})


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type, body", [("application/octet-stream", b"download bytes"), ("application/json", b"not json")])
async def test_downloaded_response_returns_binary_marker(monkeypatch, content_type, body):
    from nodes.core.binary_output import BinaryOutput

    mock_client(monkeypatch, lambda _: httpx.Response(200, content=body, headers={"content-type": content_type}))
    result = await PostmarkNode._request(server_token(), "server_get_bounce_dump", {"path_bounceid": "692560173"})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == body
    assert result["data"].content_type == content_type
    assert "content_base64" not in result
