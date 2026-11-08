"""Exercise Trestle's published requests and provider-authored response fixtures.

MockTransport keeps keys and live-call feedback off the network while checking
query aliases, product versions, partial results and rejection semantics.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import trestle_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-trestle-token-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/trestle/responses.json").read_text())
CONFIGS = {
    "get_address_validation": {"street_line_1": "800 Bellevue Way NE", "postal_code": "98004"},
    "get_caller_identification": {"phone": "2069735100", "phone_country_hint": "US", "add_ons": ["litigator_checks", "spam_checks"]},
    "get_decision_signals": {"transaction_id": "txn_123", "transaction_time": "2026-06-15T10:00", "primary_name": "Robin Cooke", "is_sandbox": False},
    "submit_phone_feedback": {"response_id": "T_b5d031b8-e8a3-4eef-8fa8-d87d3b7e386f", "phone": "2069735100", "name": "Waidong Syrws", "phone_status": "Connected", "phone_right_party_contact": True},
    "get_phone_validation": {"phone": "2069735100", "add_ons": ["litigator_checks"], "source_id": "Example campaign"},
    "get_real_contact_v1_1": {"name": "John Doe", "phone": "4259853735", "address_city": "Lynden", "add_ons": ["litigator_checks", "email_checks_deliverability"]},
    "get_real_contact": {"name": "John Doe", "phone": "4259853735", "business_name": "The Golden Company"},
    "get_reverse_address": {"street_line_1": "100 Syrws St", "state_code": "WA"},
    "get_reverse_phone": {"phone": "2069735100", "phone_name_hint": "John Doe"},
    "get_smart_cnam": {"phone": "2069735100", "phone_postal_code_hint": "98264", "add_ons": ["spam_checks"]},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation="get_phone_validation", **config):
    return NodeFactory.create_node(node_id="trestle-fixture", node_type="automation-trestle", node_data={
        "config": {"operation": operation, **config},
        "credentials": {"credential_type": "trestle_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body, headers={"Response-ID": "T_fixture"})
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_trestle_published_operations(monkeypatch, operation):
    fixture = FIXTURES[operation]
    calls = transport(monkeypatch, fixture["response"])
    result = await node(operation, **CONFIGS[operation]).execute({})
    assert result["status"] == "success"
    assert result["data"] == fixture["response"]
    assert result["response_id"] == "T_fixture"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == fixture["method"]
    assert str(request.url).startswith("https://api.trestleiq.com/")
    assert request.url.path == fixture["path"]
    assert request.headers["x-api-key"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    if operation == "submit_phone_feedback":
        assert dict(request.url.params) == {}
        assert json.loads(request.content) == CONFIGS[operation]
        assert result["feedback_accepted"] is True
    else:
        assert not request.content
        values = dict(request.url.params)
        if operation == "get_caller_identification":
            assert values["phone.country_hint"] == "US"
            assert values["add_ons"] == "litigator_checks,spam_checks"
        if operation == "get_decision_signals":
            assert values["primary.name"] == "Robin Cooke"
            assert values["is_sandbox"] == "false"
        if operation == "get_real_contact_v1_1":
            assert values["address.city"] == "Lynden"
        if operation == "get_real_contact":
            assert values["business.name"] == "The Golden Company"


@pytest.mark.asyncio
async def test_trestle_connection_is_a_read_and_only_proves_reachability(monkeypatch):
    calls = transport(monkeypatch, FIXTURES["get_phone_validation"]["response"])
    result = await node("check_connection").execute({})
    assert result["status"] == "success"
    assert native.TrestleNode.connection_evidence.proves == "reachability"
    assert calls[0].method == "GET" and dict(calls[0].url.params) == {"phone": "2069735100"}


@pytest.mark.asyncio
async def test_trestle_unknown_envelope_cannot_confirm_connection(monkeypatch):
    transport(monkeypatch, {"message": "unexpected response"})
    assert (await node("check_connection").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_trestle_feedback_rejected_inside_http_200(monkeypatch):
    calls = transport(monkeypatch, {"status": "failed", "name": "Invalid Input", "message": "Invalid phone status in request body"})
    result = await node("submit_phone_feedback", phone="2069735100").execute({})
    assert result["status"] == "error" and result["feedback_accepted"] is False
    assert result["error"] == "Invalid phone status in request body"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_trestle_partial_results_preserved_and_connection_not_confirmed(monkeypatch):
    body = {**FIXTURES["get_phone_validation"]["response"], "error": {"name": "InternalError", "message": "Could not retrieve entire response"}, "warnings": ["Missing Input"]}
    transport(monkeypatch, body)
    result = await node(phone="2069735100").execute({})
    assert result["partial"] is True and result["data"] == body
    assert (await node("check_connection").execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 429, 500, 302])
async def test_trestle_http_failures_and_secret_redaction(monkeypatch, status):
    calls = transport(monkeypatch, {"errorCode": "AUTHENTICATION_FAILED", "message": "Rejected " + TOKEN}, status)
    result = await node(phone="2069735100").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and TOKEN not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_trestle_timeout_write_is_ambiguous_and_never_retried(monkeypatch):
    calls = transport(monkeypatch, httpx.ReadTimeout("sensitive " + TOKEN))
    result = await node("submit_phone_feedback", phone="2069735100").execute({})
    assert result["status"] == "error" and result["outcome_unknown"] is True
    assert len(calls) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], "unexpected"])
async def test_trestle_bad_response_shape(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node(phone="2069735100").execute({}))["status"] == "error"


@pytest.mark.parametrize("operation,config", [
    ("get_reverse_address", {"street_line_1": "100 Syrws St"}),
    ("get_decision_signals", {"transaction_id": "txn_123", "transaction_time": "2026-06-15T10:00"}),
    ("get_smart_cnam", {"phone": "2069735100", "add_ons": ["not_an_add_on"]}),
    ("submit_phone_feedback", {"phone": "2069735100", "phone_status": "Unknown"}),
    ("submit_phone_feedback", {"phone": "2069735100", "phone_right_party_contact": "yes"}),
])
def test_trestle_invalid_input(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **config)


@pytest.mark.parametrize("key", ["https://example.com/token", "<token>", "has space", "bad\r\nheader"])
def test_trestle_secret_validation(key):
    with pytest.raises(ValueError):
        native.TrestleAPIKeyCredential(api_key=key)
