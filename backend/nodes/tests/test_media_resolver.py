"""Tests for the shared media-input resolver (resource_id / URL / data URI /
base64 → bytes). Uses the local httpx MockTransport shim, not external respx."""

import base64

import httpx
import pytest

from nodes.core.media_resolver import _stream_to_bytes, resolve_media_input
from nodes.tests import _httpx_mock as respx


@pytest.fixture
def allow_private(monkeypatch):
    monkeypatch.setenv("HTTP_NODE_ALLOW_PRIVATE_IPS", "true")


async def test_data_uri():
    payload = base64.b64encode(b"\x89PNG\r\n").decode()
    m = await resolve_media_input(f"data:image/png;base64,{payload}")
    assert m.data == b"\x89PNG\r\n"
    assert m.mime_type == "image/png"
    assert m.filename == "file.png"
    assert m.download_url is None


async def test_raw_base64():
    m = await resolve_media_input(base64.b64encode(b"hello").decode(), default_mime="text/plain")
    assert m.data == b"hello"
    assert m.mime_type == "text/plain"


@respx.mock
async def test_http_url(allow_private):
    respx.get("https://cdn.test/clip.mp4").mock(
        return_value=httpx.Response(200, content=b"VIDEO", headers={"content-type": "video/mp4"})
    )
    m = await resolve_media_input("https://cdn.test/clip.mp4")
    assert m.data == b"VIDEO"
    assert m.mime_type == "video/mp4"
    assert m.filename == "clip.mp4"  # derived from URL path
    assert m.download_url == "https://cdn.test/clip.mp4"


@respx.mock
async def test_resource_id_allows_only_the_owned_presigned_url(monkeypatch):
    rid = "12345678-1234-1234-1234-1234567890ab"

    class _Pool:
        async def fetchrow(self, *a, **k):
            return {
                "storage_ref": "owner/wf/res/video.mp4",
                "mime_type": "video/mp4",
                "name": "video.mp4",
                "size_bytes": 5,
            }

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: _Pool())
    monkeypatch.setattr(
        "utils.r2_cloudflare.generate_presigned_download_url",
        lambda bucket, key, **k: "http://storage.localhost:9000/presigned",
    )
    respx.get("http://storage.localhost:9000/presigned").mock(
        return_value=httpx.Response(200, content=b"VIDEO", headers={"content-type": "video/mp4"})
    )
    workflow_id = "87654321-4321-4321-4321-ba0987654321"
    m = await resolve_media_input(rid, workflow_id=workflow_id)
    assert m.data == b"VIDEO"
    assert m.mime_type == "video/mp4"
    assert m.filename == "video.mp4"
    assert m.download_url == "http://storage.localhost:9000/presigned"


async def test_resource_id_requires_a_workflow_scope(monkeypatch):
    rid = "12345678-1234-1234-1234-1234567890ab"

    class _Pool:
        async def fetchrow(self, *a, **k):
            raise AssertionError("unscoped lookup must not reach the database")

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: _Pool())
    with pytest.raises(ValueError, match="workflow execution context"):
        await resolve_media_input(rid)


@respx.mock
async def test_owned_presigned_url_still_guards_redirect_targets():
    owned_url = "http://storage.localhost:9000/presigned"
    metadata_url = "http://169.254.169.254/latest/meta-data/"
    respx.get(owned_url).mock(
        return_value=httpx.Response(302, headers={"location": metadata_url})
    )
    metadata_route = respx.get(metadata_url).mock(
        return_value=httpx.Response(200, content=b"credentials")
    )

    with pytest.raises(ValueError, match="non-public address"):
        await _stream_to_bytes(owned_url, 1024, trusted_initial_url=True)

    assert metadata_route.call_count == 0


async def test_resource_not_found(monkeypatch):
    class _Pool:
        async def fetchrow(self, *a, **k):
            return None

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: _Pool())
    with pytest.raises(ValueError, match="Resource not found"):
        await resolve_media_input(
            "12345678-1234-1234-1234-1234567890ab",
            workflow_id="87654321-4321-4321-4321-ba0987654321",
        )


@pytest.mark.parametrize("bad", ["", "   ", "not a media value !!!"])
async def test_invalid_inputs(bad):
    with pytest.raises(ValueError):
        await resolve_media_input(bad)


async def test_size_cap_data_uri():
    payload = base64.b64encode(b"x" * 2048).decode()
    with pytest.raises(ValueError, match="too large"):
        await resolve_media_input(f"data:application/octet-stream;base64,{payload}", max_bytes=1024)


@respx.mock
async def test_http_error_surfaces_as_valueerror(allow_private):
    # A non-2xx fetch must raise ValueError (not httpx.HTTPStatusError) so callers
    # that `except ValueError` return a structured error instead of crashing.
    respx.get("https://cdn.test/missing.mp4").mock(return_value=httpx.Response(404))
    with pytest.raises(ValueError):
        await resolve_media_input("https://cdn.test/missing.mp4")
