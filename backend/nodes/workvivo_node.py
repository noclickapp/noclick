"""Native Workvivo employee-experience metadata and ordinary draft-page management.

The tenant supplies its regional API base, organisation header and static key.
Collection links remain tenant/resource/filter-bound; page writes are multipart,
retain draft state and never claim production mutations are notification-free.
"""
from __future__ import annotations

import json
import math
import re
from typing import Annotated, Literal, Union
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "workvivo_api_key"
MAX_BYTES = 2 * 1024 * 1024


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("Use an exact positive Workvivo ID")
    return value


def _response_id(value):
    if type(value) is int and value > 0:
        value = str(value)
    return _id(value)


ID = Annotated[str, BeforeValidator(_id), Field(max_length=18)]


def _op(name, label, category, write=False):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label,
        "x-category": category, "x-is-trigger": False, "x-read-only": not write})


def _pick(name, parent=None):
    return {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True,
        **({"depends_on": parent} if parent else {})}, "x-resource-type": name}


class WorkvivoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Workvivo API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.workvivo.com/guides/quick-start"})
    credential_type: Literal["workvivo_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_base: str = Field(..., title="Tenant API Base URL", max_length=256,
        description="Copy the regional Base URL from API Keys & JWT Settings, adding /v1. For example https://api.workvivo.com/v1 or https://api.us2.workvivo.com/v1. All requests use production data.")
    workvivo_id: str = Field(..., title="Workvivo Organisation ID", max_length=128,
        description="Exact Workvivo-Id header shown by your tenant administrator; not a user identity.")
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=8192,
        description="Static app API key with the endpoint and visibility permissions you need. This is not OAuth or a user login.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base")
    @classmethod
    def regional_base(cls, value):
        if not re.fullmatch(r"https://api(?:\.[a-z0-9]+)?\.workvivo\.com/v1", value):
            raise ValueError("Use your exact HTTPS Workvivo regional API base ending /v1")
        return value

    @field_validator("workvivo_id", "api_key")
    @classmethod
    def header_value(cls, value):
        if not value or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Use the issued header value without whitespace or control characters")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Config):
    page_size: int = Field(25, strict=True, ge=1, le=100, title="Page Size")
    next_page_url: str | None = Field(None, max_length=8192, title="Returned Next Page URL",
        description="Exact next_page_url from this tenant, resource, filters and page size. No snapshot guarantee.")


class PageScope(Config):
    page_scope: Literal["global", "space"] = Field("global", title="Page Location",
        description="The pages endpoint returns global pages when space_id is omitted.")
    space_id: ID | None = Field(None, title="Space", json_schema_extra=_pick("space_id"))

    @model_validator(mode="after")
    def scope(self):
        if (self.page_scope == "space") != (self.space_id is not None):
            raise ValueError("Choose a space ID only for the Space page location")
        return self


class DateRange(Config):
    from_timestamp: int | None = Field(None, strict=True, ge=0, title="Created From (Unix Seconds)")
    to_timestamp: int | None = Field(None, strict=True, ge=0, title="Created Through (Unix Seconds)")

    @model_validator(mode="after")
    def dates(self):
        if self.from_timestamp is not None and self.to_timestamp is not None and self.from_timestamp > self.to_timestamp:
            raise ValueError("Created From must not follow Created Through")
        return self


class ListUsers(Page):
    operation: Literal["list_users"] = _op("list_users", "List User Metadata", "Users")


class GetUser(Config):
    operation: Literal["get_user"] = _op("get_user", "Get User Metadata", "Users")
    user_id: ID = Field(..., title="User", json_schema_extra=_pick("user_id"))


class ListSpaces(Page):
    operation: Literal["list_spaces"] = _op("list_spaces", "List Space Metadata", "Spaces")
    name: str | None = Field(None, max_length=250, title="Name Contains")
    visibility: Literal["public", "private", "hidden"] | None = Field(None, title="Visibility",
        description="Private and hidden reads require corresponding app visibility permissions.")


