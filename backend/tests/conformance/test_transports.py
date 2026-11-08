"""Real SDK controls for the offline transport boundary (synthetic test data)."""
import asyncio
import base64
from contextlib import closing
from io import BytesIO
from typing import Literal

import boto3
import aiohttp
import httpx
import pytest
from botocore.config import Config
from botocore.httpsession import URLLib3Session
from pydantic import BaseModel

from tests.conformance import harness
from tests.conformance.transports import intercept_http


def aws_client(service, **kwargs):
    return boto3.client(
        service,
        aws_access_key_id="fake-key",
        aws_secret_access_key="fake-secret",
        aws_session_token="fake-session",
        region_name="us-east-1",
        config=Config(signature_version="s3v4" if service == "s3" else "v4"),
        **kwargs,
    )


def test_botocore_captures_signed_serialized_upload_and_restores_patch():
    captured = []
    original = URLLib3Session.send
    payload = b"\x00\xff\x80binary"

    def respond(request):
        captured.append(request)
        return httpx.Response(200, headers={"etag": '"synthetic"'}, request=request)

    with intercept_http(respond), closing(aws_client("s3")) as client:
        result = client.put_object(
            Bucket="transport-test",
            Key="folder/a b.bin",
            Body=BytesIO(payload),
            ContentType="application/octet-stream",
        )
    assert URLLib3Session.send is original
    assert result["ETag"] == '"synthetic"'
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "PUT"
    assert (
        str(request.url) == "https://transport-test.s3.amazonaws.com/folder/a%20b.bin"
    )
    assert request.headers["content-type"] == "application/octet-stream"
    assert request.headers["x-amz-security-token"] == "fake-session"
    assert request.headers["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=fake-key/"
    )
    assert "SignedHeaders=" in request.headers["authorization"]
    # Current botocore adds aws-chunked checksum framing to streamed S3 uploads.
    # Capture those bytes too; do not repair the body or hide the encoding header.
    if request.headers.get("content-encoding") == "aws-chunked":
        assert request.content.startswith(
            f"{len(payload):x}\r\n".encode() + payload + b"\r\n"
        )
        assert b"x-amz-checksum-" in request.content
    else:
        assert request.content == payload


def test_botocore_streamed_response_reaches_sdk_parser_and_body_reader():
    payload = b"\x00\xffsynthetic download"
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(
            200,
            content=payload,
            headers={"content-length": str(len(payload)), "etag": '"synthetic"'},
            request=request,
        )

    with intercept_http(respond), closing(aws_client("s3")) as client:
        result = client.get_object(Bucket="transport-test", Key="a b", VersionId="v/1")
        with closing(result["Body"]) as body:
            assert body.read(2) + body.read() == payload
        assert body._raw_stream.closed
    assert result["ContentLength"] == len(payload)
    assert result["ETag"] == '"synthetic"'
    assert captured[0].method == "GET"
    assert captured[0].url.params["versionId"] == "v/1"


