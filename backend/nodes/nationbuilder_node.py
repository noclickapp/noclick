"""NationBuilder v2 JSON:API CRM operations for a supplied, nation-bound token.

Uses staging credential loading with a supplied, non-refreshing token. Outputs omit
private contact, political, financial and credential data rather than raw records.
"""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import is_placeholder, is_url_shaped
from utils.ssrf import SSRFError, guarded_async_client

NODE_TYPE = "automation-nationbuilder"
FAMILIES = {"nationbuilder_v2_token"}
MEDIA = "application/vnd.api+json"
MAX_BYTES = 2_097_152
Id = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Name = Annotated[StrictStr, Field(min_length=1, max_length=200)]
Page = Annotated[StrictInt, Field(ge=1, le=1_000_000)]


class NationBuilderV2TokenCredential(BaseModel):
    """An existing v2 JWT; NoClick does not register or impersonate an OAuth app."""
    model_config = ConfigDict(title="NationBuilder V2 Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://nationbuilder.com/api/v2/reference"})
    credential_type: Literal["nationbuilder_v2_token"] = Field("nationbuilder_v2_token", json_schema_extra={"ui:hidden": True})
    nation_slug: StrictStr = Field(..., min_length=1, max_length=63, title="Nation slug", description="Only the nation subdomain, such as acme, from acme.nationbuilder.com. Custom domains and arbitrary URLs are not supported.")
    access_token: StrictStr = Field(..., min_length=1, max_length=16384, repr=False, title="V2 access token", description="Paste an existing v2 JWT, without Bearer. V1 tokens do not work. V2 tokens expire after 24 hours; replace an expired token. This connection does not mint or refresh tokens.", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[StrictStr] = Field(None, title="Known token expiry", description="Optional actual expiry supplied with your token, in ISO 8601 with timezone. It is not inferred from an unverified JWT.")

    @field_validator("nation_slug")
    @classmethod
    def slug(cls, value):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value) or value in {"www", "api", "support", "assets", "marketing", "setup", "status", "uptime"} or is_placeholder(value):
            raise ValueError("Supply the lowercase nation slug, without a URL or reserved host")
        return value

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value) or is_placeholder(value) or is_url_shaped(value):
            raise ValueError("Supply an existing v2 JWT without a header, placeholder or control characters")
        return value

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value is not None:
            _expiry(value)
        return value