class GetSpace(Config):
    operation: Literal["get_space"] = _op("get_space", "Get Space Metadata", "Spaces")
    space_id: ID = Field(..., title="Space", json_schema_extra=_pick("space_id"))


class ListPages(PageScope, Page, DateRange):
    operation: Literal["list_pages"] = _op("list_pages", "List Page Metadata", "Pages")


class FindPage(PageScope):
    operation: Literal["find_page"] = _op("find_page", "Find Page Metadata by ID", "Pages")
    page_id: ID = Field(..., title="Page", json_schema_extra=_pick("page_id", "page_scope"))
    max_scan_pages: int = Field(5, strict=True, ge=1, le=20, title="Maximum Collection Pages",
        description="No page GET endpoint is documented. Scan at most this many pages of 100, following returned next_page links.")


class Change(PageScope):
    confirm_draft_change: Literal[True] = Field(..., title="Confirm Production Draft Change",
        description="Workvivo has no sandbox. Draft state limits visibility but does not guarantee quiet notifications, automation or a reversible deletion.")

    @field_validator("confirm_draft_change", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Confirm this real draft-page change explicitly")
        return value


class DraftFields(Config):
    title: str = Field(..., min_length=1, max_length=250, title="Title")
    html_content: str = Field(..., min_length=1, max_length=100000, title="HTML Content",
        description="Literal page HTML. No files are uploaded and embedded URLs are not fetched.")
    subtitle: str = Field("", max_length=1000, title="Subtitle")


class CreateDraftPage(DraftFields, Change):
    operation: Literal["create_draft_page"] = _op("create_draft_page", "Create Draft Page", "Pages", True)


class UpdateDraftPage(Change):
    operation: Literal["update_draft_page"] = _op("update_draft_page", "Update Draft Page Content", "Pages", True)
    page_id: ID = Field(..., title="Page", json_schema_extra=_pick("page_id", "page_scope"))
    title: str | None = Field(None, min_length=1, max_length=250, title="New Title")
    html_content: str | None = Field(None, min_length=1, max_length=100000, title="New HTML Content")
    subtitle: str | None = Field(None, max_length=1000, title="New Subtitle",
        description="An empty string clears the subtitle; an omitted value preserves it.")
    max_scan_pages: int = Field(5, strict=True, ge=1, le=20, title="Maximum Preflight Pages")

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, name) is None for name in ("title", "html_content", "subtitle")):
            raise ValueError("Supply at least one ordinary draft content change")
        return self


class DeleteDraftPage(Change):
    operation: Literal["delete_draft_page"] = _op("delete_draft_page", "Delete Owned Draft Page", "Pages", True)
    page_id: ID = Field(..., title="Page", json_schema_extra=_pick("page_id", "page_scope"))
    max_scan_pages: int = Field(5, strict=True, ge=1, le=20, title="Maximum Preflight Pages")


class ListArticles(Page, DateRange):
    operation: Literal["list_articles"] = _op("list_articles", "List Published Article Metadata", "Articles")


class GetArticle(Config):
    operation: Literal["get_article"] = _op("get_article", "Get Article Metadata", "Articles")
    article_id: ID = Field(..., title="Article", json_schema_extra=_pick("article_id"))


class ListEvents(Page, DateRange):
    operation: Literal["list_events"] = _op("list_events", "List Event Metadata", "Events")
    upcoming_only: bool = Field(True, strict=True, title="Upcoming Only")


class GetEvent(Config):
    operation: Literal["get_event"] = _op("get_event", "Get Event Metadata", "Events")
    event_id: ID = Field(..., title="Event", json_schema_extra=_pick("event_id"))


OperationConfig = Annotated[Union[ListUsers, GetUser, ListSpaces, GetSpace, ListPages, FindPage,
    CreateDraftPage, UpdateDraftPage, DeleteDraftPage, ListArticles, GetArticle, ListEvents, GetEvent],
    Field(discriminator="operation")]


class WorkvivoNodeConfig(NodeConfig):
    config: OperationConfig
    credentials: WorkvivoAPIKeyCredential | None = None


