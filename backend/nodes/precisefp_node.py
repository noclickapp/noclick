"""PreciseFP account, professional-contact and financial profile operations.

Each operation sends exactly one documented REST request. Production endpoints
and OAuth scopes follow https://app.precisefp.com/docs/api/ rather than its stale Swagger hosts.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.precisefp import PRECISEFP_SCOPES
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://four.precisefp.com/api"
Identifier = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=4096)]


class PreciseFPOAuthCredential(BaseModel):
    model_config = ConfigDict(title="PreciseFP Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "precisefp",
            "x-oauth-scopes": PRECISEFP_SCOPES.declared_scopes(),
            "x-credential-url": "https://app.precisefp.com/docs/api/#authentication",
            "x-credential-instructions": "Connect your PreciseFP account. PreciseFP must register the application's client ID, client secret and callback URL first; contact PreciseFP to request API access. The connection check reads your user profile and does not prove write access.",
        })
    credential_type: Literal["precisefp_oauth"] = Field("precisefp_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh token", max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token expiry")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None: return None
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "credentialIds" and not k.endswith("__label")}
        return value


class _Account(_Input):
    account_id: Identifier = Field(..., title="Account ID")


class _Contact(_Account):
    contact_id: Text = Field(..., title="Contact ID")

    @field_validator("contact_id")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
            raise ValueError("Use a single PreciseFP contact ID")
        return value


class _Member(_Input):
    first_name: Text
    last_name: Text
    email: Text
    phone: Optional[Text] = None


class _AccountBody(_Input):
    type: Literal["clients", "prospects"] = Field(..., title="Account type")
    client: _Member
    coclient: Optional[_Member] = None


class _ContactBody(_Input):
    type: Literal["accountant", "attorney", "broker", "insurance-agent", "tax-preparer", "other"]
    first_name: Text
    last_name: Text
    company: Optional[Text] = None
    email: Optional[Text] = None
    phone: Optional[Text] = None


class PreciseFPGetCurrentUser(_Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class PreciseFPListAccounts(_Input):
    """List accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})
    type: Optional[Literal["clients", "prospects"]] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class PreciseFPGetAccount(_Account):
    """Get account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class PreciseFPCreateAccount(_AccountBody):
    """Create account."""
    operation: Literal["create_account"] = Field("create_account", json_schema_extra={"ui:hidden": True})


class PreciseFPUpdateAccount(_Account, _AccountBody):
    """Update account."""
    operation: Literal["update_account"] = Field("update_account", json_schema_extra={"ui:hidden": True})


class PreciseFPDeleteAccount(_Account):
    """Delete account."""
    operation: Literal["delete_account"] = Field("delete_account", json_schema_extra={"ui:hidden": True})


class PreciseFPGetAccountMember(_Account):
    """Get account member."""
    operation: Literal["get_account_member"] = Field("get_account_member", json_schema_extra={"ui:hidden": True})
    client: Literal["client", "coclient"] = Field("client", title="Account member")


class PreciseFPListContacts(_Account):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class PreciseFPGetContact(_Contact):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class PreciseFPCreateContact(_Account, _ContactBody):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})


class PreciseFPUpdateContact(_Contact, _ContactBody):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})


class PreciseFPDeleteContact(_Contact):
    """Delete contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class PreciseFPListAssets(_Account):
    """List assets."""
    operation: Literal["list_assets"] = Field("list_assets", json_schema_extra={"ui:hidden": True})


class PreciseFPListLiabilities(_Account):
    """List liabilities."""
    operation: Literal["list_liabilities"] = Field("list_liabilities", json_schema_extra={"ui:hidden": True})


class PreciseFPListGoals(_Account):
    """List goals."""
    operation: Literal["list_goals"] = Field("list_goals", json_schema_extra={"ui:hidden": True})


class PreciseFPListFamily(_Account):
    """List family."""
    operation: Literal["list_family"] = Field("list_family", json_schema_extra={"ui:hidden": True})


class PreciseFPListInsurance(_Account):
    """List insurance."""
    operation: Literal["list_insurance"] = Field("list_insurance", json_schema_extra={"ui:hidden": True})


