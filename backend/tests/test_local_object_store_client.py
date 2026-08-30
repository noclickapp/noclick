"""The storage client hands every operation to the local store when no S3
endpoint is configured — the case every one-click deploy is in."""

import pytest

from utils import local_object_store as store
from utils import r2_cloudflare


@pytest.fixture(autouse=True)
def local_instance(monkeypatch, tmp_path):
    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    monkeypatch.setenv("WORKFLOW_JWT_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_API_URL", "http://testserver")
    monkeypatch.delenv("OBJECT_STORAGE_ENDPOINT", raising=False)


def test_the_storage_client_delegates_when_no_endpoint_is_configured():
    assert store.enabled()
    url = r2_cloudflare.generate_presigned_upload_url("workflow-resources", "a/b.txt", "text/plain", content_length=3)
    assert "/storage/workflow-resources/a/b.txt?" in url
    store.put("workflow-resources", "a/b.txt", b"abc", "text/plain")
    assert r2_cloudflare.download_from_r2("workflow-resources", "a/b.txt") == (b"abc", "text/plain")
    assert r2_cloudflare.r2_prefix_exists("workflow-resources", "a") is True
    assert r2_cloudflare.fetch_etags_from_r2("workflow-resources", "a") == {"/b.txt": store.etag("workflow-resources", "a/b.txt")}
    assert r2_cloudflare.delete_files_from_r2("workflow-resources", "a", ["/b.txt"]) == 1
    assert r2_cloudflare.r2_prefix_exists("workflow-resources", "a") is False
    with pytest.raises(ValueError):
        r2_cloudflare.create_s3_client()
