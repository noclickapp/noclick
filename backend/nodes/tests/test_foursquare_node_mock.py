"""Offline request, response and credential regressions for Foursquare Places."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import foursquare_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-foursquare-service-key"
AUTH = {"credential_type": "foursquare_service_key", "api_key": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/foursquare/routes.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(
        node_id="foursquare-fixture", node_type="automation-foursquare",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH},
    )


def transport(monkeypatch, body=None, *, status=200, headers=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={} if body is None else body, headers=headers)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_each_operation_uses_one_pinned_endpoint(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case["body"])
    result = await node(operation, **case["config"]).execute({})
    assert result["data"] == case["body"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "places-api.foursquare.com"
    assert request.url.path == case["path"].replace("{fsq_place_id}", "sample")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-Places-Api-Version"] == "2025-06-17"
    assert not request.content  # Foursquare's POST mutations use query parameters.
    if "/suggest/" in case["path"] and request.method == "POST":
        assert request.url.params["dry_run"] == "false"
    assert "fsq_place_id" not in request.url.params or operation == "confirm_geotagging"


@pytest.mark.asyncio
async def test_search_filters_and_false_values_are_preserved(monkeypatch):
    body = {"results": [{"fsq_place_id": "5a187743ccad6b307315e6fe", "name": "HQ"}]}
    requests = transport(monkeypatch, body)
    result = await node("search_places", query="coffee & tea", ll="41.8781,-87.6298", limit=50,
                        radius=0, open_now=False, sort="DISTANCE").execute({})
    assert dict(requests[0].url.params) == {
        "query": "coffee & tea", "ll": "41.8781,-87.6298", "limit": "50",
        "radius": "0", "open_now": "false", "sort": "DISTANCE",
    }
    assert result["data"] == body


@pytest.mark.asyncio
async def test_suggestion_is_not_reported_as_completed_place_change(monkeypatch):
    body = {"suggested_edits": [{"id": "edit-1", "status": "PENDING"}], "errors": []}
    requests = transport(monkeypatch, body)
    result = await node("suggest_edit", fsq_place_id="sample", name="New name", dry_run=True).execute({})
    assert dict(requests[0].url.params) == {"dry_run": "true", "name": "New name"}
    assert result["data"] == body
    assert "success" not in result
    assert "written_id" not in result


@pytest.mark.asyncio
async def test_connection_evidence_lists_only_calling_keys_suggestions(monkeypatch):
    body = {"suggested_edits": [{"id": "edit-1", "fsq_place_id": "place-1", "status": "PENDING"}]}
    requests = transport(monkeypatch, body)
    result = await node("get_suggestion_status").execute({})
    assert result["items"] == body["suggested_edits"]
    assert requests[0].url.path == "/places/suggest/status"
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_geotagging_preserves_request_id_for_confirmation(monkeypatch):
    requests = transport(monkeypatch, {"candidates": []}, headers={"X-Fsq-Request-Id": "request-1"})
    result = await node("get_geotagging_candidates", ll="41.8781,-87.6298").execute({})
    assert result["request_id"] == "request-1" and len(requests) == 1
    requests = transport(monkeypatch, {"response": "ok"})
    await node("confirm_geotagging", request_id=result["request_id"], fsq_place_id="place-1",
               confirm_context="CurrentLocation", delayed=False).execute({})
    assert dict(requests[0].url.params) == {"request_id": "request-1", "fsq_place_id": "place-1",
                                            "confirm_context": "CurrentLocation", "delayed": "false"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_errors_fail_and_redact_key(monkeypatch, status):
    transport(monkeypatch, {"message": TOKEN}, status=status)
    with pytest.raises(ValueError) as exc:
        await node("get_suggestion_status").execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_partial_suggestion_errors_remain_visible_and_redacted(monkeypatch):
    transport(monkeypatch, {"suggested_edits": [{"id": "edit-1"}], "errors": [TOKEN]})
    result = await node("suggest_removal", fsq_place_id="sample", reason="CLOSED").execute({})
    assert result["status"] == "error" and result["data"]["suggested_edits"] == [{"id": "edit-1"}]
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("get_place_photos", {}), ("get_place", []), ("get_suggestion_status", "login")])
async def test_wrong_shapes_do_not_prove_connection(monkeypatch, operation, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="shape"):
        await node(operation, **CASES[operation]["config"]).execute({})


@pytest.mark.asyncio
async def test_html_and_oversized_responses_fail(monkeypatch):
    transport(monkeypatch, {}, headers={"Content-Type": "text/html"})
    with pytest.raises(ValueError, match="JSON"):
        await node("get_suggestion_status").execute({})
    transport(monkeypatch, {"huge": "x" * 8_000_001})
    with pytest.raises(ValueError, match="bounded"):
        await node("get_suggestion_status").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("place_id", ["..", ".", "a/b", "a\\b"])
async def test_place_ids_cannot_change_route(monkeypatch, place_id):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError):
        await node("get_place", fsq_place_id=place_id).execute({})
    assert requests == []


@pytest.mark.parametrize("key", ["Bearer token", "https://example.com/key", "token\nheader", ""])
def test_manual_key_rejects_headers_urls_and_empty_values(key):
    with pytest.raises((ValueError, ValidationError)):
        native.FoursquareServiceKey(api_key=key)


def test_credential_has_default_family_and_only_one_required_secret():
    credential = native.FoursquareServiceKey(api_key=TOKEN)
    assert credential.credential_type == "foursquare_service_key"
    assert native.FoursquareServiceKey.model_json_schema()["required"] == ["api_key"]


@pytest.mark.parametrize("operation,config", [
    ("search_places", {"limit": 51}), ("suggest_removal", {"fsq_place_id": "sample", "reason": "invented"}),
    ("get_place", {}), ("search_places", {"arbitrary": "injected"}),
])
def test_invalid_configuration_is_rejected(operation, config):
    with pytest.raises(ValueError):
        node(operation, **config)