class PreciseFPListDocuments(_Account):
    """List documents."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})


PreciseFPOperation = Annotated[Union[PreciseFPGetCurrentUser, PreciseFPListAccounts, PreciseFPGetAccount, PreciseFPCreateAccount, PreciseFPUpdateAccount, PreciseFPDeleteAccount, PreciseFPGetAccountMember, PreciseFPListContacts, PreciseFPGetContact, PreciseFPCreateContact, PreciseFPUpdateContact, PreciseFPDeleteContact, PreciseFPListAssets, PreciseFPListLiabilities, PreciseFPListGoals, PreciseFPListFamily, PreciseFPListInsurance, PreciseFPListDocuments], Field(discriminator="operation")]


class PreciseFPConfig(NodeConfig[PreciseFPOperation, PreciseFPOAuthCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {'get_current_user': ('GET', '/user'), 'list_accounts': ('GET', '/accounts'), 'get_account': ('GET', '/accounts/{account_id}'), 'create_account': ('POST', '/accounts'), 'update_account': ('PUT', '/accounts/{account_id}'), 'delete_account': ('DELETE', '/accounts/{account_id}'), 'get_account_member': ('GET', '/accounts/{account_id}/{client}/details'), 'list_contacts': ('GET', '/accounts/{account_id}/contacts'), 'get_contact': ('GET', '/accounts/{account_id}/contacts/{contact_id}'), 'create_contact': ('POST', '/accounts/{account_id}/contacts'), 'update_contact': ('PUT', '/accounts/{account_id}/contacts/{contact_id}'), 'delete_contact': ('DELETE', '/accounts/{account_id}/contacts/{contact_id}'), 'list_assets': ('GET', '/accounts/{account_id}/assets'), 'list_liabilities': ('GET', '/accounts/{account_id}/liabilities'), 'list_goals': ('GET', '/accounts/{account_id}/goals'), 'list_family': ('GET', '/accounts/{account_id}/family'), 'list_insurance': ('GET', '/accounts/{account_id}/insurance'), 'list_documents': ('GET', '/accounts/{account_id}/documents')}


def _redact(value, secrets):
    if isinstance(value, dict): return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list): return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret: value = value.replace(secret, "[redacted]")
    return value


class PreciseFPNode(WorkflowNode):
    integration_type = "automation-precisefp"
    scope_registry = PRECISEFP_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_current_user", noun="PreciseFP account")

    @classmethod
    def get_config_model(cls):
        return PreciseFPConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.precisefp_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="precisefp")

    @staticmethod
    def _request_parts(op):
        method, path = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        return method, path, values if op.operation == "list_accounts" else {}, values if method in {"POST", "PUT"} else None

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a PreciseFP account")
        op, credential = self.config.config, self.config.credentials
        method, path, params, body = self._request_parts(op)
        writing = method != "GET"
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.precisefp_oauth import refresh_access_token
        raw = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=raw, refresh=refresh_access_token, provider="precisefp", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in raw: setattr(credential, key, raw[key])
        secrets = (token, credential.access_token, credential.refresh_token)
        output = {"operation": op.operation}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                message = "PreciseFP rejected the request"
                try:
                    error = response.json()
                    if isinstance(error, dict): message = error.get("messages") or error.get("message") or error.get("error") or message
                except ValueError: pass
                return _redact({**output, "status": "error", "http_status": response.status_code, "error": message,
                    "write_outcome": "unverified" if writing and response.status_code >= 500 else None}, secrets)
            output.update(status="success", http_status=response.status_code)
            if response.status_code == 204:
                if method != "DELETE": raise ValueError("Expected a PreciseFP JSON response")
                return {**output, "write_acknowledged": True}
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected bounded JSON from PreciseFP")
            payload = response.json()
            if not isinstance(payload, (dict, list)) or isinstance(payload, dict) and (payload.get("status") == "error" or "error" in payload or "errors" in payload):
                raise ValueError("Unexpected PreciseFP response")
            if op.operation.startswith("list_"):
                items = payload if isinstance(payload, list) else payload.get("items")
                if op.operation == "list_family" and isinstance(items, dict) and items.get("id"):
                    # The published family example wraps a single member in items.
                    items = [items]
                if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                    raise ValueError("Expected a PreciseFP items list")
                output.update(data=payload, items=items)
                if op.operation == "list_accounts" and isinstance(payload, dict):
                    # Only /accounts documents pagination inputs. Never silently fetch all pages.
                    total = payload.get("total")
                    next_offset = op.offset + len(items)
                    output["next_offset"] = next_offset if type(total) is int and next_offset < total and items else None
            else:
                if not isinstance(payload, dict): raise ValueError("Expected a PreciseFP object")
                if op.operation == "get_current_user" and not payload.get("email"):
                    raise ValueError("PreciseFP did not identify the current user")
                output["data"] = payload
            if writing: output["write_acknowledged"] = True
            return _redact(output, secrets)
        except (ValueError, SSRFError, httpx.HTTPError):
            return {**output, "status": "error", "error": "PreciseFP returned an incomplete or invalid response",
                "write_outcome": "unverified" if writing else None}
