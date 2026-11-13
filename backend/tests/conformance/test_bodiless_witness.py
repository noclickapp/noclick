"""A response the spec declares without a body still gets the provider's documented witness."""
import httpx
import pytest

from tests.conformance import harness, triggers
from tests.conformance.harness import Contract

WITNESS = {
    "POST /webhooks": {
        "body": {"id": 1, "url": "https://example.test/hook", "token": "73f82127d57a2cea"},
        "source": "https://docs.example.test/webhooks",
    },
    "DELETE /webhooks/{id}": {"body": {"deleted": True}, "source": "https://docs.example.test/webhooks"},
}


@pytest.fixture
def contract():
    return Contract({
        "openapi": "3.0.3",
        "info": {"title": "Bodiless responses", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "paths": {
            "/webhooks": {"post": {"responses": {"200": {"description": "Created"}}}},
            "/webhooks/{id}": {"delete": {
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"204": {"description": "Deleted"}},
            }},
        },
    })


def answer(contract, method, url, witnesses):
    request = httpx.Request(method, url)
    path, verb, operation = contract.match(request)
    record = {}
    response = contract.response(request, operation, key=f"{verb.upper()} {path}", record=record,
                                 witnesses=witnesses)
    return response, record


def test_documented_body_is_served_for_a_response_the_spec_leaves_empty(contract, monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    response, record = answer(contract, "POST", "https://api.example.test/webhooks", WITNESS)
    assert response.status_code == 200 and response.json() == WITNESS["POST /webhooks"]["body"]
    assert record == {"response_source": "docs", "response_witness": "POST /webhooks",
                      "response_source_url": "https://docs.example.test/webhooks"}
    # The documented fields are the response's schema for the trigger checks' field reads.
    reads = triggers.Reads(frozenset([__file__]))
    triggers.track_response(response, reads, "POST /webhooks response", record["response_source"])
    body = response.json()
    body.get("token")
    body.get("secret")
    assert list(reads.unknown) == ["secret"]


def test_without_a_witness_or_in_minimal_mode_the_response_stays_empty(contract, monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    assert answer(contract, "POST", "https://api.example.test/webhooks", {})[0].content == b""
    monkeypatch.setattr(harness, "FULL", False)
    assert answer(contract, "POST", "https://api.example.test/webhooks", WITNESS)[0].content == b""


def test_a_no_content_status_never_carries_the_witness(contract, monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    response, record = answer(contract, "DELETE", "https://api.example.test/webhooks/w1", WITNESS)
    assert response.status_code == 204 and response.content == b"" and "response_source" not in record