def _expiry(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Use the actual ISO 8601 token expiry with timezone") from None


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") not in FAMILIES:
        raise ValueError("Connect a native NationBuilder v2 token")
    try:
        return NationBuilderV2TokenCredential.model_validate(raw)
    except ValueError:
        raise ValueError("Supply a valid nation-bound NationBuilder v2 token") from None


def _picker(name, parents=None):
    value = {"field_name": name, "searchable": True, "allow_custom": True}
    if parents:
        value["depends_on"] = parents
    return {"x-dynamic-options": value}


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def text(cls, value):
        if isinstance(value, str) and (value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use metadata without surrounding whitespace or control characters")
        return value


class _Page(_Config):
    page_number: Page = 1
    page_size: Annotated[StrictInt, Field(ge=1, le=100)] = 20


class NationBuilderGetMeConfig(_Config):
    """Read the signup assigned to the protected v2 token."""
    operation: Literal["get_me"] = "get_me"


class NationBuilderListSignupsConfig(_Page):
    """Read minimal CRM signup metadata; no sensitive attributes or sideloads."""
    operation: Literal["list_signups"] = "list_signups"
    last_name_prefix: Optional[Name] = None


class NationBuilderGetSignupConfig(_Config):
    """Read a signup by its explicit nation-local identifier."""
    operation: Literal["get_signup"] = "get_signup"
    signup_id: Id = Field(..., json_schema_extra=_picker("signup_id"))


class _SignupAttributes(_Config):
    first_name: Optional[Name] = None
    last_name: Optional[Name] = None
    email: Optional[Annotated[StrictStr, Field(min_length=3, max_length=254)]] = Field(None, description="Ordinary CRM email field; not returned in output. This does not opt a person into messages.")

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+", value):
            raise ValueError("Supply one email address")
        return value

    @model_validator(mode="after")
    def attributes(self):
        if all(getattr(self, key) is None for key in ("first_name", "last_name", "email")):
            raise ValueError("Supply at least one ordinary signup attribute")
        return self


class NationBuilderCreateSignupConfig(_SignupAttributes):
    """Create an ordinary CRM signup, without subscriptions or sideposting."""
    operation: Literal["create_signup"] = "create_signup"


class NationBuilderUpdateSignupConfig(_SignupAttributes):
    """Update only the supplied basic CRM fields; unspecified fields are omitted."""
    operation: Literal["update_signup"] = "update_signup"
    signup_id: Id = Field(..., json_schema_extra=_picker("signup_id"))


class NationBuilderListTagsConfig(_Page):
    """Read nation-local signup tag metadata."""
    operation: Literal["list_tags"] = "list_tags"
    signup_id: Optional[Id] = Field(None, json_schema_extra=_picker("signup_id"))


class NationBuilderGetTagConfig(_Config):
    """Read one signup tag."""
    operation: Literal["get_tag"] = "get_tag"
    tag_id: Id = Field(..., json_schema_extra=_picker("tag_id"))


class NationBuilderCreateTagConfig(_Config):
    """Create an ordinary signup tag; configured provider automations may react."""
    operation: Literal["create_tag"] = "create_tag"
    name: Name


class NationBuilderUpdateTagConfig(_Config):
    """Rename a signup tag."""
    operation: Literal["update_tag"] = "update_tag"
    tag_id: Id = Field(..., json_schema_extra=_picker("tag_id"))
    name: Name


class NationBuilderDeleteTagConfig(_Config):
    """Permanently delete a selected tag, not its signup records."""
    operation: Literal["delete_tag"] = "delete_tag"
    tag_id: Id = Field(..., json_schema_extra=_picker("tag_id"))


class NationBuilderListListsConfig(_Page):
    """Read custom list metadata."""
    operation: Literal["list_lists"] = "list_lists"


class NationBuilderGetListConfig(_Config):
    """Read one custom list."""
    operation: Literal["get_list"] = "get_list"
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))


class NationBuilderCreateListConfig(_Config):
    """Create a custom list without widening sharing permissions."""
    operation: Literal["create_list"] = "create_list"
    name: Name
    description: Optional[Annotated[StrictStr, Field(min_length=1, max_length=1000)]] = None


class NationBuilderUpdateListConfig(NationBuilderCreateListConfig):
    """Update the selected custom list's ordinary name and description."""
    operation: Literal["update_list"] = "update_list"
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))


class NationBuilderDeleteListConfig(_Config):
    """Permanently delete a list; this is a record mutation."""
    operation: Literal["delete_list"] = "delete_list"
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))


class NationBuilderListListSignupsConfig(_Page):
    """Read minimal signup metadata under a verified custom list."""
    operation: Literal["list_list_signups"] = "list_list_signups"
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))


class NationBuilderListSignupTaggingsConfig(_Page):
    """Read tagging associations, optionally scoped to a verified signup."""
    operation: Literal["list_signup_taggings"] = "list_signup_taggings"
    signup_id: Optional[Id] = Field(None, json_schema_extra=_picker("signup_id"))


class NationBuilderTagSignupConfig(_Config):
    """Associate an existing signup and tag after checking both parents."""
    operation: Literal["tag_signup"] = "tag_signup"
    signup_id: Id = Field(..., json_schema_extra=_picker("signup_id"))
    tag_id: Id = Field(..., json_schema_extra=_picker("tag_id"))


class NationBuilderUntagSignupConfig(_Config):
    """Delete only a tagging whose signup and tag match the selected parents."""
    operation: Literal["untag_signup"] = "untag_signup"
    signup_id: Id = Field(..., json_schema_extra=_picker("signup_id"))
    tag_id: Id = Field(..., json_schema_extra=_picker("tag_id"))
    tagging_id: Id = Field(..., json_schema_extra=_picker("tagging_id", ["signup_id", "tag_id"]))


