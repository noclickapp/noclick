"""Community object-storage contract and first-boot provisioning."""

from __future__ import annotations

import importlib.util
import io
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


class _OldMinio:
    """The S3 surface bootstrap reads an upgraded install's MinIO through."""

    def __init__(self, objects: dict[tuple[str, str], tuple[bytes, str]], reachable: bool = True):
        self.objects = objects
        self.reachable = reachable

    def list_buckets(self):
        if not self.reachable:
            from botocore.exceptions import EndpointConnectionError

            raise EndpointConnectionError(endpoint_url="http://storage:9000")
        return {"Buckets": [{"Name": bucket} for bucket in {b for b, _ in self.objects}]}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objects = self.objects

        class _Pages:
            def paginate(self, *, Bucket):
                # One object per page, so the copy has to follow the pages.
                for key in sorted(k for b, k in objects if b == Bucket):
                    yield {"Contents": [{"Key": key, "Size": len(objects[(Bucket, key)][0])}]}

        return _Pages()

    def get_object(self, *, Bucket, Key):
        body, content_type = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body), "ContentType": content_type, "Metadata": {"source": "minio"}}


@pytest.fixture
def upgraded_install(monkeypatch, tmp_path):
    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    monkeypatch.setenv("WORKFLOW_JWT_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_API_URL", "http://testserver")
    monkeypatch.delenv("OBJECT_STORAGE_ENDPOINT", raising=False)
    monkeypatch.setenv("LEGACY_MINIO_URL", "http://storage:9000")
    monkeypatch.setenv("LEGACY_MINIO_ACCESS_KEY_ID", "noclick-old")
    monkeypatch.setenv("LEGACY_MINIO_SECRET_ACCESS_KEY", "old-secret")
    return tmp_path


def test_bootstrap_copies_an_upgraded_installs_minio_files_once(upgraded_install):
    """Releases up to v0.4.1 kept files in MinIO, which no longer publishes
    images. On upgrade every file comes across to the backend's own store and
    is served through the same signed URLs a fresh upload gets."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from utils import local_object_store as store
    from utils.local_storage_routes import router

    bootstrap = _bootstrap_module()
    minio = _OldMinio({
        ("workflow-resources", "u1/wf1/r1/report.pdf"): (b"%PDF-1.7 report", "application/pdf"),
        ("workflow-resources", "u1/wf1/r2/photo.png"): (b"\x89PNG photo", "image/png"),
        ("workflow-cas", "chunks/ab/abcdef"): (b'{"big": "output"}', "application/json"),
        ("workflow-resources", "u1/../escape"): (b"nope", "text/plain"),
    })
    with patch("boto3.client", return_value=minio) as client:
        bootstrap._import_legacy_minio()
    assert client.call_args.kwargs["endpoint_url"] == "http://storage:9000"
    assert client.call_args.kwargs["aws_access_key_id"] == "noclick-old"

    assert store.get("workflow-resources", "u1/wf1/r1/report.pdf") == (b"%PDF-1.7 report", "application/pdf")
    assert store.get("workflow-cas", "chunks/ab/abcdef") == (b'{"big": "output"}', "application/json")
    assert not (upgraded_install / "storage" / "workflow-resources" / "escape").exists()

    app = FastAPI()
    app.include_router(router)
    url = store.presign("GET", "workflow-resources", "u1/wf1/r2/photo.png", expires_in=60)
    got = TestClient(app).get(url)
    assert (got.status_code, got.content, got.headers["content-type"]) == (200, b"\x89PNG photo", "image/png")

    # Once copied, a later boot neither needs MinIO nor reads it.
    with patch("boto3.client", side_effect=AssertionError("MinIO read again")):
        bootstrap._import_legacy_minio()


def test_bootstrap_stops_when_an_upgraded_installs_minio_is_gone(upgraded_install, monkeypatch):
    """Starting without the files would look like lost uploads, so bootstrap
    refuses and says how to bring MinIO back, or to skip the copy."""
    bootstrap = _bootstrap_module()
    monkeypatch.setattr(bootstrap, "LEGACY_MINIO_WAIT_SECONDS", 0)
    with patch("boto3.client", return_value=_OldMinio({}, reachable=False)):
        with pytest.raises(SystemExit) as stopped:
            bootstrap._import_legacy_minio()
    message = str(stopped.value)
    assert "http://storage:9000" in message and "Upgrading" in message
    assert "OBJECT_STORAGE_ACCESS_KEY_ID" in message
    assert not (upgraded_install / "storage" / ".imported-from-minio.json").exists()


def test_a_fresh_install_has_no_minio_to_copy(upgraded_install, monkeypatch):
    monkeypatch.delenv("LEGACY_MINIO_ACCESS_KEY_ID")
    with patch("boto3.client", side_effect=AssertionError("no MinIO to read")):
        _bootstrap_module()._import_legacy_minio()


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
