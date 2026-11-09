"""ProxiedMail aliases and received mail, using a user-supplied API token.

Contract: https://proxiedmail.com/api/v1/api-docs.yaml (1.0.0).
The endpoint docs specify object write payloads, despite the spec's array typo:
https://docs.proxiedmail.com/docs/endpoints/postproxybindings/
https://docs.proxiedmail.com/docs/endpoints/patchproxybindings/
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://proxiedmail.com/api/v1"


class ProxiedmailAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Proxiedmail API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://proxiedmail.com/en/settings",
            "x-credential-instructions": "Paste your API token from ProxiedMail Settings. NoClick sends it in the Token header. Use the API token, not an expiring login bearer token.",
        })
    credential_type: Literal["proxiedmail_api_token"] = Field("proxiedmail_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListProxyBindings(Input):
    """List the account's proxy email addresses and usage metadata."""
    operation: Literal["list_proxy_bindings"] = "list_proxy_bindings"


class Binding(Input):
    proxy_binding_id: str = Field(..., min_length=1, max_length=256, description="Proxy-binding ID returned by List Proxy Bindings.")

    @field_validator("proxy_binding_id")
    @classmethod
    def identifier(cls, value):
        if any(ord(c) < 33 for c in value) or value in {".", ".."} or any(c in value for c in "/\\?#"):
            raise ValueError("Use a single proxy-binding ID")
        return value


def _email(value):
    if not isinstance(value, str) or len(value) > 320 or value.count("@") != 1 or any(c.isspace() for c in value):
        raise ValueError("Use an email address")
    if not all(value.split("@")):
        raise ValueError("Use an email address")
    return value


def _callback(value):
    if value is None or value == "":
        return value
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Use an HTTPS callback URL")
    return value


class CreateProxyBinding(Input):
    """Create an alias forwarding to the supplied real email addresses."""
    operation: Literal["create_proxy_binding"] = "create_proxy_binding"
    proxy_address: str = Field(..., description="Alias email address to create.")
    real_addresses: list[str] = Field(..., min_length=1, max_length=100, description="Forwarding destinations. Creation may send provider verification emails.")
    callback_url: str | None = Field(None, max_length=2048, description="URL to receive incoming-email webhooks.")
    is_browsable: StrictBool = Field(True, description="Store received email for API browsing.")

    @field_validator("proxy_address")
    @classmethod
    def email(cls, value): return _email(value)

    @field_validator("real_addresses")
    @classmethod
    def addresses(cls, values): return [_email(v) for v in values]

    @field_validator("callback_url")
    @classmethod
    def callback(cls, value): return _callback(value)


class UpdateProxyBinding(Binding):
    """Change selected alias settings; omitted fields are preserved."""
    operation: Literal["update_proxy_binding"] = "update_proxy_binding"
    proxy_address: str | None = None
    real_addresses: dict[str, StrictBool] | None = Field(None, description="Destination email to enabled flag; replaces the forwarding map.")
    description: str | None = Field(None, max_length=10000)
    callback_url: str | None = Field(None, max_length=2048)
    is_browsable: StrictBool | None = None

    @field_validator("proxy_address")
    @classmethod
    def email(cls, value): return _email(value) if value is not None else value

    @field_validator("real_addresses")
    @classmethod
    def addresses(cls, value):
        if value is not None:
            if len(value) > 100: raise ValueError("Use at most 100 destinations")
            for key in value: _email(key)
        return value

    @field_validator("callback_url")
    @classmethod
    def callback(cls, value): return _callback(value)

    @model_validator(mode="after")
    def changes(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "proxy_binding_id"}):
            raise ValueError("Provide at least one alias setting to update")
        return self


class SetForwardingAddresses(Binding):
    """Replace the forwarding destinations and their enabled flags."""
    operation: Literal["set_forwarding_addresses"] = "set_forwarding_addresses"
    real_addresses: dict[str, StrictBool] = Field(..., min_length=1, max_length=100)
    _addresses = field_validator("real_addresses")(UpdateProxyBinding.addresses.__func__)


class SetCallbackURL(Binding):
    """Set the URL receiving incoming-email webhooks."""
    operation: Literal["set_callback_url"] = "set_callback_url"
    callback_url: str = Field(..., min_length=1, max_length=2048)
    _callback = field_validator("callback_url")(UpdateProxyBinding.callback.__func__)


class EnableEmailBrowsing(Binding):
    """Enable browsing received email through the API."""
    operation: Literal["enable_email_browsing"] = "enable_email_browsing"


class DisableEmailBrowsing(Binding):
    """Disable API browsing of received mail for this alias."""
    operation: Literal["disable_email_browsing"] = "disable_email_browsing"


