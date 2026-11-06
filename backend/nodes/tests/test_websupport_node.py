"""Websupport regressions exercise the factory, connect probe and signed HTTP contract.
Provider HTTP is synthetic; these tests do not prove live account access.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest
from unittest.mock import AsyncMock
from nodes import websupport_node as ad
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NODE_REGISTRY, NodeFactory

NODE = "automation-websupport"
USER, WF = "fixture-user", "fixture-workflow"
SERVICE, OTHER = "service-17", "other-service"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "websupport_api_key", "api_key": "fixture-key", "api_secret": "fixture-secret", "service_id": SERVICE, **updates}


def make_node(operation, data=None, **config):
    target = {}
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **target, **config},
        "credentials": credential() if data is None else data}, user_id=USER)

@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        item = state.responses.pop(0)
        status, payload = item[:2]
        headers = item[2] if len(item) == 3 else {}
        return httpx.Response(status, content=payload, headers=headers) if isinstance(payload, (str, bytes)) else httpx.Response(status, json=payload, headers=headers) if payload is not None else httpx.Response(status, headers=headers)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


STAMP = "2026-01-01T13:00:00.000Z"

def zone(**updates):
    return {"name": "example.com", "lastCheck": STAMP, "dnssecSigning": "active",
        "credentials": "private-sentinel", "content": "private-sentinel", **updates}

def record(**updates):
    return {"id": 17, "name": "www", "type": "A", "ttl": 3600, "content": "private-sentinel",
        "priority": None, "port": None, "weight": None, "note": "private-sentinel", **updates}

def page(*rows, **updates):
    return {"currentPage": 0, "rowsPerPage": 50, "totalPages": 3, "totalRecords": 111,
        "data": list(rows), **updates}

def test_actual_factory_schema_has_three_current_operations_and_bound_key_secret():
    assert NODE_REGISTRY[NODE] is ad.WebsupportNode
    defs = ad.WebsupportNode.get_config_schema()["$defs"]
    assert defs["WebsupportApiKeyCredential"]["required"] == ["api_key", "api_secret", "service_id"]
    ops = {d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})}
    assert ops == {"check_connection", "get_zone", "list_records"}
    assert defs["WebsupportRecordsConfig"]["properties"]["record_type"]["x-dynamic-options"]["field"] == "record_type"
    for operation in ("list_services", "get_record", "update_record", "nic_update", "get_account"):
        with pytest.raises(ConfigValidationError):
            make_node(operation)
    for extra in ({"page": 2}, {"service_id": OTHER}, {"rowsPerPage": 500}, {"filters": {"content": "private-sentinel"}}):
        with pytest.raises(ConfigValidationError):
            make_node("list_records", **extra)


@pytest.mark.asyncio
async def test_actual_request_signing_uses_exact_no_query_path_fresh_signature_and_matching_utc_date(http, monkeypatch):
    import base64
    import hashlib
    import hmac
    ticks = iter((1704067200, 1704067201))
    monkeypatch.setattr(ad, "time", SimpleNamespace(time=lambda: next(ticks)))
    http.responses = [(200, {"verified": True}), (200, zone())]
    out = await make_node("check_connection").execute({})
    assert out["verified"] is True and out["protected_zone"] is True and out["items"] == [{"lastCheck": STAMP, "dnssecSigning": "active"}]
    assert len(http.calls) == 2
    for request, stamp in zip(http.calls, (1704067200, 1704067201)):
        assert request.method == "GET" and request.url.host == "rest.websupport.sk" and not request.url.params
        canonical = f"GET {request.url.path} {stamp}".encode()
        expected = hmac.new(b"fixture-secret", canonical, hashlib.sha1).hexdigest()
        username, signature = base64.b64decode(request.headers["authorization"].removeprefix("Basic ")).decode().split(":", 1)
        assert username == "fixture-key" and signature == expected and len(signature) == 40
        assert request.headers["x-date"] == datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        assert request.headers["accept"] == "application/json" and request.headers["content-type"] == "application/json"
        assert "fixture-secret" not in json.dumps(dict(request.headers)) and "fixture-secret" not in str(request.url)
    assert http.calls[0].url.path == "/v2/check"
    assert http.calls[1].url.path == "/v2/service/service-17/dns/zone"
    assert "private-sentinel" not in json.dumps(out) and "account_label" not in out and "service_id" not in out


@pytest.mark.asyncio
async def test_default_record_envelope_preserves_nullable_ids_counts_and_unknown_completion_without_query(http):
    http.responses = [(200, zone()), (200, page(record(id=None), record(id=18, type="TXT")))]
    out = await make_node("list_records", max_items=1).execute({})
    assert out["items"] == [{"id": None, "type": "A", "ttl": 3600}]
    assert out["provider_page"] == {"currentPage": 0, "rowsPerPage": 50, "totalPages": 3, "totalRecords": 111}
    assert out["returned"] == 1 and out["provider_returned"] == 2 and out["local_truncated"] is True
    assert "unknown" in out["completion"] and "total" not in out and "next_page_token" not in out
    assert "private-sentinel" not in json.dumps(out) and "example.com" not in json.dumps(out) and "www" not in json.dumps(out)
    assert [request.url.path for request in http.calls] == ["/v2/service/service-17/dns/zone", "/v2/service/service-17/dns/record"]
    assert all(not request.url.params for request in http.calls)


@pytest.mark.asyncio
async def test_zone_optional_fields_and_names_do_not_fabricate_service_or_domain_identity(http):
    http.responses = [(200, {})]
    out = await make_node("get_zone").execute({})
    assert out["zone"] == {} and "service_id" not in out and "id" not in out["zone"]
    http.responses = [(200, zone())]
    named = await make_node("get_zone", include_names=True).execute({})
    assert named["zone"] == {"name": "example.com", "lastCheck": STAMP, "dnssecSigning": "active"}
    assert "credentials" not in named["zone"] and "service-17" not in json.dumps(named)


@pytest.mark.asyncio
async def test_local_type_filter_and_current_service_selector_ignore_forged_context(http):
    http.responses = [(200, zone()), (200, page(record(), record(id=18, type="TXT")))]
    out = await make_node("list_records", record_type="TXT", include_names=True).execute({})
    assert out["items"] == [{"id": 18, "type": "TXT", "ttl": 3600, "name": "www"}]
    http.responses = [(200, zone()), (200, page(record(), record(id=18, type="TXT"), record(id=19)))]
    options = await ad.WebsupportNode.load_field_options("record_type", credential(), context={"service_id": OTHER,
        "api_secret": "forged", "workflow_id": WF}, search="T")
    assert options["options"] == [{"value": "TXT", "label": "TXT"}] and options["next_page_token"] is None
    assert all("/service/service-17/" in request.url.path and not request.url.params for request in http.calls)
    before = len(http.calls)
    for field, kwargs in (("service_id", {}), ("record_id", {}), ("record_type", {"page_token": "forged"})):
        with pytest.raises(ValueError):
            await ad.WebsupportNode.load_field_options(field, credential(), **kwargs)
    assert len(http.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": []}, page(record(ttl=True)), page(record(id=True)), page(record(type="CUSTOM")),
    page(record(), record()), page(record(name="https://private.invalid")), page(record(), currentPage=True)])
async def test_malformed_current_record_envelopes_and_safe_metadata_fail_closed(http, payload):
    http.responses = [(200, zone()), (200, payload)]
    with pytest.raises(RuntimeError) as error:
        await make_node("list_records").execute({})
    assert "private-sentinel" not in str(error.value) and "private.invalid" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": zone()}, {"dnssecSigning": "unknown"}, {"lastCheck": None}])
async def test_direct_zone_contract_refuses_wrappers_and_invalid_optional_properties(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError):
        await make_node("get_zone").execute({})
    assert len(http.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, None, "true", 1])
async def test_verification_requires_exact_true_before_any_zone_read(http, value):
    http.responses = [(200, {"verified": value})]
    with pytest.raises(RuntimeError):
        await make_node("check_connection").execute({})
    assert len(http.calls) == 1 and http.calls[0].url.path == "/v2/check"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 500, 302, 204])
async def test_provider_refusals_are_static_without_private_body_or_retry(http, status):
    http.responses = [(status, {"message": "fixture-secret private-sentinel"})]
    with pytest.raises(RuntimeError) as error:
        await make_node("get_zone").execute({})
    assert "fixture-secret" not in str(error.value) and "private-sentinel" not in str(error.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_actual_manual_connect_requires_auth_boolean_and_zone_without_actor_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [(200, {"verified": True}), (200, zone())]
    out = await credential_connect.validate_for_connect(credential_type="websupport_api_key", credential_data=credential(), user_id=USER)
    assert out.ok and out.evidence.reachable is True and ad.WebsupportNode.connection_evidence.proves == "reachability" and out.evidence.account_label is None
    assert [sample.label for sample in out.evidence.samples] == [STAMP]
    assert "private-sentinel" not in json.dumps(asdict(out.evidence))
    http.responses = [(200, {"verified": False})]
    refused = await credential_connect.validate_for_connect(credential_type="websupport_api_key", credential_data=credential(), user_id=USER)
    assert not refused.ok and refused.evidence.reachable is False and refused.evidence.account_label is None
    assert len(http.calls) == 3


@pytest.mark.parametrize("service", ["https://foreign.invalid", "../foreign", "svc/a", "svc?query=1", "svc%2Fforeign", "", "x"*192])
def test_bound_service_is_opaque_safe_path_segment_without_domain_guessing(service):
    with pytest.raises(ValueError):
        ad._service(service)
    assert ad._service("service-17") == SERVICE and ad._service("opaque.reference") == "opaque.reference"


@pytest.mark.asyncio
async def test_wrong_raw_family_and_arbitrary_or_mutating_routes_stop_before_http(http):
    with pytest.raises(ValueError):
        await ad.WebsupportNode.load_field_options("record_type", credential(credential_type="websupport_password"))
    for kind in ("/nic/update", "ftp-account", "record-detail", "token"):
        with pytest.raises(ValueError):
            await ad._request(credential(), kind)
    assert http.calls == []


@pytest.mark.asyncio
async def test_post_connect_validation_runs_signed_verification_and_bound_zone(http):
    http.responses = [(200, {"verified": True}), (200, zone())]
    assert await ad.WebsupportNode.validate_credential_access(credential()) == {"valid": True}
    assert [request.url.path for request in http.calls] == ["/v2/check", "/v2/service/service-17/dns/zone"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"message": "private-sentinel"}), (200, {"verified": "true"}), (200, {"verified": False})])
async def test_post_connect_validation_refuses_provider_and_shape_failures(http, status, payload):
    http.responses = [(status, payload)]
    with pytest.raises(RuntimeError) as error:
        await ad.WebsupportNode.validate_credential_access(credential())
    assert "private-sentinel" not in str(error.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_node_transport_refuses_private_dns(monkeypatch):
    import asyncio
    import socket
    from utils import ssrf
    transport_calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    def guarded(**kwargs):
        return ssrf.guarded_async_client(transport=httpx.MockTransport(
            lambda request: transport_calls.append(request) or httpx.Response(200, json={})), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", guarded)
    with pytest.raises(RuntimeError, match="could not be reached"):
        await make_node("check_connection").execute({})
    lookup.assert_awaited_once_with("rest.websupport.sk", 443, type=socket.SOCK_STREAM)
    assert transport_calls == []
