"""Beaconcha.in v1 API-key chain reads and system-metric submissions.

Public reads establish reachability only; account watchlists require OAuth and
are deliberately outside this API-key integration. Requests are single-page.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://beaconcha.in"
CREDENTIAL_TYPE = "beaconchain_api_key"


class BeaconchainAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Beaconchain API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://beaconcha.in/user/settings",
            "x-credential-instructions": "Paste your beaconcha.in API key from Settings. Chain reads are public and prove service reachability only, not account ownership or permission to submit metrics. Metric submission writes to the account owning the key."})
    credential_type: Literal["beaconchain_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Epoch(_Input):
    epoch: str = Field("latest", description="Nonnegative epoch number, latest or finalized.")
    @field_validator("epoch")
    @classmethod
    def epoch_value(cls, value):
        if value not in {"latest", "finalized"} and not re.fullmatch(r"[0-9]{1,16}", value):
            raise ValueError("Use an epoch number, latest or finalized")
        return value


class _Slot(_Input):
    slot: str = Field("latest", description="Nonnegative slot number or latest.")
    @field_validator("slot")
    @classmethod
    def slot_value(cls, value):
        if value != "latest" and not re.fullmatch(r"[0-9]{1,16}", value):
            raise ValueError("Use a slot number or latest")
        return value


class _Validators(_Input):
    validators: str = Field(..., max_length=10000, description="Up to 100 comma-separated validator indices or 48-byte BLS public keys, with no spaces.")
    @field_validator("validators")
    @classmethod
    def ids(cls, value):
        if not 1 <= len(value.split(",")) <= 100 or any(not re.fullmatch(r"(?:[0-9]{1,16}|(?:0x)?[a-fA-F0-9]{96})", item) for item in value.split(",")):
            raise ValueError("Use at most 100 comma-separated indices or BLS public keys")
        return value


class _Address(_Input):
    address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$", description="0x-prefixed Ethereum address.")


class _Window(_Validators):
    epoch: int | None = Field(None, ge=0, description="Inclusive upper epoch of the provider's 100-epoch window.")


class _History(_Validators):
    latest_epoch: int | None = Field(None, ge=0, description="Inclusive end epoch; absent uses the provider's latest epoch.")
    offset: int = Field(0, ge=0, description="Epochs to skip backwards from latest_epoch.")
    limit: int = Field(100, ge=1, le=100, description="Number of epochs in this window; this is not an item count.")
    @model_validator(mode="after")
    def ordered(self):
        if self.latest_epoch is not None and self.offset > self.latest_epoch:
            raise ValueError("Offset must not exceed latest_epoch")
        return self


class _Page(_Address):
    offset: int = Field(0, ge=0, description="Number of records to skip.")
    limit: int = Field(50, ge=1, le=200, description="Maximum records in this page. Request the next offset explicitly.")


class GetLatestState(_Input):
    operation: Literal["get_latest_state"] = Field("get_latest_state", json_schema_extra={"ui:hidden": True})


class GetGasPrices(_Input):
    operation: Literal["get_gas_prices"] = Field("get_gas_prices", json_schema_extra={"ui:hidden": True})


class GetEpoch(_Epoch):
    operation: Literal["get_epoch"] = Field("get_epoch", json_schema_extra={"ui:hidden": True})


class ListEpochSlots(_Epoch):
    operation: Literal["list_epoch_slots"] = Field("list_epoch_slots", json_schema_extra={"ui:hidden": True})


class GetSlot(_Slot):
    operation: Literal["get_slot"] = Field("get_slot", json_schema_extra={"ui:hidden": True})


class ListSlotWithdrawals(_Slot):
    operation: Literal["list_slot_withdrawals"] = Field("list_slot_withdrawals", json_schema_extra={"ui:hidden": True})


class ListSlotAttestations(_Slot):
    operation: Literal["list_slot_attestations"] = Field("list_slot_attestations", json_schema_extra={"ui:hidden": True})


class GetValidators(_Validators):
    operation: Literal["get_validators"] = Field("get_validators", json_schema_extra={"ui:hidden": True})


class GetValidatorRewards(_Validators):
    operation: Literal["get_validator_rewards"] = Field("get_validator_rewards", json_schema_extra={"ui:hidden": True})


class GetExecutionRewards(_Validators):
    operation: Literal["get_execution_rewards"] = Field("get_execution_rewards", json_schema_extra={"ui:hidden": True})


class ListBalanceHistory(_History):
    operation: Literal["list_balance_history"] = Field("list_balance_history", json_schema_extra={"ui:hidden": True})


class ListIncomeHistory(_History):
    operation: Literal["list_income_history"] = Field("list_income_history", json_schema_extra={"ui:hidden": True})


class ListValidatorDeposits(_Validators):
    operation: Literal["list_validator_deposits"] = Field("list_validator_deposits", json_schema_extra={"ui:hidden": True})


class ListValidatorWithdrawals(_Window):
    operation: Literal["list_validator_withdrawals"] = Field("list_validator_withdrawals", json_schema_extra={"ui:hidden": True})


class ListValidatorProposals(_Window):
    operation: Literal["list_validator_proposals"] = Field("list_validator_proposals", json_schema_extra={"ui:hidden": True})


class GetValidatorQueue(_Input):
    operation: Literal["get_validator_queue"] = Field("get_validator_queue", json_schema_extra={"ui:hidden": True})


class GetRocketpoolStats(_Input):
    operation: Literal["get_rocketpool_stats"] = Field("get_rocketpool_stats", json_schema_extra={"ui:hidden": True})


class GetSyncCommittee(_Input):
    operation: Literal["get_sync_committee"] = Field("get_sync_committee", json_schema_extra={"ui:hidden": True})
    period: str = Field("latest", pattern=r"^(?:[0-9]{1,16}|latest|next)$", description="Sync committee period, latest or next.")


class GetAddressBalances(_Address):
    operation: Literal["get_address_balances"] = Field("get_address_balances", json_schema_extra={"ui:hidden": True})


class ListAddressTokens(_Page):
    operation: Literal["list_address_tokens"] = Field("list_address_tokens", json_schema_extra={"ui:hidden": True})


class ResolveENS(_Input):
    operation: Literal["resolve_ens"] = Field("resolve_ens", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1, max_length=255, pattern=r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+$|^0x[a-fA-F0-9]{40}$", description="ENS name such as vitalik.eth, or Ethereum address.")


class SubmitSystemMetrics(_Input):
    """Submit one system sample; no retries and no delivery/readback claim."""
    operation: Literal["submit_system_metrics"] = Field("submit_system_metrics", json_schema_extra={"ui:hidden": True})
    machine: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$", description="Machine name shown in the beaconcha.in monitoring dashboard.")
    timestamp: int = Field(..., ge=0, strict=True, description="Unix timestamp in seconds for this sample.")
    exporter_version: str = Field(..., min_length=1, max_length=100)
    cpu_cores: int = Field(..., ge=0, strict=True)
    cpu_threads: int = Field(..., ge=0, strict=True)
    memory_node_bytes_total: int = Field(..., ge=0, strict=True)
    memory_node_bytes_free: int = Field(..., ge=0, strict=True)
    disk_node_bytes_total: int = Field(..., ge=0, strict=True)
    disk_node_bytes_free: int = Field(..., ge=0, strict=True)
    @model_validator(mode="after")
    def capacities(self):
        if self.memory_node_bytes_free > self.memory_node_bytes_total or self.disk_node_bytes_free > self.disk_node_bytes_total:
            raise ValueError("Free capacity must not exceed total capacity")
        return self


BeaconchainConfig = Annotated[Union[GetLatestState, GetGasPrices, GetEpoch, ListEpochSlots, GetSlot, ListSlotWithdrawals, ListSlotAttestations, GetValidators, GetValidatorRewards, GetExecutionRewards, ListBalanceHistory, ListIncomeHistory, ListValidatorDeposits, ListValidatorWithdrawals, ListValidatorProposals, GetValidatorQueue, GetRocketpoolStats, GetSyncCommittee, GetAddressBalances, ListAddressTokens, ResolveENS, SubmitSystemMetrics], Field(discriminator="operation")]


class BeaconchainNodeConfig(NodeConfig[BeaconchainConfig, BeaconchainAPIKeyCredential]):
    pass


ROUTES = {'get_latest_state': '/api/v1/latestState', 'get_gas_prices': '/api/v1/execution/gasnow', 'get_epoch': '/api/v1/epoch/{epoch}', 'list_epoch_slots': '/api/v1/epoch/{epoch}/slots', 'get_slot': '/api/v1/slot/{slot}', 'list_slot_withdrawals': '/api/v1/slot/{slot}/withdrawals', 'list_slot_attestations': '/api/v1/slot/{slot}/attestations', 'get_validators': '/api/v1/validator/{validators}', 'get_validator_rewards': '/api/v1/validator/{validators}/performance', 'get_execution_rewards': '/api/v1/validator/{validators}/execution/performance', 'list_balance_history': '/api/v1/validator/{validators}/balancehistory', 'list_income_history': '/api/v1/validator/{validators}/incomedetailhistory', 'list_validator_deposits': '/api/v1/validator/{validators}/deposits', 'list_validator_withdrawals': '/api/v1/validator/{validators}/withdrawals', 'list_validator_proposals': '/api/v1/validator/{validators}/proposals', 'get_validator_queue': '/api/v1/validators/queue', 'get_rocketpool_stats': '/api/v1/rocketpool/stats', 'get_sync_committee': '/api/v1/sync_committee/{period}', 'get_address_balances': '/api/v1/execution/address/{address}', 'list_address_tokens': '/api/v1/execution/address/{address}/erc20tokens', 'resolve_ens': '/api/v1/ens/lookup/{domain}'}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(str(key), secret): _redact(item, secret) for key, item in value.items()}
    return value


class BeaconchainNode(WorkflowNode):
    integration_type = "automation-beaconchain"
    connection_evidence = ConnectionEvidence(noun="network state", operation="get_latest_state", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BeaconchainNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Beaconchain API key")
        op = self.config.config
        key = self.config.credentials.api_key
        write = isinstance(op, SubmitSystemMetrics)
        values = op.model_dump(exclude_none=True)
        body = None
        params = {}
        if write:
            route = "/api/v1/client/metrics"
            # Required query key in the pinned contract; header also works live.
            params = {"apikey": key, "machine": op.machine}
            body = {"version": 2, "process": "system", **op.model_dump(exclude={"operation", "machine"})}
        else:
            route = ROUTES[op.operation]
            used = re.findall(r"{(\w+)}", route)
            for field in used:
                route = route.replace("{" + field + "}", quote(str(values[field]), safe=""))
            params = {k: v for k, v in values.items() if k not in {"operation", *used}}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request("POST" if write else "GET", BASE + route,
                    headers={"apikey": key, "Accept": "application/json"}, params=params,
                    **({"json": body} if write else {}))
        except httpx.RequestError:
            result = {"status": "error", "success": False, "message": "Beaconchain request failed", "write_outcome": "unknown" if write else None}
        else:
            try:
                payload = response.json()
            except (ValueError, UnicodeDecodeError):
                payload = None
            accepted = response.status_code == 200 and isinstance(payload, dict) and (payload.get("code") == 200 if op.operation == "get_gas_prices" else payload.get("status") == "OK")
            if not accepted:
                message = payload.get("status") if isinstance(payload, dict) else None
                result = {"status": "error", "success": False, "http_status": response.status_code,
                    "message": message if isinstance(message, str) and message != "OK" else "Beaconchain returned an unsuccessful or unexpected response",
                    "write_outcome": "unknown" if write else None}
            else:
                result = {"status": "success", "success": True, "http_status": response.status_code,
                    "data": payload.get("data"), "account_identity_verified": False}
                if write:
                    result.update(submission_acknowledged=True, readback_verified=False)
                elif hasattr(op, "offset"):
                    result.update(window={k: values[k] for k in ("offset", "limit", "latest_epoch") if k in values}, automatic_pagination=False)
        result = _redact(result, key)
        await self.emit(result)
        return result
