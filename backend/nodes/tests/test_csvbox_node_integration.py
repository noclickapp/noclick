"""Prove that a manually entered Csvbox key pair uses the real connect seam.

Only the HTTP transport is replaced; credential shaping and evidence run normally.
"""
import httpx
import pytest

from nodes.core import credential_connect
from nodes.core.connection_evidence import collect_evidence
from nodes.tests.test_csvbox_node_mock import KEY, SECRET, transport

USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.mark.asyncio
async def test_manual_connect_reads_owned_sheets_without_a_saved_credential(monkeypatch):
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    requests = transport(monkeypatch, {"data": [{"sheet_license_key": "a1b2c3d4", "title": "Customer Import"}], "links": {}, "meta": {}})
    verdict = await credential_connect.validate_for_connect(
        credential_type="csvbox_api_key", credential_data={"api_key": " " + KEY + "\n", "secret_api_key": SECRET}, user_id=USER, probe=True)
    assert verdict.ok and verdict.field_errors == {}
    assert verdict.node_type == "automation-csvbox"
    assert verdict.credential_data == {"api_key": KEY, "secret_api_key": SECRET}
    assert verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == "Customer Import"
    assert len(requests) == 1 and requests[0].method == "GET" and requests[0].url.path == "/1.1/sheet"


@pytest.mark.asyncio
async def test_empty_account_is_accepted_and_provider_rejection_is_verbatim(monkeypatch):
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    transport(monkeypatch, {"data": []})
    empty = await credential_connect.validate_for_connect(
        credential_type="csvbox_api_key", credential_data={"api_key": KEY, "secret_api_key": SECRET}, user_id=USER, probe=True)
    assert empty.ok and empty.evidence.reachable is True and empty.evidence.samples == []
    transport(monkeypatch, lambda r: httpx.Response(401, json={"message": "Invalid API credentials"}))
    rejected = await credential_connect.validate_for_connect(
        credential_type="csvbox_api_key", credential_data={"api_key": KEY, "secret_api_key": SECRET}, user_id=USER, probe=True)
    assert not rejected.ok and rejected.evidence.reachable is False
    assert rejected.rejection == "Invalid API credentials (HTTP 401)"
