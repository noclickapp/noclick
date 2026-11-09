"""Automate Vast.ai GPU rentals using the provider's published REST contract.

Each operation makes one API request. Paginated reads return one page and the
provider's cursor; lifecycle writes report acknowledgement, not completion.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://console.vast.ai"


class VastAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Vast Ai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://cloud.vast.ai/manage-keys/",
            "x-credential-instructions": "Paste a Vast.ai API key from Manage Keys. Grant only the permissions needed for your operations, including the current-user read used to check the connection. NoClick sends it as a Bearer token to console.vast.ai. Creating instances and renting volumes incurs provider charges; deleting them removes their data.",
        },
    )
    credential_type: Literal["vast_ai_api_key"] = Field("vast_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Vast.ai API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCurrentUser(_Input):
    """Read the authenticated account's profile and balance."""
    operation: Literal["get_current_user"] = "get_current_user"


class ListInstances(_Input):
    """Read one page of your instances; pass data.next_token as after_token."""
    operation: Literal["list_instances"] = "list_instances"
    limit: int = Field(25, ge=1, le=25)
    after_token: str | None = Field(None, min_length=1, max_length=4096, description="The previous response's data.next_token; omit for the first page.")


class _Instance(_Input):
    instance_id: int = Field(..., gt=0, description="Vast.ai instance contract ID.")


class GetInstance(_Instance):
    """Read one instance by contract ID."""
    operation: Literal["get_instance"] = "get_instance"


class CreateInstance(_Input):
    """Accept an offer and create a paid instance."""
    operation: Literal["create_instance"] = "create_instance"
    offer_id: int = Field(..., gt=0, description="Offer ID returned by search_offers.")
    image: str = Field(..., min_length=1, max_length=2048, description="Docker image, for example vastai/base-image:@vastai-automatic-tag.")
    disk: float | None = Field(None, gt=0, allow_inf_nan=False, description="Local disk size in GB; fixed for the lifetime of the instance.")
    label: str | None = Field(None, max_length=1024)
    runtype: Literal["ssh", "jupyter", "args", "ssh_proxy", "ssh_direct", "jupyter_proxy", "jupyter_direct"] | None = None
    target_state: Literal["running", "stopped"] | None = None
    price: float | None = Field(None, ge=0.001, le=128, allow_inf_nan=False, description="Hourly bid for interruptible instances.")
    env: str | None = Field(None, max_length=32768, description="Docker flags for environment variables and port mappings.")
    onstart: str | None = Field(None, max_length=32768)
    cancel_unavail: StrictBool | None = None
    template_hash_id: str | None = Field(None, min_length=1, max_length=256)


class ManageInstance(_Instance):
    """Start, stop or relabel an instance; state changes are asynchronous."""
    operation: Literal["manage_instance"] = "manage_instance"
    state: Literal["running", "stopped"] | None = None
    label: str | None = Field(None, max_length=1024)

    @model_validator(mode="after")
    def change(self):
        if self.state is None and self.label is None:
            raise ValueError("Provide a state or label")
        return self


class DestroyInstance(_Instance):
    """Destroy an instance and its local data permanently."""
    operation: Literal["destroy_instance"] = "destroy_instance"


class RebootInstance(_Instance):
    """Request an instance reboot."""
    operation: Literal["reboot_instance"] = "reboot_instance"


class RecycleInstance(_Instance):
    """Request recycling of an instance container."""
    operation: Literal["recycle_instance"] = "recycle_instance"


class ChangeBid(_Instance):
    """Change an interruptible instance's hourly bid price."""
    operation: Literal["change_bid"] = "change_bid"
    price: float = Field(..., ge=0.001, le=32, allow_inf_nan=False)


class RequestLogs(_Instance):
    """Request a log download URL without downloading the external file."""
    operation: Literal["request_logs"] = "request_logs"
    tail: int = Field(1000, ge=1, le=100000)
    filter: str | None = Field(None, max_length=4096)
    daemon_logs: StrictBool = False


class SearchOffers(_Input):
    """Search a bounded set of GPU offers with documented comparison filters."""
    operation: Literal["search_offers"] = "search_offers"
    limit: int = Field(100, ge=1, le=1000)
    offer_type: Literal["ondemand", "bid", "reserved"] = "ondemand"
    gpu_name: str | None = Field(None, min_length=1, max_length=128, description="Provider model name, for example RTX_4090.")
    min_gpus: int | None = Field(None, ge=1, le=1024)
    min_gpu_ram: int | None = Field(None, ge=1, description="Minimum GPU RAM in MB.")
    max_hourly_price: float | None = Field(None, gt=0, allow_inf_nan=False)
    min_reliability: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    verified: StrictBool = True
    rentable: StrictBool = True


