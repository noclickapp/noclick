"""The self-hosted object store: signed URLs are capabilities, keys stay in
their bucket, and the storage client delegates to it when no S3 endpoint
is configured — the case every one-click deploy is in."""

import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils import local_object_store as store
from utils.local_storage_routes import router


@pytest.fixture(autouse=True)
def local_instance(monkeypatch, tmp_path):
    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    monkeypatch.setenv("WORKFLOW_JWT_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_API_URL", "http://testserver")
    monkeypatch.delenv("OBJECT_STORAGE_ENDPOINT", raising=False)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_upload_download_delete_through_signed_urls(client):
    put_url = store.presign("PUT", "workflow-resources", "u1/wf1/r1/notes.md", expires_in=60, content_type="text/markdown", content_length=5)
    assert put_url.startswith("http://testserver/storage/workflow-resources/u1/wf1/r1/notes.md?")
    assert client.put(put_url, content=b"hello", headers={"Content-Type": "text/markdown"}).status_code == 200

    get_url = store.presign("GET", "workflow-resources", "u1/wf1/r1/notes.md", expires_in=60)
    got = client.get(get_url)
    assert (got.status_code, got.content, got.headers["content-type"].split(";")[0]) == (200, b"hello", "text/markdown")

    assert client.delete(store.presign("DELETE", "workflow-resources", "u1/wf1/r1/notes.md", expires_in=60)).status_code == 204
    assert client.get(get_url).status_code == 404


def test_a_link_is_bound_to_its_method_size_and_expiry(client):
    put_url = store.presign("PUT", "workflow-resources", "k", expires_in=60, content_length=5)
    assert client.get(put_url).status_code == 403, "a PUT capability is not a GET capability"
    assert client.put(put_url, content=b"toolong").status_code == 400, "the signed length is enforced"
    expired = store.presign("GET", "workflow-resources", "k", expires_in=-1)
    assert client.get(expired).status_code == 403
    forged = store.presign("GET", "workflow-resources", "k", expires_in=60).replace("sig=", "sig=0")
    assert client.get(forged).status_code == 403


def test_keys_cannot_leave_their_bucket():
    for bad in ("../secrets", "a/../../b", "", "a//b", "a/./b"):
        with pytest.raises(ValueError):
            store.object_path("workflow-resources", bad)
    # A leading slash is S3's own convention for the keys callers pass ("/index.html").
    assert store.object_path("workflow-resources", "/etc/passwd").as_posix().endswith("/workflow-resources/etc/passwd")
    with pytest.raises(ValueError):
        store.object_path("Not A Bucket", "k")


def test_an_s3_endpoint_switches_the_store_off(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://objects.example.test")
    assert not store.enabled()