class _Membership(_Config):
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))
    signup_ids: Annotated[list[Id], Field(min_length=1, max_length=100)] = Field(..., description="Up to 100 unique signup IDs per node request (provider supports 10,000). Returns async acceptance, not completion.")

    @field_validator("signup_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Supply unique signup IDs")
        return value


class NationBuilderAddListSignupsConfig(_Membership):
    """Start an asynchronous addition to a custom list; no message is sent here."""
    operation: Literal["add_list_signups"] = "add_list_signups"


class NationBuilderRemoveListSignupsConfig(_Membership):
    """Start an asynchronous removal from a custom list."""
    operation: Literal["remove_list_signups"] = "remove_list_signups"


class NationBuilderGetAsyncProcessConfig(_Config):
    """Read the status of the process identifier returned by membership changes."""
    operation: Literal["get_async_process"] = "get_async_process"
    process_id: Id


NationBuilderConfig = Annotated[Union[NationBuilderGetMeConfig, NationBuilderListSignupsConfig, NationBuilderGetSignupConfig, NationBuilderCreateSignupConfig, NationBuilderUpdateSignupConfig, NationBuilderListTagsConfig, NationBuilderGetTagConfig, NationBuilderCreateTagConfig, NationBuilderUpdateTagConfig, NationBuilderDeleteTagConfig, NationBuilderListListsConfig, NationBuilderGetListConfig, NationBuilderCreateListConfig, NationBuilderUpdateListConfig, NationBuilderDeleteListConfig, NationBuilderListListSignupsConfig, NationBuilderListSignupTaggingsConfig, NationBuilderTagSignupConfig, NationBuilderUntagSignupConfig, NationBuilderAddListSignupsConfig, NationBuilderRemoveListSignupsConfig, NationBuilderGetAsyncProcessConfig], Field(discriminator="operation")]


class NationBuilderNodeConfig(NodeConfig):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    config: NationBuilderConfig
    credentials: Optional[NationBuilderV2TokenCredential] = None


_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("nationbuilder_private_request", default=False)


class _PrivateRequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


for _logger in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "utils.ssrf"):
    logging.getLogger(_logger).addFilter(_PrivateRequestLogFilter())


