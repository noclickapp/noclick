"""Mighty unified GraphQL API: closed metadata and explicit draft management.

The host API key and an externally issued OAuth access token are separate
families. This node neither creates an application nor mints/refreshes tokens.
"""
from __future__ import annotations
import base64
import contextvars
import hashlib
import hmac
import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.mighty_networks import MIGHTY_NETWORKS_SCOPES, MUTATION_SCOPES, TYPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN = "https://api.mn.co"
MAX_BODY = 2 * 1024 * 1024
ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_:/+.=~-]{0,511}$")]
_PRIVATE = contextvars.ContextVar("mighty_networks_private", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record): return not _PRIVATE.get()


for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks_proxy"):
    logging.getLogger(_name).addFilter(_PrivateFilter())


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:/+.=~-]{0,511}", value):
        raise ValueError("Supply an actual bounded Mighty resource ID.")
    return value


def _text(value, maximum=512, *, empty=False, multiline=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= maximum or any((ord(c) < 32 and not (multiline and c in "\n\r\t")) or ord(c) == 127 for c in value):
        raise ValueError("Supply bounded Mighty text without unsupported control characters.")
    return value


def _instant(value):
    try:
        parsed = datetime.fromisoformat(_text(value, 64).replace("Z", "+00:00"))
        if parsed.tzinfo is None: raise ValueError()
        return parsed
    except Exception: raise ValueError("Supply the actual timezone-qualified OAuth expiry.") from None


class _Credential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    network_id: str = Field(..., pattern=r"^[1-9][0-9]{0,19}$", title="Network Numeric ID", description="Actual numeric ID of the intended Mighty Network. Bound to every request and checked against network.resourceId; this form does not accept arbitrary hosts.")
    allow_management_writes: bool = Field(False, strict=True, description="Off by default. Enables private-space creation, names, collection/tag management and owned draft posts. Provider webhooks/automations may react; no notification suppression is promised for metadata writes.")
    @field_validator("network_id", mode="before")
    @classmethod
    def network(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value): raise ValueError("Supply the actual numeric Mighty Network ID.")
        return value
    @field_validator("api_key", "access_token", "client_id", mode="before", check_fields=False)
    @classmethod
    def secret_fields(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 32768 or any(ord(c) < 33 or ord(c) > 126 for c in value): raise ValueError("Supply already issued Mighty credential material without whitespace.")
        return value
    @field_validator("scope", mode="before", check_fields=False)
    @classmethod
    def scopes(cls, value):
        if value is None: return None
        if not isinstance(value, str) or not 1 <= len(value) <= 2048 or value != value.strip() or not re.fullmatch(r"[a-z_]+(?::[a-z_]+)+(?: [a-z_]+(?::[a-z_]+)+)*", value) or len(value.split()) > 64 or len(set(value.split())) != len(value.split()): raise ValueError("Supply the actual space-separated scope grant without duplicates.")
        return value


class MightyNetworksAPIKeyCredential(_Credential):
    model_config = ConfigDict(title="Mighty Networks API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.mightynetworks.com/api/api-keys"})
    credential_type: Literal["mighty_networks_api_key"] = Field("mighty_networks_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, title="Mighty API Host Key", json_schema_extra={"ui:widget": "password"}, description="Issued in Network Admin → Integrations → Mighty API. Acts as its host, holds host scopes only and never expires until revoked. Admin REST keys are a different credential. Scale or above is required by the vendor; your plan/access is unverified.")
    scope: Optional[str] = Field(None, description="Exact host scopes selected for this key, when known. Unknown stays unknown; these supplied labels are not independent provider proof.")
    @field_validator("scope")
    @classmethod
    def host_scopes(cls, value):
        if value is not None and any(not scope.startswith("host:") for scope in value.split()): raise ValueError("Mighty API keys accept host scopes only.")
        return value


class MightyNetworksSuppliedOAuthCredential(_Credential):
    model_config = ConfigDict(title="Mighty Networks Supplied OAuth", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.mightynetworks.com/api/authentication"})
    credential_type: Literal["mighty_networks_supplied_oauth"] = Field("mighty_networks_supplied_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing OAuth Access Token", json_schema_extra={"ui:widget": "password"}, description="Already issued token for a specific user and Network. NoClick does not register an app, perform consent, exchange a code or refresh this supplied grant.")
    client_id: str = Field(..., repr=False, description="Actual application Client ID that issued this token, retained as supplied grant context.")
    scope: str = Field(..., description="Exact scope from the successful token response, not the requested scope list. Member and host grants differ; role and plan remain vendor-enforced.")
    expires_at: str = Field(..., description="Actual expiry calculated from the issuing response. Tokens are short-lived, typically one hour; expired tokens must be replaced externally.")
    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value): _instant(value); return value


MightyNetworksCredential = Annotated[Union[MightyNetworksAPIKeyCredential, MightyNetworksSuppliedOAuthCredential], Discriminator("credential_type")]


def _credential(value):
    if isinstance(value, (MightyNetworksAPIKeyCredential, MightyNetworksSuppliedOAuthCredential)): return value
    if not isinstance(value, dict) or value.get("credential_type") not in TYPES: raise ValueError("Attach a native Mighty API key or supplied OAuth credential.")
    try: return TypeAdapter(MightyNetworksCredential).validate_python({k: v for k, v in value.items() if k not in ("token_version", "updated_at")})
    except Exception: raise ValueError("Check the native Mighty credential family, Network ID, actual grant and write policy.") from None


def _bearer(credential): return credential.api_key if isinstance(credential, MightyNetworksAPIKeyCredential) else credential.access_token


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    @field_validator("space_id", "post_id", "tag_id", "collection_id", "template_canonical_name", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value): return _id(value)
    @field_validator("title", "name", "description", "body_text", mode="before", check_fields=False)
    @classmethod
    def text_fields(cls, value, info): return _text(value, 8192 if info.field_name == "body_text" else 512, multiline=info.field_name == "body_text") if value is not None else None


def _op(value, label, category="Metadata"):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _resource(kind, parent=None):
    options = {"field_name": kind + "_id", "searchable": True, "allow_custom": True}
    if parent: options["depends_on"] = parent
    return {"x-resource-type": "mighty_networks_" + kind, "x-dynamic-options": options}


class _Page(_Config):
    limit: int = Field(25, strict=True, ge=1, le=50)
    page_token: Optional[str] = Field(None, max_length=8192, description="Native continuation bound to this grant, Network, operation, selected Space, filter and page size. Not an arbitrary provider cursor or URL.")
class _Space(_Config):
    space_id: ID = Field(..., json_schema_extra=_resource("space"))
class _Post(_Space):
    post_id: ID = Field(..., json_schema_extra=_resource("post", "space_id"))
class _Tag(_Config):
    tag_id: ID = Field(..., json_schema_extra=_resource("tag"))
class _Collection(_Config):
    collection_id: ID = Field(..., json_schema_extra=_resource("collection"))
class _Title(_Config):
    title: str = Field(..., min_length=1, max_length=512)
class _Name(_Config):
    name: str = Field(..., min_length=1, max_length=512)
class _DraftBody(_Title):
    body_text: str = Field(..., min_length=1, max_length=8192, json_schema_extra={"ui:widget": "textarea"}, description="Plain draft content. Escaped before sending to the style-HTML body input; never published or fetched as media. Readback text normalization can leave completion unknown.")


class MightyNetworksTestConfig(_Config):
    operation: Literal["test_connection"] = _op("test_connection", "Test User and Network")
class MightyNetworksMeConfig(_Config):
    operation: Literal["get_me"] = _op("get_me", "Get Current User Metadata")
class MightyNetworksNetworkConfig(_Config):
    operation: Literal["get_network"] = _op("get_network", "Get Network Metadata")
class MightyNetworksSpacesConfig(_Page):
    operation: Literal["list_spaces"] = _op("list_spaces", "List Spaces")
class MightyNetworksSpaceConfig(_Space):
    operation: Literal["get_space"] = _op("get_space", "Get Space Metadata")
class MightyNetworksTemplatesConfig(_Config):
    operation: Literal["list_space_templates"] = _op("list_space_templates", "List Space Templates")
class MightyNetworksCreateSpaceConfig(_Title):
    operation: Literal["create_private_space"] = _op("create_private_space", "Create Private Space", "Management")
    template_canonical_name: ID = Field(..., json_schema_extra={"x-dynamic-options": {"field_name": "template_canonical_name", "searchable": True, "allow_custom": True}}, description="Actual template returned by this Network. Build-your-own templates require feature setup and are excluded from this form.")
class MightyNetworksRenameSpaceConfig(_Space, _Title):
    operation: Literal["rename_space"] = _op("rename_space", "Rename Space", "Management")
class MightyNetworksCollectionsConfig(_Config):
    operation: Literal["list_collections"] = _op("list_collections", "List Collections")
class MightyNetworksCollectionConfig(_Collection):
    operation: Literal["get_collection"] = _op("get_collection", "Get Collection Metadata")
class MightyNetworksCreateCollectionConfig(_Name):
    operation: Literal["create_collection"] = _op("create_collection", "Create or Reuse Collection", "Management")
class MightyNetworksRenameCollectionConfig(_Collection, _Name):
    operation: Literal["rename_collection"] = _op("rename_collection", "Rename Collection", "Management")
class MightyNetworksDeleteCollectionConfig(_Collection):
    operation: Literal["delete_empty_collection"] = _op("delete_empty_collection", "Delete Empty Collection", "Management")
class MightyNetworksTagsConfig(_Page):
    operation: Literal["list_tags"] = _op("list_tags", "List Tag Definitions")
class MightyNetworksTagConfig(_Tag):
    operation: Literal["get_tag"] = _op("get_tag", "Get Tag Definition")
class MightyNetworksCreateTagConfig(_Title):
    operation: Literal["create_tag"] = _op("create_tag", "Create Tag Definition", "Management")
    description: Optional[str] = Field(None, max_length=512)
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
class MightyNetworksUpdateTagConfig(_Tag, _Title):
    operation: Literal["update_tag"] = _op("update_tag", "Rename Tag Definition", "Management")
class MightyNetworksDeleteTagConfig(_Tag):
    operation: Literal["delete_tag"] = _op("delete_tag", "Delete Tag Definition", "Management",)
class MightyNetworksPostsConfig(_Space, _Page):
    operation: Literal["list_posts"] = _op("list_posts", "List Space Post Metadata")
    status: Optional[Literal["DRAFT", "POSTED", "SCHEDULED"]] = Field(None, description="Optional actual lifecycle filter. This operation never publishes content.")
class MightyNetworksPostConfig(_Post):
    operation: Literal["get_post"] = _op("get_post", "Get Space Post Metadata")
class MightyNetworksCreatePostConfig(_Space, _DraftBody):
    operation: Literal["create_draft_post"] = _op("create_draft_post", "Create Owned Draft Post", "Drafts")
    post_type: Literal["post", "article"] = "post"
class MightyNetworksUpdatePostConfig(_Post, _DraftBody):
    operation: Literal["update_draft_post"] = _op("update_draft_post", "Update Owned Draft Post", "Drafts")
class MightyNetworksDeletePostConfig(_Post):
    operation: Literal["delete_draft_post"] = _op("delete_draft_post", "Delete Owned Draft Post", "Drafts")


MightyNetworksOperation = Annotated[Union[MightyNetworksTestConfig, MightyNetworksMeConfig, MightyNetworksNetworkConfig, MightyNetworksSpacesConfig, MightyNetworksSpaceConfig, MightyNetworksTemplatesConfig, MightyNetworksCreateSpaceConfig, MightyNetworksRenameSpaceConfig, MightyNetworksCollectionsConfig, MightyNetworksCollectionConfig, MightyNetworksCreateCollectionConfig, MightyNetworksRenameCollectionConfig, MightyNetworksDeleteCollectionConfig, MightyNetworksTagsConfig, MightyNetworksTagConfig, MightyNetworksCreateTagConfig, MightyNetworksUpdateTagConfig, MightyNetworksDeleteTagConfig, MightyNetworksPostsConfig, MightyNetworksPostConfig, MightyNetworksCreatePostConfig, MightyNetworksUpdatePostConfig, MightyNetworksDeletePostConfig], Discriminator("operation")]


class MightyNetworksNodeConfig(NodeConfig):
    # Flat nullable union is the current native credential-form/selector shape;
    # raw family admission and _credential use the literal discriminator first.
    credentials: Optional[Union[MightyNetworksAPIKeyCredential, MightyNetworksSuppliedOAuthCredential]] = None
    config: MightyNetworksOperation = Field(default_factory=MightyNetworksTestConfig)


class MightyNetworksDenied(ValueError): pass
class MightyNetworksUnavailable(ValueError): pass
class _Missing(MightyNetworksUnavailable): pass
class _Unknown(MightyNetworksUnavailable): pass


_NETWORK = "__typename id resourceId title"
_ME = "__typename id resourceId name"
_SPACE = "__typename id resourceId title discoverable explorable spacesCollection { id name }"
_TAG = "__typename id resourceId title description color createdAt updatedAt"
_COLLECTION = "__typename id name visibleToMembers"
_TEMPLATE = "__typename canonicalName title templateType"
_POST = "__typename id resourceId title status postType lastEditedAt createdAt updatedAt space { id resourceId } creator { id resourceId }"
_PAGE_INFO = "pageInfo { hasNextPage endCursor }"
_PROBE = "query NCMightyIdentity { me { " + _ME + " } network { " + _NETWORK + " } }"
_QUERIES = {
    "probe": _PROBE,
    "spaces": "query NCSpaces($first:Int!,$after:String){network{" + _NETWORK + " result:spaces(first:$first,after:$after){nodes{" + _SPACE + "} " + _PAGE_INFO + "}}}",
    "tags": "query NCTags($first:Int!,$after:String){network{" + _NETWORK + " result:tags(first:$first,after:$after){nodes{" + _TAG + "} " + _PAGE_INFO + "}}}",
    "posts": "query NCPosts($first:Int!,$after:String,$spaceId:ID!,$statuses:[PostStatus!]){network{" + _NETWORK + " result:posts(first:$first,after:$after,spaceId:$spaceId,postTypes:[POST,ARTICLE],statuses:$statuses){nodes{__typename ... on Post{" + _POST + "}} " + _PAGE_INFO + "}}}",
    "space": "query NCSpace($id:String!){network{" + _NETWORK + " result:space(idOrSlug:$id){" + _SPACE + "}}}",
    "tag": "query NCTag($id:ID!){network{" + _NETWORK + " result:tag(id:$id){" + _TAG + "}}}",
    "post": "query NCPost($id:String!){network{" + _NETWORK + " result:post(idOrSlug:$id){__typename ... on Post{" + _POST + "}}}}",
    "post_text": "query NCPostText($id:String!){network{" + _NETWORK + " result:post(idOrSlug:$id){__typename ... on Post{" + _POST + " bodyText}}}}",
    "collections": "query NCCollections{network{" + _NETWORK + " result:spacesCollections{" + _COLLECTION + "}}}",
    "templates": "query NCTemplates{network{" + _NETWORK + " result:spaceTemplates{" + _TEMPLATE + "}}}",
}
_MUTATIONS = {
    "create_private_space": ("createSpace", "CreateSpaceInput", "space", _SPACE),
    "rename_space": ("updateSpace", "UpdateSpaceInput", "space", _SPACE),
    "create_collection": ("createSpacesCollection", "CreateSpacesCollectionInput", "spacesCollection", _COLLECTION),
    "rename_collection": ("updateSpacesCollection", "UpdateSpacesCollectionInput", "spacesCollection", _COLLECTION),
    "delete_empty_collection": ("deleteSpacesCollection", "DeleteSpacesCollectionInput", "deletedSpacesCollectionId", None),
    "create_tag": ("createTag", "CreateTagInput", "tag", _TAG),
    "update_tag": ("updateTag", "UpdateTagInput", "tag", _TAG),
    "delete_tag": ("deleteTag", "DeleteTagInput", "tag", _TAG),
    "create_draft_post": ("createPost", "CreatePostInput", "post", _POST),
    "update_draft_post": ("updatePost", "UpdatePostInput", "post", _POST),
    "delete_draft_post": ("deletePost", "DeletePostInput", "deletedId", None),
}
for _operation, (_field, _input, _receipt, _selection) in _MUTATIONS.items():
    _QUERIES[_operation] = "mutation NCMightyMutation($input:" + _input + "!){result:" + _field + "(input:$input){errors " + _receipt + ("{" + _selection + "}" if _selection else "") + "}}"


def _record(raw, kind, *, selected=None, parent=None, text=False):
    try:
        typename = {"network": "Network", "me": "User", "space": "Space", "tag": "Tag", "collection": "SpacesCollection", "template": "SpaceTemplate", "post": "Post"}[kind]
        if not isinstance(raw, dict) or raw.get("__typename") != typename: raise ValueError()
        key = "canonicalName" if kind == "template" else "id"
        rid = _id(raw.get(key)); out = {key: rid}
        if kind in ("network", "me", "space", "tag", "post"): out["resourceId"] = _id(raw.get("resourceId"))
        if selected is not None and selected not in (rid, out.get("resourceId")): raise MightyNetworksDenied("Mighty returned a different selected resource ID.")
        for field in {"network": ("title",), "me": ("name",), "space": ("title",), "tag": ("title", "description", "color"), "collection": ("name",), "template": ("title", "templateType"), "post": ("title", "status", "postType")}[kind]:
            if field not in raw: raise ValueError()
            value = raw.get(field)
            if field in ("title", "name") and kind in ("space", "tag", "collection", "template") and value is None: raise ValueError()
            out[field] = _text(value, 512, empty=True) if value is not None else None
        required_dates = ("createdAt", "updatedAt", "lastEditedAt") if kind == "post" else ("createdAt", "updatedAt") if kind == "tag" else ()
        if any(field not in raw for field in required_dates): raise ValueError()
        if any(raw.get(field) is None for field in required_dates if field != "lastEditedAt"): raise ValueError()
        for field in ("createdAt", "updatedAt", "lastEditedAt"):
            if field in raw:
                if raw[field] is not None: _instant(raw[field])
                out[field] = raw[field]
        if kind == "space":
            if any(type(raw.get(k)) is not bool for k in ("discoverable", "explorable")): raise ValueError()
            out.update({k: raw[k] for k in ("discoverable", "explorable")})
            collection = raw.get("spacesCollection")
            if collection is not None and not isinstance(collection, dict): raise ValueError()
            out["collection_id"] = _id(collection.get("id")) if isinstance(collection, dict) else None
        if kind == "collection":
            if type(raw.get("visibleToMembers")) is not bool: raise ValueError()
            out["visibleToMembers"] = raw["visibleToMembers"]
        if kind == "post":
            if out["status"] is None or out["status"].upper() not in ("DRAFT", "POSTED", "SCHEDULED") or out["postType"] is None or out["postType"].lower() not in ("post", "article"): raise ValueError()
            space, creator = raw.get("space"), raw.get("creator")
            if not isinstance(space, dict) or not isinstance(creator, dict): raise ValueError()
            out["space_id"], out["creator_id"] = _id(space.get("id")), _id(creator.get("id"))
            if parent is not None and parent not in (out["space_id"], _id(space.get("resourceId"))): raise MightyNetworksDenied("Mighty post belongs to a different selected Space.")
            if text: out["bodyText"] = _text(raw.get("bodyText"), 8192, empty=True, multiline=True)
        return out
    except MightyNetworksDenied: raise
    except Exception: raise _Unknown("Mighty returned malformed or unsupported bounded metadata.") from None


def _continuation(credential, operation, limit, parent, status, *, token=None, cursor=None):
    binding = hashlib.sha256(json.dumps([credential.model_dump(), operation, limit, parent, status], sort_keys=True).encode()).hexdigest()
    secret = _bearer(credential).encode()
    if cursor is not None:
        body = base64.urlsafe_b64encode(json.dumps({"v": 1, "scope": binding, "cursor": cursor}, separators=(",", ":")).encode()).decode().rstrip("=")
        return body + "." + hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 8192: raise ValueError()
        body, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not isinstance(data, dict) or set(data) != {"v", "scope", "cursor"} or data["v"] != 1 or data["scope"] != binding: raise ValueError()
        return _text(data["cursor"], 2048)
    except Exception: raise ValueError("Mighty continuation no longer matches the current grant, Network, parent, filter or page size.") from None


class MightyNetworksNode(WorkflowNode):
    integration_type = "automation-mighty-networks"
    credential_provider_labels = {"mighty_networks": "Mighty Networks Account"}
    scope_registry = MIGHTY_NETWORKS_SCOPES
    connection_evidence = ConnectionEvidence(noun="Mighty Network", operation="test_connection", proves="account", label_keys=("network_title",), identity_keys=("user_id", "network_id"))
    edit_examples = ["List Spaces in my Mighty Network", "Read the selected Space's post metadata", "Create an owned draft article", "Rename a tag definition with management enabled"]
    @classmethod
    def get_config_model(cls): return MightyNetworksNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        credential = _credential(config_data["credentials"]) if isinstance(config_data, dict) and config_data.get("credentials") is not None else None
        try:
            view = runtime_config_view(config_data, MightyNetworksNodeConfig)
            if credential is not None: view["credentials"] = credential.model_dump()
            if isinstance(view.get("config"), dict):
                view["config"] = {k: v for k, v in view["config"].items() if not k.endswith("__label") and k not in ("_settings", "agent_tool_operations")}
                if not view["config"]: view.pop("config")
            return TypeAdapter(MightyNetworksNodeConfig).validate_python(view)
        except Exception: raise ValueError("Check the native Mighty operation, current credential and typed fields.") from None
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging resolves and authorizes saved credentials before calling the
        # node. Both native families are supplied grants; neither is refreshed.
        credential = _credential(credential_data)
        if isinstance(credential, MightyNetworksSuppliedOAuthCredential) and _instant(credential.expires_at) <= datetime.now(timezone.utc):
            raise MightyNetworksDenied("The supplied Mighty OAuth token expired; replace it with a fresh actual grant. Automatic refresh is not configured.")
        return credential.model_dump()

    @classmethod
    async def validate_credential_access(cls, data):
        from nodes.core.registry import NodeFactory
        try:
            credential = await cls.freshen_credential(data)
            node = NodeFactory.create_node(node_id="mighty-validation", node_type=cls.integration_type,
                node_data={"credentials": credential, "config": {"operation": "test_connection"}})
            await node.execute({})
        except MightyNetworksDenied:
            return {"valid": False, "error": "Mighty refused the current token, selected Network or protected probe permission."}
        except Exception:
            return {"valid": None, "error": "Mighty protected identity could not be verified."}
        return {"valid": True}

    @classmethod
    async def _transport(cls, key, variables, *, credential):
        if key not in _QUERIES: raise ValueError("Unsupported closed Mighty API operation.")
        path = "/networks/" + credential.network_id + "/graphql"
        assert_exact_url_origin(ORIGIN + path, ORIGIN)
        private = _PRIVATE.set(True)
        try:
            async with guarded_async_client( trust_env=False, follow_redirects=False, timeout=25) as client:
                async with client.stream("POST", ORIGIN + path, headers={"Authorization": "Bearer " + _bearer(credential), "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "NoClick/1.0 (+https://www.noclick.com)"}, json={"query": _QUERIES[key], "variables": variables}) as response:
                    if response.status_code == 401: raise MightyNetworksDenied("Mighty refused the Bearer credential; provider details withheld.")
                    if response.status_code != 200: raise _Unknown("Mighty request was not verified; Network/plan, challenge, rate or service failures need inspection. No automatic retry.")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in ("application/json", "application/graphql-response+json"): raise _Unknown("Mighty did not return documented GraphQL JSON.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_BODY: raise _Unknown("Mighty response exceeded the native byte bound.")
                        content.extend(chunk)
                    payload = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(payload, dict): raise _Unknown("Mighty omitted a GraphQL response object.")
                    if "errors" in payload:
                        errors = payload["errors"]
                        if not isinstance(errors, list): raise _Unknown("Mighty returned malformed GraphQL errors.")
                        if errors:
                            codes = [error.get("extensions", {}).get("code") if isinstance(error, dict) and isinstance(error.get("extensions", {}), dict) else None for error in errors]
                            if all(code in ("UNAUTHENTICATED", "FORBIDDEN") for code in codes): raise MightyNetworksDenied("Mighty refused token or protected operation permission; raw messages withheld.")
                            if all(code == "NOT_FOUND" for code in codes): raise _Missing("Mighty did not expose this resource in the current viewer's selected Network.")
                            raise _Unknown("Mighty returned GraphQL errors, including possible partial data; completion is unverified and raw messages are withheld.")
                    if not isinstance(payload.get("data"), dict): raise _Unknown("Mighty omitted completed GraphQL data.")
                    return payload["data"]
        except (MightyNetworksDenied, MightyNetworksUnavailable): raise
        except Exception: raise _Unknown("Mighty request or response could not be verified; no automatic retry.") from None
        finally: _PRIVATE.reset(private)

    async def execute(self, inputs):
        config, supplied = self.config.config, _credential(self.config.credentials)
        credential = _credential(await self.freshen_credential(supplied.model_dump()))
        operation = config.operation; self.scope_registry.require(operation)
        if operation in MUTATION_SCOPES:
            if not credential.allow_management_writes: raise MightyNetworksDenied("Management writes are disabled on this current Mighty credential.")
            if credential.scope is not None and not set(credential.scope.split()).intersection(MUTATION_SCOPES[operation]): raise MightyNetworksDenied("The supplied actual Mighty scope grant does not cover this mutation.")
        secret, calls, write_started = _bearer(credential), 0, False
        async def current():
            if isinstance(credential, MightyNetworksSuppliedOAuthCredential) and _instant(credential.expires_at) <= datetime.now(timezone.utc): raise MightyNetworksDenied("The supplied Mighty token expired before this request.")
        async def call(key, variables=None):
            nonlocal calls, write_started
            await current()
            if calls >= 12: raise _Unknown("Mighty native request budget exceeded.")
            if secret in json.dumps(variables or {}, allow_nan=False): raise ValueError("Keep credential material out of Mighty content fields.")
            calls += 1
            if key in _MUTATIONS: write_started = True
            try: return await self._transport(key, variables or {}, credential=credential)
            finally: await current()
        def result(data):
            if secret in json.dumps(data, allow_nan=False): raise _Unknown("Mighty echoed credential material; output withheld.")
            return {"action": operation, "data": data, **({"status": "unknown"} if data.get("outcome") == "unknown" else {})}
        def network(data):
            out = _record(data.get("network"), "network")
            if out["resourceId"] != credential.network_id: raise MightyNetworksDenied("Mighty returned a different selected Network.")
            return data["network"]
        async def read(key, rid=None, *, parent=None, text=False):
            data = await call(key, {"id": rid} if rid is not None else {})
            raw = network(data).get("result")
            if raw is None: raise _Missing("Mighty did not expose the selected resource to this viewer.")
            if key in ("collections", "templates"):
                if not isinstance(raw, list) or len(raw) > 200: raise _Unknown("Mighty array exceeds the complete native bound; no undocumented cursor is invented.")
                kind = "collection" if key == "collections" else "template"
                rows = [_record(row, kind) for row in raw]; field = "id" if kind == "collection" else "canonicalName"
                if len({row[field] for row in rows}) != len(rows): raise _Unknown("Mighty duplicated array identifiers.")
                return rows
            return _record(raw, "post" if key == "post_text" else key, selected=rid, parent=parent, text=text)
        identity = await call("probe"); network(identity)
        actor, net = _record(identity.get("me"), "me"), _record(identity["network"], "network")
        if operation == "test_connection": return result({"reachable": True, "authentication_verified": True, "account_identity_verified": True, "network_identity_verified": True, "user_id": actor["id"], "network_id": net["resourceId"], "network_title": net["title"], "grant_scope_verified": None, "entitlement_verified": None})
        if operation in ("get_me", "get_network"): return result(actor if operation == "get_me" else net)
        parent = getattr(config, "space_id", None)
        space = await read("space", parent) if parent else None
        if parent: parent = space["id"]
        if operation in ("list_spaces", "list_tags", "list_posts"):
            key = {"list_spaces": "spaces", "list_tags": "tags", "list_posts": "posts"}[operation]
            status = getattr(config, "status", None)
            cursor = _continuation(credential, operation, config.limit, parent, status, token=config.page_token) if config.page_token else None
            variables = {"first": config.limit, "after": cursor}
            if key == "posts": variables.update({"spaceId": parent, "statuses": [status] if status else None})
            raw = network(await call(key, variables)).get("result")
            if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list) or len(raw["nodes"]) > config.limit or not isinstance(raw.get("pageInfo"), dict) or type(raw["pageInfo"].get("hasNextPage")) is not bool: raise _Unknown("Mighty omitted bounded Relay nodes/pageInfo.")
            kind = {"spaces": "space", "tags": "tag", "posts": "post"}[key]
            rows = [_record(row, kind, parent=parent) for row in raw["nodes"]]
            if len({row["id"] for row in rows}) != len(rows): raise _Unknown("Mighty duplicated page IDs.")
            if status and any(row["status"].upper() != status for row in rows): raise _Unknown("Mighty returned posts outside the selected lifecycle filter.")
            more, end = raw["pageInfo"]["hasNextPage"], raw["pageInfo"].get("endCursor")
            if end is not None: _text(end, 2048)
            if more and (not rows or not end or end == cursor): raise _Unknown("Mighty continuation did not advance.")
            return result({"items": rows, "has_more": more, "next_page_token": _continuation(credential, operation, config.limit, parent, status, cursor=end) if more else None})
        if operation in ("list_collections", "list_space_templates"):
            return result({"items": await read("collections" if operation == "list_collections" else "templates"), "has_more": False, "next_page_token": None})
        if operation == "get_space": return result(space)
        if operation == "get_tag": return result(await read("tag", config.tag_id))
        if operation == "get_post": return result(await read("post", config.post_id, parent=parent))
        collection = None
        if hasattr(config, "collection_id"):
            matches = [row for row in await read("collections") if row["id"] == config.collection_id]
            if not matches: raise _Missing("Selected collection is absent from this viewer's complete bounded Network list.")
            collection = matches[0]
            if operation == "get_collection": return result(collection)
        attrs, kind, selected = {}, None, None
        if operation == "create_private_space":
            templates = await read("templates")
            if config.template_canonical_name not in {row["canonicalName"] for row in templates} or config.template_canonical_name == "build_your_own_v1": raise MightyNetworksDenied("Choose an available configured Space template; build-your-own feature changes are excluded.")
            attrs = {"templateCanonicalName": config.template_canonical_name, "title": config.title}; kind = "space"
        elif operation == "rename_space": attrs = {"spaceId": space["id"], "title": config.title}; kind, selected = "space", space["id"]
        elif operation in ("create_collection", "rename_collection", "delete_empty_collection"):
            kind, selected = "collection", collection["id"] if collection else None
            attrs = {"collectionId": selected} if selected else {}
            if operation != "delete_empty_collection": attrs["name"] = config.name
            # Provider atomically refuses deleting a nonempty collection. No move,
            # archive or membership-changing helper is exposed by this node.
        elif operation in ("create_tag", "update_tag", "delete_tag"):
            kind = "tag"
            tag = await read("tag", config.tag_id) if hasattr(config, "tag_id") else None
            if tag: selected = tag["id"]; attrs["tagId"] = selected
            if operation != "delete_tag": attrs["title"] = config.title
            if operation == "create_tag": attrs.update({key: getattr(config, key) for key in ("description", "color") if getattr(config, key) is not None})
        else:
            kind = "post"
            post = await read("post", config.post_id, parent=parent) if hasattr(config, "post_id") else None
            if post:
                if post["status"].upper() != "DRAFT" or post["creator_id"] != actor["id"]: raise MightyNetworksDenied("Draft management requires this token user's own current draft in the selected Space.")
                selected = post["id"]; attrs["id"] = selected
            if operation != "delete_draft_post":
                attrs.update({"title": config.title, "body": html.escape(config.body_text), "status": "DRAFT", "notify": False})
                if post:
                    if not post.get("lastEditedAt"): raise MightyNetworksDenied("This draft has no actual lastEditedAt concurrency anchor; inspect it before editing.")
                    attrs["expectedLastEditedAt"] = post["lastEditedAt"]
                else: attrs.update({"spaceId": parent, "postType": config.post_type})
        receipt_id, acknowledged = None, False
        removing = operation.startswith("delete_")
        try:
            payload = (await call(operation, {"input": attrs})).get("result")
            if not isinstance(payload, dict) or not isinstance(payload.get("errors"), list) or payload["errors"]: raise _Unknown("Mighty mutation payload contains errors or omitted acknowledgment; possible partial effects remain unknown.")
            receipt_field = _MUTATIONS[operation][2]
            receipt = payload.get(receipt_field)
            if _MUTATIONS[operation][3]:
                returned = _record(receipt, kind, selected=selected, parent=parent)
                receipt_id = returned["id"]
            else: receipt_id = _id(receipt)
            if operation == "delete_draft_post" and receipt_id != selected: raise _Unknown("Mighty deletion receipt changed the selected draft ID.")
            acknowledged = True
            async def readback():
                if kind == "collection":
                    matches = [row for row in await read("collections") if row["id"] == (selected or receipt_id)]
                    if not matches: raise _Missing("Collection absent from this viewer's complete list.")
                    return matches[0]
                return await read("post_text" if kind == "post" and not removing else kind, selected or receipt_id, parent=parent, text=kind == "post" and not removing)
            if removing:
                try: await readback()
                except _Missing: pass
                else: raise _Unknown("Mighty removed resource remains visible.")
                # Collection.id is a resource ID, while its delete receipt is a
                # GlobalID. The public contract defines no conversion: retain
                # both actual IDs without guessing their encoding/binding.
                return result({"receipt_id": receipt_id, "selected_id": selected, "receipt_shape_verified": True, "receipt_resource_binding_verified": None if kind == "collection" else True, "absent_from_selected_view": True, "global_deletion_verified": None, "notification_delivery_verified": None, "restore_verified": None})
            verified = await readback()
            if hasattr(config, "title") and verified.get("title") != config.title or hasattr(config, "name") and verified.get("name") != config.name: raise _Unknown("Mighty content name was not read back.")
            if kind == "tag" and any(verified.get(key) != attrs[key] for key in ("description", "color") if key in attrs): raise _Unknown("Mighty tag fields were not read back.")
            if kind == "space" and operation == "create_private_space" and (verified["discoverable"] or verified["explorable"]): raise _Unknown("Mighty new Space was not read back as hidden/private.")
            if kind == "post" and (verified["status"].upper() != "DRAFT" or verified["creator_id"] != actor["id"] or verified.get("bodyText") != config.body_text): raise _Unknown("Mighty owned draft text/status was not read back.")
            verified.pop("bodyText", None)
            return result({**verified, "receipt_id": receipt_id, "readback_verified": True, **({"created_new_verified": None if operation == "create_collection" else True} if operation.startswith("create_") else {}), "notification_delivery_verified": None})
        except Exception:
            if not write_started: raise
        return result({"outcome": "unknown", "receipt_id": receipt_id, "selected_id": selected, "acknowledgment_verified": acknowledged, "readback_verified": False, "notification_delivery_verified": None, "message": "This Mighty change may have occurred. Inspect the actual selected Network/resource before repeating; no automatic retry or rollback."})

    @classmethod
    async def load_field_options(cls, field_name, user_id=None, *, credential_data=None, credential_id=None, context=None, search=None, page_token=None, **kwargs):
        operations = {"space_id": "list_spaces", "post_id": "list_posts", "tag_id": "list_tags", "collection_id": "list_collections", "template_canonical_name": "list_space_templates"}
        if field_name not in operations: return {"options": [], "next_page_token": None}
        context = context or {}; user_id = user_id or context.get("_user_id")
        if field_name == "post_id" and not context.get("space_id"): raise ValueError("Choose the Space before loading its posts.")
        if field_name in ("collection_id", "template_canonical_name") and page_token: raise ValueError("Mighty collections/templates have no documented Relay paging arguments.")
        credential = await cls.freshen_credential(credential_data)
        arguments = {"limit": 50, "page_token": page_token} if field_name in ("space_id", "post_id", "tag_id") else {}
        if field_name == "post_id": arguments["space_id"] = _id(context["space_id"])
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="mighty-options", node_type=cls.integration_type,
            node_data={"credentials": credential, "config": {"operation": operations[field_name], **arguments}})
        output = await node.execute({})
        query = _text(search, 128).casefold() if search else None
        key = "canonicalName" if field_name == "template_canonical_name" else "id"
        options = []
        for row in output["data"]["items"]:
            label = row.get("title") or row.get("name") or row[key]
            if query is None or query in label.casefold(): options.append({"value": row[key], "label": label})
        return {"options": options, "next_page_token": output["data"]["next_page_token"]}