class ListVolumes(_Input):
    """List your rented persistent volumes."""
    operation: Literal["list_volumes"] = "list_volumes"


class SearchVolumes(_Input):
    """Search one bounded set of volume offers."""
    operation: Literal["search_volumes"] = "search_volumes"
    limit: int = Field(64, ge=1, le=1000)


class RentVolume(_Input):
    """Rent a paid persistent volume from a volume offer."""
    operation: Literal["rent_volume"] = "rent_volume"
    volume_offer_id: int = Field(..., gt=0)
    size: int = Field(15, ge=1, description="Size in GB.")


class DeleteVolume(_Input):
    """Delete a rented volume and its stored data."""
    operation: Literal["delete_volume"] = "delete_volume"
    volume_id: int = Field(..., gt=0)


class _BillingPage(_Input):
    start_time: int = Field(..., ge=0, description="Inclusive start, Unix seconds UTC.")
    end_time: int = Field(..., ge=0, description="Inclusive end, Unix seconds UTC.")
    limit: int = Field(100, ge=1, le=500)
    after_token: str | None = Field(None, min_length=1, max_length=4096, description="Previous data.next_token; omit for the first page.")

    @model_validator(mode="after")
    def range(self):
        if self.end_time < self.start_time:
            raise ValueError("End time must be on or after start time")
        return self


class ListInvoices(_BillingPage):
    """Read one page of billing transactions within a date range."""
    operation: Literal["list_invoices"] = "list_invoices"


class ListCharges(_BillingPage):
    """Read one page of per-contract charges within a date range."""
    operation: Literal["list_charges"] = "list_charges"


class ListSshKeys(_Input):
    """List the public SSH keys belonging to your account."""
    operation: Literal["list_ssh_keys"] = "list_ssh_keys"


class _PublicKey(_Input):
    ssh_key: str = Field(..., min_length=1, max_length=16384, description="Public SSH key from your .pub file, never a private key.")

    @field_validator("ssh_key")
    @classmethod
    def public(cls, value):
        if "PRIVATE KEY" in value or not value.startswith(("ssh-", "ecdsa-", "sk-")) or len(value.split()) < 2:
            raise ValueError("Provide an SSH public key from a .pub file")
        return value.strip()


class CreateSshKey(_PublicKey):
    """Add an account SSH key; Vast.ai also adds it to current instances."""
    operation: Literal["create_ssh_key"] = "create_ssh_key"


class DeleteSshKey(_Input):
    """Delete a public SSH key from your account."""
    operation: Literal["delete_ssh_key"] = "delete_ssh_key"
    ssh_key_id: int = Field(..., gt=0)


class AttachSshKey(_PublicKey, _Instance):
    """Attach a public SSH key to one instance."""
    operation: Literal["attach_ssh_key"] = "attach_ssh_key"


class DetachSshKey(_Instance):
    """Detach a public SSH key from one instance by key ID."""
    operation: Literal["detach_ssh_key"] = "detach_ssh_key"
    ssh_key_id: int = Field(..., gt=0)


VastAiOperation = Annotated[Union[
    GetCurrentUser, ListInstances, GetInstance, CreateInstance, ManageInstance,
    DestroyInstance, RebootInstance, RecycleInstance, ChangeBid, RequestLogs,
    SearchOffers, ListVolumes, SearchVolumes, RentVolume, DeleteVolume,
    ListInvoices, ListCharges, ListSshKeys, CreateSshKey, DeleteSshKey,
    AttachSshKey, DetachSshKey,
], Field(discriminator="operation")]


class VastAiConfig(NodeConfig[VastAiOperation, VastAiAPIKeyCredential]):
    pass


# One node operation maps to exactly one operation in Vast.ai OpenAPI 1.0.0.
ROUTES = {
    "get_current_user": ("GET", "/api/v0/users/current"),
    "list_instances": ("GET", "/api/v1/instances"),
    "get_instance": ("GET", "/api/v0/instances/{instance_id}"),
    "create_instance": ("PUT", "/api/v0/asks/{offer_id}"),
    "manage_instance": ("PUT", "/api/v0/instances/{instance_id}"),
    "destroy_instance": ("DELETE", "/api/v0/instances/{instance_id}"),
    "reboot_instance": ("PUT", "/api/v0/instances/reboot/{instance_id}"),
    "recycle_instance": ("PUT", "/api/v0/instances/recycle/{instance_id}"),
    "change_bid": ("PUT", "/api/v0/instances/bid_price/{instance_id}"),
    "request_logs": ("PUT", "/api/v0/instances/request_logs/{instance_id}"),
    "search_offers": ("POST", "/api/v0/bundles"),
    "list_volumes": ("GET", "/api/v0/volumes"),
    "search_volumes": ("POST", "/api/v0/volumes/search"),
    "rent_volume": ("PUT", "/api/v0/volumes"),
    "delete_volume": ("DELETE", "/api/v0/volumes"),
    "list_invoices": ("GET", "/api/v1/invoices"),
    "list_charges": ("GET", "/api/v0/charges"),
    "list_ssh_keys": ("GET", "/api/v0/ssh"),
    "create_ssh_key": ("POST", "/api/v0/ssh"),
    "delete_ssh_key": ("DELETE", "/api/v0/ssh/{ssh_key_id}"),
    "attach_ssh_key": ("POST", "/api/v0/instances/{instance_id}/ssh"),
    "detach_ssh_key": ("DELETE", "/api/v0/instances/{instance_id}/ssh/{ssh_key_id}"),
}


