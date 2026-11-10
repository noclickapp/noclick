"""Exercise Bandsintown through the real node factory and connection seam.

HTTP responses use pinned contract field examples; no live account is needed.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import bandsintown_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential, typed_fields
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/bandsintown/responses.json").read_text())
AUTH = {"credential_type": "bandsintown_api_key", "api_key": "bandsintown-fixture-token-42", "artist_name": "Maroon 5"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    def reply(request):
        requests.append(request)
        response = replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies


def node(config, credential=AUTH):
    return NodeFactory.create_node(node_id="bandsintown-fixture", node_type="automation-bandsintown",
                                 node_data={"config": config, "credentials": credential})


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,key", [
    ({"operation": "get_artist"}, "/artists/Maroon%205", "artist"),
    ({"operation": "get_artist_by_id", "artist_id": "510"}, "/artists/id_510", "artist"),
    ({"operation": "list_artist_events", "artist_name": "Skrillex", "date": "2015-05-05,2017-05-05"}, "/artists/Skrillex/events", "events"),
])
async def test_contract_routes_and_query_auth_through_factory(wire, config, path, key):
    requests, replies = wire
    replies.append(httpx.Response(200, json=FIXTURE[key]))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["events" if key == "events" else "data"] == FIXTURE[key]
    request = requests[0]
    assert request.method == "GET" and request.url.host == "rest.bandsintown.com"
    assert request.url.raw_path.split(b"?")[0].decode() == path
    assert dict(request.url.params) == {"app_id": AUTH["api_key"], **({"date": config["date"]} if key == "events" else {})}
    assert "authorization" not in request.headers and not replies


@pytest.mark.asyncio
@pytest.mark.parametrize("name,encoded", [
    ("AC/DC", "AC%252FDC"), ("Who?", "Who%253F"), ("Star*", "Star%252A"),
    ('The "Band"', "The%20%27CBand%27C"), ("Björk", "Bj%C3%B6rk"),
    ("A&B#C", "A%26B%23C"),
])
async def test_documented_special_artist_encoding(wire, name, encoded):
    requests, replies = wire
    replies.append(httpx.Response(200, json=FIXTURE["artist"]))
    await node({"operation": "get_artist", "artist_name": name}).execute({})
    assert requests[0].url.raw_path.split(b"?")[0] == ("/artists/" + encoded).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("dates", ["upcoming", "past", "all", "2015-05-05,2017-05-05"])
async def test_event_filters_empty_lists_and_provider_metadata(wire, dates):
    requests, replies = wire
    replies.append(httpx.Response(200, json=[]))
    result = await node({"operation": "list_artist_events", "date": dates}).execute({})
    assert result == {"status": "success", "events": [], "count": 0}
    assert requests[0].url.params["date"] == dates


@pytest.mark.asyncio
async def test_default_events_filter_and_key_not_in_result(wire):
    requests, replies = wire
    replies.append(httpx.Response(200, json={**FIXTURE["artist"], "url": "https://www.bandsintown.com/a/510?app_id=" + AUTH["api_key"]}))
    result = await node({"operation": "get_artist"}).execute({})
    assert AUTH["api_key"] not in json.dumps(result)
    replies.append(httpx.Response(200, json=[]))
    await node({"operation": "list_artist_events"}).execute({})
    assert requests[-1].url.params["date"] == "upcoming"


@pytest.mark.asyncio
async def test_connection_proves_only_reachability_and_reports_rejections(wire):
    requests, replies = wire
    assert native.BandsintownNode.connection_evidence.proves == "reachability"
    replies.append(httpx.Response(200, json=FIXTURE["artist"]))
    result = await collect_evidence(node_type="automation-bandsintown", credential_data=AUTH, user_id="fixture")
    assert result.reachable is True
    assert requests[-1].url.path == "/artists/Maroon 5"
    replies.append(httpx.Response(403, text="Application ID rejected: " + AUTH["api_key"]))
    rejected = await collect_evidence(node_type="automation-bandsintown", credential_data=AUTH, user_id="fixture")
    assert rejected.reachable is False and AUTH["api_key"] not in rejected.error
    replies.append(httpx.ReadTimeout("timeout"))
    uncertain = await collect_evidence(node_type="automation-bandsintown", credential_data=AUTH, user_id="fixture")
    assert uncertain.reachable is None
    replies.append(httpx.Response(200, json={}))
    uncertain = await collect_evidence(node_type="automation-bandsintown", credential_data=AUTH, user_id="fixture")
    assert uncertain.reachable is None


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://other.test"}),
    httpx.Response(429, text="rate limited"), httpx.Response(500, text="Unavailable"),
    httpx.Response(200, text="<html>Sign in</html>"),
    httpx.Response(200, json={"error": "Not found"}), httpx.Response(200, json=[]),
])
async def test_failed_or_malformed_responses_never_claim_success(wire, response):
    requests, replies = wire
    replies.append(response)
    with pytest.raises(ValueError):
        await node({"operation": "get_artist"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_events_wrong_envelope_or_missing_id_rejected(wire):
    for body in ({"events": []}, [{}], ["wrong"]):
        wire[1].append(httpx.Response(200, json=body))
        with pytest.raises(ValueError, match="events response"):
            await node({"operation": "list_artist_events"}).execute({})


@pytest.mark.asyncio
async def test_long_key_is_redacted_before_error_text_is_truncated(wire):
    key = "fixture-secret-part-" * 100
    wire[1].append(httpx.Response(403, text="Rejected application ID: " + key))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_artist"}, credential={**AUTH, "api_key": key}).execute({})
    assert "fixture-secret-part-" not in str(error.value)
    assert "[redacted]" in str(error.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_artist_by_id", "artist_id": "../123"},
    {"operation": "get_artist", "artist_name": ".."},
    {"operation": "get_artist", "artist_name": "bad\nname"},
    {"operation": "list_artist_events", "date": "tomorrow"},
    {"operation": "list_artist_events", "date": "2026-02-30,2026-03-01"},
    {"operation": "list_artist_events", "date": "2026-03-02,2026-03-01"},
    {"operation": "create_event"},
])
def test_invalid_fields_and_unsupported_writes_fail_before_http(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_connect_lists_required_fields_and_defaults_type():
    shaped, errors, _ = shape_credential("bandsintown_api_key", {"api_key": AUTH["api_key"], "artist_name": " Maroon 5 "})
    assert not errors and shaped == {"api_key": AUTH["api_key"], "artist_name": AUTH["artist_name"]}
    assert native.BandsintownAPIKeyCredential.model_validate(shaped).credential_type == "bandsintown_api_key"
    fields = {f["name"] for f in typed_fields("bandsintown_api_key")}
    assert fields == {"api_key", "artist_name"}
    for bad in ("https://example.test/key", "<token>", "bad\nkey"):
        with pytest.raises(ValidationError):
            native.BandsintownAPIKeyCredential(api_key=bad, artist_name="Maroon 5")
