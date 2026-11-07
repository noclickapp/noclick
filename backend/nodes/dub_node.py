"""Closed Dub workspace-key metadata reads; protected catalogs prove access, not identity."""
import json
import math
import re
from typing import Annotated, Any, Dict, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.dub.co"
MAX_BYTES, MAX_ROWS = 2 * 1024 * 1024, 1000


def _text(value, limit=255, nullable=False, empty=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I):
        raise ValueError("Expected bounded metadata text without controls or URLs")
    return value


def _id(value):
    value = _text(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Use a bounded opaque resource ID")
    return value


def _domain(value):
    value = _text(value, 253)
    if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", value):
        raise ValueError("Expected a protected domain slug without URL components")
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected finite nonnegative provider NUMBER")
    return value


class DubApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dub Workspace API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dub.co/docs/api-reference/authentication",
        "x-credential-instructions": "Supply an existing server workspace API key. Bearer header only; publishable keys, OAuth exchange and key issuance are unsupported. Protected domain catalog access proves reachability, not a user or workspace ownership. Read permissions and entitlement must be checked in Dub."
    })
    credential_type: Literal["dub_api_key"] = Field("dub_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, min_length=1, max_length=4096, title="Existing Server Workspace API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def raw_key(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value):
            raise ValueError("Supply raw API key without prefix or whitespace")
        return clean_secret(value, field_name="Dub workspace API key")


def _credential(raw):
    if isinstance(raw, DubApiKeyCredential):
        raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "dub_api_key":
        raise ValueError("Select the authoritative Dub workspace API-key family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1):
        raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None)
    raw.pop("updated_at", None)
    if set(raw) != {"credential_type", "api_key"}:
        raise ValueError("Only the explicit workspace API-key family is supported")
    try:
        return DubApiKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("Dub supplied API-key shape unsupported") from None


def _stored(raw):
    return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    """Recheck saved API keys through staging's canonical credential resolver."""
    def __init__(self, data, authority):
        super().__init__(data)
        self.authority = authority

    async def reload(self):
        from utils.credentials import resolve_credential_with_owner_fallback
        current = await resolve_credential_with_owner_fallback(**self.authority)
        if current is None or _stored(current) != _stored(self):
            raise ValueError("Dub current saved key is unavailable or changed")

    def __repr__(self):
        return "<Dub current credential>"


def _op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Dub Metadata", "x-is-trigger": False})


class _Catalog(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    include_names: bool = Field(False, strict=True, title="Include Domain and Link Names", description="Opt in to private domain slugs, link keys and nullable titles. Default outputs use IDs, flags, counts and raw resource times.")
    domain_page: int = Field(1, strict=True, ge=1, le=10000, title="Domain Catalog Page", description="First documented page is1; local default1 and maximum10000. OAS does not declare a page default or coherent minimum. One bounded page; completion remains unknown.")
    domain_page_size: int = Field(50, strict=True, ge=1, le=50, title="Domain Page Size", description="Documented default/max50; local minimum1.")


class DubDomainsConfig(_Catalog):
    operation: Literal["list_domains"] = _op("list_domains", "Read Accessible Domain Metadata")


class _DomainSelection(_Catalog):
    domain_id: str = Field(..., title="Current Domain ID", json_schema_extra={"x-resource-type": "domain_id", "x-dynamic-options": {"field_name": "domain_id", "depends_on": ["domain_page", "domain_page_size", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})

    @field_validator("domain_id", mode="before")
    @classmethod
    def selected_domain(cls, value):
        return _id(value)


class _LinkPage(_DomainSelection):
    # Describe the same constraint as one_direction for schema-driven clients.
    # A missing or null cursor is allowed, including two null cursors.
    model_config = ConfigDict(json_schema_extra={"allOf": [{"anyOf": [
        {"properties": {"starting_after": {"const": None}}},
        {"properties": {"ending_before": {"const": None}}},
    ]}]})
    page_size: int = Field(100, strict=True, ge=1, le=100, title="Link Page Size", description="Documented default/max100; local minimum1. No total or completion witness.")
    starting_after: str | None = Field(None, max_length=255, title="Starting After", description="Optional documented opaque cursor, mutually exclusive with Ending Before. No deprecated page parameter.")
    ending_before: str | None = Field(None, max_length=255, title="Ending Before", description="Optional documented opaque cursor, mutually exclusive with Starting After.")

    @field_validator("starting_after", "ending_before", mode="before")
    @classmethod
    def opaque_cursor(cls, value):
        return None if value is None else _id(value)

    @model_validator(mode="after")
    def one_direction(self):
        if self.starting_after is not None and self.ending_before is not None:
            raise ValueError("Supply Starting After or Ending Before, never both")
        return self


class DubLinksConfig(_LinkPage):
    operation: Literal["list_links"] = _op("list_links", "Read Selected Domain Link Metadata")


class DubLinkConfig(_LinkPage):
    operation: Literal["get_link"] = _op("get_link", "Get Current Link Metadata")
    link_id: str = Field(..., title="Current Link ID", json_schema_extra={"x-resource-type": "link_id", "x-dynamic-options": {"field_name": "link_id", "depends_on": "domain_id", "allow_custom": True, "auto_select_sole_option": False}})

    @field_validator("link_id", mode="before")
    @classmethod
    def selected_link(cls, value):
        return _id(value)


class DubCountConfig(_DomainSelection):
    operation: Literal["count_links"] = _op("count_links", "Count Selected Domain Nonarchived Links")


DubOperation = Annotated[Union[DubDomainsConfig, DubLinksConfig, DubLinkConfig, DubCountConfig], Field(discriminator="operation")]


class DubNodeConfig(NodeConfig[DubOperation, DubApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _project(raw, kind, names=False):
    if not isinstance(raw, dict):
        raise ValueError("Expected current documented metadata object")
    out = {"id": _id(raw.get("id"))}
    if type(raw.get("archived")) is not bool or raw["archived"]:
        raise ValueError("Expected current nonarchived resource")
    out["archived"] = raw["archived"]
    for field in ("createdAt", "updatedAt"):
        out[field] = _text(raw.get(field), 100)
    if kind == "domains":
        slug = _domain(raw.get("slug"))
        for field in ("verified", "primary"):
            if type(raw.get(field)) is not bool:
                raise ValueError("Expected typed domain flag")
            out[field] = raw[field]
        if names:
            out["slug"] = slug
        return out, (out["id"], slug)
    if kind != "links":
        raise ValueError("Closed native projection required")
    domain, workspace = _domain(raw.get("domain")), _id(raw.get("workspaceId"))
    out["workspaceId"], out["clicks"] = workspace, _number(raw.get("clicks"))
    for field in ("expiresAt", "disabledAt", "lastClicked"):
        if field not in raw:
            raise ValueError("Expected explicit nullable resource time")
        out[field] = _text(raw[field], 100, nullable=True)
    if names:
        out.update(domain=domain, key=_text(raw.get("key"), 512), title=_text(raw.get("title"), 512, nullable=True, empty=True))
    return out, (out["id"], domain, workspace)


class _ProviderError(Exception):
    def __init__(self, result):
        self.result = result


class _Session:
    def __init__(self, credential, config):
        self.raw, self.key, self.config = credential, _credential(credential), config
        self.attempted, self.status, self.link_header = False, None, False

    def error(self, message):
        return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}

    async def request(self, route, domain=None, link_id=None):
        if route == "domains":
            path, params = "/domains", {"archived": "false", "page": self.config.domain_page, "pageSize": self.config.domain_page_size}
        elif route == "links" and domain is not None:
            path, params = "/links", {"domain": _domain(domain), "showArchived": "false", "pageSize": self.config.page_size}
            for field, key in (("starting_after", "startingAfter"), ("ending_before", "endingBefore")):
                value = getattr(self.config, field)
                if value is not None:
                    params[key] = _id(value)
        elif route == "info" and link_id is not None:
            path, params = "/links/info", {"linkId": _id(link_id)}
        elif route == "count" and domain is not None:
            path, params = "/links/count", {"domain": _domain(domain), "showArchived": "false"}
        else:
            raise ValueError("Closed bound metadata route required")
        try:
            if isinstance(self.raw, _CurrentCredential):
                await self.raw.reload()
            key = _credential(self.raw)
            self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", BASE + path, params=params, headers={"Authorization": "Bearer " + key.api_key, "Accept": "application/json", "User-Agent": "NoClick-Dub-Metadata/1.0"}) as response:
                    self.status = response.status_code
                    headers, body = response.headers, bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise ValueError("Metadata response exceeds local bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential):
                await self.raw.reload()
            if self.status != 200:
                reason = {401: "Workspace key authentication failed", 403: "Read permission or entitlement unverified", 404: "Resource missing or invisible", 429: "Rate limit prevents current verification"}.get(self.status, "Protected metadata outcome unverified")
                raise _ProviderError(self.error(reason + "; private response body omitted; no retry"))
            if "application/json" not in headers.get("content-type", "").lower():
                raise ValueError("Expected documented JSON representation")
            self.link_header = "link" in headers
            return json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON number")))
        except (httpx.HTTPError, SSRFError):
            raise _ProviderError(self.error("Dub transport outcome unknown; no retry or alternate host")) from None

    async def catalog(self, kind, domain=None):
        raw = await self.request(kind, domain=domain)
        if not isinstance(raw, list) or len(raw) > MAX_ROWS:
            raise ValueError("Expected bounded documented bare catalog array")
        limit = self.config.domain_page_size if kind == "domains" else self.config.page_size
        parsed = [_project(row, kind, self.config.include_names) for row in raw[:limit]]
        anchors = [anchor for _, anchor in parsed]
        if len({a[0] for a in anchors}) != len(anchors):
            raise ValueError("Ambiguous current catalog IDs")
        if kind == "domains" and len({a[1] for a in anchors}) != len(anchors):
            raise ValueError("Ambiguous current domain slugs")
        if kind == "links" and (any(a[1] != domain for a in anchors) or len({a[2] for a in anchors}) > 1):
            raise ValueError("Link catalog crosses selected domain or returned workspace")
        return {"data": [row for row, _ in parsed], "returned_count": len(raw), "exposed_count": len(parsed), "local_truncated": len(raw) > limit, "has_more": None, "pagination_complete": None, "next_page_token": None, "pagination_link_header_present": self.link_header, "count_scope": "current_token_filtered_page", "global_workspace_coverage_proven": False}, anchors


class DubNode(WorkflowNode):
    integration_type = "automation-dub"
    connection_evidence = ConnectionEvidence(operation="list_domains", noun="protected Dub domain catalog", proves="reachability")
    edit_examples = ["Read selected domain link IDs and nonarchived counts without exposing destination URLs", "Inspect link archive flags and raw expiry times, with names omitted"]

    @classmethod
    def get_config_model(cls):
        return DubNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try:
                _stored(config_data["credentials"])
            except ValueError as error:
                raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Workspace API keys do not rotate; staging resolves saved credentials at load.
        return _stored(credential_data)

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        try:
            result = await cls._dispatch(_stored(credential_data), DubDomainsConfig())
        except ValueError:
            return {"valid": False, "error": "Dub workspace API-key family unsupported"}
        if result.get("status") == "success":
            return {"valid": True, "provider_verified": True, "proves": "reachability"}
        return {"valid": False if result.get("http_status") == 401 else None,
                "error": result.get("error", "Protected catalog access unverified")}

    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            domains, domain_anchors = await session.catalog("domains")
            if config.operation == "list_domains":
                out = domains
                if set((await session.catalog("domains"))[1]) != set(domain_anchors):
                    raise ValueError("Current domain catalog witnesses changed")
            else:
                selected = next((a for a in domain_anchors if a[0] == config.domain_id), None)
                if selected is None:
                    raise ValueError("Domain not established on bounded current catalog page; no global absence claim")
                if config.operation == "count_links":
                    out = {"count": _number(await session.request("count", domain=selected[1])), "count_scope": "current_token_filtered_selected_domain_nonarchived_links"}
                elif config.operation in {"list_links", "get_link"}:
                    links, link_anchors = await session.catalog("links", selected[1])
                    if config.operation == "list_links":
                        out = links
                    else:
                        link = next((a for a in link_anchors if a[0] == config.link_id), None)
                        if link is None:
                            raise ValueError("Link not established on selected-domain current bounded catalog page")
                        data, anchor = _project(await session.request("info", link_id=link[0]), "links", config.include_names)
                        if anchor != link:
                            raise ValueError("Link detail differs from current id/domain/workspace catalog witness")
                        out = {"data": data}
                    if set((await session.catalog("links", selected[1]))[1]) != set(link_anchors):
                        raise ValueError("Current selected-domain link witnesses changed")
                    if link_anchors:
                        out["returned_workspace_id"] = link_anchors[0][2]
                else:
                    raise ValueError("Closed native operation required")
                if selected not in (await session.catalog("domains"))[1]:
                    raise ValueError("Current protected selected domain changed")
                out["domain_id"] = selected[0]
            if session.key.api_key in json.dumps(out, ensure_ascii=False, allow_nan=False):
                raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": 200, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "workspace_ownership_proven": False, **out}
        except _ProviderError as error:
            return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError):
            return session.error("Current saved key/catalog ancestry or typed metadata could not be established; no raw fallback or retry")

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data)
        if field_name not in {"domain_id", "link_id"}:
            raise ValueError("Select a native domain or link ID field")
        if page_token is not None:
            raise ValueError("No provider continuation witness; set documented page or cursor fields explicitly")
        if search is not None:
            _text(search, 100, empty=True)
        context = context or {}
        options_config = {key: context[key] for key in ("domain_page", "domain_page_size", "include_names") if key in context}
        if field_name == "domain_id":
            config = DubDomainsConfig(**options_config)
        else:
            # Required parent is validated before any provider I/O; arbitrary context fields confer no authority.
            options_config["domain_id"] = _id(context.get("domain_id"))
            options_config.update({key: context[key] for key in ("page_size", "starting_after", "ending_before") if key in context})
            config = DubLinksConfig(**options_config)
        result = await cls._dispatch(credential_data, config)
        if result.get("status") != "success":
            raise ValueError(result["error"])
        options = [{"value": row["id"], "label": row.get("slug") if field_name == "domain_id" and config.include_names else (row.get("title") or row.get("key")) if field_name == "link_id" and config.include_names else ("Domain " if field_name == "domain_id" else "Link ") + row["id"], "metadata": {"id": row["id"], "protected_catalog": True, "ownership_proven": False, **({"domain_id": config.domain_id} if field_name == "link_id" else {})}} for row in result["data"]]
        return {"options": [row for row in options if not search or search.casefold() in row["label"].casefold()], "has_more": None, "next_page_token": None}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, DubNodeConfig) or self.config.credentials is None:
            raise ValueError("Dub workspace API key and configuration are required")
        credential = _stored(self.config.credentials)
        if self.node_data.get("credential_id"):
            from utils.database_pool import get_native_pool
            credential = _CurrentCredential(credential, dict(
                credential_id=self.node_data["credential_id"], user_id=self.user_id,
                pool=getattr(self, "_approval_pool", None) or get_native_pool(),
                org_id=getattr(self, "organization_id", None),
                workflow_id=getattr(self, "workflow_id", None)))
        return await self._dispatch(credential, self.config.config)
