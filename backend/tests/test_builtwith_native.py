"""BuiltWith native factory, connect, projection and transport fixtures.
HTTPX MockTransport is the provider boundary; staging owns credential loading.
"""
from contextlib import asynccontextmanager
import asyncio
from copy import deepcopy
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from nodes import builtwith_node as api
from nodes.builtwith_node import BuiltWithNode, BuiltWithApiKeyCredential, LookupDomainTechnologies, validate_credential
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core import credential_connect as cc, connection_evidence as ce, run_op

USER = "00000000-0000-4000-8000-000000000001"
KEY = "11111111-1111-4111-8111-111111111111"
GRANT = {"credential_type": api.FAMILY, "api_key": KEY}
TYPE = "automation-builtwith"


@pytest.fixture
def ensure_native_db_pool():
    yield


def node(config=None, credential=None, **extra):
    data = {"config": {"operation": "lookup_domain_technologies", "domains": ["example.com"], **(config or {})},
            "credentials": deepcopy(GRANT if credential is None else credential), **extra}
    return NodeFactory.create_node("fixture-builtwith", TYPE, data, user_id=USER)


def domain_result(lookup="example.com", **extra):
    return {"Lookup": lookup, "FirstIndexed": 1700000000000, "LastIndexed": None,
            "Result": {"IsDB": "True", "Paths": [{"Domain": lookup, "Url": "dd", "SubDomain": "",
                "Technologies": [{"Name": "nginx", "Id": 1515864597, "confidence": 0.75,
                    "IsPremium": "No", "FirstDetected": "2022-01-01T00:00:00Z", "LastDetected": 1760000000000}]}]},
            "Meta": {"Names": [{"Email": "never-return@example.com"}]}, "Attributes": {"Employees": 99}, **extra}


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(calls=[], response=httpx.Response(200, json={"Results": [domain_result()], "Errors": []}), on_request=None)

    async def handle(request):
        state.calls.append(request)
        if state.on_request:
            state.on_request()
        return state.response

    original_client = httpx.AsyncClient

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 45.0, "trust_env": False, "follow_redirects": False}
        async with original_client(transport=httpx.MockTransport(handle), trust_env=False, follow_redirects=False) as value:
            yield value
    monkeypatch.setattr(api.httpx, "AsyncClient", client)
    return state


def test_actual_registry_factory_schema_and_saved_canvas_metadata():
    assert NODE_REGISTRY[TYPE] is BuiltWithNode
    instance = node({"label": "Owned lookup", "goal": "stack", "_settings": {"retryOnFail": "false"}})
    assert isinstance(instance.config.config, LookupDomainTechnologies)
    assert instance.node_data["credentials"] == GRANT
    schema = BuiltWithNode.get_config_schema()
    config = schema["$defs"]["LookupDomainTechnologies"]
    assert config["properties"]["domains"]["maxItems"] == 16
    assert config["properties"]["operation"]["const"] == "lookup_domain_technologies"
    assert set(schema["$defs"]["BuiltWithApiKeyCredential"]["required"]) == {"api_key"}
    assert not any("x-dynamic-options" in field for field in config["properties"].values())


@pytest.mark.parametrize("config", [
    {"domains": []}, {"domains": ["example.com"] * 17}, {"domains": ["example.com", "EXAMPLE.COM"]},
    {"domains": ["https://example.com"]}, {"domains": ["example.com/path"]}, {"domains": ["example.com?KEY=x"]},
    {"domains": ["127.0.0.1"]}, {"domains": ["localhost"]}, {"domains": ["site.local"]},
    {"domains": ["a@site.com"]}, {"domains": ["example.com:443"]}, {"domains": ["*.example.com"]},
    {"first_detected_start": "2026-01-01"}, {"last_detected_start": "2026-03-01", "last_detected_end": "2026-02-01"},
    {"first_detected_start": "2026-02-30", "first_detected_end": "2026-03-01"}, {"live_only": "yes"},
    {"operation": "bulk_submit"},
])
def test_actual_factory_rejects_invalid_native_inputs(config):
    with pytest.raises(ValueError):
        node(config)


