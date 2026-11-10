"""OpenSea API v2: NFT discovery, market data, signed orders and event polling.

Wire contract: https://api.opensea.io/api/v2/openapi.json (2.0.0).
Signed orders must be prepared and signed outside NoClick. No private keys or
wallet signing are accepted. API-key reads prove reachability, not identity.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.opensea.io"
CREDENTIAL_TYPE = "open_sea_api_key"


class OpenSeaApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenSea API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.opensea.io/reference/api-keys",
            "x-credential-instructions": "Paste an OpenSea API key. NoClick sends it as x-api-key to api.opensea.io. The connection check reads public collections and proves API reachability, not wallet ownership. Listings and offers require an already-signed Seaport order; NoClick does not sign transactions.",
        })
    credential_type: Literal["open_sea_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header or whitespace")
        return value


def _segment(value):
    if not isinstance(value, str) or not value or len(value) > 512 or value in {".", ".."} or any(c in value for c in "/\\?#%") or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use a single OpenSea resource identifier")
    return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"slug", "address", "identifier", "protocol", "order_hash", "protocol_address", "address_or_username", "chain"} and value is not None:
            return _segment(value)
        return value


Chain = Literal['base', 'ethereum', 'zora', 'arbitrum', 'sei', 'avalanche', 'polygon', 'optimism', 'ape_chain', 'flow', 'soneium', 'ronin', 'bera_chain', 'solana', 'shape', 'unichain', 'gunzilla', 'abstract', 'animechain', 'hyperevm', 'somnia', 'monad', 'hyperliquid', 'megaeth', 'ink', 'robinhood']


class OfferItem(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    endAmount: str = Field(...)
    identifierOrCriteria: str = Field(...)
    itemType: int = Field(...)
    startAmount: str = Field(...)
    token: str = Field(...)


class ConsiderationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    endAmount: str = Field(...)
    identifierOrCriteria: str = Field(...)
    itemType: int = Field(...)
    recipient: str = Field(...)
    startAmount: str = Field(...)
    token: str = Field(...)


class SeaportParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    conduitKey: str = Field(...)
    consideration: list[ConsiderationItem] = Field(...)
    counter: str = Field(...)
    endTime: str = Field(...)
    offer: list[OfferItem] = Field(...)
    offerer: str = Field(...)
    orderType: int = Field(...)
    salt: str = Field(...)
    startTime: str = Field(...)
    totalOriginalConsiderationItems: int = Field(...)
    zone: Optional[str] = None
    zoneHash: str = Field(...)


class OpenSeaListCollectionsConfig(_Input):
    'Get multiple collections'
    operation: Literal['list_collections'] = Field('list_collections', title='Get multiple collections', json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=100)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)
    chain: Optional[Chain] = Field(None, description='Blockchain to filter by')
    creator_username: Optional[str] = Field(None, description='Username of collection creator to filter by', min_length=1, max_length=512)
    include_hidden: Optional[bool] = Field(None, description='Include hidden collections in results')
    order_by: Optional[str] = Field(None, description='Field to order results by', min_length=1, max_length=512)


class OpenSeaGetCollectionConfig(_Input):
    'Get a single collection'
    operation: Literal['get_collection'] = Field('get_collection', title='Get a single collection', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique identifier for the specific collection', min_length=1, max_length=512)


class OpenSeaGetCollectionStatsConfig(_Input):
    'Get collection stats'
    operation: Literal['get_collection_stats'] = Field('get_collection_stats', title='Get collection stats', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique identifier for the specific collection', min_length=1, max_length=512)


class OpenSeaGetCollectionTraitsConfig(_Input):
    'Get collection traits'
    operation: Literal['get_collection_traits'] = Field('get_collection_traits', title='Get collection traits', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique identifier for the specific collection', min_length=1, max_length=512)


class OpenSeaGetNftConfig(_Input):
    'Get NFT'
    operation: Literal['get_nft'] = Field('get_nft', title='Get NFT', json_schema_extra={"ui:hidden": True})
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    address: str = Field(..., description='The unique public blockchain identifier for the contract', min_length=1, max_length=512)
    identifier: str = Field(..., description='The NFT token id', min_length=1, max_length=512)


class OpenSeaGetNftsByCollectionConfig(_Input):
    'Get NFTs by collection'
    operation: Literal['get_nfts_by_collection'] = Field('get_nfts_by_collection', title='Get NFTs by collection', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Collection slug', min_length=1, max_length=512)
    traits: Optional[str] = Field(None, description='JSON array of trait filters. Each object has \'traitType\' and \'value\' fields. Multiple traits are AND-combined (items must match all). Example: [{"traitType":"Background","value":"Red"}]', min_length=1, max_length=512)
    has_agent_binding: Optional[bool] = Field(None, description='Filter by NFTs that have an ERC-8217 agent binding')
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaGetNftsByContractConfig(_Input):
    'Get NFTs by contract'
    operation: Literal['get_nfts_by_contract'] = Field('get_nfts_by_contract', title='Get NFTs by contract', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., description='Contract address', min_length=1, max_length=512)
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaGetNftsByAccountConfig(_Input):
    'Get NFTs by account'
    operation: Literal['get_nfts_by_account'] = Field('get_nfts_by_account', title='Get NFTs by account', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., description='Account address', min_length=1, max_length=512)
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    collection: Optional[str] = Field(None, min_length=1, max_length=512)
    include_auto_hidden: Optional[bool] = Field(None, description='Include NFTs that were hidden automatically because a third party minted or sent them to this account. NFTs the account holder hid themselves are not returned, and this does not surface NFTs removed for policy violations.')
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaGetNftOwnersConfig(_Input):
    'Get NFT owners'
    operation: Literal['get_nft_owners'] = Field('get_nft_owners', title='Get NFT owners', json_schema_extra={"ui:hidden": True})
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    address: str = Field(..., description='The unique public blockchain identifier for the contract', min_length=1, max_length=512)
    identifier: str = Field(..., description='The NFT token id', min_length=1, max_length=512)
    limit: int = Field(20, description='Number of results to return (default: 20, max: 100)', ge=1, le=200)
    next: Optional[str] = Field(None, description='Pagination cursor for next page', min_length=1, max_length=4096)


class OpenSeaGetAccountConfig(_Input):
    'Get an OpenSea account profile'
    operation: Literal['get_account'] = Field('get_account', title='Get an OpenSea account profile', json_schema_extra={"ui:hidden": True})
    address_or_username: str = Field(..., description='The blockchain address or username of the account to retrieve.', min_length=1, max_length=256)


class OpenSeaGetContractConfig(_Input):
    'Get contract'
    operation: Literal['get_contract'] = Field('get_contract', title='Get contract', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., description='The unique public blockchain identifier for the contract', min_length=1, max_length=512)
    chain: Chain = Field(..., description='The blockchain on which to filter the results')


class OpenSeaGetOrderConfig(_Input):
    'Get an order'
    operation: Literal['get_order'] = Field('get_order', title='Get an order', json_schema_extra={"ui:hidden": True})
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    protocol_address: str = Field(..., description='Protocol contract address', min_length=1, max_length=512)
    order_hash: str = Field(..., description='Order hash', min_length=1, max_length=512)


class OpenSeaGetBestListingsCollectionConfig(_Input):
    'Get best listings by collection'
    operation: Literal['get_best_listings_collection'] = Field('get_best_listings_collection', title='Get best listings by collection', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique string to identify a collection on OpenSea', min_length=1, max_length=512)
    include_private_listings: Optional[bool] = Field(None, description='Whether to include private listings; defaults to false')
    traits: Optional[str] = Field(None, description='JSON array of trait filters to narrow listings by item traits. Each object has \'traitType\' and \'value\' fields. Multiple traits are AND-combined (items must match all). Example: [{"traitType":"Background","value":"Red"}]', min_length=1, max_length=512)
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaListListingsCollectionAllConfig(_Input):
    'Get all listings by collection'
    operation: Literal['list_listings_collection_all'] = Field('list_listings_collection_all', title='Get all listings by collection', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique string to identify a collection on OpenSea', min_length=1, max_length=512)
    include_private_listings: Optional[bool] = Field(None, description='Whether to include private listings; defaults to false')
    maker: Optional[str] = Field(None, description='Filter by the wallet address of the order maker', min_length=1, max_length=512)
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaListOffersCollectionAllConfig(_Input):
    'Get all offers by collection'
    operation: Literal['list_offers_collection_all'] = Field('list_offers_collection_all', title='Get all offers by collection', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique string to identify a collection on OpenSea', min_length=1, max_length=512)
    maker: Optional[str] = Field(None, description='Filter by the wallet address of the order maker', min_length=1, max_length=512)
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaGetBestOfferNftConfig(_Input):
    'Get best offer by NFT'
    operation: Literal['get_best_offer_nft'] = Field('get_best_offer_nft', title='Get best offer by NFT', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique string to identify a collection on OpenSea', min_length=1, max_length=512)
    identifier: str = Field(..., description='NFT token id', min_length=1, max_length=512)


class OpenSeaListEventsByCollectionConfig(_Input):
    'Get events (by collection)'
    operation: Literal['list_events_by_collection'] = Field('list_events_by_collection', title='Get events (by collection)', json_schema_extra={"ui:hidden": True})
    slug: str = Field(..., description='Unique identifier for the collection', min_length=1, max_length=512)
    after: Optional[int] = Field(None, description='Only show events after this timestamp (Unix timestamp in seconds)')
    before: Optional[int] = Field(None, description='Only show events before this timestamp (Unix timestamp in seconds)')
    event_type: Optional[list[Literal['sale', 'transfer', 'mint', 'listing', 'offer', 'trait_offer', 'collection_offer']]] = Field(None, description='Filter by event types. To get order invalidation and revalidation events, please use the Stream API. The order status can also be checked on the Get Order endpoint.')
    traits: Optional[str] = Field(None, description='JSON array of trait filters. Each object has \'traitType\' and \'value\' fields. Multiple traits are AND-combined (items must match all). Example: [{"traitType":"Background","value":"Red"}]', min_length=1, max_length=512)
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaListEventsByAccountConfig(_Input):
    'Get events (by account)'
    operation: Literal['list_events_by_account'] = Field('list_events_by_account', title='Get events (by account)', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., description='The blockchain address of the account', min_length=1, max_length=512)
    after: Optional[int] = Field(None, description='Only show events after this timestamp (Unix timestamp in seconds)')
    before: Optional[int] = Field(None, description='Only show events before this timestamp (Unix timestamp in seconds)')
    event_type: Optional[list[Literal['sale', 'transfer', 'mint', 'listing', 'offer', 'trait_offer', 'collection_offer']]] = Field(None, description='Filter by event types. To get order invalidation and revalidation events, please use the Stream API. The order status can also be checked on the Get Order endpoint.')
    chain: Optional[Chain] = Field(None, description='Filter by blockchain')
    limit: int = Field(20, description='Number of items to return per page', ge=1, le=200)
    next: Optional[str] = Field(None, min_length=1, max_length=4096)


class OpenSeaRefreshNftMetadataConfig(_Input):
    'Refresh NFT metadata'
    operation: Literal['refresh_nft_metadata'] = Field('refresh_nft_metadata', title='Refresh NFT metadata', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., description='Contract address', min_length=1, max_length=512)
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    identifier: str = Field(..., description='Token identifier', min_length=1, max_length=512)
    ignoreCachedItemUrls: Optional[bool] = Field(None)


class OpenSeaPostListingConfig(_Input):
    'Create a listing'
    operation: Literal['post_listing'] = Field('post_listing', title='Submit Signed Listing', json_schema_extra={"ui:hidden": True})
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    protocol: Literal["seaport"] = Field("seaport")
    parameters: SeaportParameters = Field(..., description="Complete Seaport parameters from the already-signed order. NoClick never signs or modifies these fields.")
    protocol_address: str = Field(..., min_length=1, max_length=512)
    signature: str = Field(..., min_length=1, max_length=4096, description="Signature from the order maker; this submits the signed order to OpenSea.")


class OpenSeaPostOfferConfig(_Input):
    'Create an item offer'
    operation: Literal['post_offer'] = Field('post_offer', title='Submit Signed Offer', json_schema_extra={"ui:hidden": True})
    chain: Chain = Field(..., description='The blockchain on which to filter the results')
    protocol: Literal["seaport"] = Field("seaport")
    parameters: SeaportParameters = Field(..., description="Complete Seaport parameters from the already-signed order. NoClick never signs or modifies these fields.")
    protocol_address: str = Field(..., min_length=1, max_length=512)
    signature: str = Field(..., min_length=1, max_length=4096, description="Signature from the order maker; this submits the signed order to OpenSea.")


class _EventPoll(PollTriggerConfigBase):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-webhook": True})
    event_type: Optional[Literal["sale", "transfer", "mint", "listing", "offer", "trait_offer", "collection_offer"]] = Field(None, description="Leave empty for all documented event types.")
    lookback_seconds: int = Field(86400, ge=60, le=604800, description="Poll the last 24 hours by default. First poll baselines silently; downtime beyond this window may miss events. A poll refuses more than 4,000 events; narrow the scope or window.")

    @field_validator("slug", "address", check_fields=False)
    @classmethod
    def identifier(cls, value):
        return _segment(value)


class OpenSeaOnCollectionEventConfig(_EventPoll):
    operation: Literal["on_collection_event"] = Field("on_collection_event", title="On New Collection Event",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    slug: str = Field(..., min_length=1, max_length=512, title="Collection slug")


class OpenSeaOnAccountEventConfig(_EventPoll):
    operation: Literal["on_account_event"] = Field("on_account_event", title="On New Account Event",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    address: str = Field(..., min_length=1, max_length=512, title="Account address")


OpenSeaOperation = Annotated[Union[
    OpenSeaListCollectionsConfig,
    OpenSeaGetCollectionConfig,
    OpenSeaGetCollectionStatsConfig,
    OpenSeaGetCollectionTraitsConfig,
    OpenSeaGetNftConfig,
    OpenSeaGetNftsByCollectionConfig,
    OpenSeaGetNftsByContractConfig,
    OpenSeaGetNftsByAccountConfig,
    OpenSeaGetNftOwnersConfig,
    OpenSeaGetAccountConfig,
    OpenSeaGetContractConfig,
    OpenSeaGetOrderConfig,
    OpenSeaGetBestListingsCollectionConfig,
    OpenSeaListListingsCollectionAllConfig,
    OpenSeaListOffersCollectionAllConfig,
    OpenSeaGetBestOfferNftConfig,
    OpenSeaListEventsByCollectionConfig,
    OpenSeaListEventsByAccountConfig,
    OpenSeaRefreshNftMetadataConfig,
    OpenSeaPostListingConfig,
    OpenSeaPostOfferConfig,
    OpenSeaOnCollectionEventConfig,
    OpenSeaOnAccountEventConfig
], Field(discriminator="operation")]


class OpenSeaNodeConfig(NodeConfig[OpenSeaOperation, OpenSeaApiKeyCredential]):
    pass


# Each action maps to one published operation; query names are never inferred.
OPERATIONS = {
    'list_collections': ('GET', '/api/v2/collections', ('limit', 'next', 'chain', 'creator_username', 'include_hidden', 'order_by')),
    'get_collection': ('GET', '/api/v2/collections/{slug}', ()),
    'get_collection_stats': ('GET', '/api/v2/collections/{slug}/stats', ()),
    'get_collection_traits': ('GET', '/api/v2/traits/{slug}', ()),
    'get_nft': ('GET', '/api/v2/chain/{chain}/contract/{address}/nfts/{identifier}', ()),
    'get_nfts_by_collection': ('GET', '/api/v2/collection/{slug}/nfts', ('traits', 'has_agent_binding', 'limit', 'next')),
    'get_nfts_by_contract': ('GET', '/api/v2/chain/{chain}/contract/{address}/nfts', ('limit', 'next')),
    'get_nfts_by_account': ('GET', '/api/v2/chain/{chain}/account/{address}/nfts', ('collection', 'include_auto_hidden', 'limit', 'next')),
    'get_nft_owners': ('GET', '/api/v2/chain/{chain}/contract/{address}/nfts/{identifier}/owners', ('limit', 'next')),
    'get_account': ('GET', '/api/v2/accounts/{address_or_username}', ()),
    'get_contract': ('GET', '/api/v2/chain/{chain}/contract/{address}', ()),
    'get_order': ('GET', '/api/v2/orders/chain/{chain}/protocol/{protocol_address}/{order_hash}', ()),
    'get_best_listings_collection': ('GET', '/api/v2/listings/collection/{slug}/best', ('include_private_listings', 'traits', 'limit', 'next')),
    'list_listings_collection_all': ('GET', '/api/v2/listings/collection/{slug}/all', ('include_private_listings', 'maker', 'limit', 'next')),
    'list_offers_collection_all': ('GET', '/api/v2/offers/collection/{slug}/all', ('maker', 'limit', 'next')),
    'get_best_offer_nft': ('GET', '/api/v2/offers/collection/{slug}/nfts/{identifier}/best', ()),
    'list_events_by_collection': ('GET', '/api/v2/events/collection/{slug}', ('after', 'before', 'event_type', 'traits', 'limit', 'next')),
    'list_events_by_account': ('GET', '/api/v2/events/accounts/{address}', ('after', 'before', 'event_type', 'chain', 'limit', 'next')),
    'refresh_nft_metadata': ('POST', '/api/v2/chain/{chain}/contract/{address}/nfts/{identifier}/refresh', ('ignoreCachedItemUrls',)),
    'post_listing': ('POST', '/api/v2/orders/{chain}/{protocol}/listings', ()),
    'post_offer': ('POST', '/api/v2/orders/{chain}/{protocol}/offers', ()),
}


_LIST_KEYS = {
    "list_collections": "collections", "get_nfts_by_collection": "nfts",
    "get_nfts_by_contract": "nfts", "get_nfts_by_account": "nfts",
    "get_nft_owners": "owners", "get_best_listings_collection": "listings",
    "list_listings_collection_all": "listings", "list_offers_collection_all": "offers",
    "list_events_by_collection": "asset_events", "list_events_by_account": "asset_events",
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class OpenSeaAPIError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _event_key(event):
    # One transaction can contain multiple transfers. Retain token, participants,
    # quantity and event kind, rather than treating transaction alone as an ID.
    nft = event.get("nft") or event.get("asset") or {}
    identity = {
        "type": event["event_type"], "timestamp": event["event_timestamp"],
        "chain": event["chain"], "quantity": event["quantity"],
        "transaction": event.get("transaction"), "order_hash": event.get("order_hash"),
        "contract": nft.get("contract"), "identifier": nft.get("identifier"),
        "maker": event.get("maker"), "seller": event.get("seller"), "buyer": event.get("buyer"),
        "from_address": event.get("from_address"), "to_address": event.get("to_address"),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


class OpenSeaNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-open-sea"
    connection_evidence = ConnectionEvidence(
        noun="collections", operation="list_collections", label_keys=("name", "collection"),
        proves="reachability",
    )
    edit_examples = [
        "Find NFTs in this wallet", "Get the best listings for this collection",
        "Submit this signed Seaport offer", "Watch new collection sales",
    ]

    @classmethod
    def get_config_model(cls):
        return OpenSeaNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_collection_event", "on_account_event"}:
            return bool(output.get("new_event_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "events" not in output:
            return super().resolve_agent_event(output)
        events = output.get("events")
        if not isinstance(events, list) or not events:
            return None
        lines = []
        for event in events[:10]:
            nft = event.get("nft") or event.get("asset") or {}
            actor = event.get("maker") or event.get("seller") or event.get("from_address") or "Unknown participant"
            recipient = event.get("buyer") or event.get("to_address") or event.get("taker")
            item = nft.get("name") or nft.get("identifier") or "collection order"
            lines.append(
                f"- {event.get('event_type')}: {actor}"
                f"{(' → ' + recipient) if recipient else ''}; {event.get('quantity')} × {item}"
                f" on {event.get('chain')} at {event.get('event_timestamp')}"
                f" (contract {nft.get('contract')}, token {nft.get('identifier')},"
                f" order {event.get('order_hash')}, transaction {event.get('transaction')})."
            )
        return {"text": f"OpenSea: {len(events)} new event(s) for {output.get('scope')}:\n" + "\n".join(lines),
                "conversation_key": None}

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None, text_response=False):
        # The host is fixed; a pagination token is only a query value. Redirects
        # and ambient proxies cannot forward the credential to another origin.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                method, BASE_URL + path, headers={"x-api-key": api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}),
            )
        if not 200 <= response.status_code < 300:
            message = _redact(response.text[:4000], api_key)
            raise OpenSeaAPIError(response.status_code, message or f"OpenSea HTTP {response.status_code}")
        if text_response and "json" not in response.headers.get("content-type", "").lower():
            return response.text
        try:
            result = response.json()
        except ValueError:
            raise ValueError("OpenSea returned an invalid JSON response") from None
        if not text_response and not isinstance(result, dict):
            raise ValueError("OpenSea returned an unexpected response envelope")
        if text_response and not isinstance(result, str):
            raise ValueError("OpenSea metadata refresh returned an unexpected response")
        return result

    async def _perform(self, operation, api_key, values):
        method, path, query_names = OPERATIONS[operation]
        for name, value in values.items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        params = {name: values[name] for name in query_names if name in values}
        body = None
        if operation in {"post_listing", "post_offer"}:
            body = {name: values[name] for name in ("parameters", "protocol_address", "signature")}
        result = await self._request(api_key, method, path, params=params, body=body,
                                     text_response=operation == "refresh_nft_metadata")
        key = _LIST_KEYS.get(operation)
        if key is not None:
            rows = result.get(key)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("OpenSea returned an incomplete list response")
        return result

    async def _poll(self, api_key, config):
        collection = config.operation == "on_collection_event"
        operation = "list_events_by_collection" if collection else "list_events_by_account"
        field = "slug" if collection else "address"
        values = {field: getattr(config, field), "limit": 200,
                  "after": max(0, int(time.time()) - config.lookback_seconds)}
        if config.event_type is not None:
            values["event_type"] = [config.event_type]
        events, cursors = [], set()
        for _ in range(20):
            result = await self._perform(operation, api_key, values)
            events.extend(result["asset_events"])
            cursor = result.get("next")
            if cursor is None or cursor == "":
                break
            if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in cursors:
                raise ValueError("OpenSea returned an invalid or repeated event cursor")
            cursors.add(cursor)
            values["next"] = cursor
        else:
            # No seen-set update on truncation: never silently drop a backlog.
            raise ValueError("OpenSea event window exceeds 4,000 events; narrow the scope or lookback")
        if len(events) > 4000:
            raise ValueError("OpenSea event window exceeds 4,000 events")
        # Oldest first helps downstream automations preserve event order.
        events.sort(key=lambda event: event["event_timestamp"])
        fresh = await self._filter_unseen(events, _event_key)
        return {"status": "success", "operation": config.operation, "events": fresh,
                "new_event_count": len(fresh), "scope": f"{field} {getattr(config, field)}"}

    async def execute(self, inputs):
        if not isinstance(self.config, OpenSeaNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an OpenSea API key")
        config = self.config.config
        api_key = self.config.credentials.api_key
        writing = config.operation in {"post_listing", "post_offer", "refresh_nft_metadata"}
        try:
            if isinstance(config, _EventPoll):
                return _redact(await self._poll(api_key, config), api_key)
            values = config.model_dump(exclude_none=True, exclude={"operation"})
            result = await self._perform(config.operation, api_key, values)
            # Preserve the provider's native envelope (and opaque next cursor).
            output = {"status": "success", "operation": config.operation, "data": result,
                      "identity_verified": False}
            if config.operation == "refresh_nft_metadata":
                output["refresh_requested"] = True
            return _redact(output, api_key)
        except OpenSeaAPIError as exc:
            return {"status": "error", "operation": config.operation, "http_status": exc.status, "status_code": exc.status,
                    "error": str(exc), "identity_verified": False}
        except httpx.HTTPError:
            return {"status": "unknown" if writing else "error", "operation": config.operation,
                    "error": "OpenSea request did not complete; inspect the provider before retrying" if writing else "OpenSea could not be reached",
                    "write_outcome": "unverified" if writing else None, "identity_verified": False}
