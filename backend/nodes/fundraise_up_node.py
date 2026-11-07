"""Native Fundraise Up metadata and designation operations.

The saved key, explicit data mode and local account fence are reloaded from the
current authoritative row; no donation, payment or publishing route is exposed.
"""
from __future__ import annotations
import json
import re
from contextvars import ContextVar
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-fundraise-up"
FAMILY = "fundraise_up_api_key"
ROOT = "https://api.fundraiseup.com"
_MISSING = object()
_REQUEST_CONTEXT: ContextVar[Optional[tuple]] = ContextVar("fundraise_up_request", default=None)
WRITES = frozenset({"create_designation", "update_designation", "delete_designation"})
KINDS = ("supporters", "campaigns", "fundraisers", "designations")
PREFIXES = {"supporters": "S", "campaigns": "FUN", "fundraisers": "N", "designations": "E"}


def _id(value, kind):
    # Path examples and descriptions disagree on lengths; preserve opaque IDs.
    if not isinstance(value, str) or not re.fullmatch(PREFIXES[kind] + r"[A-Z0-9]{1,61}", value):
        raise ValueError("Use the resource's Fundraise Up ID")
    return value


def _account(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{8}", value):
        raise ValueError("Use the eight-character Fundraise Up account ID")
    return value


def _picker(field):
    return {"x-dynamic-options": {"field_name": field, "placeholder": "Choose resource", "searchable": False,
        "allow_custom": True, "custom_placeholder": "Paste Fundraise Up ID"}}


class FundraiseUpAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Fundraise Up API Key",
        json_schema_extra={"x-credential-url": "https://dashboard.fundraiseup.com/settings/api-keys",
            "x-credential-instructions": "Use an organization-admin-issued Bearer API key. Choose test or live explicitly; permissions are independent and NoClick never switches modes. Campaigns, fundraisers and designations exist only in live mode. Select a permitted read resource for connection checking. Account ID is a local output fence, not an account identity claim. Keys do not expire; old keys created before January 30, 2026 were scheduled for deactivation six months later. No token mint or refresh."})
    credential_type: Literal["fundraise_up_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    livemode: bool = Field(..., title="Live data", description="Required: false for test supporter data; true for live data. No fallback.")
    account_id: str = Field(..., title="Account ID", description="Eight-character account ID used to fence returned metadata. Parent keys may read subaccounts.")
    check_resource: Literal["supporters", "campaigns", "fundraisers", "designations"] = Field("supporters", title="Connection read resource", description="Choose a resource the key has Read permission for in this mode.")

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the issued API key")
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key alone, without the Bearer header")
        return value

    @field_validator("livemode", mode="before")
    @classmethod
    def explicit_mode(cls, value):
        if type(value) is not bool:
            raise ValueError("Choose test or live explicitly")
        return value

    @field_validator("account_id", mode="before")
    @classmethod
    def account(cls, value):
        return _account(value)

    @model_validator(mode="after")
    def mode_resource(self):
        if not self.livemode and self.check_resource != "supporters":
            raise ValueError("Only supporter reads support test mode in this node")
        return self


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    limit: int = Field(10, ge=1, le=100, description="One bounded page; API order is newest first.")
    starting_after: Optional[str] = Field(None, max_length=64, description="Last ID of the previous older-record page.")
    ending_before: Optional[str] = Field(None, max_length=64, description="First ID for a newer-record page; exclusive with starting_after.")

    @field_validator("limit", mode="before")
    @classmethod
    def strict_limit(cls, value):
        if type(value) is not int:
            raise ValueError("Limit must be an integer")
        return value

    @model_validator(mode="after")
    def cursors(self):
        kind = self.operation.removeprefix("list_")
        if self.starting_after is not None and self.ending_before is not None:
            raise ValueError("Choose only one pagination direction")
        for value in (self.starting_after, self.ending_before):
            if value is not None:
                _id(value, kind)
        return self


class FundraiseUpCheckConfig(_Input):
    """Check the chosen mode/resource permission without claiming identity."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class FundraiseUpListSupportersConfig(_List):
    """List supporter IDs and creation metadata; contact data is opt-in."""
    operation: Literal["list_supporters"] = Field("list_supporters", json_schema_extra={"ui:hidden": True})
    include_contact: bool = Field(False, description="Include name/email/phone only when the workflow needs it. Address/employer/occupation are never returned.")


class FundraiseUpGetSupporterConfig(_Input):
    """Read an account-fenced supporter, optionally including basic contact fields."""
    operation: Literal["get_supporter"] = Field("get_supporter", json_schema_extra={"ui:hidden": True})
    supporter_id: str = Field(..., json_schema_extra=_picker("supporter_id"))
    include_contact: bool = False

    @field_validator("supporter_id", mode="before")
    @classmethod
    def identifier(cls, value): return _id(value, "supporters")


class FundraiseUpListCampaignsConfig(_List):
    """List base campaign metadata in live mode."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class FundraiseUpGetCampaignConfig(_Input):
    """Read base campaign name/status without modifying assignments."""
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: str = Field(..., json_schema_extra=_picker("campaign_id"))
    @field_validator("campaign_id", mode="before")
    @classmethod
    def identifier(cls, value): return _id(value, "campaigns")


class FundraiseUpListFundraisersConfig(_List):
    """Read fundraiser metadata; verify each campaign's account before output."""
    operation: Literal["list_fundraisers"] = Field("list_fundraisers", json_schema_extra={"ui:hidden": True})


class FundraiseUpGetFundraiserConfig(_Input):
    """Read a fundraiser with its campaign's current account fence."""
    operation: Literal["get_fundraiser"] = Field("get_fundraiser", json_schema_extra={"ui:hidden": True})
    fundraiser_id: str = Field(..., json_schema_extra=_picker("fundraiser_id"))
    @field_validator("fundraiser_id", mode="before")
    @classmethod
    def identifier(cls, value): return _id(value, "fundraisers")


class FundraiseUpListDesignationsConfig(_List):
    """List allocation metadata, including inherited entries only if they match the saved account."""
    operation: Literal["list_designations"] = Field("list_designations", json_schema_extra={"ui:hidden": True})


class FundraiseUpGetDesignationConfig(_Input):
    """Read a designation's account, name, code and default status."""
    operation: Literal["get_designation"] = Field("get_designation", json_schema_extra={"ui:hidden": True})
    designation_id: str = Field(..., json_schema_extra=_picker("designation_id"))
    @field_validator("designation_id", mode="before")
    @classmethod
    def identifier(cls, value): return _id(value, "designations")


class FundraiseUpCreateDesignationConfig(_Input):
    """Create ordinary allocation metadata in the API key's account, with no campaign assignment."""
    operation: Literal["create_designation"] = Field("create_designation", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500, description="Local 500-character bound; provider validates its current constraints.")
    code: Optional[str] = Field(None, max_length=500)


class FundraiseUpUpdateDesignationConfig(FundraiseUpGetDesignationConfig):
    """POST a partial name/code update; omitted fields retain their current values."""
    operation: Literal["update_designation"] = Field("update_designation", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    code: Optional[str] = Field(None, max_length=500, description="Set clear_code to remove a code; omission preserves it.")
    clear_code: bool = False

    @model_validator(mode="after")
    def changes(self):
        if self.clear_code and self.code is not None:
            raise ValueError("Use either a code or clear_code")
        if self.name is None and self.code is None and not self.clear_code:
            raise ValueError("Change at least one field")
        return self


class FundraiseUpDeleteDesignationConfig(FundraiseUpGetDesignationConfig):
    """Delete a non-default designation after checking its current account."""
    operation: Literal["delete_designation"] = Field("delete_designation", json_schema_extra={"ui:hidden": True})


FundraiseUpConfig = Annotated[Union[
    FundraiseUpCheckConfig, FundraiseUpListSupportersConfig, FundraiseUpGetSupporterConfig,
    FundraiseUpListCampaignsConfig, FundraiseUpGetCampaignConfig, FundraiseUpListFundraisersConfig,
    FundraiseUpGetFundraiserConfig, FundraiseUpListDesignationsConfig, FundraiseUpGetDesignationConfig,
    FundraiseUpCreateDesignationConfig, FundraiseUpUpdateDesignationConfig, FundraiseUpDeleteDesignationConfig,
], Field(discriminator="operation")]


class FundraiseUpFullConfig(NodeConfig[FundraiseUpConfig, FundraiseUpAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _credential_id(data):
    ids = []
    selected = data.get("credential_id")
    if selected is not None and selected != "":
        ids.append(selected)
    for scope in (data, data.get("config", {})):
        mapping = scope.get("credentialIds", {}) if isinstance(scope, dict) else {}
        if not isinstance(mapping, dict):
            raise ValueError("Credential attachment is invalid")
        for family, value in mapping.items():
            if family == "credential_type":
                continue
            if value is not None and value != "":
                if family != FAMILY:
                    raise ValueError("Attach only a Fundraise Up credential")
                ids.append(value)
    if not ids:
        return None
    if any(not isinstance(value, str) or "{{" in value for value in ids) or len(set(ids)) != 1:
        raise ValueError("Choose one saved Fundraise Up credential")
    try:
        UUID(ids[0])
    except ValueError:
        raise ValueError("Credential attachment is invalid") from None
    return ids[0]


def _guard(data):
    cid = _credential_id(data)
    raw = data.get("credentials")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("Fundraise Up credential data is invalid")
    tag = raw.get("credential_type", _MISSING)
    if tag is not _MISSING and tag != FAMILY:
        raise ValueError("This credential is not a Fundraise Up API key")
    if cid and tag is _MISSING:
        raise ValueError("Saved Fundraise Up credentials require their original family")


def _native_config_view(data):
    if not isinstance(data.get("config"), dict):
        return data
    labels = {"credentialIds", "supporter_id__label", "campaign_id__label", "fundraiser_id__label", "designation_id__label"}
    return {**data, "config": {k: v for k, v in data["config"].items() if k not in labels}}


class _ResponseError(ValueError):
    def __init__(self, status, code=None):
        self.status, self.code = status, code
        super().__init__("Fundraise Up request was not confirmed")


class FundraiseUpNode(WorkflowNode):
    integration_type = "automation-fundraise-up"
    connection_evidence = ConnectionEvidence(noun="Fundraise Up resource access", operation="check_connection", proves="reachability")
    workflow_credential_refresh = True

    @classmethod
    def get_config_model(cls):
        return FundraiseUpFullConfig

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(_native_config_view(config_data))

    @classmethod
    def parse_config(cls, config_data):
        _guard(config_data)
        return super().parse_config(_native_config_view(config_data))

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Non-expiring API keys use staging's current credential loader."""
        _guard({"credentials": credential_data})
        return FundraiseUpAPIKeyCredential.model_validate(credential_data).model_dump()

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        kinds = {"supporter_id": "supporters", "campaign_id": "campaigns", "fundraiser_id": "fundraisers", "designation_id": "designations"}
        if field_name not in kinds or search:
            raise ValueError("This picker uses cursor pages without a server search filter")
        kind = kinds[field_name]
        if page_token is not None:
            _id(page_token, kind)
        from nodes.core.registry import NodeFactory
        instance = NodeFactory.create_node(node_id="fundraise-up-options", node_type=NODE_TYPE,
            node_data={"credentials": credential_data, "config": {"operation": "list_" + kind, "starting_after": page_token}})
        result = await instance.run({})
        if result.get("status") != "success":
            raise ValueError("Fundraise Up choices were not completed; check mode and access")
        return {"options": [{"value": item["id"], "label": item.get("name") or item["id"]} for item in result["items"]],
            "next_page_token": result["next_starting_after"]}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        from nodes.core.registry import NodeFactory
        instance = NodeFactory.create_node(node_id="fundraise-up-access", node_type=NODE_TYPE,
            node_data={"credentials": credential_data, "config": {"operation": "check_connection"}})
        result = await instance.run({})
        if result.get("status") == "success":
            return {"valid": True, "proves": "reachability", "account_identity_verified": False}
        return {"valid": False if result.get("http_status") in (401, 403) else None,
            "error": result.get("error", "Fundraise Up access remains unverified")}

    async def _current(self):
        _guard(self.node_data)
        cid = _credential_id(self.node_data)
        if cid is None:
            if not self.config or not self.config.credentials:
                raise ValueError("Supply a Fundraise Up credential")
            return None, self.config.credentials
        from utils.database_pool import get_native_pool
        from utils.credentials import resolve_credential_with_owner_fallback
        authority = dict(credential_id=cid, user_id=self.user_id,
            pool=self.node_data.get("_approval_pool") or get_native_pool(),
            org_id=self.organization_id, workflow_id=self.workflow_id)
        raw = await resolve_credential_with_owner_fallback(**authority)
        if raw is None:
            raise ValueError("Fundraise Up credential is unavailable or access denied")
        _guard({"credentials": raw, "credential_id": cid})
        return authority, FundraiseUpAPIKeyCredential.model_validate(raw)

    async def _revalidate(self, authority):
        from utils.credentials import resolve_credential_with_owner_fallback
        current = await resolve_credential_with_owner_fallback(**authority)
        ticket = _REQUEST_CONTEXT.get()
        if current is None or ticket is None:
            raise ValueError("Fundraise Up credential is unavailable or access denied")
        _guard({"credentials": current, "credential_id": authority["credential_id"]})
        if FundraiseUpAPIKeyCredential.model_validate(current) != ticket[2]:
            raise ValueError("Fundraise Up credential changed; retry with current configuration")

    async def execute(self, inputs):
        context, credential = await self._current()
        if context is not None:
            self.node_data["credential_id"] = context["credential_id"]
        token = _REQUEST_CONTEXT.set((self, context, credential))
        try:
            result = await self._execute(inputs)
            if context is not None:
                await self._revalidate(context)
            return result
        finally:
            _REQUEST_CONTEXT.reset(token)

    async def _request(self, method, path, *, params=None, payload=None):
        ticket = _REQUEST_CONTEXT.get()
        if ticket is None or ticket[0] is not self:
            raise ValueError("Native request admission required")
        _, context, credential = ticket
        if context is not None: await self._revalidate(context)
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if payload is not None:
            if len(json.dumps(payload).encode()) > 100_000:
                raise ValueError("Designation request exceeds this node's bound")
            headers["Content-Type"] = "application/json"
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, ROOT + path, headers=headers, params=params, json=payload)
        if context is not None: await self._revalidate(context)
        if response.status_code != 200:
            code = None
            if len(response.content) <= 2_000_000:
                try:
                    body = response.json()
                    error = body.get("error", body) if isinstance(body, dict) else {}
                    supplied = error.get("code") if isinstance(error, dict) else None
                    known = {"tokens_rate_limit_exceeded", "requests_rate_limit_exceeded", "concurrent_requests_limit_exceeded", "not_found", "update_conflict", "parameter_unexpected", "parameter_required", "parameter_invalid"}
                    if isinstance(supplied, str) and supplied in known: code = supplied
                except ValueError: pass
            raise _ResponseError(response.status_code, code)
        if len(response.content) > 2_000_000 or "application/json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Expected bounded JSON from Fundraise Up")
        body = response.json()
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Unexpected response or provider error")
        return body

    @staticmethod
    def _mode(credential, kind):
        if kind != "supporters" and not credential.livemode:
            raise ValueError("This resource exists only in live mode; no automatic fallback")
        return {"livemode": "true" if credential.livemode else "false"}

    async def _record(self, raw, kind, credential, *, include_contact=False):
        if not isinstance(raw, dict): raise ValueError("Resource response is invalid")
        identifier = _id(raw.get("id"), kind)
        account = raw.get("account")
        result = {"id": identifier}
        if kind == "fundraisers":
            campaign = raw.get("campaign")
            if not isinstance(campaign, dict): raise ValueError("Fundraiser campaign is missing")
            cid = _id(campaign.get("id"), "campaigns")
            parent = await self._request("GET", "/v1/campaigns/" + cid, params=self._mode(credential, "campaigns"))
            if parent.get("id") != cid: raise ValueError("Fundraiser campaign ID changed")
            account = parent.get("account")
            result["campaign"] = {"id": cid}
        if not isinstance(account, dict): raise ValueError("Account metadata is missing")
        aid = _account(account.get("id"))
        # Filtering happens after paging. Never return another account's fields.
        if aid != credential.account_id: return None
        result["account_id"] = aid
        if kind == "supporters":
            if type(raw.get("livemode")) is not bool or raw["livemode"] is not credential.livemode:
                raise ValueError("Supporter data crossed the saved mode")
            result["livemode"] = raw["livemode"]
            fields = ("created_at", "language") + (("first_name", "last_name", "email", "phone") if include_contact else ())
        elif kind == "campaigns":
            if raw.get("status") not in {"active", "disabled", "auto_archive"}: raise ValueError("Campaign status is invalid")
            fields = ("name", "code", "status", "end_date", "designation_mode")
        elif kind == "fundraisers":
            if raw.get("status") not in {"active", "paused"}: raise ValueError("Fundraiser status is invalid")
            fields = ("name", "code", "slug", "status", "created_at")
        else:
            if type(raw.get("is_default")) is not bool: raise ValueError("Designation default flag is missing")
            result["is_default"] = raw["is_default"]
            fields = ("name", "code", "created_at", "updated_at")
        for field in fields:
            if field in raw:
                value = raw[field]
                if value is not None and (not isinstance(value, str) or len(value) > 10_000):
                    raise ValueError("Resource metadata is invalid")
                result[field] = value
        return result

    async def _list(self, kind, config, credential):
        params = {**self._mode(credential, kind), "limit": config.limit}
        for field in ("starting_after", "ending_before"):
            value = getattr(config, field, None)
            if value is not None: params[field] = value
        if kind == "campaigns": params["account"] = credential.account_id
        body = await self._request("GET", "/v1/" + kind, params=params)
        raw, more = body.get("data"), body.get("has_more")
        if not isinstance(raw, list) or len(raw) > config.limit or type(more) is not bool or (more and not raw):
            raise ValueError("Resource pagination envelope is incomplete")
        ids = [_id(item.get("id") if isinstance(item, dict) else None, kind) for item in raw]
        cursor = config.starting_after or config.ending_before
        if len(ids) != len(set(ids)) or (cursor and cursor in ids):
            raise ValueError("Pagination did not make progress")
        items = []
        for item in raw:
            record = await self._record(item, kind, credential, include_contact=getattr(config, "include_contact", False))
            if record is not None: items.append(record)
        reverse = config.ending_before is not None
        return {"items": items, "has_more": more, "fetched_count": len(raw), "excluded_other_account_count": len(raw) - len(items),
            "next_starting_after": ids[-1] if more and not reverse else None,
            "next_ending_before": ids[0] if more and reverse else None,
            "pagination_direction": "newer" if reverse else "older", "complete": not more}

    async def _execute(self, inputs):
        ticket = _REQUEST_CONTEXT.get()
        if ticket is None or ticket[0] is not self: raise ValueError("Native request context required")
        _, context, credential = ticket
        if context is not None: await self._revalidate(context)
        config, attempted = self.config.config, False
        operation = config.operation
        output = {"operation": operation, "livemode": credential.livemode, "account_fence": credential.account_id,
            "account_identity_verified": False, "ownership_verified": False}
        if operation in WRITES: output.update(write_verified=False, readback_required=True)
        try:
            if operation == "check_connection":
                kind = credential.check_resource
                cls = {"supporters": FundraiseUpListSupportersConfig, "campaigns": FundraiseUpListCampaignsConfig,
                    "fundraisers": FundraiseUpListFundraisersConfig, "designations": FundraiseUpListDesignationsConfig}[kind]
                page = await self._list(kind, cls(limit=1), credential)
                # Reachability/resource ACL is distinct from account or user identity.
                return {**output, **page, "status": "success", "key_accepted": True, "resource": kind,
                    "returned_account_match": bool(page["items"])}
            if operation.startswith("list_"):
                kind = operation.removeprefix("list_")
                return {**output, "status": "success", **await self._list(kind, config, credential)}
            get_kinds = {"get_supporter": "supporters", "get_campaign": "campaigns", "get_fundraiser": "fundraisers", "get_designation": "designations"}
            if operation in get_kinds:
                kind = get_kinds[operation]
                identifier = getattr(config, operation.removeprefix("get_") + "_id")
                raw = await self._request("GET", "/v1/" + kind + "/" + identifier, params=self._mode(credential, kind))
                item = await self._record(raw, kind, credential, include_contact=getattr(config, "include_contact", False))
                if item is None or item["id"] != identifier: raise ValueError("Resource crossed the saved ID or account fence")
                return {**output, "status": "success", "item": item}
            if operation in WRITES:
                self._mode(credential, "designations")
                path, payload = "/v1/designations", None
                if operation == "create_designation":
                    payload = {"name": config.name, "livemode": credential.livemode}
                    if config.code is not None: payload["code"] = config.code
                else:
                    identifier = config.designation_id
                    output["attempted_designation_id"] = identifier
                    path += "/" + identifier
                    existing = await self._record(await self._request("GET", path, params=self._mode(credential, "designations")), "designations", credential)
                    if existing is None or existing["id"] != identifier: raise ValueError("Designation crossed the saved account/ID fence")
                    if existing["is_default"]: raise ValueError("This node does not edit default designations")
                    if operation == "delete_designation":
                        # The API's explicit livemode requirement is for GET/POST.
                        # DELETE documents only the path ID and returns that ID.
                        attempted = True
                        body = await self._request("DELETE", path)
                        if body.get("id") != identifier:
                            raise ValueError("Deleted designation ID differs from the requested ID")
                        return {**output, "status": "success", "deleted_designation_id": identifier, "http_status": 200}
                    payload = {"livemode": credential.livemode}
                    if config.name is not None: payload["name"] = config.name
                    if config.code is not None or config.clear_code: payload["code"] = None if config.clear_code else config.code
                attempted = True
                body = await self._request("POST", path, payload=payload)
                try: output["attempted_designation_id"] = _id(body.get("id"), "designations")
                except ValueError: pass
                item = await self._record(body, "designations", credential)
                if item is None or (operation == "update_designation" and item["id"] != config.designation_id):
                    raise ValueError("Write response crossed the account or ID fence")
                return {**output, "status": "success", "item": item, "http_status": 200}
            raise ValueError("Unsupported Fundraise Up operation")
        except _ResponseError as exc:
            return {**output, "status": "error", "http_status": exc.status, "provider_code": exc.code,
                "error": f"Fundraise Up HTTP {exc.status}" + (f" ({exc.code})" if exc.code else ""),
                "write_outcome_unknown": attempted and (200 <= exc.status < 400 or exc.status >= 500)}
        except (httpx.RequestError, SSRFError, ValueError):
            return {**output, "status": "error", "error": "Fundraise Up mode, response, account scope or transport was not confirmed.", "write_outcome_unknown": attempted}