def _request(op):
    """Build only the parameters documented for the selected operation."""
    action = op.operation
    values = op.model_dump(exclude_none=True, exclude={"operation"})
    method, template = ROUTES[action]
    path = template.format(**values)
    params, body = {}, None
    if action in {"list_instances", "list_invoices", "list_charges"}:
        params = {k: values[k] for k in ("limit", "after_token") if k in values}
        if action != "list_instances":
            key = "when" if action == "list_invoices" else "day"
            params["select_filters"] = json.dumps({key: {"gte": op.start_time, "lte": op.end_time}})
    elif action == "search_offers":
        body = {"limit": op.limit, "type": op.offer_type, "verified": {"eq": op.verified}, "rentable": {"eq": op.rentable}}
        for source, target, comparison in (
            ("gpu_name", "gpu_name", "eq"), ("min_gpus", "num_gpus", "gte"),
            ("min_gpu_ram", "gpu_ram", "gte"), ("max_hourly_price", "dph_total", "lte"),
            ("min_reliability", "reliability", "gte"),
        ):
            if source in values:
                body[target] = {comparison: values[source]}
    elif action == "search_volumes":
        body = {"limit": op.limit}
    elif action in {"create_instance", "manage_instance", "create_ssh_key", "attach_ssh_key"}:
        body = {k: v for k, v in values.items() if k not in {"offer_id", "instance_id"}}
    elif action == "change_bid":
        body = {"client_id": "me", "price": op.price}
    elif action == "request_logs":
        body = {"tail": str(op.tail)}
        if op.filter is not None:
            body["filter"] = op.filter
        if op.daemon_logs:
            body["daemon_logs"] = "true"
    elif action == "rent_volume":
        body = {"id": op.volume_offer_id, "size": op.size}
    elif action == "delete_volume":
        body = {"id": op.volume_id}
    return method, path, params, body


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class VastAiNode(WorkflowNode):
    integration_type = "automation-vast-ai"
    connection_evidence = ConnectionEvidence(
        noun="account", identity_operation="get_current_user", identity_keys=("email", "id"),
    )
    edit_examples = ["Find available RTX 4090 GPUs", "Stop my training instance", "List this month's GPU charges"]

    @classmethod
    def get_config_model(cls):
        return VastAiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Vast.ai API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path, params, body = _request(op)
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
                response = await client.request(
                    method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
                )
        except httpx.HTTPError:
            raise ValueError("Vast.ai request could not be completed; inspect the provider before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Vast.ai returned HTTP {response.status_code} without a JSON response") from None
        data = _redact(data, secret)
        if not 200 <= response.status_code < 300 or (isinstance(data, dict) and (data.get("success") is False or data.get("error"))):
            message = (data.get("msg") or data.get("error") or data.get("detail")) if isinstance(data, dict) else None
            raise ValueError(f"Vast.ai HTTP {response.status_code}: {str(message or 'request rejected')[:1000]}")
        if not isinstance(data, (dict, list)):
            raise ValueError("Vast.ai returned an unexpected JSON response")
        if op.operation == "get_current_user":
            if not isinstance(data, dict) or not isinstance(data.get("id"), int) or isinstance(data.get("id"), bool) or not data.get("email"):
                raise ValueError("Vast.ai did not return a recognisable account profile")
        elif op.operation == "list_ssh_keys":
            if not isinstance(data, list):
                raise ValueError("Vast.ai did not return an SSH key list")
        elif op.operation in {"list_instances", "list_volumes", "search_volumes", "list_invoices", "list_charges"}:
            key = {"list_instances": "instances", "list_volumes": "volumes", "search_volumes": "offers"}.get(op.operation, "results")
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ValueError("Vast.ai did not return the documented list envelope")
        elif op.operation == "get_instance":
            if not isinstance(data, dict) or not isinstance(data.get("instances"), dict):
                raise ValueError("Vast.ai did not return the documented instance envelope")
        output = {"status": "success", "action": op.operation, "data": data}
        await self.emit(output)
        return output
