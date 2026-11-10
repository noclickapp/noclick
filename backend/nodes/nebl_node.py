"""Neblio REST API Suite 1.3.0 public mainnet NTP1 and Insight operations.

These endpoints have no authentication. Keys and transaction signing stay in the
user's wallet: construction returns unsigned transactions; broadcasting requires
an already signed transaction. No automatic retries or implicit broadcasting.
Contract: https://github.com/NeblioTeam/neblio-api-swagger-docs/blob/master/swagger.yaml
"""
import math
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://ntp1node.nebl.io"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def safe_segment(cls, value, info):
        if info.field_name in {"tokensymbol", "address", "txid", "tokenid", "utxo", "blockhash"} and isinstance(value, str) and (value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a value without path traversal or control characters")
        return value


class GetTokenIdConfig(_Input):
    """Returns the tokenId representing a token. GET /ntp1/tokenid/{tokensymbol}."""
    operation: Literal["get_token_id"] = Field("get_token_id", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Token Id"})
    tokensymbol: str = Field(..., description='Token symbol', min_length=1, max_length=4096)


class BroadcastTxRequest(_Input):
    txHex: str = Field(..., description='Signed raw tx hex to broadcast', min_length=1, max_length=1000000)


class BroadcastTxConfig(_Input):
    """Broadcasts a signed raw transaction to the network. POST /ntp1/broadcast."""
    operation: Literal["broadcast_tx"] = Field("broadcast_tx", json_schema_extra={"ui:hidden": True, "x-display-name": "Broadcast Signed NTP1 Transaction"})
    body: BroadcastTxRequest = Field(..., description="Broadcasts a signed raw transaction to the network. Supply the provider request fields; never a private key.")


class GetAddressInfoConfig(_Input):
    """Information On a Neblio Address. GET /ntp1/addressinfo/{address}."""
    operation: Literal["get_address_info"] = Field("get_address_info", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address Info"})
    address: str = Field(..., description='Neblio Address to get information on.', min_length=1, max_length=4096)


class GetTransactionInfoConfig(_Input):
    """Information On an NTP1 Transaction. GET /ntp1/transactioninfo/{txid}."""
    operation: Literal["get_transaction_info"] = Field("get_transaction_info", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Transaction Info"})
    txid: str = Field(..., description='Neblio txid to get information on.', min_length=1, max_length=4096)


class GetTokenMetadataConfig(_Input):
    """Get Metadata of Token. GET /ntp1/tokenmetadata/{tokenid}."""
    operation: Literal["get_token_metadata"] = Field("get_token_metadata", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Token Metadata"})
    tokenid: str = Field(..., description='TokenId to request metadata for', min_length=1, max_length=4096)
    verbosity: Literal[0, 1, 2] | None = Field(None, description='0 (Default) is fastest, 1 contains token stats, 2 contains token holding addresses')


class GetTokenMetadataOfUtxoConfig(_Input):
    """Get UTXO Metadata of Token. GET /ntp1/tokenmetadata/{tokenid}/{utxo}."""
    operation: Literal["get_token_metadata_of_utxo"] = Field("get_token_metadata_of_utxo", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Token Metadata Of Utxo"})
    tokenid: str = Field(..., description='TokenId to request metadata for', min_length=1, max_length=4096)
    utxo: str = Field(..., description='Specific UTXO to request metadata for', min_length=1, max_length=4096)
    verbosity: Literal[0, 1, 2] | None = Field(None, description='0 (Default) is fastest, 1 contains token stats, 2 contains token holding addresses')


class GetTokenHoldersConfig(_Input):
    """Get Addresses Holding a Token. GET /ntp1/stakeholders/{tokenid}."""
    operation: Literal["get_token_holders"] = Field("get_token_holders", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Token Holders"})
    tokenid: str = Field(..., description='TokenId to request metadata for', min_length=1, max_length=4096)


class IssueTokenRequestFlags(_Input):
    splitChange: bool | None = Field(None, description='If true change will be split into 2 outputs, one for NEBL change and one for NTP1 change (recommended)')


class IssueTokenRequestTransferItem(_Input):
    address: str | None = Field(None, description='Address to send the amount of issued tokens to', min_length=1, max_length=4096)
    amount: float | None = Field(None)


class IssueTokenRequestMetadataUrlsItem(_Input):
    name: str | None = Field(None, description='Name of the URL', min_length=1, max_length=4096)
    url: str | None = Field(None, description='Actual URL', min_length=1, max_length=4096)
    mimeType: str | None = Field(None, description='mimeType of URL content', min_length=1, max_length=4096)
    dataHash: str | None = Field(None, description='Hash of data at the URL, used for verification', min_length=1, max_length=4096)


class IssueTokenRequestMetadataUserDataMetaItem(_Input):
    key: str | None = Field(None, min_length=1, max_length=4096)
    value: str | None = Field(None, min_length=1, max_length=4096)


class IssueTokenRequestMetadataUserData(_Input):
    meta: list[IssueTokenRequestMetadataUserDataMetaItem] | None = Field(None)


class IssueTokenRequestMetadataEncryptionsItem(_Input):
    key: str | None = Field(None, description='userData key to encrypt', min_length=1, max_length=4096)
    pubkey: str | None = Field(None, description='RSA public key used for encryption', min_length=1, max_length=4096)
    format: str | None = Field(None, description='key format (pem or der)', min_length=1, max_length=4096)
    type: str | None = Field(None, description='pkcs1 or pkcs8', min_length=1, max_length=4096)


class IssueTokenRequestMetadataRulesFeesItemsItem(_Input):
    address: str | None = Field(None, description='Address fee is auto sent to', min_length=1, max_length=4096)
    tokenId: str | None = Field(None, description='How fee should be paid, either with a tokenId, or with NEBL if null', min_length=1, max_length=4096)
    value: str | None = Field(None, description='Amount of NTP1 token, or NEBL (in satoshi) to pay as fee', min_length=1, max_length=4096)


class IssueTokenRequestMetadataRulesFees(_Input):
    items: list[IssueTokenRequestMetadataRulesFeesItemsItem] | None = Field(None, description='Array of objects describing fee rules')
    locked: bool | None = Field(None, description='Whether this rule can be modified in future transactions')


class IssueTokenRequestMetadataRulesHoldersItem(_Input):
    address: str | None = Field(None, description='Address that can hold the token', min_length=1, max_length=4096)
    locked: bool | None = Field(None, description='Whether this rule can be modified in future transactions')


class IssueTokenRequestMetadataRulesExpiration(_Input):
    validUntil: float | None = Field(None, description='Blockheight at wh')
    locked: bool | None = Field(None, description='Whether this rule can be modified in future transactions')


class IssueTokenRequestMetadataRules(_Input):
    fees: IssueTokenRequestMetadataRulesFees | None = Field(None)
    holders: list[IssueTokenRequestMetadataRulesHoldersItem] | None = Field(None, description='Array of objects describing what addresses can hold the token')
    expiration: IssueTokenRequestMetadataRulesExpiration | None = Field(None, description='Object describing expiration rules of the token')


class IssueTokenRequestMetadata(_Input):
    tokenName: str | None = Field(None, description='Token Symbol it will be identified by (ex. NIBBL)', min_length=1, max_length=4096)
    issuer: str | None = Field(None, description='Name of token issuer', min_length=1, max_length=4096)
    description: str | None = Field(None, description='Long name or description of token (ex. Nibble)', min_length=1, max_length=4096)
    urls: list[IssueTokenRequestMetadataUrlsItem] | None = Field(None)
    userData: IssueTokenRequestMetadataUserData | None = Field(None, description='Metadata set by user on token')
    encryptions: list[IssueTokenRequestMetadataEncryptionsItem] | None = Field(None, description='Array of encryption instruction objects for encrypting userData')
    rules: IssueTokenRequestMetadataRules | None = Field(None, description='Object describing token rules')


class IssueTokenRequest(_Input):
    issueAddress: str = Field(..., description='Address issuing the token', min_length=1, max_length=4096)
    amount: float = Field(..., description='Number of tokens to issue')
    divisibility: int = Field(..., ge=0, le=7, description='Number of decimal places the token should be divisble by (0-7)')
    fee: int = Field(..., ge=1000000000, description='Fee in satoshi to include in the issuance transaction min 1000000000 (10 NEBL)')
    reissuable: bool = Field(..., description='whether the token should be reissuable')
    flags: IssueTokenRequestFlags | None = Field(None, description='Object representing flags that potentialy modify this transaction')
    transfer: list[IssueTokenRequestTransferItem] = Field(...)
    metadata: IssueTokenRequestMetadata | None = Field(None, description='Object representing all metadata at token issuance')


class IssueTokenConfig(_Input):
    """Builds a transaction that issues a new NTP1 Token. POST /ntp1/issue."""
    operation: Literal["issue_token"] = Field("issue_token", json_schema_extra={"ui:hidden": True, "x-display-name": "Build Token Issuance"})
    body: IssueTokenRequest = Field(..., description="Builds a transaction that issues a new NTP1 Token. Supply the provider request fields; never a private key.")


class SendTokenRequestToItem(_Input):
    address: str | None = Field(None, description='Address to transfer tokens to', min_length=1, max_length=4096)
    amount: float | None = Field(None, description='Number of tokens to send')
    tokenId: str | None = Field(None, description='ID of token we are sending', min_length=1, max_length=4096)


class SendTokenRequestFlags(_Input):
    splitChange: bool | None = Field(None, description='If true change will be split into 2 outputs, one for NEBL change and one for NTP1 change (recommended)')


class SendTokenRequestMetadataUrlsItem(_Input):
    name: str | None = Field(None, description='Name of the URL', min_length=1, max_length=4096)
    url: str | None = Field(None, description='Actual URL', min_length=1, max_length=4096)
    mimeType: str | None = Field(None, description='mimeType of URL content', min_length=1, max_length=4096)
    dataHash: str | None = Field(None, description='Hash of data at the URL, used for verification', min_length=1, max_length=4096)


class SendTokenRequestMetadataUserDataMetaItem(_Input):
    key: str | None = Field(None, min_length=1, max_length=4096)
    value: str | None = Field(None, min_length=1, max_length=4096)


class SendTokenRequestMetadataUserData(_Input):
    meta: list[SendTokenRequestMetadataUserDataMetaItem] | None = Field(None)


class SendTokenRequestMetadataEncryptionsItem(_Input):
    key: str | None = Field(None, description='userData key to encrypt', min_length=1, max_length=4096)
    pubkey: str | None = Field(None, description='RSA public key used for encryption', min_length=1, max_length=4096)
    format: str | None = Field(None, description='key format (pem or der)', min_length=1, max_length=4096)
    type: str | None = Field(None, description='pkcs1 or pkcs8', min_length=1, max_length=4096)


class SendTokenRequestMetadataRulesFeesItemsItem(_Input):
    address: str | None = Field(None, description='Address fee is auto sent to', min_length=1, max_length=4096)
    tokenId: str | None = Field(None, description='How fee should be paid, either with a tokenId, or with NEBL if null', min_length=1, max_length=4096)
    value: str | None = Field(None, description='Amount of NTP1 token, or NEBL (in satoshi) to pay as fee', min_length=1, max_length=4096)


class SendTokenRequestMetadataRulesFees(_Input):
    items: list[SendTokenRequestMetadataRulesFeesItemsItem] | None = Field(None, description='Array of objects describing fee rules')
    locked: bool | None = Field(None, description='Whether this rule can be modified in future transactions')


class SendTokenRequestMetadataRulesHoldersItem(_Input):
    address: str | None = Field(None, description='Address that can hold the token', min_length=1, max_length=4096)
    locked: bool | None = Field(None, description='Whether this rule can be modified in future transactions')


class SendTokenRequestMetadataRulesExpiration(_Input):
    validUntil: float | None = Field(None, description='Blockheight at wh')
    locked: bool | None = Field(None, description='Whether this rule can be modified in future transactions')


class SendTokenRequestMetadataRules(_Input):
    fees: SendTokenRequestMetadataRulesFees | None = Field(None)
    holders: list[SendTokenRequestMetadataRulesHoldersItem] | None = Field(None, description='Array of objects describing what addresses can hold the token')
    expiration: SendTokenRequestMetadataRulesExpiration | None = Field(None, description='Object describing expiration rules of the token')


class SendTokenRequestMetadata(_Input):
    tokenName: str | None = Field(None, description='Token Symbol it will be identified by (ex. NIBBL)', min_length=1, max_length=4096)
    issuer: str | None = Field(None, description='Name of token issuer', min_length=1, max_length=4096)
    description: str | None = Field(None, description='Long name or description of token (ex. Nibble)', min_length=1, max_length=4096)
    urls: list[SendTokenRequestMetadataUrlsItem] | None = Field(None)
    userData: SendTokenRequestMetadataUserData | None = Field(None, description='Metadata set by user on token')
    encryptions: list[SendTokenRequestMetadataEncryptionsItem] | None = Field(None, description='Array of encryption instruction objects for encrypting userData')
    rules: SendTokenRequestMetadataRules | None = Field(None, description='Object describing token rules')


class SendTokenRequest(_Input):
    fee: int = Field(..., ge=10000, description='Fee in satoshi to include in the issuance transaction min 10000 (0.0001 NEBL)')
    from_: list[str] | None = Field(None, alias="from", description='Array of addresses to send the token from')
    sendutxo: list[str] | None = Field(None, description='Array of UTXOs to send the token from')
    to: list[SendTokenRequestToItem] = Field(...)
    flags: SendTokenRequestFlags | None = Field(None, description='Object representing flags that potentialy modify this transaction')
    metadata: SendTokenRequestMetadata | None = Field(None, description='Object representing all metadata at token issuance')


class SendTokenConfig(_Input):
    """Builds a transaction that sends an NTP1 Token. POST /ntp1/sendtoken."""
    operation: Literal["send_token"] = Field("send_token", json_schema_extra={"ui:hidden": True, "x-display-name": "Build Token Transfer"})
    body: SendTokenRequest = Field(..., description="Builds a transaction that sends an NTP1 Token. Supply the provider request fields; never a private key.")


class BurnTokenRequestTransferItem(_Input):
    address: str | None = Field(None, description='Address to transfer tokens to', min_length=1, max_length=4096)
    amount: float | None = Field(None, description='Number of tokens to send')
    tokenId: str | None = Field(None, description='ID of token we are sending', min_length=1, max_length=4096)


class BurnTokenRequestBurnItem(_Input):
    amount: float | None = Field(None, description='Amount of tokens to burn')
    tokenId: str | None = Field(None, description='Unique token id we are burning', min_length=1, max_length=4096)


class BurnTokenRequest(_Input):
    fee: int = Field(..., ge=10000, description='Fee in satoshi to include in the issuance transaction min 10000 (0.0001 NEBL)')
    from_: list[str] | None = Field(None, alias="from", description='Array of addresses to send the token from')
    transfer: list[BurnTokenRequestTransferItem] | None = Field(None)
    burn: list[BurnTokenRequestBurnItem] = Field(..., description='Array of objects representing tokens to be burned')


class BurnTokenConfig(_Input):
    """Builds a transaction that burns an NTP1 Token. POST /ntp1/burntoken."""
    operation: Literal["burn_token"] = Field("burn_token", json_schema_extra={"ui:hidden": True, "x-display-name": "Build Token Burn"})
    body: BurnTokenRequest = Field(..., description="Builds a transaction that burns an NTP1 Token. Supply the provider request fields; never a private key.")


class SendTxRequest(_Input):
    rawtx: str = Field(..., description='Signed raw tx hex to broadcast', min_length=1, max_length=1000000)


class SendTxConfig(_Input):
    """Broadcasts a signed raw transaction to the network (not NTP1 specific). POST /ins/tx/send."""
    operation: Literal["send_tx"] = Field("send_tx", json_schema_extra={"ui:hidden": True, "x-display-name": "Broadcast Signed Transaction"})
    body: SendTxRequest = Field(..., description="Broadcasts a signed raw transaction to the network (not NTP1 specific). Supply the provider request fields; never a private key.")


class GetBlockConfig(_Input):
    """Returns information regarding a Neblio block. GET /ins/block/{blockhash}."""
    operation: Literal["get_block"] = Field("get_block", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Block"})
    blockhash: str = Field(..., description='Block Hash', min_length=1, max_length=4096)


class GetBlockIndexConfig(_Input):
    """Returns block hash of block. GET /ins/block-index/{blockindex}."""
    operation: Literal["get_block_index"] = Field("get_block_index", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Block Index"})
    blockindex: int = Field(..., ge=0, description='Block Index')


class GetTxConfig(_Input):
    """Returns transaction object. GET /ins/tx/{txid}."""
    operation: Literal["get_tx"] = Field("get_tx", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Tx"})
    txid: str = Field(..., description='Transaction ID', min_length=1, max_length=4096)


class GetRawTxConfig(_Input):
    """Returns raw transaction hex. GET /ins/rawtx/{txid}."""
    operation: Literal["get_raw_tx"] = Field("get_raw_tx", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Raw Tx"})
    txid: str = Field(..., description='Transaction ID', min_length=1, max_length=4096)


class GetAddressConfig(_Input):
    """Returns address object. GET /ins/addr/{address}."""
    operation: Literal["get_address"] = Field("get_address", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address"})
    address: str = Field(..., description='Address', min_length=1, max_length=4096)


class GetAddressBalanceConfig(_Input):
    """Returns address balance in sats. GET /ins/addr/{address}/balance."""
    operation: Literal["get_address_balance"] = Field("get_address_balance", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address Balance"})
    address: str = Field(..., description='Address', min_length=1, max_length=4096)


class GetAddressUnconfirmedBalanceConfig(_Input):
    """Returns address unconfirmed balance in sats. GET /ins/addr/{address}/unconfirmedBalance."""
    operation: Literal["get_address_unconfirmed_balance"] = Field("get_address_unconfirmed_balance", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address Unconfirmed Balance"})
    address: str = Field(..., description='Address', min_length=1, max_length=4096)


class GetAddressTotalReceivedConfig(_Input):
    """Returns total received by address in sats. GET /ins/addr/{address}/totalReceived."""
    operation: Literal["get_address_total_received"] = Field("get_address_total_received", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address Total Received"})
    address: str = Field(..., description='Address', min_length=1, max_length=4096)


class GetAddressUtxosConfig(_Input):
    """Returns all UTXOs at a given address. GET /ins/addr/{address}/utxo."""
    operation: Literal["get_address_utxos"] = Field("get_address_utxos", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address Utxos"})
    address: str = Field(..., description='Address', min_length=1, max_length=4096)


class GetAddressTotalSentConfig(_Input):
    """Returns total sent by address in sats. GET /ins/addr/{address}/totalSent."""
    operation: Literal["get_address_total_sent"] = Field("get_address_total_sent", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Address Total Sent"})
    address: str = Field(..., description='Address', min_length=1, max_length=4096)


class GetTxsConfig(_Input):
    """Get transactions by block or address. GET /ins/txs."""
    operation: Literal["get_txs"] = Field("get_txs", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Txs"})
    address: str | None = Field(None, description='Address', min_length=1, max_length=4096)
    block: str | None = Field(None, description='Block Hash', min_length=1, max_length=4096)
    pageNum: int | None = Field(None, description='Page number to display', ge=0)


class GetSyncConfig(_Input):
    """Get node sync status. GET /ins/sync."""
    operation: Literal["get_sync"] = Field("get_sync", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Sync"})


class GetStatusConfig(_Input):
    """Utility API for calling several blockchain node functions. GET /ins/status."""
    operation: Literal["get_status"] = Field("get_status", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Status"})
    q: Literal["getInfo", "getDifficulty", "getBestBlockHash", "getLastBlockHash"] = Field("getInfo", description='Function to call, getInfo, getDifficulty, getBestBlockHash, or getLastBlockHash')


NeblioOperation = Annotated[Union[
    GetTokenIdConfig, BroadcastTxConfig, GetAddressInfoConfig, GetTransactionInfoConfig, GetTokenMetadataConfig, GetTokenMetadataOfUtxoConfig, GetTokenHoldersConfig, IssueTokenConfig, SendTokenConfig, BurnTokenConfig, SendTxConfig, GetBlockConfig, GetBlockIndexConfig, GetTxConfig, GetRawTxConfig, GetAddressConfig, GetAddressBalanceConfig, GetAddressUnconfirmedBalanceConfig, GetAddressTotalReceivedConfig, GetAddressUtxosConfig, GetAddressTotalSentConfig, GetTxsConfig, GetSyncConfig, GetStatusConfig
], Field(discriminator="operation")]


class NeblioFullConfig(NodeConfig[NeblioOperation, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


ROUTES = {'get_token_id': ('GET', '/ntp1/tokenid/{tokensymbol}', ['tokensymbol']),
 'broadcast_tx': ('POST', '/ntp1/broadcast', []),
 'get_address_info': ('GET', '/ntp1/addressinfo/{address}', ['address']),
 'get_transaction_info': ('GET', '/ntp1/transactioninfo/{txid}', ['txid']),
 'get_token_metadata': ('GET', '/ntp1/tokenmetadata/{tokenid}', ['tokenid']),
 'get_token_metadata_of_utxo': ('GET', '/ntp1/tokenmetadata/{tokenid}/{utxo}', ['tokenid', 'utxo']),
 'get_token_holders': ('GET', '/ntp1/stakeholders/{tokenid}', ['tokenid']),
 'issue_token': ('POST', '/ntp1/issue', []),
 'send_token': ('POST', '/ntp1/sendtoken', []),
 'burn_token': ('POST', '/ntp1/burntoken', []),
 'send_tx': ('POST', '/ins/tx/send', []),
 'get_block': ('GET', '/ins/block/{blockhash}', ['blockhash']),
 'get_block_index': ('GET', '/ins/block-index/{blockindex}', ['blockindex']),
 'get_tx': ('GET', '/ins/tx/{txid}', ['txid']),
 'get_raw_tx': ('GET', '/ins/rawtx/{txid}', ['txid']),
 'get_address': ('GET', '/ins/addr/{address}', ['address']),
 'get_address_balance': ('GET', '/ins/addr/{address}/balance', ['address']),
 'get_address_unconfirmed_balance': ('GET', '/ins/addr/{address}/unconfirmedBalance', ['address']),
 'get_address_total_received': ('GET', '/ins/addr/{address}/totalReceived', ['address']),
 'get_address_utxos': ('GET', '/ins/addr/{address}/utxo', ['address']),
 'get_address_total_sent': ('GET', '/ins/addr/{address}/totalSent', ['address']),
 'get_txs': ('GET', '/ins/txs', []),
 'get_sync': ('GET', '/ins/sync', []),
 'get_status': ('GET', '/ins/status', [])}


class NeblioNode(WorkflowNode):
    integration_type = "automation-nebl"
    connection_evidence = ConnectionEvidence(
        operation="get_sync", noun="public Neblio blockchain status", proves="reachability",
    )
    edit_examples = ["Look up a Neblio address balance", "Build an unsigned NTP1 token transfer", "Broadcast a signed Neblio transaction"]

    @classmethod
    def get_config_model(cls):
        return NeblioFullConfig

    async def execute(self, inputs):
        config = self.config.config
        method, path, path_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation", "body"})
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        kwargs = {"params": values, "headers": {"Accept": "application/json"}}
        if method == "POST":
            kwargs["json"] = config.body.model_dump(mode="json", by_alias=True, exclude_none=True)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Neblio request did not complete; inspect transaction state before retrying a broadcast") from None
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code,
                    "error": "Neblio did not confirm the request; inspect transaction state before retrying a broadcast"}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Neblio returned invalid JSON") from None
        numeric = config.operation in {
            "get_address_balance", "get_address_unconfirmed_balance",
            "get_address_total_received", "get_address_total_sent",
        }
        if numeric:
            valid = type(body) in {int, float} and math.isfinite(body)
        elif config.operation == "get_address_utxos":
            valid = isinstance(body, list) and all(isinstance(item, dict) for item in body)
        else:
            valid = isinstance(body, dict)
        if not valid or isinstance(body, dict) and ("errors" in body or "error" in body and config.operation != "get_sync"):
            raise ValueError("Neblio returned an error or unexpected response shape")
        return {"status": "success", "operation": config.operation, "data": body}