def test_raw_foreign_credential_tag_and_safe_secret_shape():
    with pytest.raises(ValueError) as error:
        node(credential={"credential_type": "foreign_api_key", "api_key": KEY})
    assert KEY not in str(error.value)
    shaped, errors, resolved = cc.shape_credential(api.FAMILY, {"api_key": KEY})
    assert not errors and resolved[0] == TYPE and shaped["credential_type"] == api.FAMILY
    _, errors, _ = cc.shape_credential(api.FAMILY, {"api_key": KEY + "\r\nsecret"})
    assert errors and KEY not in json.dumps(errors)
    with pytest.raises(ValueError):
        validate_credential({"api_key": "00000000-0000-0000-0000-000000000000"})


@pytest.mark.asyncio
async def test_actual_connect_and_health_make_no_credit_consuming_request(monkeypatch, transport):
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=api.FAMILY, credential_data={"api_key": KEY}, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is None
    assert verdict.verified_metadata() == {}
    assert verdict.evidence.samples == [] and verdict.evidence.account_label is None
    assert (await BuiltWithNode.validate_credential_access(GRANT, user_id=USER))["valid"] is None
    assert transport.calls == []


@pytest.mark.asyncio
async def test_actual_execute_and_dispatcher_use_header_and_exact_privacy_filters(transport):
    result = await run_op.run_node_operation(node_type=TYPE, operation="lookup_domain_technologies",
        arguments={"operation": "bulk_submit", "domains": ["EXAMPLE.COM"], "live_only": True,
            "details": "no_description_links", "first_detected_start": "2022-01-01", "first_detected_end": "2023-01-01"},
        credential_data=GRANT, user_id=USER)
    request = transport.calls[0]
    assert len(transport.calls) == 1 and str(request.url).startswith(api.ENDPOINT + "?")
    assert request.headers["authorization"] == "API " + KEY
    assert dict(request.url.params) == {"LOOKUP": "example.com", "NOPII": "yes", "NOMETA": "yes", "NOATTR": "yes",
        "LIVEONLY": "yes", "HIDEDL": "yes", "FDRANGE": "2022-01-01|2023-01-01"}
    assert KEY not in str(request.url)
    assert result["status"] == "success" and result["protected_reachability_verified"] is True
    assert result["principal_identity_verified"] is False and result["account_identity_verified"] is False
    assert "never-return@example.com" not in json.dumps(result) and "Meta" not in json.dumps(result)


@pytest.mark.asyncio
async def test_owned_key_cannot_be_smuggled_into_lookup_query_and_echo_is_redacted(transport):
    with pytest.raises(ValueError):
        await node({"domains": [KEY + ".com"]}).execute({})
    assert transport.calls == []
    row = domain_result()
    row["Result"]["Paths"][0]["Technologies"][0]["Description"] = "Echo " + KEY
    result = api.project_response({"Results": [row], "Errors": []}, ["example.com"], KEY)
    assert KEY not in json.dumps(result)


def test_projection_preserves_nulls_unknowns_dates_and_partial_missing_domains():
    row = domain_result()
    row["Result"]["IsDB"] = "Misleading"
    row["Result"]["Paths"][0]["Technologies"][0]["confidence"] = None
    result = api.project_response({"Results": [row], "Errors": [{"Lookup": "other.com", "Code": -8, "Message": KEY}]},
        ["example.com", "other.com", "missing.com"], KEY)
    assert result["status"] == "partial" and (result["successful_count"], result["error_count"], result["missing_count"]) == (1, 1, 1)
    first = result["lookups"][0]
    assert first["lookup_source"] == "misleading" and first["data"]["LastIndexed"] is None
    tech = first["data"]["Result"]["Paths"][0]["Technologies"][0]
    assert tech["confidence"] is None and tech["FirstDetected"] == "2022-01-01T00:00:00Z"
    assert result["lookups"][1]["error"]["code"] == -8 and KEY not in json.dumps(result)
    del row["Result"]["IsDB"]
    del row["Result"]["Paths"][0]["Technologies"][0]["confidence"]
    unknown = api.project_response({"Results": [row], "Errors": []}, ["example.com"], KEY)["lookups"][0]
    assert unknown["lookup_source"] is None
    assert "confidence" not in unknown["data"]["Result"]["Paths"][0]["Technologies"][0]
    empty = api.project_response({"Results": [], "Errors": []}, ["example.com"], KEY)
    assert empty["status"] == "error" and empty["protected_reachability_verified"] is None


