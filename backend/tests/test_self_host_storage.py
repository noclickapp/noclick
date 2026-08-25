"""Community object-storage contract and first-boot provisioning."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def _bootstrap_module():
    path = None
    for ancestor in Path(__file__).resolve().parents:
        for candidate in (
            ancestor / "docker" / "bootstrap.py",
            ancestor / "oss" / "overrides" / "docker" / "bootstrap.py",
        ):
            if candidate.exists():
                path = candidate
                break
        if path:
            break
    assert path is not None
    spec = importlib.util.spec_from_file_location("community_bootstrap", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_reads_the_documented_object_storage_contract(monkeypatch):
    from utils import r2_cloudflare

    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://objects.example.test")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY_ID", "community-key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "community-secret")
    monkeypatch.setenv("OBJECT_STORAGE_REGION", "eu-test-1")
    for name in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(r2_cloudflare, "_s3_client", None)

    sentinel = object()
    with patch.object(r2_cloudflare.boto3, "client", return_value=sentinel) as client:
        assert r2_cloudflare.create_s3_client() is sentinel

    assert client.call_args.kwargs == {
        "endpoint_url": "https://objects.example.test",
        "aws_access_key_id": "community-key",
        "aws_secret_access_key": "community-secret",
        "region_name": "eu-test-1",
    }


def test_private_resource_download_is_presigned(monkeypatch):
    from utils import r2_cloudflare

    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    with patch.object(
        r2_cloudflare,
        "generate_presigned_download_url",
        return_value="https://objects.example.test/signed",
    ) as signer:
        assert r2_cloudflare.get_public_download_url("owner/file.pdf") == (
            "https://objects.example.test/signed"
        )
    signer.assert_called_once_with(
        "workflow-resources", "owner/file.pdf", expires_in=900,
    )


def test_bootstrap_creates_resource_and_cas_buckets(monkeypatch):
    bootstrap = _bootstrap_module()

    client = type("Client", (), {})()
    created: list[str] = []
    client.create_bucket = lambda *, Bucket: created.append(Bucket)

    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://objects.example.test")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setattr(bootstrap, "DEADLINE_SECONDS", 0.1)
    # The production code catches botocore ClientError. Make the fake inherit
    # that exact class's interface by raising a real instance instead.
    from botocore.exceptions import ClientError

    client.head_bucket = lambda **_kwargs: (_ for _ in ()).throw(
        ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadBucket")
    )
    with patch("boto3.client", return_value=client):
        bootstrap._ensure_buckets()

    assert created == ["workflow-resources", "workflow-cas"]


@pytest.mark.asyncio
async def test_output_over_4kb_is_written_to_workflow_cas(monkeypatch):
    from utils.cas.chunking import decompose
    from utils.cas import store

    _manifest, chunks = decompose({"body": "x" * 5000}, threshold=4096)
    assert chunks, "the >4KB output must leave the inline-only path"

    uploads = []

    async def capture(**kwargs):
        uploads.append(kwargs)

    monkeypatch.setattr(store.r2_cloudflare, "upload_bytes_to_r2_async", capture)
    sizes = await store._put_owed(chunks, list(chunks))

    assert sizes
    assert uploads
    assert {upload["bucket"] for upload in uploads} == {"workflow-cas"}
