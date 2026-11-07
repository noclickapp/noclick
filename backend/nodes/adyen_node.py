"""Adyen Management v3 metadata and Checkout v72 payment-link status.

A protected /me API credential plus an authorized company is service evidence,
not a personal user, settlement proof or permission to move money.
"""
import base64
from contextvars import ContextVar
import hashlib
import hmac
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, normalize_search
from utils.credentials import resolve_credential_with_owner_fallback
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

FAMILIES = {"adyen_api_key"}
PRIVATE_REQUEST = ContextVar("adyen_private_http_request", default=False)


class _RequestFilter(logging.Filter):
    def filter(self, record):
        if not PRIVATE_REQUEST.get():
            return True
        record.msg, record.args = "Adyen HTTP transport activity", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Enter a valid Adyen resource ID")
    return value


Identifier = Annotated[str, BeforeValidator(_id)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or ("credential_type" in raw and (not isinstance(raw["credential_type"], str) or raw["credential_type"] not in FAMILIES)):
        raise ValueError("Connect a native Adyen API key credential")
    return raw


class AdyenApiKeyCredential(BaseModel):
    credential_type: Literal["adyen_api_key"] = Field("adyen_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=8192, title="Adyen API Key", json_schema_extra={"ui:widget": "password"})
    environment: Literal["test", "live"] = Field(..., title="Adyen Environment", description="Test and live keys are separate. This connection uses fixed Management v3 endpoints.")
    expected_api_credential_id: Identifier = Field(..., title="Expected API Credential ID", description="Must match the protected Management /me response. This identifies a service credential, not a person.")
    company_id: Identifier = Field(..., title="Authorized Company ID", description="Restricts merchant selection to this company. A successful company read proves access, not personal ownership.")
    live_url_prefix: Optional[str] = Field(None, min_length=3, max_length=63, title="Checkout Live URL Prefix", description="Actual prefix issued in your Adyen Customer Area, hex part followed by a hyphen and company name. Needed only for live payment-link status.")
    model_config = ConfigDict(title="Adyen API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.adyen.com/development-resources/api-authentication"})

    @field_validator("api_key")
    @classmethod
    def token(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid Adyen API key")
        return value

    @field_validator("live_url_prefix")
    @classmethod
    def prefix(cls, value):
        if value is not None and not re.fullmatch(r"[0-9a-f]{1,32}-[A-Za-z0-9][A-Za-z0-9-]{0,48}", value):
            raise ValueError("Supply the actual issued Adyen Checkout live prefix")
        return value

    @model_validator(mode="after")
    def environment_binding(self):
        if self.environment == "test" and self.live_url_prefix is not None:
            raise ValueError("A test connection cannot carry a live Checkout prefix")
        return self


def _credential(raw):
    raw = _family(raw)
    try:
        return AdyenApiKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("Adyen credential is invalid; reconnect") from None


def _op(value, title, group):
    return Field(value, title=title, json_schema_extra={"x-operation-group": group})


def _selector(title, name, parent=None):
    options = {"field_name": name + "_id", "searchable": True, "allow_custom": True, "placeholder": "Select or type an ID"}
    if parent:
        options["depends_on"] = parent
    return Field(..., title=title, json_schema_extra={"x-dynamic-options": options, "x-resource-type": "adyen_" + name})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetIdentity(Settings):
    operation: Literal["get_identity"] = _op("get_identity", "Get API Credential and Company Evidence", "Connection")


class GetCompany(Settings):
    operation: Literal["get_company"] = _op("get_company", "Get Connected Company Metadata", "Company")


class Page(Settings):
    page_size: int = Field(25, ge=1, le=100, title="Page Size")
    page_token: Optional[str] = Field(None, max_length=18000, title="Continuation", json_schema_extra={"ui:hidden": True})


class ListMerchants(Page):
    operation: Literal["list_merchants"] = _op("list_merchants", "List Connected Company Merchants", "Merchants")


class GetMerchant(Settings):
    operation: Literal["get_merchant"] = _op("get_merchant", "Get Company Merchant Metadata", "Merchants")
    merchant_id: Identifier = _selector("Merchant", "merchant")


class ListStores(Page, GetMerchant):
    operation: Literal["list_stores"] = _op("list_stores", "List Merchant Stores", "Stores")


class GetStore(GetMerchant):
    operation: Literal["get_store"] = _op("get_store", "Get Merchant Store Metadata", "Stores")
    store_id: Identifier = _selector("Store", "store", "merchant_id")


class UpdateStoreDescription(GetStore):
    operation: Literal["update_store_description"] = _op("update_store_description", "Update Store Description", "Store Management")
    description: str = Field(..., min_length=1, max_length=300, title="New Store Description", description="Changes only the existing store description; the text is not returned in workflow outputs.")
    confirm_store_change: Literal[True] = Field(..., title="Confirm Store Description Change", description="Changes this authorized merchant's store metadata. Notifications and automation are not qualified.")


class GetPaymentLinkStatus(GetMerchant):
    operation: Literal["get_payment_link_status"] = _op("get_payment_link_status", "Get Payment Link Status", "Payment Status")
    link_id: Identifier = Field(..., title="Existing Payment Link ID", description="Reads status only, verifying the returned merchant account. Does not return the payment URL, amount, reference or shopper information.", json_schema_extra={"x-resource-type": "adyen_payment_link"})


Operations = Annotated[Union[GetIdentity, GetCompany, ListMerchants, GetMerchant, ListStores,
    GetStore, UpdateStoreDescription, GetPaymentLinkStatus], Field(discriminator="operation")]


class AdyenNodeConfig(NodeConfig[Operations, AdyenApiKeyCredential]):
    pass


class _Authority:
    def __init__(self, credential, *, credential_id=None, user_id=None, pool=None, organization_id=None, workflow_id=None):
        self.credential = _credential(credential)
        self.credential_id, self.user_id, self.pool = credential_id, user_id, pool
        self.organization_id, self.workflow_id = organization_id, workflow_id

    async def check(self):
        _credential(self.credential)
        if not self.credential_id:
            return
        if not self.user_id:
            raise ValueError("Adyen saved credential requires an authorized actor")
        row = await resolve_credential_with_owner_fallback(self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not row:
            raise ValueError("Adyen current credential is unavailable or revoked")
        if _credential(row).model_dump() != self.credential.model_dump():
            raise ValueError("Adyen credential binding changed; reconnect")

    def key(self):
        return hashlib.sha256(json.dumps([self.credential.model_dump(mode="json"), self.credential_id, self.user_id,
            self.organization_id, self.workflow_id], sort_keys=True, default=str).encode()).hexdigest()


def _public(value, credential):
    key = credential.api_key
    canaries = {key, quote(key, safe=""), base64.b64encode(key.encode()).decode(), base64.urlsafe_b64encode(key.encode()).decode(), key.encode().hex()}
    if any(s in json.dumps(value, ensure_ascii=False) for s in canaries):
        raise ValueError("Adyen response contained protected credential data")
    return value


ACCOUNT_READ = {"management api - account read", "management api - accounts read"}
STORES_READ = {"management api - stores read", "management api - stores read and write"}
STORES_WRITE = {"management api - stores read and write"}


def _role(value):
    return re.sub(r"\s*[-—–]\s*", " - ", value.strip().lower())


def _project(kind, row, credential, parent=None, identifier=None):
    if not isinstance(row, dict):
        raise ValueError("Adyen resource metadata is invalid")
    # The documented single-store response omits id; bind it to the exact
    # requested route and verify the provider self link when supplied.
    resource_id = row.get("id")
    if resource_id is None and kind == "store" and identifier is not None:
        resource_id = _id(identifier)
        links = row.get("_links", {})
        if not isinstance(links, dict):
            raise ValueError("Adyen store links are invalid")
        if "self" in links:
            link = links["self"]
            origin = "https://management-" + credential.environment + ".adyen.com"
            if not isinstance(link, dict) or link.get("href") not in {
                origin + "/v1/stores/" + resource_id,
                origin + "/v3/stores/" + resource_id,
                origin + "/v3/merchants/" + _id(parent) + "/stores/" + resource_id,
            }:
                raise ValueError("Adyen store self link changed identity")
    result = {"id": _id(resource_id)}
    if kind == "merchant":
        # Merchant responses have no documented companyId. Membership comes
        # from the protected company-scoped collection, not a fabricated field.
        if parent != credential.company_id or ("companyId" in row and _id(row["companyId"]) != credential.company_id):
            raise ValueError("Adyen merchant belongs to another company or lacks its parent")
        result["company_id"] = credential.company_id
    if kind == "store":
        if _id(row.get("merchantId")) != parent:
            raise ValueError("Adyen store belongs to another merchant or lacks its parent")
        result["merchant_id"] = parent
    for key in ("name", "reference", "status"):
        if key in row:
            if not isinstance(row[key], str) or len(row[key]) > 300:
                raise ValueError("Adyen metadata text is invalid")
            result[key] = row[key]
    if kind == "store" and row.get("status") not in {"active", "inactive", "closed"}:
        raise ValueError("Adyen store status is invalid")
    if "description" in row:
        if not isinstance(row["description"], str) or len(row["description"]) > 100_000:
            raise ValueError("Adyen description metadata is invalid")
        result["description_present"] = bool(row["description"])
    return _public(result, credential)


class AdyenRequestError(ValueError):
    def __init__(self, message, *, status=None, outcome="unverified"):
        super().__init__(message)
        self.status, self.outcome = status, outcome


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.management = "https://management-" + self.credential.environment + ".adyen.com"
        self.company, self.roles = None, set()

    def checkout(self):
        if self.credential.environment == "test":
            return "https://checkout-test.adyen.com", "/v72"
        if not self.credential.live_url_prefix:
            raise ValueError("Supply the actual Checkout live URL prefix to read live payment-link status")
        return "https://" + self.credential.live_url_prefix + "-checkout-live.adyenpayments.com", "/checkout/v72"

    async def _http(self, method, path, *, service="management", params=None, body=None):
        identifier = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
        collection = bool(re.fullmatch(r"/companies/" + identifier + r"/merchants|/merchants/" + identifier + r"/stores", path))
        store = bool(re.fullmatch(r"/merchants/" + identifier + r"/stores/" + identifier, path))
        if service == "management":
            read = path == "/me" or bool(re.fullmatch(r"/companies/" + identifier + r"|/merchants/" + identifier, path)) or collection or store
            if not (method == "GET" and read or method == "PATCH" and store):
                raise ValueError("Unsupported Adyen native Management route")
            origin, version = self.management, "/v3"
        elif service == "checkout" and method == "GET" and re.fullmatch(r"/paymentLinks/" + identifier, path):
            origin, version = self.checkout()
        else:
            raise ValueError("Unsupported Adyen native service or payment route")
        if params is not None and (service != "management" or not collection or method != "GET" or set(params) != {"pageNumber", "pageSize"} or type(params["pageNumber"]) is not int or not 1 <= params["pageNumber"] <= 100 or type(params["pageSize"]) is not int or not 1 <= params["pageSize"] <= 100):
            raise ValueError("Unsupported Adyen native query")
        if method == "GET" and body is not None:
            raise ValueError("Adyen reads cannot carry write payloads")
        if method == "PATCH" and (not isinstance(body, dict) or set(body) != {"description"} or not isinstance(body["description"], str) or not 1 <= len(body["description"]) <= 300 or params is not None):
            raise ValueError("Adyen supports only the typed store description patch")
        url = origin + version + path
        assert_exact_url_origin(url, origin)
        await self.authority.check()
        headers = {"X-API-Key": self.credential.api_key, "Accept": "application/json", "Content-Type": "application/json"}
        _install_privacy()
        private = PRIVATE_REQUEST.set(True)
        try:
            with OutboundTraceProvider().get_tracer(__name__).start_as_current_span(method, kind=SpanKind.CLIENT,
                attributes={"http.request.method": method, "url.full": origin + "/[native-resource]", "url.scheme": "https", "server.address": urlsplit(origin).hostname, "server.port": 443},
                record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > 2_000_000:
                                        raise AdyenRequestError("Adyen response exceeds its bound; verify any write")
                                    content.extend(chunk)
                                status, media = response.status_code, response.headers.get("content-type", "")
                                span.set_attribute("http.response.status_code", status)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    if isinstance(error, httpx.HTTPError):
                        raise AdyenRequestError("Adyen store change outcome is unknown; read back before retrying" if method != "GET" else "Adyen request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        expected = {200, 204} if method == "PATCH" else {200}
        if status not in expected:
            outcome = "unauthenticated" if status == 401 else "forbidden" if status == 403 else "rate_limited" if status == 429 else "unverified"
            raise AdyenRequestError(f"Adyen returned HTTP {status}; check access and verify any uncertain change", status=status, outcome=outcome)
        if status == 204:
            if content:
                raise AdyenRequestError("Adyen HTTP 204 unexpectedly contained a body; verify before retrying", status=status)
            return None, status
        try:
            if media.split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError
            return json.loads(content), status
        except Exception:
            raise AdyenRequestError("Adyen response is not documented JSON; verify any change before retrying", status=status) from None

    def require(self, roles):
        if not self.roles.intersection(roles):
            raise ValueError("Adyen current API credential lacks a required Management role")

    async def identity(self):
        row, _ = await self._http("GET", "/me")
        if not isinstance(row, dict) or _id(row.get("id")) != self.credential.expected_api_credential_id or row.get("active") is not True or not isinstance(row.get("username"), str) or not 1 <= len(row["username"]) <= 255 or not isinstance(row.get("roles"), list) or len(row["roles"]) > 1000 or any(not isinstance(r, str) or not 1 <= len(r) <= 255 for r in row["roles"]):
            raise ValueError("Adyen protected API credential does not match the configured active principal")
        self.roles = {_role(r) for r in row["roles"]}
        links = row.get("_links", {})
        if not isinstance(links, dict):
            raise ValueError("Adyen API credential links are malformed")
        if "company" in links:
            link = links["company"]
            if not isinstance(link, dict) or link.get("href") not in {self.management + "/v3/companies/" + self.credential.company_id, self.management + "/v1/companies/" + self.credential.company_id}:
                raise ValueError("Adyen API credential company link differs from the configured company")
        self.require(ACCOUNT_READ)
        company, _ = await self._http("GET", "/companies/" + self.credential.company_id)
        projected = _project("company", company, self.credential)
        if projected["id"] != self.credential.company_id:
            raise ValueError("Adyen company access response changed identity")
        self.company = company
        return _public({"api_credential_id": row["id"], "company_id": projected["id"], "principal_kind": "api_credential", "role_source": "protected_me", "active": True}, self.credential)

    async def one(self, kind, identifier, merchant=None):
        if self.company is None:
            raise ValueError("Adyen company access binding is required")
        _id(identifier)
        if kind == "merchant":
            self.require(ACCOUNT_READ)
            token = None
            while True:
                page = await self.page("merchant", 100, token)
                if any(row["id"] == identifier for row in page["data"]):
                    break
                token = page["next_page_token"]
                if not token:
                    raise ValueError("Adyen merchant is not in the authorized company")
            path = "/merchants/" + identifier
        elif kind == "store":
            self.require(STORES_READ)
            path = "/merchants/" + _id(merchant) + "/stores/" + identifier
        else:
            raise ValueError("Unsupported Adyen native resource")
        row, _ = await self._http("GET", path)
        projected = _project(kind, row, self.credential, self.credential.company_id if kind == "merchant" else merchant, identifier)
        if projected["id"] != identifier:
            raise ValueError("Adyen selected resource changed identity")
        return row, projected

    async def page(self, kind, size, token=None, merchant=None):
        if self.company is None or kind not in {"merchant", "store"} or type(size) is not int or not 1 <= size <= 100:
            raise ValueError("Unsupported Adyen collection")
        self.require(ACCOUNT_READ if kind == "merchant" else STORES_READ)
        path = "/companies/" + self.credential.company_id + "/merchants" if kind == "merchant" else "/merchants/" + _id(merchant) + "/stores"
        scope = hashlib.sha256(json.dumps([self.authority.key(), kind, size, merchant]).encode()).hexdigest()
        page, seen = 1, []
        if token:
            try:
                encoded, signature = token.split(".")
                blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
                data = json.loads(blob)
                if not hmac.compare_digest(signature, hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()) or set(data) != {"scope", "page", "seen"} or data["scope"] != scope or type(data["page"]) is not int or not 2 <= data["page"] <= 100 or not isinstance(data["seen"], list) or len(data["seen"]) != data["page"] - 1 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in data["seen"]):
                    raise ValueError
                page, seen = data["page"], data["seen"]
            except Exception:
                raise ValueError("Adyen continuation is invalid or belongs to another scope") from None
        payload, _ = await self._http("GET", path, params={"pageNumber": page, "pageSize": size})
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or len(payload["data"]) > size or type(payload.get("itemsTotal")) is not int or payload["itemsTotal"] < 0 or type(payload.get("pagesTotal")) is not int or payload["pagesTotal"] < 0:
            raise ValueError("Adyen collection is not a documented bounded envelope")
        total, pages = payload["itemsTotal"], payload["pagesTotal"]
        rows = [_project(kind, r, self.credential, self.credential.company_id if kind == "merchant" else merchant) for r in payload["data"]]
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Adyen collection contains duplicate resource IDs")
        fingerprint = hashlib.sha256(json.dumps(sorted(r["id"] for r in rows)).encode()).hexdigest()
        if rows and fingerprint in seen:
            raise ValueError("Adyen pagination repeated a page")
        more = page < pages
        if pages != (total + size - 1) // size or page > max(pages, 1) or total < (page - 1) * size + len(rows) or more and (len(rows) != size or page >= 100) or not more and (page - 1) * size + len(rows) != total:
            raise ValueError("Adyen collection count or continuation changed; restart")
        # Only numeric pagination is used. Provider hyperlinks are never followed
        # or exported; examples in the v3 spec retain older v1 link URLs.
        next_token = None
        if more:
            blob = json.dumps({"scope": scope, "page": page + 1, "seen": seen + [fingerprint]}, separators=(",", ":")).encode()
            next_token = base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()
        return {"data": rows, "total": total, "next_page_token": next_token, "http_status": 200}


class AdyenNode(WorkflowNode):
    integration_type = "automation-adyen"
    connection_evidence = ConnectionEvidence(noun="Adyen API credential", operation="get_identity", identity_operation="get_identity", identity_keys=("api_credential_id", "company_id"), proves="account")

    @classmethod
    def get_config_model(cls):
        return AdyenNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, AdyenNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("Adyen configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["Adyen credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials, credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            pool=self.node_data.get("_approval_pool"), organization_id=self.organization_id, workflow_id=self.workflow_id)

    async def run(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        self._native_authority = self._authority()
        await self._native_authority.check()
        return await super().run(inputs)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # API keys do not rotate. Staging resolves access before this hook.
        return _credential(credential_data).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run protected API credential and company evidence to verify Adyen access; it does not prove a personal user or payment privileges"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(getattr(self, "_native_authority", None) or self._authority())
        cfg, op = self.config.config, self.config.config.operation
        identity = await client.identity()
        if op == "get_identity":
            return identity
        if op == "get_company":
            return {**identity, "data": _project("company", client.company, client.credential)}
        merchant = getattr(cfg, "merchant_id", None)
        if merchant:
            raw_merchant, projected = await client.one("merchant", merchant)
            if op == "get_merchant":
                return {**identity, "data": projected}
        if op in {"list_merchants", "list_stores"}:
            return {**identity, **await client.page("merchant" if op == "list_merchants" else "store", cfg.page_size, cfg.page_token, merchant)}
        if op in {"get_store", "update_store_description"}:
            raw_store, projected = await client.one("store", cfg.store_id, merchant)
            if op == "get_store":
                return {**identity, "data": projected}
            client.require(STORES_WRITE)
            body = _public({"description": cfg.description}, client.credential)
            receipt, status = await client._http("PATCH", "/merchants/" + merchant + "/stores/" + cfg.store_id, body=body)
            if receipt is not None:
                ack = _project("store", receipt, client.credential, merchant, cfg.store_id)
                if ack["id"] != cfg.store_id:
                    raise ValueError("Adyen store acknowledgement changed identity; verify before retrying")
            readback, projected = await client.one("store", cfg.store_id, merchant)
            if readback.get("description") != cfg.description or readback.get("status") != raw_store.get("status") or readback.get("reference") != raw_store.get("reference"):
                raise ValueError("Adyen store description readback differs; verify before retrying")
            return {**identity, "data": projected, "http_status": status, "acknowledged": True, "effect": "Store description changed; automation and notifications are unqualified"}
        if op == "get_payment_link_status":
            payload, _ = await client._http("GET", "/paymentLinks/" + cfg.link_id, service="checkout")
            if not isinstance(payload, dict) or _id(payload.get("id")) != cfg.link_id or payload.get("merchantAccount") != merchant or payload.get("status") not in {"active", "completed", "expired", "paid", "paymentPending"}:
                raise ValueError("Adyen payment link identity, merchant or status differs")
            result = {"id": cfg.link_id, "merchant_id": merchant, "status": payload["status"], "settlement_verified": False}
            for key in ("expiresAt", "updatedAt"):
                if key in payload:
                    if not isinstance(payload[key], str) or len(payload[key]) > 64:
                        raise ValueError("Adyen payment link timestamp is invalid")
                    result[key] = payload[key]
            return {**identity, "data": _public(result, client.credential)}
        raise ValueError("Unsupported Adyen native operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data)
        if field_name not in {"merchant_id", "store_id"}:
            raise ValueError("Unsupported Adyen selector")
        authority = _Authority(credential_data)
        merchant = _id((context or {}).get("merchant_id")) if field_name == "store_id" else None
        client = _Client(authority)
        await client.identity()
        if merchant:
            await client.one("merchant", merchant)
        async def fetch(token):
            page = await client.page("merchant" if field_name == "merchant_id" else "store", 50, token, merchant)
            return [{"value": row["id"], "label": row.get("name") or row.get("reference") or row["id"]} for row in page["data"]], page["next_page_token"]
        return await load_paginated_options(fetch, page_token=page_token, search=normalize_search(search), cap=1000, log_label="adyen_metadata")