class WorkvivoError(ValueError):
    def __init__(self, message, status_code=None, uncertain=False):
        super().__init__(message)
        self.status_code, self.uncertain = status_code, uncertain


class WorkvivoSession:
    def __init__(self, credential):
        self.credential, self.base = credential, credential.api_base

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self.credential.api_key, "[redacted]")
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value

    async def request(self, method, resource, params=None, form=None, href=None):
        write, status = method != "GET", None
        try:
            async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
                # A filename=None part is an ordinary multipart field, not a file upload.
                files = [(key, (None, value)) for key, value in form.items()] if form is not None else None
                async with client.stream(method, href or self.base + "/" + resource, params=params,
                    files=files, headers={"Authorization": "Bearer " + self.credential.api_key,
                    "Workvivo-Id": self.credential.workvivo_id, "Accept": "application/json",
                    "Cache-Control": "no-cache"}) as response:
                    status = response.status_code
                    if status != (201 if method == "POST" else 200):
                        raise WorkvivoError("Workvivo rejected or did not verify this request", status,
                            write and (200 <= status < 300 or status >= 500 or status in {408, 429}))
                    raw = bytearray()
                    async for block in response.aiter_bytes():
                        raw.extend(block)
                        if len(raw) > MAX_BYTES:
                            raise WorkvivoError("Workvivo response exceeded the metadata limit", status, write)
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise WorkvivoError("Workvivo returned unverified response content", status, write)
                    def pairs(items):
                        result = {}
                        for key, value in items:
                            if key in result:
                                raise ValueError
                            result[key] = value
                        return result
                    def finite(value):
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError
                        return number
                    def constant(_):
                        raise ValueError
                    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
                    if not isinstance(data, dict) or data.get("status") != "success" or "data" not in data or not isinstance(data.get("meta"), dict):
                        raise ValueError
                    if any(key in data for key in ("error", "errors", "error_description")) or data.get("executed") is False or data.get("success") is False or "errors" in data["meta"]:
                        raise ValueError
                    return data, status
        except WorkvivoError:
            raise
        except Exception:
            raise WorkvivoError("Workvivo request outcome could not be verified", status, write) from None

    def record(self, row, resource, status=200):
        try:
            if not isinstance(row, dict):
                raise ValueError
            ident = _response_id(row.get("id"))
            label = row.get("name" if resource in {"users", "spaces"} else "title")
            if not isinstance(label, str) or not label or len(label) > 1000:
                raise ValueError
            result = {"id": ident, "name" if resource in {"users", "spaces"} else "title": label}
            # Deliberately omit employee email/phones/DOB, HTML, media and nested creator identities.
            allowed = {"users": ("display_name", "job_title", "timezone", "locale", "has_access", "is_frontline"),
                "spaces": ("visibility", "is_external", "is_corporate", "is_mandatory", "is_read_only"),
                "pages": ("slug", "subtitle", "space_id", "is_draft", "is_standalone", "is_sidebar_enabled"),
                "articles": ("slug", "subtitle", "is_archived", "published_at", "archive_at"),
                "events": ("scheduled_at", "ends_at", "all_day_event")}[resource]
            for key in (*allowed, "created_at", "updated_at"):
                if key not in row:
                    continue
                value = row[key]
                if key == "space_id":
                    value = None if value is None else _response_id(value)
                elif key.startswith("is_") or key in {"has_access", "all_day_event"}:
                    if type(value) is not bool:
                        raise ValueError
                elif value is not None and (not isinstance(value, str) or len(value) > 4096):
                    raise ValueError
                result[key] = value
            return result
        except Exception:
            raise WorkvivoError("Workvivo returned unverified record metadata", status) from None

    def continuation(self, href, resource, size, filters, previous_skip=None):
        try:
            if not isinstance(href, str) or len(href) > 8192 or not href.isascii() or any(ord(c) < 33 for c in href):
                raise ValueError
            url, base = urlsplit(href), urlsplit(self.base + "/" + resource)
            if url.scheme != base.scheme or url.netloc != base.netloc or url.path != base.path or url.fragment or url.username or url.password:
                raise ValueError
            pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
            params = dict(pairs)
            if len(pairs) != len(params) or set(params) != {"skip", "take", *filters} or params.get("take") != str(size):
                raise ValueError
            if any(params.get(key) != str(value) for key, value in filters.items()):
                raise ValueError
            skip = params["skip"]
            if not re.fullmatch(r"0|[1-9][0-9]{0,11}", skip):
                raise ValueError
            if previous_skip is not None and int(skip) <= previous_skip:
                raise ValueError
            return href, int(skip)
        except Exception:
            raise WorkvivoError("Workvivo pagination must advance within this exact tenant, resource and filters") from None

    async def page(self, resource, size=25, href=None, filters=None, raw=False):
        filters = filters or {}
        skip = 0
        if href is not None:
            href, skip = self.continuation(href, resource, size, filters)
        data, status = await self.request("GET", resource,
            params=None if href else {"skip": "0", "take": str(size), **filters}, href=href)
        rows, pagination = data["data"], data["meta"].get("pagination")
        if not isinstance(rows, list) or len(rows) > size or not isinstance(pagination, dict):
            raise WorkvivoError("Workvivo returned unverified collection metadata", status)
        if type(pagination.get("skip")) is not int or pagination["skip"] != skip or type(pagination.get("take")) is not int or pagination["take"] != size or "next_page" not in pagination:
            raise WorkvivoError("Workvivo returned unverified pagination metadata", status)
        projected = [self.record(row, resource, status) for row in rows]
        if len({row["id"] for row in projected}) != len(projected):
            raise WorkvivoError("Workvivo returned duplicate resource IDs", status)
        if resource == "pages":
            for row in projected:
                if "space_id" not in row or row["space_id"] != filters.get("space_id"):
                    raise WorkvivoError("Workvivo returned a page outside the selected location", status)
        next_url = pagination["next_page"]
        if next_url is not None:
            try:
                next_url, _ = self.continuation(next_url, resource, size, filters, skip)
            except WorkvivoError:
                raise WorkvivoError("Workvivo returned an unsafe continuation link", status) from None
            if not rows:
                raise WorkvivoError("Workvivo returned an empty nonadvancing page", status)
        if "total_records" in pagination and (type(pagination["total_records"]) is not int or pagination["total_records"] < skip + len(rows)):
            raise WorkvivoError("Workvivo returned an unverified total count", status)
        out = {"items": rows if raw else projected, "next_page_url": next_url, "snapshot_verified": False}
        if "total_records" in pagination:
            out["total_records"] = pagination["total_records"]
        return out, status

    async def find_page(self, ident, space, maximum):
        href, seen = None, set()
        for _ in range(maximum):
            page, status = await self.page("pages", 100, href, {"space_id": space} if space else {}, raw=True)
            for row in page["items"]:
                if _response_id(row["id"]) == ident:
                    return row, status
            href = page["next_page_url"]
            if href is None:
                raise WorkvivoError("Page ID was not present in the selected current location", status)
            if href in seen:
                raise WorkvivoError("Workvivo returned a repeated page continuation", status)
            seen.add(href)
        raise WorkvivoError("Page scan limit reached; no mutation was sent")

    def editable_draft(self, row, space, status):
        try:
            self.record(row, "pages", status)
            if row.get("is_draft") is not True or "external_id" not in row or row["external_id"] is not None:
                raise ValueError
            if (None if row.get("space_id") is None else _response_id(row["space_id"])) != space:
                raise ValueError
            if not isinstance(row.get("title"), str) or not row["title"] or not isinstance(row.get("html_content"), str) or not row["html_content"] or len(row["html_content"]) > 100000:
                raise ValueError
            if row.get("subtitle") is not None and (not isinstance(row["subtitle"], str) or len(row["subtitle"]) > 1000):
                raise ValueError
            for key in ("is_standalone", "is_sidebar_enabled"):
                if type(row.get(key)) is not bool:
                    raise ValueError
            # Full PUT cannot preserve unsupported media, translation or presentation state.
            if "featured_image" not in row or row["featured_image"] is not None or "language_variants" not in row or row["language_variants"] != [] or row.get("hide_title_and_subtitle", False) is not False:
                raise ValueError
            if row.get("parent_id") is not None or row.get("external_parent_id") is not None:
                raise ValueError
            audience = row.get("audience")
            if not isinstance(audience, dict) or type(audience.get("is_global")) is not bool or not isinstance(audience.get("spaces"), list) or audience.get("teams") != []:
                raise ValueError
            audience_spaces = [_response_id(item["id"]) for item in audience["spaces"]]
            if audience["is_global"] != (space is None) or audience_spaces != ([] if space is None else [space]):
                raise ValueError
            return {"title": row["title"], "subtitle": row.get("subtitle") or "", "html_content": row["html_content"],
                "is_draft": "1", "is_standalone": str(int(row["is_standalone"])),
                "is_sidebar_enabled": str(int(row["is_sidebar_enabled"])), **({"space_id": space} if space else {})}
        except Exception:
            raise WorkvivoError("Only a verified ordinary draft without external IDs, parent/media/translation or extra audience state can be changed by this node", status) from None


