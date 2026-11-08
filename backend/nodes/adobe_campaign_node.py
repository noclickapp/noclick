"""Adobe Campaign's native REST metadata and ordinary owned-profile management.

Explicit Standard and enabled v8 FDA modes share only documented endpoints.
Supplied expiring OAuth access is tenant-bound; no messages, workflows, consent,
privacy requests, token minting or automatic mutation replay is available here.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Annotated, Literal, Union
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "adobe_campaign_access_token"
ORIGIN = "https://mc.adobe.io"
MAX_BYTES = 2 * 1024 * 1024


def _segment(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Use the exact Campaign instance tenant identifier")
    return value


def _pkey(value):
    if not isinstance(value, str) or not re.fullmatch(r"@?[A-Za-z0-9_-]{1,2048}", value):
        raise ValueError("Use a current response-provided opaque PKey")
    return value


def _custom(value):
    if not isinstance(value, str) or not re.fullmatch(r"cus[A-Za-z][A-Za-z0-9_]{0,100}", value):
        raise ValueError("Use the exact cus-prefixed custom resource name")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use nonempty text without control characters")
    return value


PKey = Annotated[str, BeforeValidator(_pkey), Field(min_length=1, max_length=2049)]
CustomName = Annotated[str, Field(pattern=r"^cus[A-Za-z][A-Za-z0-9_]{0,100}$"), BeforeValidator(_custom)]
Text = Annotated[str, BeforeValidator(_text), Field(min_length=1, max_length=250)]


def _op(name, label, category, write=False):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label,
                 "x-category": category, "x-is-trigger": False, "x-read-only": not write})


def _pick(field, scopes=()):
    return {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True,
                                  **({"depends_on": scopes[-1]} if scopes else {})}, "x-resource-type": field}


class AdobeCampaignAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Adobe Campaign Access Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://experienceleague.adobe.com/en/docs/campaign/campaign-v8/developer/apis/setting-up-api-access"})
    credential_type: Literal["adobe_campaign_access_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    product_mode: Literal["v8_fda", "campaign_standard"] = Field(..., title="Campaign Product",
        description="v8 REST requires enabled FDA; Enterprise FFDA is unsupported. Standard is a separate existing product tenant.")
    tenant_id: Annotated[str, BeforeValidator(_segment)] = Field(..., title="Campaign Tenant ID",
        description="Exact instance route identifier supplied by Adobe, including stage suffix if applicable. Use the current v8 tenant after migration; not an IMS @AdobeOrg ID.")
    api_key: str = Field(..., title="API Key (Client ID)", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})
    access_token: str = Field(..., title="Issued OAuth Access Token", repr=False, min_length=1, max_length=8192,
        description="Already-issued OAuth server-to-server Bearer token for this tenant and Campaign API product profile. JWT authentication is retired; no token mint or refresh is performed.",
        json_schema_extra={"ui:widget": "password"})
    expires_at: int = Field(..., title="Token Expiry (Unix Seconds)", strict=True, ge=1,
        description="Actual expiry derived from the issuer's token response. Replace this saved credential when it expires.")

    @field_validator("api_key", "access_token")
    @classmethod
    def header_secret(cls, value):
        if not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Use issued credentials without whitespace or control characters")
        return value


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(CampaignConfig):
    page_size: int = Field(25, strict=True, ge=1, le=100, title="Page Size",
                          description="A single bounded page. Large-table continuation is requested explicitly.")
    next_page_url: str | None = Field(None, max_length=8192, title="Returned Next Page URL",
        description="Paste the next_page_url from this same resource, tenant and page size. Never synthesize _lineStart.")


class ProfileMetadata(CampaignConfig):
    operation: Literal["get_profile_metadata"] = _op("get_profile_metadata", "Get Profile Field Metadata", "Profiles")
    extended: bool = Field(False, strict=True, title="Extended Profile Fields",
                           description="Use profileAndServicesExt, including v8 timezone; ordinary profileAndServices excludes extensions.")


class Profiles(Page):
    operation: Literal["list_profiles"] = _op("list_profiles", "List Profiles", "Profiles")
    extended: bool = Field(False, strict=True, title="Extended Profile Fields")


class Profile(CampaignConfig):
    operation: Literal["get_profile"] = _op("get_profile", "Get Profile", "Profiles")
    profile_pkey: PKey = Field(..., title="Current Profile PKey", json_schema_extra=_pick("profile_pkey"))
    extended: bool = Field(False, strict=True, title="Extended Profile Fields")


class ProfileFields(CampaignConfig):
    first_name: Text | None = Field(None, title="First Name")
    last_name: Text | None = Field(None, title="Last Name")
    email: str | None = Field(None, max_length=254, title="Email")
    phone: Text | None = Field(None, title="Phone")

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value is not None and (not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or not value.isascii()):
            raise ValueError("Use an email address")
        return value

    @model_validator(mode="after")
    def nonempty(self):
        if not any(getattr(self, name) is not None for name in ("first_name", "last_name", "email", "phone")):
            raise ValueError("Supply at least one ordinary profile field")
        return self


class Change(CampaignConfig):
    confirm_profile_change: Literal[True] = Field(..., title="Confirm Owned Profile Change",
        description="Mutates real targeting records; tenant automation and notifications are not guaranteed quiet. Only change a record you are authorized to manage.")

    @field_validator("confirm_profile_change", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Confirm this profile change explicitly")
        return value


class CreateProfile(ProfileFields, Change):
    operation: Literal["create_profile"] = _op("create_profile", "Create Profile", "Profiles", True)


class UpdateProfile(ProfileFields, Change):
    operation: Literal["update_profile"] = _op("update_profile", "Update Profile Fields", "Profiles", True)
    profile_pkey: PKey = Field(..., title="Current Profile PKey", json_schema_extra=_pick("profile_pkey"))


class DeleteProfile(Change):
    operation: Literal["delete_profile"] = _op("delete_profile", "Delete Owned Profile", "Profiles", True)
    profile_pkey: PKey = Field(..., title="Current Profile PKey", json_schema_extra=_pick("profile_pkey"))


class Services(Page):
    operation: Literal["list_services"] = _op("list_services", "List Services", "Services")


class Service(CampaignConfig):
    operation: Literal["get_service"] = _op("get_service", "Get Service", "Services")
    service_pkey: PKey = Field(..., title="Current Service PKey", json_schema_extra=_pick("service_pkey"))


class ServiceMetadata(CampaignConfig):
    operation: Literal["get_service_metadata"] = _op("get_service_metadata", "Get Service Field Metadata", "Services")


class LinkedTypes(CampaignConfig):
    operation: Literal["list_extended_resource_types"] = _op("list_extended_resource_types", "List Profile-linked Resource Types", "Custom Resources")


class UnlinkedTypes(CampaignConfig):
    operation: Literal["list_custom_resource_types"] = _op("list_custom_resource_types", "List Unlinked Resource Types", "Custom Resources")


class Custom(CampaignConfig):
    resource_api: Literal["profileAndServicesExt", "customResources"] = Field(..., title="Custom Resource API",
        description="Profile-linked extensions use profileAndServicesExt; unlinked resources use customResources and are not also exposed in the extension API.")
    resource_name: CustomName = Field(..., title="Custom Resource", json_schema_extra=_pick("resource_name", ("resource_api",)))


class CustomMetadata(Custom):
    operation: Literal["get_custom_resource_metadata"] = _op("get_custom_resource_metadata", "Get Custom Resource Field Metadata", "Custom Resources")


class CustomRecords(Custom, Page):
    operation: Literal["list_custom_records"] = _op("list_custom_records", "List Custom Records", "Custom Resources")


class CustomRecord(Custom):
    operation: Literal["get_custom_record"] = _op("get_custom_record", "Get Custom Record", "Custom Resources")
    record_pkey: PKey = Field(..., title="Current Record PKey",
        json_schema_extra=_pick("record_pkey", ("resource_api", "resource_name")))


OperationConfig = Annotated[Union[ProfileMetadata, Profiles, Profile, CreateProfile, UpdateProfile, DeleteProfile,
    Services, Service, ServiceMetadata, LinkedTypes, UnlinkedTypes, CustomMetadata, CustomRecords, CustomRecord], Field(discriminator="operation")]


class AdobeCampaignNodeConfig(NodeConfig):
    config: OperationConfig
    credentials: AdobeCampaignAccessTokenCredential | None = None


class CampaignError(ValueError):
    def __init__(self, message, status_code=None, uncertain=False):
        super().__init__(message)
        self.status_code, self.uncertain = status_code, uncertain


class CampaignSession:
    def __init__(self, credential):
        self.credential = credential
        self.base = ORIGIN + "/" + credential.tenant_id + "/campaign/"
        self.secrets = (credential.api_key, credential.access_token)

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value

    def live_token(self):
        if self.credential.expires_at <= time.time() + 5:
            raise CampaignError("Campaign access token expired; replace the saved issued token")

    def page_url(self, href, collection, size):
        if not isinstance(href, str) or len(href) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in href):
            raise CampaignError("Campaign returned an unverified pagination link")
        url = urlsplit(href)
        if url.scheme != "https" or url.netloc != "mc.adobe.io" or url.fragment or url.username or url.password or url.path != urlsplit(self.base + collection).path:
            raise CampaignError("Campaign pagination must stay on this exact tenant resource")
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        params = dict(pairs)
        if len(params) != len(pairs) or set(params) - {"_lineCount", "_lineStart", "_forcePagination"} or params.get("_lineCount") != str(size) or not params.get("_lineStart") or len(params["_lineStart"]) > 4096 or params.get("_forcePagination", "true") != "true":
            raise CampaignError("Use the provider's exact bounded continuation link")
        _pkey(params["_lineStart"])
        return href

    def record_url(self, href, collection, pkey):
        expected = self.base + collection + "/" + quote(pkey, safe="@")
        if href is None:
            return expected
        if not isinstance(href, str) or href != expected:
            raise CampaignError("Campaign returned a record link outside its current tenant resource")
        return href

    async def request(self, method, url, body=None):
        self.live_token()
        write = method != "GET"
        headers = {"Authorization": "Bearer " + self.credential.access_token, "X-Api-Key": self.credential.api_key,
                   "Accept": "application/json", "Content-Type": "application/json", "Cache-Control": "no-cache"}
        status = None
        try:
            async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, url, headers=headers, json=body) as response:
                    status = response.status_code
                    if status not in ({"POST": {200, 201}, "PATCH": {200}, "DELETE": {200}, "GET": {200}}[method]):
                        raise CampaignError("Campaign rejected or did not verify this request", status,
                            write and (200 <= status < 300 or status >= 500 or status in {408, 429}))
                    raw = bytearray()
                    async for block in response.aiter_bytes():
                        raw.extend(block)
                        if len(raw) > MAX_BYTES:
                            raise CampaignError("Campaign response exceeded the metadata limit", status, write)
                    if method == "DELETE":
                        # The documented acknowledgement is HTTP 200, not subscription-delete 204.
                        if not raw.strip():
                            return {}, status
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise CampaignError("Campaign returned unverified response content", status, write)
                    def pairs(items):
                        out = {}
                        for key, item in items:
                            if key in out:
                                raise ValueError
                            out[key] = item
                        return out
                    def constant(_):
                        raise ValueError
                    def finite(value):
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError
                        return number
                    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
                    if not isinstance(data, dict) or any(key in data for key in ("error", "errors", "errorCode", "error_description")) or data.get("success") is False or data.get("executed") is False or data.get("status") in {"error", "halted", "pending", "rejected"}:
                        raise CampaignError("Campaign returned an unverified response envelope", status, write)
                    return data, status
        except CampaignError:
            raise
        except Exception:
            raise CampaignError("Campaign request outcome could not be verified", status, write) from None

    def metadata(self, data, resource, status=200):
        try:
            if data.get("name") != resource or not isinstance(data.get("content"), dict) or len(data["content"]) > 500:
                raise ValueError
            fields = []
            for key, field in data["content"].items():
                if not isinstance(field, dict) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key):
                    raise ValueError
                if field.get("apiName", key) != key or not isinstance(field.get("type"), str):
                    raise ValueError
                item = {"apiName": key, "type": field["type"]}
                for name in ("label", "dataPolicy", "resType", "resTarget", "category"):
                    if isinstance(field.get(name), str) and len(field[name]) <= 1000:
                        item[name] = field[name]
                for name in ("readOnly", "sortable", "mandatory"):
                    if name in field:
                        if type(field[name]) is not bool:
                            raise ValueError
                        item[name] = field[name]
                fields.append(item)
            return {"name": resource, "fields": fields, "label": data.get("label") if isinstance(data.get("label"), str) else resource}
        except Exception:
            raise CampaignError("Campaign returned unverified resource metadata", status) from None

    def record(self, data, collection, status=200, custom_fields=None):
        try:
            if "content" in data:
                if not isinstance(data["content"], list) or len(data["content"]) != 1:
                    raise ValueError
                data = data["content"][0]
            if not isinstance(data, dict):
                raise ValueError
            pkey = _pkey(data.get("PKey"))
            href = self.record_url(data.get("href"), collection, pkey)
            out = {"PKey": pkey, "href": href}
            allowed = custom_fields if custom_fields is not None else (
                "firstName", "lastName", "email", "phone", "birthDate", "timezone", "label", "name", "title",
                "messageType", "mode", "created", "lastModified")
            for key in allowed:
                if re.search(r"(?i)(secret|password|token|authorization|credential|private|api.?key|access.?key|bearer|cookie)", key):
                    continue
                value = data.get(key)
                if value is None:
                    continue
                if type(value) not in (str, bool, int, float) or isinstance(value, str) and len(value) > 4096:
                    raise ValueError
                out[key] = value
            return out
        except Exception:
            raise CampaignError("Campaign returned unverified record metadata", status) from None

    def page(self, data, collection, size, status=200, custom_fields=None):
        rows = data.get("content")
        if not isinstance(rows, list) or len(rows) > size:
            raise CampaignError("Campaign returned unverified collection metadata", status)
        result = [self.record(row, collection, status, custom_fields) for row in rows]
        if len({row["PKey"] for row in result}) != len(result):
            raise CampaignError("Campaign returned duplicate PKeys", status)
        next_url = None
        if "next" in data and data["next"] is not None:
            if not isinstance(data["next"], dict) or not isinstance(data["next"].get("href"), str):
                raise CampaignError("Campaign returned unverified continuation metadata", status)
            try:
                next_url = self.page_url(data["next"]["href"], collection, size)
            except Exception:
                raise CampaignError("Campaign returned an unsafe continuation link", status) from None
            if not rows:
                raise CampaignError("Campaign returned a nonadvancing empty page", status)
        if "serverSidePagination" in data and type(data["serverSidePagination"]) is not bool:
            raise CampaignError("Campaign returned unverified pagination flags", status)
        return {"items": result, "next_page_url": next_url, "continuation_requested": True, "snapshot_verified": False}

    async def list_page(self, collection, size, next_url=None, custom_fields=None):
        if next_url:
            url = self.page_url(next_url, collection, size)
        else:
            url = self.base + collection + f"?_lineCount={size}&_forcePagination=true"
        data, status = await self.request("GET", url)
        page = self.page(data, collection, size, status, custom_fields)
        if next_url and page["next_page_url"] == next_url:
            raise CampaignError("Campaign returned a repeated continuation link", status)
        return page, status

    async def types(self, api):
        data, status = await self.request("GET", self.base + api + "/")
        if data.get("apiName") != "resourceType":
            raise CampaignError("Campaign returned an unverified resource catalog", status)
        result = []
        for name, item in data.items():
            if name == "apiName":
                continue
            if not name.startswith("cus"):
                continue
            try:
                _custom(name)
                if not isinstance(item, dict) or item.get("name") != name or item.get("type") not in {"collection", "item"} or item.get("data") != "/" + api + "/" + name + "/":
                    raise ValueError
                href = item.get("href")
                if href != self.base + api + "/" + name + "/metadata":
                    raise ValueError
                result.append({"name": name, "label": item.get("label") or item.get("help") or name})
            except Exception:
                raise CampaignError("Campaign returned unverified custom resource types", status) from None
        if len(result) > 500 or any(not isinstance(row["label"], str) or len(row["label"]) > 1000 for row in result):
            raise CampaignError("Campaign returned unverified custom resource labels", status)
        return result, status

    async def custom_fields(self, api, resource):
        types, status = await self.types(api)
        if resource not in {row["name"] for row in types}:
            raise CampaignError("Custom resource was not verified in this current API catalog", status)
        data, status = await self.request("GET", self.base + api + "/resourceType/" + resource)
        metadata = self.metadata(data, resource, status)
        scalars = {field["apiName"] for field in metadata["fields"] if field["type"] in {"string", "number", "boolean", "enumeration", "date", "datetime"}}
        return metadata, scalars, status


OPERATIONS = ("get_profile_metadata", "list_profiles", "get_profile", "create_profile", "update_profile",
              "delete_profile", "list_services", "get_service", "get_service_metadata", "list_extended_resource_types",
              "list_custom_resource_types", "get_custom_resource_metadata", "list_custom_records", "get_custom_record")


class AdobeCampaignNode(WorkflowNode):
    integration_type = "automation-adobe-campaign"
    scope_registry = ScopeRegistry("adobe_campaign", {name: ScopeRequirement(credential_types=(FAMILY,),
        note="Issued Campaign OAuth access and tenant product profiles control permission; this supplied-token node requests no OAuth scopes.") for name in OPERATIONS})
    connection_evidence = ConnectionEvidence(operation="list_services", noun="services", label_keys=("label", "name", "PKey"))

    @classmethod
    def get_config_model(cls):
        return AdobeCampaignNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type") not in (None, FAMILY):
            raise ValueError("Use current Adobe Campaign issued-access credentials")
        return super().parse_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            session = CampaignSession(AdobeCampaignAccessTokenCredential.model_validate(credential_data))
            await session.list_page("profileAndServices/service", 5)
            return {"valid": True, "name": None}
        except CampaignError as error:
            return {"valid": False if error.status_code in {401, 403} else None, "name": None,
                    "error": str(error), "status_code": error.status_code}
        except Exception:
            return {"valid": False, "name": None, "error": "Use a valid issued Campaign token and exact tenant binding"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"profile_pkey", "service_pkey", "resource_name", "record_pkey"}:
            return {"options": [], "next_page_token": None}
        session = CampaignSession(AdobeCampaignAccessTokenCredential.model_validate(credential_data))
        context = context or {}
        if field_name == "resource_name":
            api = context.get("resource_api")
            if api not in {"profileAndServicesExt", "customResources"} or page_token is not None:
                raise ValueError("Choose the current custom resource API before loading resources")
            rows, _ = await session.types(api)
            return {"options": [{"value": row["name"], "label": session.redact(row["label"])}
                    for row in rows if not search or search.casefold() in row["label"].casefold()], "next_page_token": None}
        fields = None
        if field_name == "record_pkey":
            api, resource = context.get("resource_api"), _custom(context.get("resource_name"))
            if api not in {"profileAndServicesExt", "customResources"}:
                raise ValueError("Choose the parent custom resource API")
            _, fields, _ = await session.custom_fields(api, resource)
            collection = api + "/" + resource
        else:
            collection = "profileAndServices/" + ("profile" if field_name == "profile_pkey" else "service")
        page, _ = await session.list_page(collection, 25, page_token, fields)
        options = []
        for row in page["items"]:
            label = row.get("label") or row.get("name") or " ".join(filter(None, (row.get("firstName"), row.get("lastName")))) or row["PKey"]
            if not search or search.casefold() in label.casefold():
                options.append({"value": row["PKey"], "label": session.redact(label)})
        return {"options": options, "next_page_token": page["next_page_url"]}

    async def execute(self, input_data):
        session = None
        mutation, status = False, None
        try:
            if self.config.credentials is None:
                raise ValueError
            config = self.config.config
            session = CampaignSession(self.config.credentials)
            self.scope_registry.require(config.operation)
            if isinstance(config, (Profiles, Services)):
                collection = "profileAndServicesExt/profile" if isinstance(config, Profiles) and config.extended else "profileAndServices/" + ("profile" if isinstance(config, Profiles) else "service")
                output, status = await session.list_page(collection, config.page_size, config.next_page_url)
            elif isinstance(config, (ProfileMetadata, ServiceMetadata)):
                resource = "profile" if isinstance(config, ProfileMetadata) else "service"
                api = "profileAndServicesExt" if isinstance(config, ProfileMetadata) and config.extended else "profileAndServices"
                data, status = await session.request("GET", session.base + api + "/resourceType/" + resource)
                output = {"metadata": session.metadata(data, resource, status)}
            elif isinstance(config, (LinkedTypes, UnlinkedTypes)):
                rows, status = await session.types("profileAndServicesExt" if isinstance(config, LinkedTypes) else "customResources")
                output = {"items": rows}
            elif isinstance(config, (CustomMetadata, CustomRecords, CustomRecord)):
                metadata, fields, status = await session.custom_fields(config.resource_api, config.resource_name)
                collection = config.resource_api + "/" + config.resource_name
                if isinstance(config, CustomMetadata):
                    output = {"metadata": metadata}
                elif isinstance(config, CustomRecords):
                    output, status = await session.list_page(collection, config.page_size, config.next_page_url, fields)
                else:
                    data, status = await session.request("GET", session.base + collection + "/" + quote(config.record_pkey, safe="@"))
                    output = {"record": session.record(data, collection, status, fields)}
            elif isinstance(config, (Profile, Service)):
                collection = ("profileAndServicesExt" if isinstance(config, Profile) and config.extended else "profileAndServices") + "/" + ("profile" if isinstance(config, Profile) else "service")
                pkey = config.profile_pkey if isinstance(config, Profile) else config.service_pkey
                data, status = await session.request("GET", session.base + collection + "/" + quote(pkey, safe="@"))
                output = {"record": session.record(data, collection, status)}
            else:
                collection = "profileAndServices/profile"
                target, method = session.base + collection, "POST"
                if isinstance(config, (UpdateProfile, DeleteProfile)):
                    data, status = await session.request("GET", target + "/" + quote(config.profile_pkey, safe="@"))
                    current = session.record(data, collection, status)
                    target = current["href"]  # Fresh response PKey, never a remembered raw ID.
                    method = "DELETE" if isinstance(config, DeleteProfile) else "PATCH"
                body = None
                if isinstance(config, (CreateProfile, UpdateProfile)):
                    body = {remote: getattr(config, local) for local, remote in (
                        ("first_name", "firstName"), ("last_name", "lastName"), ("email", "email"), ("phone", "phone"))
                        if getattr(config, local) is not None}
                mutation = True
                data, status = await session.request(method, target, body)
                if method == "DELETE":
                    output = {"deleted_pkey": current["PKey"]}
                else:
                    output = {"record": session.record(data, collection, status)}
                output.update(provider_acknowledged=True, readback_verified=False, status_code=status)
            return session.redact({"status": "success", "product_mode": session.credential.product_mode, **output})
        except CampaignError as error:
            return {"status": "error", "error": str(error), "status_code": error.status_code,
                    "uncertain_outcome": error.uncertain or mutation and error.status_code in {200, 201}}
        except Exception:
            return {"status": "error", "error": "Campaign configuration or response could not be verified",
                    "status_code": status, "uncertain_outcome": mutation}
