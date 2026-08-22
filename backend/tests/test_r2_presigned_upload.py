"""Focused tests for the constraints carried by presigned R2 PUT URLs."""

from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from botocore.config import Config
from botocore.session import Session

from utils import r2_cloudflare


def _test_client():
    return Session().create_client(
        "s3",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _signed_headers(url: str) -> set[str]:
    query = parse_qs(urlsplit(url).query)
    return set(query["X-Amz-SignedHeaders"][0].split(";"))


def test_presigned_upload_can_bind_exact_content_length():
    with patch.object(r2_cloudflare, "create_s3_client", _test_client):
        url = r2_cloudflare.generate_presigned_upload_url(
            "workflow-resources",
            "owner/workflow/resource/file.bin",
            "application/octet-stream",
            content_length=1234,
        )

    assert {"content-length", "content-type"} <= _signed_headers(url)


def test_presigned_upload_content_length_remains_optional():
    with patch.object(r2_cloudflare, "create_s3_client", _test_client):
        url = r2_cloudflare.generate_presigned_upload_url(
            "workflow-resources",
            "server-generated/file.bin",
        )

    assert "content-type" in _signed_headers(url)
    assert "content-length" not in _signed_headers(url)
