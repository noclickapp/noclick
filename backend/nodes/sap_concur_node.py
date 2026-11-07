"""Native SAP Concur profile, configuration list and report metadata.

Closed regional endpoints and allowlisted projections keep financial contents,
private profiles and token claims out of outputs. Configuration writes are explicit.
"""
from __future__ import annotations
import base64
from datetime import datetime
import json
import re
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, is_token_expired
from nodes.oauth.sap_concur_oauth import make_refresh
from utils.ssrf import SSRFError, guarded_async_client

FAMILY = "sap_concur_oauth"
ORIGINS = tuple("https://" + zone + ".api.concursolutions.com" for zone in ("apj1", "eu2", "us2", "usg", "glz"))
MAX_BYTES = 2_000_000


class ConcurError(ValueError):
    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code, self.retry_after = status_code, retry_after


def origin(value):
    if not isinstance(value, str) or value not in ORIGINS:
        raise ValueError("Select the exact current server geolocation returned with the SAP Concur token")
    return value


def text(value, maximum=255):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter a nonempty value without edge whitespace or control characters")
    return value


def secret(value):
    value = text(value, 16384)
    if not value.isascii() or any(c.isspace() for c in value) or "://" in value:
        raise ValueError("Enter the issued token or client secret without a header or URL")
    return value


def uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower():
            raise ValueError()
        return value.lower()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Enter the exact SAP Concur UUID without a URL") from None


def guard(data, stored=False):
    if not isinstance(data, dict) or ((stored or "credential_type" in data) and data.get("credential_type") != FAMILY):
        raise ValueError("Select a native SAP Concur OAuth credential")


class SAPConcurOAuthCredential(BaseModel):
    model_config = ConfigDict(title="SAP Concur OAuth Tokens", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.concur.com/api-reference/authentication/apidoc.html",
            "x-credential-instructions": "Use existing issued OAuth tokens and their exact current server geolocation. Optional refresh requires the same application's client ID/secret and expiry. No login or initial token mint is performed."})
    credential_type: Literal["sap_concur_oauth"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    geolocation: Literal["https://apj1.api.concursolutions.com", "https://eu2.api.concursolutions.com", "https://us2.api.concursolutions.com", "https://usg.api.concursolutions.com", "https://glz.api.concursolutions.com"]
    access_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    client_id: str | None = None
    client_secret: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, description="Issued access-token expiry as ISO 8601 with timezone; required when refresh is configured")
    scope: str | None = Field(None, description="Actual granted scope string, if known; this field grants no permissions", max_length=4096)
    token_type: Literal["Bearer"] = Field("Bearer", json_schema_extra={"ui:hidden": True})

    @field_validator("access_token", "refresh_token", "client_secret", mode="before")
    @classmethod
    def validate_secret(cls, value):
        return secret(value) if value is not None else None

    @field_validator("client_id", mode="before")
    @classmethod
    def validate_client_id(cls, value):
        return uuid(value) if value is not None else None

    @field_validator("expires_at", mode="before")
    @classmethod
    def validate_expiry(cls, value):
        if value is None:
            return None
        try:
            stamp = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError()
            return stamp.isoformat()
        except (ValueError, TypeError):
            raise ValueError("Enter token expiry as ISO 8601 with timezone") from None

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter only the granted scope string")
        return value

    @model_validator(mode="after")
    def refresh_configuration(self):
        if self.refresh_token and not (self.client_id and self.client_secret and self.expires_at):
            raise ValueError("Refresh requires the original client ID, client secret and token expiry")
        if not self.refresh_token and (self.client_id or self.client_secret):
            raise ValueError("Supply the matching refresh token with its client configuration")
        return self


def credential(data):
    guard(data)
    try:
        return SAPConcurOAuthCredential.model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Check the SAP Concur OAuth token, regional origin and refresh fields") from None