@pytest.mark.parametrize("payload", [
    {}, {"Results": {}, "Errors": []}, {"Results": [domain_result(), domain_result()], "Errors": []},
    {"Results": [domain_result("foreign.com")], "Errors": []},
    {"Results": [domain_result(Result={"Paths": [{"Domain": "foreign.com", "Technologies": []}]})], "Errors": []},
    {"Results": [domain_result(Result={"Paths": [{"Technologies": [{"Name": "nginx", "Id": True}]}]})], "Errors": []},
    {"Results": [domain_result(Result={"Paths": [{"Technologies": [{"Name": "nginx", "confidence": 1.1}]}]})], "Errors": []},
    {"Results": [], "Errors": [{"Code": -2, "Message": KEY}]},
    {"Results": [], "Errors": [{"Code": -3, "Lookup": None, "Message": KEY}]},
    {"Results": [], "Errors": [{"Code": True, "Lookup": "example.com"}]}, {"error": "Rate limit exceeded", "retryAfterSeconds": 2},
])
def test_parser_refuses_errors_or_unbound_malformed_data_without_echoing_secrets(payload):
    with pytest.raises(ValueError) as error:
        api.project_response(payload, ["example.com"], KEY)
    assert KEY not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(401, text=KEY), httpx.Response(429, headers={"Retry-After": "2"}, text=KEY),
    httpx.Response(503, text=KEY), httpx.Response(302, headers={"Location": "https://foreign.invalid/?KEY=" + KEY}),
    httpx.Response(200, headers={"Content-Type": "text/html"}, text=KEY),
    httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{"),
])
async def test_transport_failure_media_and_redirect_are_safe_and_single_attempt(transport, response):
    transport.response = response
    with pytest.raises(ValueError) as error:
        await node().execute({})
    assert KEY not in str(error.value) and len(transport.calls) == 1


def test_actual_request_loggers_hide_key_and_restore_unrelated_diagnostics(caplog):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    logger = logging.getLogger("httpx")
    with api.private_request_logging():
        logger.debug("Authorization API %s", KEY)
        logging.getLogger("fixture.unrelated").info("unrelated diagnostic survives")
    logger.info("outside request diagnostic survives")
    assert KEY not in caplog.text
    assert "unrelated diagnostic survives" in caplog.text and "outside request diagnostic survives" in caplog.text


@pytest.mark.asyncio
async def test_request_logging_context_does_not_mute_a_concurrent_task(caplog):
    caplog.set_level(logging.DEBUG)
    entered, finished = asyncio.Event(), asyncio.Event()
    logger = logging.getLogger("httpcore.http11")
    async def private_task():
        with api.private_request_logging():
            entered.set()
            await finished.wait()
            logger.debug("Authorization API %s", KEY)
    async def unrelated_task():
        await entered.wait()
        logger.debug("concurrent unrelated diagnostic survives")
        finished.set()
    await asyncio.gather(private_task(), unrelated_task())
    assert KEY not in caplog.text and "concurrent unrelated diagnostic survives" in caplog.text


@pytest.mark.asyncio
async def test_execute_uses_validated_config_without_raw_node_data_or_user_context(transport):
    from nodes.builtwith_node import BuiltWithFullConfig
    instance = BuiltWithNode(node_id="config-only", node_type=TYPE, node_data={},
        config=BuiltWithFullConfig.model_validate({"config": {"domains": ["example.com"]}, "credentials": GRANT}))
    result = await instance.execute({})
    assert result["status"] == "success" and len(transport.calls) == 1
    assert transport.calls[0].headers["authorization"] == "API " + KEY


@pytest.mark.asyncio
async def test_missing_credential_fails_before_transport(transport):
    instance = node()
    instance.config.credentials = None
    with pytest.raises(ValueError, match="Connect a BuiltWith API key"):
        await instance.execute({})
    assert transport.calls == []


@pytest.mark.asyncio
async def test_api_key_freshening_is_staging_noop():
    assert await BuiltWithNode.freshen_credential(GRANT) is GRANT