@pytest.mark.asyncio
@pytest.mark.parametrize("stack", ["botocore", "aiohttp"])
@pytest.mark.parametrize(
    "bad_request,bad_response", [(False, False), (True, False), (False, True)]
)
async def test_run_provider_validates_sdk_requests_and_generated_responses(
    monkeypatch, bad_request, bad_response, stack
):
    from nodes.core.registry import NODE_REGISTRY

    # A deliberately small, synthetic contract exercises the common validator;
    # it is not a provider example or a replacement for any catalog's pinned spec.
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "SDK transport control", "version": "1"},
        "servers": [{"url": "https://apigateway.us-east-1.amazonaws.com"}],
        "security": [{"signature": []}],
        "components": {
            "securitySchemes": {
                "signature": {"type": "apiKey", "in": "header", "name": "Authorization"}
            }
        },
        "paths": {
            "/restapis": {
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1, "maximum": 10},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Synthetic success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["items"],
                                        "properties": {
                                            "items": {
                                                "type": "array",
                                                "minItems": 1,
                                                "items": {
                                                    "type": "object",
                                                    "required": ["name"],
                                                    "properties": {
                                                        "name": {
                                                            "type": "string",
                                                            "minLength": 3,
                                                            **(
                                                                {"maxLength": 1}
                                                                if bad_response
                                                                else {}
                                                            ),
                                                        }
                                                    },
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }

    class Inputs(BaseModel):
        operation: Literal["get_rest_apis"]

    class NodeConfig(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: NodeConfig)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            if stack == "aiohttp":
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://apigateway.us-east-1.amazonaws.com/restapis",
                        params={"limit": 11 if bad_request else 1},
                        headers={"authorization": "synthetic-signature"},
                    ) as response:
                        return await response.json()

            def run():
                with closing(aws_client("apigateway")) as client:
                    return client.get_rest_apis(limit=11 if bad_request else 1)

            return await asyncio.to_thread(run)

    monkeypatch.setitem(harness.PROVIDERS, "sdk-control", ("test-sdk-control", {}))
    monkeypatch.setitem(NODE_REGISTRY, "test-sdk-control", Node)
    monkeypatch.setattr(harness, "load_specs", lambda provider: [doc])
    monkeypatch.setattr(harness, "spec_entry", lambda provider: (None, {}))
    monkeypatch.setattr(harness, "FULL", False)
    report = await harness.run_provider("sdk-control", enrich=False)
    op = report["operations"][0]
    assert len(op["requests"]) == 1
    request = op["requests"][0]
    assert request["headers"]["authorization"].startswith(
        "AWS4-HMAC-SHA256 " if stack == "botocore" else "synthetic-signature"
    )
    assert request["url"].endswith("?limit=11" if bad_request else "?limit=1")
    assert request["body"] == ""
    if bad_response:
        assert report["fixture_errors"] == 1 and not report["passed"]
        assert "Cannot generate spec-valid response" in op["fixture_errors"][0]
        assert "response_status" not in request
    elif bad_request:
        assert report["failed"] == 1 and not report["fixture_errors"]
        assert any(f.startswith("request:") for f in op["failures"])
    else:
        assert (
            report["passed"]
            == report["response_checked"]
            == report["auth_checked"]
            == 1
        ), op
        assert request["response_status"] == 200


@pytest.mark.asyncio
async def test_binary_request_is_recorded_losslessly(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["upload"]

    class NodeConfig(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        get_config_model = staticmethod(lambda: NodeConfig)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            with closing(aws_client("s3")) as client:
                client.put_object(
                    Bucket="transport-test", Key="binary", Body=b"\xff\x00"
                )

    monkeypatch.setitem(harness.PROVIDERS, "binary-control", ("test-binary-control", {}))
    monkeypatch.setitem(NODE_REGISTRY, "test-binary-control", Node)
    # An unmatched route must still be captured, including the binary body.
    monkeypatch.setattr(
        harness,
        "load_specs",
        lambda provider: [
            {
                "openapi": "3.0.3",
                "info": {"title": "Binary control", "version": "1"},
                "paths": {},
            }
        ],
    )
    monkeypatch.setattr(harness, "spec_entry", lambda provider: (None, {}))
    report = await harness.run_provider("binary-control", enrich=False)
    op = report["operations"][0]
    request = op["requests"][0]
    assert request["body_encoding"] == "base64"
    assert b"\xff\x00" in base64.b64decode(request["body"], validate=True)
    assert report["failed"] == 1
    assert "No spec operation" in op["failures"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["json", "multipart", "stream", "gzip", "continue"])
async def test_aiohttp_keeps_real_serialization_and_response_parser(kind):
    import gzip

    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"synthetic": True}, request=request)

    async def chunks():
        yield b"first"
        yield b"second"

    kwargs = {"json": {"synthetic": 1}}
    if kind == "multipart":
        form = aiohttp.FormData()
        form.add_field("purpose", "synthetic")
        form.add_field(
            "file",
            b"\x00\xff",
            filename="data.bin",
            content_type="application/octet-stream",
        )
        kwargs = {"data": form}
    elif kind == "stream":
        kwargs = {"data": chunks()}
    elif kind == "gzip":
        kwargs = {"data": b"synthetic payload", "compress": "gzip"}
    elif kind == "continue":
        kwargs = {"data": b"synthetic payload", "expect100": True}

    original_send = aiohttp.ClientRequest.send
    original_connect = aiohttp.TCPConnector.connect
    with intercept_http(respond):
        async with aiohttp.ClientSession(
            headers={"authorization": "Bearer fake"}
        ) as session:
            async with session.post(
                "https://example.test/upload?a=1", params={"q": "a b"}, **kwargs
            ) as response:
                assert response.status == 200
                assert await response.json() == {"synthetic": True}
                assert await response.text() == '{"synthetic":true}'
    assert aiohttp.ClientRequest.send is original_send
    assert aiohttp.TCPConnector.connect is original_connect
    request = captured[0]
    assert request.method == "POST"
    assert dict(request.url.params) == {"a": "1", "q": "a b"}
    assert request.headers["authorization"] == "Bearer fake"
    if kind == "json":
        assert request.headers["content-type"] == "application/json"
        assert request.content == b'{"synthetic": 1}'
    elif kind == "multipart":
        boundary = request.headers["content-type"].split("boundary=", 1)[1]
        assert request.content.startswith(b"--" + boundary.encode() + b"\r\n")
        assert b'name="purpose"' in request.content
        assert b'filename="data.bin"' in request.content
        assert b"\x00\xff" in request.content
    elif kind == "stream":
        assert request.headers["transfer-encoding"] == "chunked"
        assert request.content == b"firstsecond"
    elif kind == "gzip":
        assert request.headers["content-encoding"] == "gzip"
        assert gzip.decompress(request.content) == b"synthetic payload"
    else:
        assert request.headers["expect"] == "100-continue"
        assert request.content == b"synthetic payload"


@pytest.mark.asyncio
async def test_aiohttp_contract_rejection_and_invalid_response_propagate():
    from tests.conformance.test_inputs import contract_for

    contract = contract_for(
        {
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer", "minimum": 1}},
        }
    )

    def respond(request):
        contract.validate_request(request)
        return contract.response(request, contract.match(request)[2])

    with intercept_http(respond):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://example.test/items", json={"count": 1}
            ) as response:
                assert response.status == 200
            with pytest.raises(ValueError, match="Request body validation error"):
                await session.post("https://example.test/items", json={"count": 0})
            doc = contract.doc
            doc["paths"]["/items"]["post"]["responses"]["200"]["content"] = {
                "application/json": {
                    "schema": {"type": "string", "minLength": 3, "maxLength": 1}
                }
            }
            contract = harness.Contract(doc)
            with pytest.raises(ValueError, match="Cannot generate spec-valid response"):
                await session.post("https://example.test/items", json={"count": 1})