def picker(field, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    @field_validator("list_id", "item_id", "user_id", mode="before", check_fields=False)
    @classmethod
    def validate_id(cls, value):
        return uuid(value)
    @field_validator("value", "short_code", mode="before", check_fields=False)
    @classmethod
    def validate_value(cls, value):
        return text(value)


class ListIdentities(Config):
    operation: Literal["list_identities"] = Field("list_identities")
    start_index: int = Field(1, ge=1, le=2147483647, strict=True)
    count: int = Field(20, ge=1, le=100, strict=True)


class GetIdentity(Config):
    operation: Literal["get_identity"] = Field("get_identity")
    user_id: str = Field(..., json_schema_extra=picker("user_id"))


class ListLists(Config):
    operation: Literal["list_lists"] = Field("list_lists")
    page: int = Field(1, ge=1, le=2147483647, strict=True)


class GetList(Config):
    operation: Literal["get_list"] = Field("get_list")
    list_id: str = Field(..., json_schema_extra=picker("list_id"))


class ListItems(GetList):
    operation: Literal["list_list_items"] = Field("list_list_items")
    page: int = Field(1, ge=1, le=2147483647, strict=True)


class GetItem(GetList):
    operation: Literal["get_list_item"] = Field("get_list_item")
    item_id: str = Field(..., json_schema_extra=picker("item_id", "list_id"))


class GetReport(GetIdentity):
    operation: Literal["get_report"] = Field("get_report")
    context_type: Literal["TRAVELER", "MANAGER", "PROCESSOR", "PROXY"] = "TRAVELER"
    report_id: str
    @field_validator("report_id", mode="before")
    @classmethod
    def validate_report_id(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{1,128}", value):
            raise ValueError("Enter the exact report ID without a URL or path")
        return value


class Write(Config):
    confirm_configuration_change: Literal[True] = Field(..., description="Changes shared SAP Concur configuration; requires applicable administrator permission. Actual notification behavior is unverified.")


class CreateList(Write):
    operation: Literal["create_list"] = Field("create_list")
    value: str
    search_criteria: Literal["TEXT", "CODE"] = "TEXT"
    display_format: Literal["(CODE) TEXT", "TEXT (CODE)"] = "(CODE) TEXT"


class UpdateList(CreateList):
    operation: Literal["update_list"] = Field("update_list")
    list_id: str = Field(..., json_schema_extra=picker("list_id"))


class DeleteList(Write, GetList):
    operation: Literal["delete_list"] = Field("delete_list")


class CreateItem(Write, GetList):
    operation: Literal["create_list_item"] = Field("create_list_item")
    short_code: str
    value: str
    @field_validator("short_code", "value")
    @classmethod
    def no_hyphen(cls, value):
        if "-" in value:
            raise ValueError("SAP Concur item names and codes do not support hyphens")
        return value


class UpdateItem(CreateItem, GetItem):
    operation: Literal["update_list_item"] = Field("update_list_item")


class RemoveItem(Write, GetItem):
    operation: Literal["remove_list_item"] = Field("remove_list_item")


ConcurConfig = Annotated[Union[ListIdentities, GetIdentity, ListLists, GetList, ListItems, GetItem, GetReport, CreateList, UpdateList, DeleteList, CreateItem, UpdateItem, RemoveItem], Field(discriminator="operation")]
class SAPConcurNodeConfig(NodeConfig[ConcurConfig, SAPConcurOAuthCredential]):
    pass


async def freshen(data, *, pool=None, user_id=None, credential_id=None, **_context):
    """Use staging's shared OAuth lock and CAS persistence for saved tokens."""
    current = credential(data)
    # Preserve row metadata used by the common compare-and-swap store.
    for key in ("token_version", "updated_at"):
        if key in data:
            current[key] = data[key]
    if current.get("refresh_token") and is_token_expired(current["expires_at"]) and not (credential_id and user_id):
        raise RuntimeError("Save the native SAP Concur connection before refreshing; access is unverified")
    if current.get("refresh_token"):
        # The callback reads the same dict the manager updates after its locked
        # re-read, including the current client and regional token endpoint.
        async def refresh(token):
            return await make_refresh(current)(token)
        await ensure_fresh_oauth_token(pool=pool, user_id=user_id, credential_id=credential_id,
            credential=current, refresh=refresh, provider="sap_concur", caller_path="freshen",
            additional_token_fields=("geolocation", "scope"))
    return current


async def request(data, method, route, *, query=None, body=None, expected=200, empty=False):
    guard(data, stored=True)
    origin(data["geolocation"])
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.request(method, origin(data["geolocation"]) + route, params=query, json=body,
                headers={"Authorization": "Bearer " + data["access_token"], "Accept": "application/json"})
    except (SSRFError, httpx.RequestError):
        raise ConcurError("SAP Concur request could not be completed; access is unverified") from None
    if response.status_code != expected:
        delay = response.headers.get("Retry-After")
        retry = int(delay) if delay and delay.isascii() and delay.isdecimal() and len(delay) <= 8 else None
        raise ConcurError(f"SAP Concur HTTP {response.status_code}: request was not accepted", response.status_code, retry)
    if empty:
        if response.content:
            raise ConcurError("SAP Concur returned content for a documented empty response")
        return None
    try:
        if len(response.content) > MAX_BYTES:
            raise ValueError()
        raw = response.json()
        if not isinstance(raw, dict) or any(k in raw for k in ("error", "errors", "errorMessage")):
            raise ValueError()
        return raw
    except (ValueError, TypeError):
        raise ConcurError("SAP Concur returned unreadable or unsuccessful JSON") from None


def safe(value, data):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value) or any(data.get(k) and data[k] in value for k in ("access_token", "refresh_token", "client_secret")):
        raise ConcurError("SAP Concur returned unreadable or protected metadata")
    return value


def profile(raw, data):
    if not isinstance(raw, dict):
        raise ConcurError("SAP Concur returned an unreadable identity")
    out = {"id": uuid(raw.get("id"))}
    if raw.get("displayName") is not None:
        out["displayName"] = safe(raw["displayName"], data)
    if "active" in raw:
        if type(raw["active"]) is not bool:
            raise ConcurError("SAP Concur returned an unreadable identity status")
        out["active"] = raw["active"]
    return out


def listing(raw, data):
    if not isinstance(raw, dict):
        raise ConcurError("SAP Concur returned unreadable list metadata")
    out = {"id": uuid(raw.get("id")), "value": safe(raw.get("value"), data)}
    for k in ("isReadOnly", "isDeleted"):
        if k in raw:
            if type(raw[k]) is not bool:
                raise ConcurError("SAP Concur returned an unreadable list flag")
            out[k] = raw[k]
    for k in ("searchCriteria", "displayFormat"):
        if raw.get(k) is not None:
            out[k] = safe(raw[k], data)
    return out


def item(raw, data, list_id):
    if not isinstance(raw, dict) or not isinstance(raw.get("lists"), list):
        raise ConcurError("SAP Concur returned unreadable item membership")
    memberships = [uuid(x.get("id")) for x in raw["lists"] if isinstance(x, dict)]
    if len(memberships) != len(raw["lists"]) or list_id not in memberships:
        raise ConcurError("SAP Concur returned an item outside the selected list")
    return {"id": uuid(raw.get("id")), "value": safe(raw.get("value"), data), "shortCode": safe(raw.get("shortCode"), data), "list_ids": memberships}


def paged(raw, data, project, requested):
    if not isinstance(raw.get("content"), list) or len(raw["content"]) > 1000 or not isinstance(raw.get("page"), dict):
        raise ConcurError("SAP Concur returned an unreadable or oversized page")
    p = raw["page"]
    if any(type(p.get(k)) is not int or not 0 <= p[k] <= 2147483647 for k in ("size", "totalElements", "totalPages", "number")) or p["number"] != requested or p["size"] < len(raw["content"]) or p["totalElements"] < len(raw["content"]):
        raise ConcurError("SAP Concur returned inconsistent page metadata")
    rows = [project(x, data) for x in raw["content"]]
    if len({r["id"] for r in rows}) != len(rows):
        raise ConcurError("SAP Concur returned duplicate resource identifiers")
    return {"items": rows, "page": requested, "total_pages": p["totalPages"], "total_items": p["totalElements"], "has_more": requested < p["totalPages"]}


async def lists(data, page=1):
    return paged(await request(data, "GET", "/list/v4/lists", query={"page": page}), data, listing, page)


async def identities(data, index=1, count=20):
    raw = await request(data, "GET", "/profile/identity/v4/Users", query={"startIndex": index, "count": count, "attributes": "id,displayName,active"})
    rows = raw.get("Resources")
    if not isinstance(rows, list) or len(rows) > count or any(type(raw.get(k)) is not int or raw[k] < 0 for k in ("totalResults", "startIndex", "itemsPerPage")) or raw["startIndex"] != index or raw["itemsPerPage"] < len(rows) or raw["totalResults"] < len(rows):
        raise ConcurError("SAP Concur returned inconsistent identity pagination")
    projected = [profile(x, data) for x in rows]
    if len({r["id"] for r in projected}) != len(projected):
        raise ConcurError("SAP Concur returned duplicate identities")
    return {"items": projected, "start_index": index, "total_items": raw["totalResults"], "has_more": bool(rows and index + len(rows) - 1 < raw["totalResults"])}


async def get_list(data, list_id, *, writable=False):
    result = listing(await request(data, "GET", "/list/v4/lists/" + list_id), data)
    if result["id"] != list_id or (writable and (result.get("isReadOnly") is not False or result.get("isDeleted") is not False)):
        raise ConcurError("SAP Concur selected list identity or writable state was not confirmed")
    return result


async def get_item(data, list_id, item_id):
    result = item(await request(data, "GET", "/list/v4/items/" + item_id), data, list_id)
    if result["id"] != item_id:
        raise ConcurError("SAP Concur returned a different item")
    return result


class SAPConcurNode(WorkflowNode):
    integration_type = "automation-sap-concur"
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="configuration lists", label_keys=("value",), proves="account")
    edit_examples = ["List my SAP Concur configuration lists", "Look up a Concur user's profile", "Check report status metadata", "Create a configuration list item"]
    @classmethod
    def get_config_model(cls):
        return SAPConcurNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            raise ConfigValidationError("Select a native SAP Concur OAuth credential") from None
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["Select a native SAP Concur OAuth credential"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return "Check the SAP Concur credential and operation fields"
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def validate_credential(cls, data):
        try:
            await lists(await freshen(data))
            return {"valid": True}
        except ConcurError as exc:
            return {"valid": False if exc.status_code in {401, 403} else None, "error": str(exc)}
        except RuntimeError:
            return {"valid": None, "error": "SAP Concur refresh could not be evaluated before the connection was saved"}
        except (ValueError, TypeError, KeyError):
            return {"valid": False, "error": "SAP Concur credential could not be validated"}
    @classmethod
    async def validate_credential_access(cls, data):
        return await cls.validate_credential(data)
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"list_id", "item_id", "user_id"}:
            raise ValueError("Unknown native SAP Concur picker")
        parent = uuid((context or {}).get("list_id")) if field_name == "item_id" else None
        if search is not None:
            text(search)
        data = await freshen(credential_data)
        binding = {"field": field_name, "parent": parent, "search": search or "", "origin": data["geolocation"]}
        index = 1
        if page_token:
            try:
                if len(page_token) > 4096:
                    raise ValueError()
                token = json.loads(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
                if token.get("binding") != binding or type(token.get("page")) is not int or not 1 <= token["page"] <= 2147483647:
                    raise ValueError()
                index = token["page"]
            except (ValueError, TypeError, KeyError, AttributeError):
                raise ValueError("SAP Concur picker cursor does not match the current origin, parent or query") from None
        if field_name == "list_id":
            result = await lists(data, index)
        elif field_name == "user_id":
            result = await identities(data, index, 100)
        else:
            result = paged(await request(data, "GET", "/list/v4/lists/" + parent + "/children", query={"page": index}), data, lambda r, d: item(r, d, parent), index)
        options = [{"value": r["id"], "label": r.get("value") or r.get("displayName") or r["id"]} for r in result["items"]]
        if search:
            needle = text(search).casefold()
            options = [r for r in options if needle in r["label"].casefold()]
        next_index = index + (len(result["items"]) if field_name == "user_id" else 1)
        next_token = base64.urlsafe_b64encode(json.dumps({"binding": binding, "page": next_index}, separators=(",", ":")).encode()).decode().rstrip("=") if result["has_more"] else None
        return {"options": options, "next_page_token": next_token}
    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a native SAP Concur credential")
        cfg = self.config.config
        try:
            nested = self.node_data.get("config") or {}
            cid = self.node_data.get("credential_id")
            if isinstance(nested, dict) and nested.get("credential_id"):
                if cid and cid != nested["credential_id"]:
                    raise ConcurError("SAP Concur credential selection is ambiguous")
                cid = nested["credential_id"]
            data = await freshen(self.config.credentials.model_dump(mode="json"), credential_id=cid, pool=self.node_data.get("_approval_pool"),
                user_id=self.user_id, organization_id=self.organization_id, workflow_id=self.workflow_id)
            return {"status": "success", "action": cfg.operation, "data": await self._operation(data, cfg)}
        except ConcurError as exc:
            return {"status": "error", "action": cfg.operation, "error": str(exc), "status_code": exc.status_code, "retry_after": exc.retry_after}
        except (ValueError, RuntimeError, TypeError, KeyError):
            return {"status": "error", "action": cfg.operation, "error": "SAP Concur credential, refresh or response could not be validated"}
    async def _operation(self, data, cfg):
        op = cfg.operation
        if op == "list_lists":
            return await lists(data, cfg.page)
        if op == "list_identities":
            return await identities(data, cfg.start_index, cfg.count)
        if op == "get_identity":
            result = profile(await request(data, "GET", "/profile/identity/v4/Users/" + cfg.user_id), data)
            if result["id"] != cfg.user_id:
                raise ConcurError("SAP Concur returned a different user")
            return result
        if op == "get_list":
            return await get_list(data, cfg.list_id)
        if op == "get_list_item":
            return await get_item(data, cfg.list_id, cfg.item_id)
        if op == "list_list_items":
            return paged(await request(data, "GET", "/list/v4/lists/" + cfg.list_id + "/children", query={"page": cfg.page}), data, lambda r, d: item(r, d, cfg.list_id), cfg.page)
        if op == "get_report":
            raw = await request(data, "GET", "/expensereports/v4/users/" + cfg.user_id + "/context/" + cfg.context_type + "/reports/" + cfg.report_id)
            if raw.get("reportId") != cfg.report_id or uuid(raw.get("userId")) != cfg.user_id:
                raise ConcurError("SAP Concur returned a different report or owner binding")
            return {"reportId": cfg.report_id, "userId": cfg.user_id, **{k: safe(raw[k], data) for k in ("name", "approvalStatus", "approvalStatusId", "creationDate", "reportDate", "reportType") if raw.get(k) is not None}}
        if op != "create_list":
            await get_list(data, cfg.list_id, writable=True)
        if op in {"update_list_item", "remove_list_item"}:
            await get_item(data, cfg.list_id, cfg.item_id)
        if op == "delete_list":
            await request(data, "DELETE", "/list/v4/lists/" + cfg.list_id, expected=204, empty=True)
            return {"id": cfg.list_id, "deletion_request_completed": True, "verified_readback": None}
        if op == "remove_list_item":
            await request(data, "DELETE", "/list/v4/lists/" + cfg.list_id + "/items/" + cfg.item_id, expected=204, empty=True)
            return {"list_id": cfg.list_id, "item_id": cfg.item_id, "membership_removal_acknowledged": True, "verified_readback": None}
        if op in {"create_list", "update_list"}:
            body = {"value": cfg.value, "searchCriteria": cfg.search_criteria, "displayFormat": cfg.display_format}
            raw = await request(data, "POST" if op == "create_list" else "PUT", "/list/v4/lists" + ("/" + cfg.list_id if op == "update_list" else ""), body=body, expected=201 if op == "create_list" else 200)
            result = listing(raw, data)
            if op == "update_list" and result["id"] != cfg.list_id:
                raise ConcurError("SAP Concur returned a different updated list")
        else:
            body = {"value": cfg.value, "shortCode": cfg.short_code}
            if op == "create_list_item":
                body["listId"] = cfg.list_id
            raw = await request(data, "POST" if op == "create_list_item" else "PUT", "/list/v4/items" + ("/" + cfg.item_id if op == "update_list_item" else ""), body=body, expected=201 if op == "create_list_item" else 200)
            result = item(raw, data, cfg.list_id)
            if op == "update_list_item" and result["id"] != cfg.item_id:
                raise ConcurError("SAP Concur returned a different updated item")
        return {"resource": result, "write_acknowledged": True, "verified_readback": None}