class _AuthRefused(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("NationBuilder returned duplicate JSON properties")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("NationBuilder returned non-finite JSON")


def _text(value, maximum=1000):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("NationBuilder returned invalid text metadata")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("NationBuilder returned an invalid resource identifier")
    return value


FIELDS = {
    "signups": ("first_name", "last_name", "created_at", "updated_at"),
    "signup_tags": ("name", "taggings_count", "from_sharing_nation", "imported", "shared_with_nations"),
    "lists": ("name", "slug", "created_at", "updated_at", "signups_count"),
    "signup_taggings": ("signup_id", "tag_id", "created_at"),
}


def _fields(resource):
    return {f"fields[{resource}]": ",".join(FIELDS[resource])}


def _record(raw, resource, expected=None):
    if not isinstance(raw, dict) or raw.get("type") != resource or not isinstance(raw.get("attributes"), dict):
        raise ValueError("NationBuilder returned an invalid JSON:API resource")
    identifier = _id(raw.get("id"))
    if expected is not None and identifier != expected:
        raise ValueError("NationBuilder returned a different resource")
    result = {"id": identifier, "type": resource}
    for key in FIELDS[resource]:
        if key not in raw["attributes"]:
            continue
        value = raw["attributes"][key]
        if value is None:
            result[key] = None
            continue
        if key.endswith("_count"):
            if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
                raise ValueError("NationBuilder returned invalid count metadata")
        elif key in ("from_sharing_nation", "imported", "shared_with_nations"):
            if type(value) is not bool:
                raise ValueError("NationBuilder returned invalid boolean metadata")
        elif key in ("signup_id", "tag_id"):
            value = _id(value)
        else:
            if not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("NationBuilder returned invalid text metadata")
        result[key] = value
    return result


def _page(raw, resource, config, *, signup_id=None, tag_id=None):
    data = raw.get("data")
    if not isinstance(data, list) or len(data) > config.page_size:
        raise ValueError("NationBuilder returned an unbounded or missing page")
    rows = [_record(row, resource) for row in data]
    if len(rows) != len({row["id"] for row in rows}):
        raise ValueError("NationBuilder returned duplicate resource identifiers")
    for key, expected in (("signup_id", signup_id), ("tag_id", tag_id)):
        if expected is not None and any(row.get(key) != expected for row in rows):
            raise ValueError("NationBuilder returned a different tagging association")
    # V2 keeps a next link even when the following page will be empty. Never
    # follow provider links; closed page[number] requests end on an empty page.
    return {"items": rows, "returned_count": len(rows), "page_number": config.page_number,
            "page_size": config.page_size, "next_page_number": config.page_number + 1 if rows and config.page_number < 1_000_000 else None,
            "pagination_complete": not rows, "page_limit_reached": bool(rows) and config.page_number == 1_000_000}


class _Session:
    def __init__(self, credential):
        self.credential = credential

    async def request(self, method, path, *, params=None, body=None, expected_status=200):
        valid = (method == "GET" and re.fullmatch(r"/(?:signups(?:/me|/[A-Za-z0-9_-]{1,128})?|signup_tags(?:/[A-Za-z0-9_-]{1,128})?|lists(?:/[A-Za-z0-9_-]{1,128}(?:/signups)?)?|signup_taggings(?:/[A-Za-z0-9_-]{1,128})?|async_processes/[A-Za-z0-9_-]{1,128})", path))
        valid = valid or (method == "POST" and path in {"/signups", "/signup_tags", "/lists", "/signup_taggings"})
        valid = valid or (method == "PATCH" and re.fullmatch(r"/(?:signups|signup_tags|lists)/[A-Za-z0-9_-]{1,128}(?:/(?:add_signups|remove_signups))?", path) and (not path.endswith(("/add_signups", "/remove_signups")) or path.startswith("/lists/")))
        valid = valid or (method == "DELETE" and re.fullmatch(r"/(?:signup_tags|lists|signup_taggings)/[A-Za-z0-9_-]{1,128}", path))
        if not valid:
            raise ValueError("Unsupported NationBuilder v2 request")
        if body is not None and len(json.dumps(body, allow_nan=False).encode()) > 65_536:
            raise ValueError("NationBuilder request exceeds the bounded limit")
        if self.credential.expires_at and _expiry(self.credential.expires_at) <= datetime.now(timezone.utc):
            raise _AuthRefused("NationBuilder token has expired; reconnect (HTTP 401)")
        private = _PRIVATE_REQUEST.set(True)
        try:
            headers = {"Accept": MEDIA, "Authorization": "Bearer " + self.credential.access_token}
            if body is not None:
                headers["Content-Type"] = MEDIA
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=25.0) as client:
                async with client.stream(method, f"https://{self.credential.nation_slug}.nationbuilder.com/api/v2" + path, headers=headers, params=params, **({"json": body} if body is not None else {})) as response:
                    if response.status_code in (401, 403):
                        raise _AuthRefused(f"NationBuilder v2 token or permission was rejected (HTTP {response.status_code}); reconnect or check nation permissions")
                    if response.status_code != expected_status:
                        raise ValueError(f"NationBuilder request did not complete (HTTP {response.status_code}); no automatic retry")
                    media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    # The list-signups route is documented as application/json.
                    accepted = {MEDIA, "application/json"} if re.fullmatch(r"/lists/[A-Za-z0-9_-]{1,128}/signups", path) else {MEDIA}
                    if media not in accepted:
                        raise ValueError("NationBuilder returned an unsupported response format")
                    value = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(value) + len(chunk) > MAX_BYTES:
                            raise ValueError("NationBuilder response exceeds the bounded limit")
                        value.extend(chunk)
                    try:
                        raw = json.loads(value, object_pairs_hook=_unique, parse_constant=_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ValueError("NationBuilder returned invalid JSON metadata") from None
        except (httpx.HTTPError, SSRFError):
            raise ValueError("NationBuilder public HTTPS request could not complete") from None
        finally:
            _PRIVATE_REQUEST.reset(private)
        if not isinstance(raw, dict) or "errors" in raw or "code" in raw:
            raise ValueError("NationBuilder returned a failed v2 response")
        if self.credential.access_token in json.dumps(raw, ensure_ascii=False):
            raise ValueError("NationBuilder returned credential material in metadata")
        return raw


class NationBuilderNode(WorkflowNode):
    integration_type = "automation-nationbuilder"
    connection_evidence = ConnectionEvidence(noun="tags", operation="list_tags", operation_arguments={"page_size": 5}, identity_operation="get_me", label_keys=("name",), identity_keys=("name",), proves="account")

    @classmethod
    def get_config_model(cls):
        return NationBuilderNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"signup_id", "tag_id", "list_id", "tagging_id"}:
            raise ValueError("Unsupported NationBuilder picker")
        page = 1
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,6}", page_token) or int(page_token) > 1_000_000:
                raise ValueError("Use a bounded NationBuilder page number")
            page = int(page_token)
        if search is not None and (not isinstance(search, str) or len(search) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in search)):
            raise ValueError("Use a bounded metadata search")
        context = context or {}
        parents = {}
        if field_name == "tagging_id":
            parents = {key: _id(context.get(key)) for key in ("signup_id", "tag_id")}
        credential = _credential(credential_data)
        session = _Session(credential)
        resource = {"signup_id": "signups", "tag_id": "signup_tags", "list_id": "lists", "tagging_id": "signup_taggings"}[field_name]
        params = {**_fields(resource), "page[number]": str(page), "page[size]": "50"}
        for key, identifier in parents.items():
            parent_resource = "signups" if key == "signup_id" else "signup_tags"
            _record((await session.request("GET", f"/{parent_resource}/{identifier}", params=_fields(parent_resource))).get("data"), parent_resource, identifier)
            params[f"filter[{key}]"] = identifier
        if search and field_name != "tagging_id":
            params[f"filter[{'last_name' if resource == 'signups' else 'name'}][prefix]"] = search
        raw = await session.request("GET", "/" + resource, params=params)
        result = _page(raw, resource, _Page(page_number=page, page_size=50), **parents)
        options = []
        for row in result["items"]:
            label = " ".join(filter(None, (row.get("first_name"), row.get("last_name")))) if resource == "signups" else row.get("name")
            options.append({"value": row["id"], "label": label or row["id"]})
        return {"options": options, "next_page_token": str(result["next_page_number"]) if result["next_page_number"] else None}

    async def execute(self, inputs):
        if not isinstance(self.config, NationBuilderNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a nation-bound NationBuilder v2 token")
        result = await self._execute(_Session(self.config.credentials), self.config.config)
        return {"status": "success", "data": result}

    async def _execute(self, session, config):
        op = config.operation
        if op == "get_me":
            row = _record((await session.request("GET", "/signups/me", params=_fields("signups"))).get("data"), "signups")
            row["name"] = " ".join(filter(None, (row.get("first_name"), row.get("last_name")))) or row["id"]
            return row
        reads = {"get_signup": ("signups", "signup_id"), "get_tag": ("signup_tags", "tag_id"), "get_list": ("lists", "list_id")}
        if op in reads:
            resource, key = reads[op]
            identifier = getattr(config, key)
            return _record((await session.request("GET", f"/{resource}/{identifier}", params=_fields(resource))).get("data"), resource, identifier)
        lists = {"list_signups": "signups", "list_tags": "signup_tags", "list_lists": "lists", "list_list_signups": "signups", "list_signup_taggings": "signup_taggings"}
        if op in lists:
            resource, path = lists[op], "/" + lists[op]
            params = {**_fields(resource), "page[number]": str(config.page_number), "page[size]": str(config.page_size)}
            if op == "list_list_signups":
                _record((await session.request("GET", f"/lists/{config.list_id}", params=_fields("lists"))).get("data"), "lists", config.list_id)
                path = f"/lists/{config.list_id}/signups"
            signup = getattr(config, "signup_id", None)
            if signup:
                _record((await session.request("GET", f"/signups/{signup}", params=_fields("signups"))).get("data"), "signups", signup)
                params["filter[signup_id]"] = signup
            if op == "list_signups" and config.last_name_prefix:
                params["filter[last_name][prefix]"] = config.last_name_prefix
            raw = await session.request("GET", path, params=params)
            return _page(raw, resource, config, signup_id=signup if resource == "signup_taggings" else None)
        mutations = {"create_signup": ("signups", None), "update_signup": ("signups", "signup_id"), "create_tag": ("signup_tags", None), "update_tag": ("signup_tags", "tag_id"), "create_list": ("lists", None), "update_list": ("lists", "list_id")}
        if op in mutations:
            resource, key = mutations[op]
            identifier = getattr(config, key) if key else None
            names = ("first_name", "last_name", "email") if resource == "signups" else ("name", "description") if resource == "lists" else ("name",)
            attrs = {name: getattr(config, name) for name in names if getattr(config, name) is not None}
            body = {"data": {"type": resource, "attributes": attrs}}
            path = "/" + resource
            if identifier:
                path += "/" + identifier
                body["data"]["id"] = identifier
            raw = await session.request("PATCH" if identifier else "POST", path, params=_fields(resource), body=body, expected_status=200 if identifier else 201)
            return {"record": _record(raw.get("data"), resource, identifier), "mutation_acknowledged": True, "readback_verified": False}
        if op in {"delete_tag", "delete_list", "untag_signup"}:
            resource, key = {"delete_tag": ("signup_tags", "tag_id"), "delete_list": ("lists", "list_id"), "untag_signup": ("signup_taggings", "tagging_id")}[op]
            identifier = getattr(config, key)
            path = f"/{resource}/{identifier}"
            row = _record((await session.request("GET", path, params=_fields(resource))).get("data"), resource, identifier)
            if op == "untag_signup" and (row.get("signup_id") != config.signup_id or row.get("tag_id") != config.tag_id):
                raise ValueError("Selected tagging does not belong to the selected signup and tag")
            raw = await session.request("DELETE", path)
            if set(raw) != {"meta"} or raw["meta"] != {}:
                raise ValueError("NationBuilder returned an invalid deletion acknowledgment")
            return {"id": identifier, "type": resource, "deletion_acknowledged": True, "readback_verified": False}
        if op == "tag_signup":
            for resource, identifier in (("signups", config.signup_id), ("signup_tags", config.tag_id)):
                _record((await session.request("GET", f"/{resource}/{identifier}", params=_fields(resource))).get("data"), resource, identifier)
            body = {"data": {"type": "signup_taggings", "attributes": {"signup_id": config.signup_id, "tag_id": config.tag_id}}}
            raw = await session.request("POST", "/signup_taggings", params=_fields("signup_taggings"), body=body, expected_status=201)
            row = _record(raw.get("data"), "signup_taggings")
            if row.get("signup_id") != config.signup_id or row.get("tag_id") != config.tag_id:
                raise ValueError("NationBuilder acknowledged a different tagging association")
            return {"record": row, "mutation_acknowledged": True, "readback_verified": False}
        if op in {"add_list_signups", "remove_list_signups"}:
            _record((await session.request("GET", f"/lists/{config.list_id}", params=_fields("lists"))).get("data"), "lists", config.list_id)
            body = {"data": {"id": config.list_id, "type": "lists", "signup_ids": config.signup_ids}}
            raw = await session.request("PATCH", f"/lists/{config.list_id}/{'add_signups' if op == 'add_list_signups' else 'remove_signups'}", body=body, expected_status=202)
            return {"list_id": config.list_id, "process_id": _id(raw.get("token")), "accepted": True, "completed": False, "readback_verified": False}
        if op == "get_async_process":
            raw = await session.request("GET", "/async_processes/" + config.process_id)
            if _id(raw.get("id")) != config.process_id:
                raise ValueError("NationBuilder returned a different asynchronous process")
            return {"process_id": config.process_id, "provider_status": _text(raw.get("status"), 100), "readback_verified": False}
        raise ValueError("Unsupported NationBuilder operation")
