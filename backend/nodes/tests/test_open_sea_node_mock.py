"""OpenSea request, credential and polling regressions against the provider schema.

The vendored OpenAPI subset is provider-authored. Values below are synthetic;
no live account, API key or wallet signature is used.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator, RefResolver
from pydantic import ValidationError

from nodes import open_sea_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-opensea-test-key"
ADDRESS = "0x0000000000000000000000000000000000000001"
CONTRACT = "0x0000000000000000000000000000000000000002"
ORDER_HASH = "0x" + "1" * 64
SPEC = json.loads((Path(__file__).parent / "fixtures/open-sea/openapi.json").read_text())
PARAMETERS = {
    "offerer": ADDRESS, "zone": ADDRESS, "offer": [{"itemType": 2, "token": CONTRACT,
        "identifierOrCriteria": "1", "startAmount": "1", "endAmount": "1"}],
    "consideration": [{"itemType": 0, "token": ADDRESS, "identifierOrCriteria": "0",
        "startAmount": "100", "endAmount": "100", "recipient": ADDRESS}],
    "orderType": 0, "startTime": "1700000000", "endTime": "1800000000",
    "zoneHash": "0x" + "0" * 64, "salt": "1", "conduitKey": "0x" + "0" * 64,
    "counter": "0", "totalOriginalConsiderationItems": 1,
}
SIGNED = {"parameters": PARAMETERS, "signature": "0x" + "a" * 130, "protocol_address": ADDRESS}
NFT = {"collection": "example", "contract": CONTRACT, "identifier": "1", "is_disabled": False,
       "is_nsfw": False, "opensea_url": "https://opensea.io/assets/ethereum/" + CONTRACT + "/1",
       "token_standard": "erc721", "traits": [], "updated_at": "2026-11-10T00:00:00Z", "name": "Example #1"}
EVENTS = [
    {"chain": "ethereum", "event_timestamp": 1794268800, "event_type": "transfer", "from_address": ADDRESS,
     "to_address": CONTRACT, "quantity": 1, "transfer_type": "transfer", "transaction": ORDER_HASH, "nft": NFT},
    {"chain": "ethereum", "event_timestamp": 1794268801, "event_type": "sale", "buyer": CONTRACT,
     "seller": ADDRESS, "closing_date": 1794268801, "quantity": 1, "transaction": ORDER_HASH,
     "order_hash": ORDER_HASH, "nft": NFT},
    {"chain": "ethereum", "event_timestamp": 1794268802, "event_type": "order", "order_type": "listing",
     "is_private_listing": False, "maker": ADDRESS, "quantity": 1, "asset": NFT, "order_hash": ORDER_HASH},
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="open-sea-test", node_type="automation-open-sea",
        node_data={"config": config, "credentials": credential or {"api_key": TOKEN, "credential_type": native.CREDENTIAL_TYPE}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Explicit resource boundaries: IDs must not escape their selected route.
CASES = [
    ("list_collections", {}, "GET", "/api/v2/collections", {"collections": []}),
    ("get_collection", {"slug": "example"}, "GET", "/api/v2/collections/example", {"collection": "example"}),
    ("get_collection_stats", {"slug": "example"}, "GET", "/api/v2/collections/example/stats", {"total": {}}),
    ("get_collection_traits", {"slug": "example"}, "GET", "/api/v2/traits/example", {"categories": {}, "counts": {}}),
    ("get_nft", {"chain": "ethereum", "address": CONTRACT, "identifier": "1"}, "GET", f"/api/v2/chain/ethereum/contract/{CONTRACT}/nfts/1", {"nft": NFT}),
    ("get_nfts_by_collection", {"slug": "example"}, "GET", "/api/v2/collection/example/nfts", {"nfts": []}),
    ("get_nfts_by_contract", {"chain": "ethereum", "address": CONTRACT}, "GET", f"/api/v2/chain/ethereum/contract/{CONTRACT}/nfts", {"nfts": []}),
    ("get_nfts_by_account", {"chain": "ethereum", "address": ADDRESS}, "GET", f"/api/v2/chain/ethereum/account/{ADDRESS}/nfts", {"nfts": []}),
    ("get_nft_owners", {"chain": "ethereum", "address": CONTRACT, "identifier": "1"}, "GET", f"/api/v2/chain/ethereum/contract/{CONTRACT}/nfts/1/owners", {"owners": []}),
    ("get_account", {"address_or_username": ADDRESS}, "GET", f"/api/v2/accounts/{ADDRESS}", {"address": ADDRESS}),
    ("get_contract", {"chain": "ethereum", "address": CONTRACT}, "GET", f"/api/v2/chain/ethereum/contract/{CONTRACT}", {"address": CONTRACT}),
    ("get_order", {"chain": "ethereum", "protocol_address": ADDRESS, "order_hash": ORDER_HASH}, "GET", f"/api/v2/orders/chain/ethereum/protocol/{ADDRESS}/{ORDER_HASH}", {"order": {}}),
    ("get_best_listings_collection", {"slug": "example"}, "GET", "/api/v2/listings/collection/example/best", {"listings": []}),
    ("list_listings_collection_all", {"slug": "example"}, "GET", "/api/v2/listings/collection/example/all", {"listings": []}),
    ("list_offers_collection_all", {"slug": "example"}, "GET", "/api/v2/offers/collection/example/all", {"offers": []}),
    ("get_best_offer_nft", {"slug": "example", "identifier": "1"}, "GET", "/api/v2/offers/collection/example/nfts/1/best", {"chain": "ethereum"}),
    ("list_events_by_collection", {"slug": "example"}, "GET", "/api/v2/events/collection/example", {"asset_events": EVENTS}),
    ("list_events_by_account", {"address": ADDRESS}, "GET", f"/api/v2/events/accounts/{ADDRESS}", {"asset_events": EVENTS}),
    ("refresh_nft_metadata", {"chain": "ethereum", "address": CONTRACT, "identifier": "1"}, "POST", f"/api/v2/chain/ethereum/contract/{CONTRACT}/nfts/1/refresh", "success"),
    ("post_listing", {"chain": "ethereum", **SIGNED}, "POST", "/api/v2/orders/ethereum/seaport/listings", {"chain": "ethereum"}),
    ("post_offer", {"chain": "ethereum", **SIGNED}, "POST", "/api/v2/orders/ethereum/seaport/offers", {"chain": "ethereum"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload", CASES, ids=[case[0] for case in CASES])
async def test_exact_single_request_per_action(monkeypatch, operation, config, method, path, payload):
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert result["identity_verified"] is False
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.host, request.url.path) == (method, "api.opensea.io", path)
    assert request.headers["x-api-key"] == TOKEN
    if operation in {"post_listing", "post_offer"}:
        assert json.loads(request.content) == SIGNED
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_repeated_event_filters_boolean_query_and_opaque_pagination(monkeypatch):
    requests = transport(monkeypatch, {"asset_events": [], "next": "opaque+/="})
    result = await node({"operation": "list_events_by_collection", "slug": "example", "after": 1700000000,
        "event_type": ["sale", "mint"], "next": "https://untrusted.invalid/?x=1&x=2"}).execute({})
    assert requests[0].url.params.get_list("event_type") == ["sale", "mint"]
    assert requests[0].url.params["after"] == "1700000000"
    assert requests[0].url.params["next"] == "https://untrusted.invalid/?x=1&x=2"
    assert result["data"]["next"] == "opaque+/="
    requests = transport(monkeypatch, {"nfts": []})
    await node({"operation": "get_nfts_by_account", "chain": "ethereum", "address": ADDRESS, "include_auto_hidden": False}).execute({})
    assert requests[0].url.params["include_auto_hidden"] == "false"


def test_manual_connect_and_credential_defaults():
    shaped, errors, _ = shape_credential(native.CREDENTIAL_TYPE, {"api_key": "  " + TOKEN + "  "})
    assert not errors
    assert shaped["api_key"] == TOKEN
    assert native.OpenSeaApiKeyCredential.model_validate(shaped).credential_type == native.CREDENTIAL_TYPE
    assert native.OpenSeaApiKeyCredential.model_fields["credential_type"].default == native.CREDENTIAL_TYPE
    assert native.OpenSeaNode.connection_evidence.proves == "reachability"


@pytest.mark.parametrize("key", ["", "https://example.com/key", "foo\r\nx-api-key: bad", "two words", "<token>"])
def test_bad_credential_is_refused(key):
    with pytest.raises(ValidationError):
        native.OpenSeaApiKeyCredential(api_key=key)


@pytest.mark.parametrize("identifier", ["..", ".", "../other", "a%2Fb", "evil?next=1", "x#fragment", "a\\b"])
def test_path_and_trigger_scope_cannot_escape(identifier):
    for operation in ["get_collection", "on_collection_event"]:
        with pytest.raises(ValueError):
            node({"operation": operation, "slug": identifier})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_keep_provider_status_and_redact_secret(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"error": "denied " + TOKEN}))
    result = await node({"operation": "list_collections"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "denied" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_timeout_is_ambiguous_and_is_not_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("contains " + TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "post_offer", "chain": "ethereum", **SIGNED}).execute({})
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified"
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["success", "1"])
async def test_metadata_refresh_accepts_documented_string_and_plain_text(monkeypatch, text):
    transport(monkeypatch, lambda r: httpx.Response(200, text=text))
    result = await node({"operation": "refresh_nft_metadata", "chain": "ethereum", "address": CONTRACT,
        "identifier": "1", "ignoreCachedItemUrls": True}).execute({})
    assert result["data"] == text and result["refresh_requested"]


@pytest.mark.asyncio
async def test_bad_list_never_reports_success(monkeypatch):
    transport(monkeypatch, {"nfts": "bad"})
    with pytest.raises(ValueError, match="incomplete list"):
        await node({"operation": "get_nfts_by_collection", "slug": "example"}).execute({})


def state_store(n, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    n._update_node_state = update


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,scope,path", [
    ("on_collection_event", {"slug": "example"}, "/api/v2/events/collection/example"),
    ("on_account_event", {"address": ADDRESS}, f"/api/v2/events/accounts/{ADDRESS}"),
])
async def test_poll_baselines_deduplicates_pages_and_delivers_human_event(monkeypatch, operation, scope, path):
    # Every event variant's fields are checked against OpenSea's own schemas.
    for event, schema in zip(EVENTS, ["TransferEvent", "SaleEvent", "OrderEvent"]):
        Draft202012Validator({"$ref": "#/components/schemas/" + schema}, resolver=RefResolver.from_schema(SPEC)).validate(event)
    current = [EVENTS[0]]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"asset_events": current, "next": None}))
    monkeypatch.setattr(native.time, "time", lambda: 1794269900)
    n = node({"operation": operation, **scope, "event_type": "sale"})
    state = {}
    state_store(n, state)
    first = await n.execute({})
    assert first["new_event_count"] == 0 and not native.OpenSeaNode.should_propagate_output(first, {"operation": operation})
    current.extend(EVENTS[1:])
    output = await n.execute({})
    assert output["events"] == EVENTS[1:] and output["new_event_count"] == 2
    assert (await n.execute({}))["events"] == []
    event = native.OpenSeaNode.resolve_agent_event(output)
    assert "sale" in event["text"] and ADDRESS in event["text"] and CONTRACT in event["text"] and ORDER_HASH in event["text"]
    assert event["conversation_key"] is None
    assert all(r.url.path == path and r.url.params["after"] == str(1794269900 - 86400) for r in requests)
    assert requests[0].url.params.get_list("event_type") == ["sale"]
    assert poll_scope(native.OpenSeaNode, {"operation": operation, **scope}) != poll_scope(native.OpenSeaNode, {"operation": operation, **scope, "lookback_seconds": 600})


@pytest.mark.asyncio
async def test_poll_paginates_without_changing_boundary(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={
        "asset_events": [EVENTS[1]] if r.url.params.get("next") else [EVENTS[0]],
        "next": None if r.url.params.get("next") else "opaque+/="}))
    n = node({"operation": "on_collection_event", "slug": "example"})
    state_store(n, {"seen_ids": []})
    output = await n.execute({})
    assert output["events"] == EVENTS[:2]
    assert len(requests) == 2 and requests[1].url.params["next"] == "opaque+/="
    assert requests[0].url.params["after"] == requests[1].url.params["after"]


@pytest.mark.asyncio
async def test_poll_rejects_cursor_loop_before_updating_seen_set(monkeypatch):
    transport(monkeypatch, {"asset_events": EVENTS, "next": "loop"})
    n = node({"operation": "on_collection_event", "slug": "example"})
    state = {"seen_ids": []}
    state_store(n, state)
    with pytest.raises(ValueError, match="repeated event cursor"):
        await n.execute({})
    assert state == {"seen_ids": []}


def test_multi_transfer_transaction_keeps_distinct_tokens():
    other = copy.deepcopy(EVENTS[0])
    other["nft"]["identifier"] = "2"
    assert native._event_key(EVENTS[0]) != native._event_key(other)
    other["nft"]["identifier"] = "1"
    other["nft"]["name"] = "changed display metadata"
    assert native._event_key(EVENTS[0]) == native._event_key(other)