OPERATIONS = ("list_users", "get_user", "list_spaces", "get_space", "list_pages", "find_page",
    "create_draft_page", "update_draft_page", "delete_draft_page", "list_articles", "get_article", "list_events", "get_event")


class WorkvivoNode(WorkflowNode):
    integration_type = "automation-workvivo"
    scope_registry = ScopeRegistry("workvivo", {name: ScopeRequirement(credential_types=(FAMILY,),
        note="Workvivo app endpoint and visibility permissions are tenant-managed; the static key requests no OAuth scopes.") for name in OPERATIONS})
    connection_evidence = ConnectionEvidence(operation="list_spaces", noun="spaces", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return WorkvivoNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type") not in (None, FAMILY):
            raise ValueError("Use current Workvivo API-key credentials")
        return super().parse_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            session = WorkvivoSession(WorkvivoAPIKeyCredential.model_validate(credential_data))
            await session.page("spaces", 5)
            return {"valid": True, "name": None}
        except WorkvivoError as error:
            return {"valid": False if error.status_code in {401, 403} else None, "name": None,
                "error": str(error), "status_code": error.status_code}
        except Exception:
            return {"valid": False, "name": None, "error": "Use a valid static key and exact tenant API base and organisation header"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        resource = {"user_id": "users", "space_id": "spaces", "page_id": "pages",
            "article_id": "articles", "event_id": "events"}.get(field_name)
        if resource is None:
            return {"options": [], "next_page_token": None}
        context, filters = context or {}, {}
        if resource == "pages":
            scope = PageScope.model_validate({key: context[key] for key in ("page_scope", "space_id") if key in context})
            # A default is valid in execute, but dependent lookup needs an explicit location.
            if "page_scope" not in context:
                raise ValueError("Choose Global or Space before loading pages")
            if scope.space_id:
                filters["space_id"] = scope.space_id
        if resource == "events":
            filters["upcoming_only"] = "1"
        session = WorkvivoSession(WorkvivoAPIKeyCredential.model_validate(credential_data))
        page, _ = await session.page(resource, 25, page_token, filters)
        options = []
        for row in page["items"]:
            label = row.get("name") or row["title"]
            if not search or search.casefold() in label.casefold():
                options.append({"value": row["id"], "label": session.redact(label)})
        return {"options": options, "next_page_token": page["next_page_url"]}

    async def execute(self, input_data):
        session, mutation, status = None, False, None
        try:
            if self.config.credentials is None:
                raise ValueError
            config = self.config.config
            self.scope_registry.require(config.operation)
            session = WorkvivoSession(self.config.credentials)
            filters = {}
            if isinstance(config, PageScope) and config.space_id:
                filters["space_id"] = config.space_id
            if isinstance(config, DateRange):
                for key, value in (("from", config.from_timestamp), ("to", config.to_timestamp)):
                    if value is not None:
                        filters[key] = str(value)
            if isinstance(config, ListSpaces):
                if config.name is not None:
                    filters["name"] = config.name
                if config.visibility is not None:
                    filters["visibility"] = config.visibility
            if isinstance(config, ListEvents):
                filters["upcoming_only"] = str(int(config.upcoming_only))
            if isinstance(config, (ListUsers, ListSpaces, ListPages, ListArticles, ListEvents)):
                resource = {"list_users": "users", "list_spaces": "spaces", "list_pages": "pages",
                    "list_articles": "articles", "list_events": "events"}[config.operation]
                output, status = await session.page(resource, config.page_size, config.next_page_url, filters)
            elif isinstance(config, (GetUser, GetSpace, GetArticle, GetEvent)):
                resource, ident = {"get_user": ("users", getattr(config, "user_id", None)),
                    "get_space": ("spaces", getattr(config, "space_id", None)),
                    "get_article": ("articles", getattr(config, "article_id", None)),
                    "get_event": ("events", getattr(config, "event_id", None))}[config.operation]
                data, status = await session.request("GET", resource + "/" + ident)
                record = session.record(data["data"], resource, status)
                if record["id"] != ident:
                    raise WorkvivoError("Workvivo returned a different resource ID", status)
                output = {"record": record}
            elif isinstance(config, FindPage):
                row, status = await session.find_page(config.page_id, config.space_id, config.max_scan_pages)
                output = {"record": session.record(row, "pages", status), "snapshot_verified": False}
            else:
                resource, form, method = "pages", None, "POST"
                if isinstance(config, CreateDraftPage):
                    if config.space_id:
                        parent, status = await session.request("GET", "spaces/" + config.space_id)
                        if session.record(parent["data"], "spaces", status)["id"] != config.space_id:
                            raise WorkvivoError("Workvivo did not verify the selected current space", status)
                    form = {"title": config.title, "subtitle": config.subtitle, "html_content": config.html_content,
                        "is_draft": "1", "is_standalone": "0", "is_sidebar_enabled": "0", **filters}
                else:
                    row, status = await session.find_page(config.page_id, config.space_id, config.max_scan_pages)
                    form = session.editable_draft(row, config.space_id, status)
                    resource += "/" + config.page_id
                    method = "DELETE" if isinstance(config, DeleteDraftPage) else "PUT"
                    if method == "DELETE":
                        form = None
                    else:
                        for name in ("title", "subtitle", "html_content"):
                            value = getattr(config, name)
                            if value is not None:
                                form[name] = value
                mutation = True
                data, status = await session.request(method, resource, form=form)
                if method == "DELETE":
                    if not isinstance(data["data"], dict) or _response_id(data["data"].get("id")) != config.page_id:
                        raise WorkvivoError("Workvivo returned an unverified deletion acknowledgement", status, True)
                    output = {"deleted_id": config.page_id}
                else:
                    record = session.record(data["data"], "pages", status)
                    if record.get("is_draft") is not True or record.get("space_id") != config.space_id or (method == "PUT" and record["id"] != config.page_id):
                        raise WorkvivoError("Workvivo did not acknowledge the expected draft location/state", status, True)
                    if data["data"].get("title") != form["title"] or data["data"].get("html_content") != form["html_content"] or (data["data"].get("subtitle") or "") != form["subtitle"]:
                        raise WorkvivoError("Workvivo did not acknowledge the expected draft content", status, True)
                    if any(data["data"].get(key) is not (form[key] == "1") for key in ("is_standalone", "is_sidebar_enabled")):
                        raise WorkvivoError("Workvivo did not acknowledge the preserved page flags", status, True)
                    output = {"record": record}
                output.update(provider_acknowledged=True, readback_verified=False, status_code=status,
                    preflight_atomic=False, notification_behavior_verified=False)
            return session.redact({"status": "success", **output})
        except WorkvivoError as error:
            return {"status": "error", "error": str(error), "status_code": error.status_code,
                "uncertain_outcome": error.uncertain or mutation and error.status_code in {200, 201}}
        except Exception:
            return {"status": "error", "error": "Workvivo configuration or response could not be verified",
                "status_code": status, "uncertain_outcome": mutation}