class ListReceivedEmailLinks(Binding):
    """Read the last 55 received messages for a browsable alias."""
    operation: Literal["list_received_email_links"] = "list_received_email_links"


class GetReceivedEmail(Input):
    """Read one received message's payload and attachment links."""
    operation: Literal["get_received_email"] = "get_received_email"
    received_email_id: str = Field(..., min_length=1, max_length=256)
    _id = field_validator("received_email_id")(Binding.identifier.__func__)


class GetCallback(Input):
    """Read the payload captured by an existing webhook receiver hash."""
    operation: Literal["get_callback"] = "get_callback"
    callback_hash: str = Field(..., min_length=1, max_length=256)
    _id = field_validator("callback_hash")(Binding.identifier.__func__)


Operation = Annotated[Union[ListProxyBindings, CreateProxyBinding, UpdateProxyBinding,
    SetForwardingAddresses, SetCallbackURL, EnableEmailBrowsing, DisableEmailBrowsing,
    ListReceivedEmailLinks, GetReceivedEmail, GetCallback], Field(discriminator="operation")]


class ProxiedmailConfig(NodeConfig[Operation, ProxiedmailAPITokenCredential]):
    pass


class ProxiedmailNode(WorkflowNode):
    integration_type = "automation-proxiedmail"
    connection_evidence = ConnectionEvidence(operation="list_proxy_bindings", noun="proxy email addresses", label_keys=("proxy_address", "id"))

    @classmethod
    def get_config_model(cls):
        return ProxiedmailConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a ProxiedMail API token")
        op = self.config.config
        method, path, payload = "GET", "/proxy-bindings", None
        if isinstance(op, CreateProxyBinding):
            method = "POST"
            payload = {"data": {"type": "proxy_bindings", "attributes": op.model_dump(exclude={"operation"}, exclude_none=True)}}
        elif isinstance(op, (UpdateProxyBinding, SetForwardingAddresses, SetCallbackURL, EnableEmailBrowsing, DisableEmailBrowsing)):
            method, path = "PATCH", "/proxy-bindings/" + quote(op.proxy_binding_id, safe="")
            attrs = op.model_dump(exclude={"operation", "proxy_binding_id"}, exclude_none=True)
            if isinstance(op, (EnableEmailBrowsing, DisableEmailBrowsing)):
                attrs["is_browsable"] = isinstance(op, EnableEmailBrowsing)
            payload = {"data": {"id": op.proxy_binding_id, "type": "proxy_bindings", "attributes": attrs}}
        elif isinstance(op, ListReceivedEmailLinks):
            path = "/received-emails-links/" + quote(op.proxy_binding_id, safe="")
        elif isinstance(op, GetReceivedEmail):
            path = "/received-emails/" + quote(op.received_email_id, safe="")
        elif isinstance(op, GetCallback):
            path = "/callback/get/" + quote(op.callback_hash, safe="")
        token = self.config.credentials.api_token
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Token": token, "Accept": "application/json"}, **({"json": payload} if payload is not None else {}))
        except httpx.HTTPError:
            raise ValueError("ProxiedMail request could not be completed; inspect write outcomes before retrying") from None
        if response.status_code < 200 or response.status_code >= 300:
            # Keep the provider's rejection text for the shared connection seam.
            message = response.text[:2000].replace(token, "[redacted]")
            result = {"status": "error", "success": False, "http_status": response.status_code, "error": message}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("ProxiedMail response exceeds 10 MB")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("ProxiedMail did not return JSON") from None
            if not isinstance(body, (dict, list)):
                raise ValueError("ProxiedMail returned an unexpected JSON envelope")
            if isinstance(body, dict) and ("errors" in body or "error" in body):
                result = {"status": "error", "success": False, "http_status": response.status_code, "error": _redact(body, token)}
            else:
                if isinstance(op, ListProxyBindings) and (not isinstance(body, dict) or not isinstance(body.get("data"), list)):
                    raise ValueError("ProxiedMail proxy list is missing its data array")
                result = {"status": "success", "success": True, "http_status": response.status_code, "data": _redact(body, token)}
                if isinstance(op, ListProxyBindings) and isinstance(body, dict):
                    result["items"] = [{"id": row.get("id"), **row.get("attributes", {})} for row in body.get("data", []) if isinstance(row, dict) and isinstance(row.get("attributes", {}), dict)]
                    result["items"] = _redact(result["items"], token)
        await self.emit(result)
        return result


def _redact(value, token):
    if isinstance(value, str): return value.replace(token, "[redacted]")
    if isinstance(value, list): return [_redact(v, token) for v in value]
    if isinstance(value, dict): return {k.replace(token, "[redacted]"): _redact(v, token) for k, v in value.items()}
    return value
