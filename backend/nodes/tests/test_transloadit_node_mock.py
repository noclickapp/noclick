"""Exercise every native operation through the real factory with captured HTTP."""
import json
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import transloadit_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "transloadit_token", "access_token": "fixture-transloadit-token"}
ID = "0fce5b1063e611e88d8eb130f7921d8a"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments):
    return await run_node_operation(node_type="automation-transloadit", operation=operation,
        arguments=arguments, credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")


CASES = [
    ("list_assemblies", {}, "GET", "/assemblies"),
    ("get_assembly", {"assembly_id": ID}, "GET", "/assemblies/" + ID),
    ("cancel_assembly", {"assembly_id": ID}, "DELETE", "/assemblies/" + ID),
    ("create_assembly", {"template_id": ID, "fields": {"url": "https://example.com/file.jpg"}}, "POST", "/assemblies"),
    ("replay_assembly", {"assembly_id": ID, "reparse_template": 1}, "POST", "/assemblies/" + ID + "/replay"),
    ("list_assembly_notifications", {"assembly_id": ID}, "GET", "/assembly_notifications/" + ID),
    ("replay_assembly_notification", {"assembly_id": ID, "wait": True}, "POST", "/assembly_notifications/" + ID + "/replay"),
    ("list_templates", {}, "GET", "/templates"),
    ("get_template", {"template_id_or_name": "resize-images"}, "GET", "/templates/resize-images"),
    ("create_template", {"name": "resize-images", "template": {"steps": {"resize": {"robot": "/image/resize", "use": ":original", "width": 320}}}}, "POST", "/templates"),
    ("update_template", {"template_id_or_name": "resize-images", "name": "new-name"}, "PUT", "/templates/resize-images"),
    ("delete_template", {"template_id_or_name": "resize-images"}, "DELETE", "/templates/resize-images"),
    ("list_template_credentials", {}, "GET", "/template_credentials"),
    ("list_template_credential_types", {}, "GET", "/template_credentials/types"),
    ("get_template_credential", {"template_credential_id": ID}, "GET", "/template_credentials/" + ID),
    ("delete_template_credential", {"template_credential_id": ID}, "DELETE", "/template_credentials/" + ID),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_operation_wire(transport, operation, arguments, method, path):
    requests, replies = transport
    replies.append((200, {"ok": "SUCCESS", "items": [{"id": ID, "name": "resize-images"}]}))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api2.transloadit.com"
    if operation in node.CAPABILITY_OPERATIONS:
        assert "authorization" not in request.headers
        assert not request.content and not request.url.query
    else:
        assert request.headers["authorization"] == "Bearer " + AUTH["access_token"]
        if operation == "create_assembly":
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert b'"template_id":"' + ID.encode() + b'"' in request.content
        else:
            wire = request.url.params["params"] if method == "GET" else parse_qs(request.content.decode())["params"][0]
            params = json.loads(wire)
            expected = {k: v for k, v in arguments.items() if k not in {"assembly_id", "template_id_or_name", "template_credential_id"}}
            assert all(params[k] == v for k, v in expected.items())
    assert AUTH["access_token"] not in str(request.url)


@pytest.mark.asyncio
async def test_provider_error_preserved(transport):
    transport[1].append((401, {"error": "TOKEN_EXPIRED", "message": "Token has expired"}))
    with pytest.raises(ValueError, match="Token has expired"):
        await run("list_templates", {})


@pytest.mark.asyncio
async def test_stored_credential_content_not_returned(transport):
    transport[1].append((200, {"credential": {"id": ID, "name": "storage", "content": {"key": "private"}, "stringified": "private"}}))
    result = await run("get_template_credential", {"template_credential_id": ID})
    assert result["data"]["credential"] == {"id": ID, "name": "storage"}


@pytest.mark.asyncio
async def test_instructions_auth_redacted_and_results_preserved(transport):
    transport[1].append((200, {"assembly_id": ID, "params": {"auth": {"key": "private"}}, "results": {"resize": [{"ssl_url": "https://example.com/result.jpg"}]}}))
    result = await run("get_assembly", {"assembly_id": ID})
    assert result["data"]["params"] == {}
    assert result["data"]["results"]["resize"][0]["ssl_url"].endswith("result.jpg")


@pytest.mark.parametrize("value", ["../bad", "abc?x=y", "a/b", "UPPER"])
def test_path_validation(value):
    with pytest.raises(ValueError):
        node.GetAssembly(assembly_id=value)


def test_token_validation():
    with pytest.raises(ValueError):
        node.TransloaditTokenCredential(access_token="Bearer accidental-prefix")


@pytest.mark.asyncio
async def test_published_assembly_response(transport):
    # Verbatim example from the pinned API2 contract, /assemblies POST 2XX.
    body = json.loads((Path(__file__).parent / "fixtures/transloadit/assembly.json").read_text())
    transport[1].append((200, body))
    result = await run("create_assembly", {"template_id": ID})
    assert result["data"]["assembly_id"] == body["assembly_id"]
    assert result["data"]["assembly_ssl_url"] == body["assembly_ssl_url"]
    assert result["data"]["results"] == body["results"]
    assert '"auth"' not in json.dumps(result)
