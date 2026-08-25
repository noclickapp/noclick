"""Regression tests for the actionable validation error messages produced by
NodeFactory when a discriminated-union config is invalid.

Previously, missing or unknown discriminator values surfaced as the cryptic
Pydantic default ("Unable to extract tag using discriminator 'operation'"),
which gave callers no way to recover. The error formatter now lists the valid
options so the brain (or a human reader) can pick one.
"""

import pytest

from nodes.google_docs_node import GoogleDocsNode


def test_missing_operation_lists_valid_options():
    with pytest.raises(ValueError) as exc:
        GoogleDocsNode.parse_config(
            {
                "config": {"document_id": "abc"},
                "credentialIds": {"google_docs_oauth": "x"},
            }
        )
    msg = str(exc.value)
    assert "'operation' field is required" in msg
    assert "fetch_document_content" in msg
    assert "list_google_drive_documents" in msg
    # The unhelpful default must be gone:
    assert "Unable to extract tag" not in msg


def test_invalid_operation_lists_valid_options():
    with pytest.raises(ValueError) as exc:
        GoogleDocsNode.parse_config(
            {
                "config": {"operation": "bogus_op", "document_id": "abc"},
                "credentialIds": {},
            }
        )
    msg = str(exc.value)
    assert "'operation' = 'bogus_op' is not a valid option" in msg
    assert "fetch_document_content" in msg


def test_valid_operation_still_passes():
    # Sanity check — the new branch must not reject otherwise-valid configs.
    parsed = GoogleDocsNode.parse_config(
        {
            "config": {"operation": "fetch_document_content", "document_id": "abc"},
            "credentials": {
                "credential_type": "google_docs_oauth",
                "access_token": "t",
                "refresh_token": "r",
                "expires_at": "2099-01-01T00:00:00Z",
                "email": "x@y.z",
            },
        }
    )
    assert parsed is not None
