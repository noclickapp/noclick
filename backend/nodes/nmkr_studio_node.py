"""NMKR Studio v2 mainnet API: projects, NFTs, sales settings and minting.

Wire names, enums and replacement payloads follow the provider's published v2
OpenAPI contract: https://studio-api.nmkr.io/swagger/v2/swagger.json.
Mutating GET endpoints are intentionally sent once and never retried.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://studio-api.nmkr.io"
CREDENTIAL_TYPE = "nmkr_studio_api_key"


class NmkrStudioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="NMKR Studio API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://studio.nmkr.io/",
            "x-credential-instructions": "In NMKR Studio, create an API key for your account and paste it here without the Bearer prefix. Requests use the mainnet API. Minting operations spend the account's ADA balance and send NFTs to the supplied address.",
        })
    credential_type: Literal["nmkr_studio_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_segment(cls, value, info):
        if info.field_name in {"projectuid", "nftuid", "address", "receiveraddress"}:
            if not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 or ord(c) == 127 for c in value):
                raise ValueError("Use a single NMKR UID or wallet address without URL separators")
        return value


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PricelistClassV2(_Payload):
    countNft: int = Field(None, ge=1, le=9223372036854776000)
    priceInLovelace: int | None = Field(None)
    price: float | None = Field(None)
    currency: Literal['ADA', 'SOL', 'USDC', 'ETH', 'USD', 'EUR', 'JPY', 'APT', 'BTC', 'HBAR', 'SONY', 'MATIC', 'NIGHT', 'DISABLED'] = Field(None)
    isActive: StrictBool = Field(None)
    validFrom: datetime | None = Field(None)
    validTo: datetime | None = Field(None)


class PriceDiscountClassV2(_Payload):
    condition: Literal['walletcontainsminofpolicyid', 'whitlistedaddresses', 'stakeonpool', 'couponcode'] = Field(None)
    description: str | None = Field(None)
    minvalue: int | None = Field(None)
    minvalue2: int | None = Field(None)
    minvalue3: int | None = Field(None)
    minvalue4: int | None = Field(None)
    minvalue5: int | None = Field(None)
    isActive: StrictBool = Field(None)
    sendbackDiscount: float = Field(None)
    policyIdOrStakeAddress1: str | None = Field(None)
    policyIdOrStakeAddress2: str | None = Field(None)
    policyIdOrStakeAddress3: str | None = Field(None)
    policyIdOrStakeAddress4: str | None = Field(None)
    policyIdOrStakeAddress5: str | None = Field(None)
    whitelistedAddresses: list[str] | None = Field(None)
    policyProjectname: str | None = Field(None)
    operator: str | None = Field(None)
    couponcode: str | None = Field(None)


class NotificationsClassV2(_Payload):
    notificationType: Literal['webhook', 'email'] = Field(None)
    address: str | None = Field(None)
    isActive: StrictBool = Field(None)


class CountedWhitelistAddressesClass(_Payload):
    address: str | None = Field(None)
    maxCount: int = Field(None)


class SaleconditionsClassV2(_Payload):
    condition: Literal['walletcontainspolicyid', 'walletdoescontainmaxpolicyid', 'walletdoesnotcontainpolicyid', 'walletcontainsminpolicyid', 'walletmustcontainminofpolicyid', 'whitlistedaddresses', 'blacklistedaddresses', 'stakeonpool', 'countedwhitelistedaddresses', 'onlyonesale'] = Field(None)
    policyId1: str | None = Field(None)
    policyId2: str | None = Field(None)
    policyId3: str | None = Field(None)
    policyId4: str | None = Field(None)
    policyId5: str | None = Field(None)
    policyId6: str | None = Field(None)
    policyId7: str | None = Field(None)
    policyId8: str | None = Field(None)
    policyId9: str | None = Field(None)
    policyId10: str | None = Field(None)
    policyId11: str | None = Field(None)
    policyId12: str | None = Field(None)
    policyId13: str | None = Field(None)
    policyId14: str | None = Field(None)
    policyId15: str | None = Field(None)
    minOrMaxValue: int | None = Field(None)
    description: str | None = Field(None)
    isActive: StrictBool = Field(None)
    policyProjectname: str | None = Field(None)
    blacklistedAddresses: list[str] | None = Field(None)
    countedWhitelistAddresses: list[CountedWhitelistAddressesClass] | None = Field(None)


class NmkrListProjectsConfig(_Input):
    """Lists all your projects with pagination"""
    operation: Literal['list_projects'] = Field('list_projects', json_schema_extra={"ui:hidden": True})
    count: int = Field(50, ge=1, le=100)
    page: int = Field(1, ge=1, le=2147483647)
    optionalSortOrder: Literal['created', 'created_desc', 'name', 'name_desc', 'freetokens', 'freetokens_desc', 'soldtokens', 'soldtokens_desc', 'reservedtokens', 'reservedtokens_desc'] = 'created'


class NmkrGetProjectConfig(_Input):
    """Returns detail information about a project"""
    operation: Literal['get_project'] = Field('get_project', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')


class NmkrGetNftCountsConfig(_Input):
    """Returns the count of the sold, reserved and free nfts (project uid)"""
    operation: Literal['get_nft_counts'] = Field('get_nft_counts', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')


class NmkrGetDiscountsConfig(_Input):
    """Returns the discounts for this project (project uid)"""
    operation: Literal['get_discounts'] = Field('get_discounts', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')


class NmkrGetSaleConditionsConfig(_Input):
    """Returns the saleconditions for this project (project uid)"""
    operation: Literal['get_sale_conditions'] = Field('get_sale_conditions', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')


class NmkrGetNotificationsConfig(_Input):
    """Returns the notifications for this project (project uid)"""
    operation: Literal['get_notifications'] = Field('get_notifications', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')


class NmkrListWhitelistConfig(_Input):
    """Gets all entries of a projects whitelist"""
    operation: Literal['list_whitelist'] = Field('list_whitelist', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')


class NmkrListNftsConfig(_Input):
    """Returns detail information about nfts with a specific state with Pagination support. (project uid)"""
    operation: Literal['list_nfts'] = Field('list_nfts', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    state: Literal['all', 'free', 'reserved', 'sold', 'error'] = 'all'
    count: int = Field(50, ge=1, le=100)
    page: int = Field(1, ge=1, le=2147483647)
    orderby: str = 'id'


class NmkrGetNftConfig(_Input):
    """Returns detail information about one nft specified by Id (nft uid)"""
    operation: Literal['get_nft'] = Field('get_nft', json_schema_extra={"ui:hidden": True})
    nftuid: str = Field(..., min_length=1, max_length=256, title='NFT UID')


class NmkrCheckMetadataConfig(_Input):
    """Checks if the metadata is valid"""
    operation: Literal['check_metadata'] = Field('check_metadata', json_schema_extra={"ui:hidden": True})
    nftuid: str = Field(..., min_length=1, max_length=256, title='NFT UID')


class NmkrGetPricelistConfig(_Input):
    """Returns the actual valid pricelist for this project (project uid)"""
    operation: Literal['get_pricelist'] = Field('get_pricelist', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    returnAllPrices: StrictBool = False


class NmkrListProjectTransactionsConfig(_Input):
    """Returns all Transactions of a project"""
    operation: Literal['list_project_transactions'] = Field('list_project_transactions', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    fromdate: datetime | None = None
    todate: datetime | None = None


class NmkrListPayoutWalletsConfig(_Input):
    """Returns all payout wallets in your account"""
    operation: Literal['list_payout_wallets'] = Field('list_payout_wallets', json_schema_extra={"ui:hidden": True})


class NmkrGetMintCouponBalanceConfig(_Input):
    """Returns the count of mint coupons in your account"""
    operation: Literal['get_mint_coupon_balance'] = Field('get_mint_coupon_balance', json_schema_extra={"ui:hidden": True})


class NmkrAddWhitelistEntryConfig(_Input):
    """Adds an entry to a projects whitelist"""
    operation: Literal['add_whitelist_entry'] = Field('add_whitelist_entry', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    address: str = Field(..., min_length=1, max_length=256, title='Wallet address')
    countofnfts: int = Field(..., ge=1, le=9223372036854775807)


class NmkrRemoveWhitelistEntryConfig(_Input):
    """Deletes an entry from a projects whitelist"""
    operation: Literal['remove_whitelist_entry'] = Field('remove_whitelist_entry', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    address: str = Field(..., min_length=1, max_length=256, title='Wallet address')


class NmkrSetNftBlockedConfig(_Input):
    """Block or unblock an NFT. This GET changes the NFT sale availability."""
    operation: Literal['set_nft_blocked'] = Field('set_nft_blocked', json_schema_extra={"ui:hidden": True})
    nftuid: str = Field(..., min_length=1, max_length=256, title='NFT UID')
    blockNft: StrictBool = Field(...)


class NmkrDeleteNftConfig(_Input):
    """Delete an NFT from the database. This GET is destructive."""
    operation: Literal['delete_nft'] = Field('delete_nft', json_schema_extra={"ui:hidden": True})
    nftuid: str = Field(..., min_length=1, max_length=256, title='NFT UID')


class NmkrReplacePricelistConfig(_Input):
    """Replace all pricelist. All existing entries are deleted; an empty entries array clears the list."""
    operation: Literal['replace_pricelist'] = Field('replace_pricelist', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    entries: list[PricelistClassV2] = Field(..., description="Complete replacement list. An empty array clears all existing entries.")


class NmkrReplaceDiscountsConfig(_Input):
    """Replace all discounts. All existing entries are deleted; an empty entries array clears the list."""
    operation: Literal['replace_discounts'] = Field('replace_discounts', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    entries: list[PriceDiscountClassV2] = Field(..., description="Complete replacement list. An empty array clears all existing entries.")


class NmkrReplaceNotificationsConfig(_Input):
    """Replace all notifications. All existing entries are deleted; an empty entries array clears the list."""
    operation: Literal['replace_notifications'] = Field('replace_notifications', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    entries: list[NotificationsClassV2] = Field(..., description="Complete replacement list. An empty array clears all existing entries.")


class NmkrReplaceSaleConditionsConfig(_Input):
    """Replace all sale conditions. All existing entries are deleted; an empty entries array clears the list."""
    operation: Literal['replace_sale_conditions'] = Field('replace_sale_conditions', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    entries: list[SaleconditionsClassV2] = Field(..., description="Complete replacement list. An empty array clears all existing entries.")


class NmkrMintAndSendRandomConfig(_Input):
    """Mint random NFTs and send them to the receiver. Spends ADA for minting and transaction fees; sent once with no retry."""
    operation: Literal['mint_and_send_random'] = Field('mint_and_send_random', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    receiveraddress: str = Field(..., min_length=1, max_length=256, title='Receiver address')
    countnft: int = Field(..., ge=1, le=2147483647)
    blockchain: Literal['Cardano', 'Solana', 'Aptos', 'Hedara', 'Polygon', 'Ethereum', 'Bitcoin', 'Unknown', 'Midnight'] = 'Cardano'


class NmkrMintAndSendSpecificConfig(_Input):
    """Mint a specific NFT and send tokens to the receiver. Spends ADA for minting and transaction fees; sent once with no retry."""
    operation: Literal['mint_and_send_specific'] = Field('mint_and_send_specific', json_schema_extra={"ui:hidden": True})
    projectuid: str = Field(..., min_length=1, max_length=256, title='Project UID')
    nftuid: str = Field(..., min_length=1, max_length=256, title='NFT UID')
    receiveraddress: str = Field(..., min_length=1, max_length=256, title='Receiver address')
    tokencount: int = Field(..., ge=1, le=9223372036854775807)
    blockchain: Literal['Cardano', 'Solana', 'Aptos', 'Hedara', 'Polygon', 'Ethereum', 'Bitcoin', 'Unknown', 'Midnight'] = 'Cardano'


Operation = Annotated[Union[
    NmkrListProjectsConfig,
    NmkrGetProjectConfig,
    NmkrGetNftCountsConfig,
    NmkrGetDiscountsConfig,
    NmkrGetSaleConditionsConfig,
    NmkrGetNotificationsConfig,
    NmkrListWhitelistConfig,
    NmkrListNftsConfig,
    NmkrGetNftConfig,
    NmkrCheckMetadataConfig,
    NmkrGetPricelistConfig,
    NmkrListProjectTransactionsConfig,
    NmkrListPayoutWalletsConfig,
    NmkrGetMintCouponBalanceConfig,
    NmkrAddWhitelistEntryConfig,
    NmkrRemoveWhitelistEntryConfig,
    NmkrSetNftBlockedConfig,
    NmkrDeleteNftConfig,
    NmkrReplacePricelistConfig,
    NmkrReplaceDiscountsConfig,
    NmkrReplaceNotificationsConfig,
    NmkrReplaceSaleConditionsConfig,
    NmkrMintAndSendRandomConfig,
    NmkrMintAndSendSpecificConfig
], Field(discriminator="operation")]


class NmkrStudioConfig(NodeConfig[Operation, NmkrStudioAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Exactly one published endpoint for each operation.
ROUTES = {'list_projects': ('GET', '/v2/ListProjects/{count}/{page}', ['optionalSortOrder'], False, 'list'),
 'get_project': ('GET', '/v2/GetProjectDetails/{projectuid}', [], False, 'dict'),
 'get_nft_counts': ('GET', '/v2/GetCounts/{projectuid}', [], False, 'dict'),
 'get_discounts': ('GET', '/v2/GetDiscounts/{projectuid}', [], False, 'list'),
 'get_sale_conditions': ('GET', '/v2/GetSaleConditions/{projectuid}', [], False, 'list'),
 'get_notifications': ('GET', '/v2/GetNotifications/{projectuid}', [], False, 'list'),
 'list_whitelist': ('GET', '/v2/ManageWhitelist/{projectuid}', [], False, 'list'),
 'list_nfts': ('GET', '/v2/GetNfts/{projectuid}/{state}/{count}/{page}', ['orderby'], False, 'list'),
 'get_nft': ('GET', '/v2/GetNftDetailsById/{nftuid}', [], False, 'dict'),
 'check_metadata': ('GET', '/v2/CheckMetadata/{nftuid}', [], False, 'dict'),
 'get_pricelist': ('GET', '/v2/GetPricelist/{projectuid}', ['returnAllPrices'], False, 'list'),
 'list_project_transactions': ('GET',
                               '/v2/GetProjectTransactions/{projectuid}',
                               ['fromdate', 'todate'],
                               False,
                               'list'),
 'list_payout_wallets': ('GET', '/v2/GetPayoutWallets', [], False, 'list'),
 'get_mint_coupon_balance': ('GET', '/v2/GetMintCouponBalance', [], False, 'dict'),
 'add_whitelist_entry': ('POST',
                         '/v2/ManageWhitelist/{projectuid}/{address}/{countofnfts}',
                         [],
                         False,
                         'none'),
 'remove_whitelist_entry': ('DELETE', '/v2/ManageWhitelist/{projectuid}/{address}', [], False, 'none'),
 'set_nft_blocked': ('GET', '/v2/BlockUnblockNft/{nftuid}/{blockNft}', [], False, 'none'),
 'delete_nft': ('GET', '/v2/DeleteNft/{nftuid}', [], False, 'none'),
 'replace_pricelist': ('PUT', '/v2/UpdatePricelist/{projectuid}', [], True, 'none'),
 'replace_discounts': ('PUT', '/v2/UpdateDiscounts/{projectuid}', [], True, 'none'),
 'replace_notifications': ('POST', '/v2/UpdateNotifications/{projectuid}', [], True, 'list'),
 'replace_sale_conditions': ('PUT', '/v2/UpdateSaleConditions/{projectuid}', [], True, 'none'),
 'mint_and_send_random': ('GET',
                          '/v2/MintAndSendRandom/{projectuid}/{countnft}/{receiveraddress}',
                          ['blockchain'],
                          False,
                          'dict'),
 'mint_and_send_specific': ('GET',
                            '/v2/MintAndSendSpecific/{projectuid}/{nftuid}/{tokencount}/{receiveraddress}',
                            ['blockchain'],
                            False,
                            'dict')}


def _wire(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    return value


class NmkrStudioNode(WorkflowNode):
    integration_type = "automation-nmkr-studio"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects",
        label_keys=("projectname", "uid", "id"))

    @classmethod
    def get_config_model(cls):
        return NmkrStudioConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an NMKR Studio API key")
        config = self.config.config
        method, path, query_names, has_body, expected = ROUTES[config.operation]
        for segment in path.split("/"):
            if segment.startswith("{"):
                field = segment[1:-1]
                path = path.replace(segment, quote(_wire(getattr(config, field)), safe=""))
        params = {name: _wire(getattr(config, name)) for name in query_names
            if getattr(config, name) is not None}
        kwargs = {}
        if has_body:
            kwargs["json"] = [entry.model_dump(mode="json", exclude_unset=True) for entry in config.entries]
        async with guarded_async_client(timeout=60.0,
                follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **kwargs)
        output = {"operation": config.operation, "http_status": response.status_code}
        if response.status_code != 200:
            message = "NMKR Studio rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("errorMessage"), str) and error["errorMessage"]:
                    message = error["errorMessage"]
            except ValueError:
                pass
            return {**output, "status": "error", "error": _redact(message, credential.api_key)}
        if not response.content:
            if expected != "none":
                raise ValueError("NMKR Studio returned an empty response for a data operation")
            return {**output, "status": "success"}
        body = response.json()
        if isinstance(body, dict) and (body.get("resultState") == "Error" or body.get("errorMessage")):
            return {**output, "status": "error", "error": _redact(body.get("errorMessage") or "NMKR Studio reported an error", credential.api_key)}
        if expected == "list" and not isinstance(body, list):
            raise ValueError("NMKR Studio returned an unexpected list response")
        if expected == "dict" and not isinstance(body, dict):
            raise ValueError("NMKR Studio returned an unexpected object response")
        result = {**output, "status": "success", "data": _redact(body, credential.api_key)}
        if config.operation in {"list_projects", "list_nfts"}:
            # A full page is only a continuation candidate, never a total count.
            result.update(page=config.page, count=config.count,
                next_page=config.page + 1 if len(body) == config.count else None)
        return result
