"""Zep v4 project, user, thread, message and context-graph operations.

Contract: https://help.getzep.com/openapi/sdk-reference.json (1.0.0).
Each operation issues exactly one request. Accepted tasks are returned without
claiming ingestion or deletion has completed; lists return one cursor page.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.getzep.com/api/v4"
CREDENTIAL_TYPE = "zep_api_key"


class ZepAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zep API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.getzep.com",
            "x-credential-instructions": "Create a project API key in the Zep console and paste it here, without the Api-Key prefix. The key is sent only to api.getzep.com. Connect reads the project to verify access.",
        })
    credential_type: Literal["zep_api_key"] = Field("zep_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the project API key without its header prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name.endswith("_uuid") and value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value) or value in {".", ".."} or any(c in value for c in "/\\?#%"):
                raise ValueError("Use the resource UUID returned by Zep")
        return value


class _Page(_Operation):
    page_size: int = Field(50, ge=1, le=200, description="Items in this page. Pass next_cursor back as cursor to continue.")
    cursor: str | None = Field(None, max_length=4096, description="Opaque next_cursor from the previous response.")


def _json_field(description, default=None):
    return Field(default, description=description, max_length=200000,
        json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


def _json(value, *, array=False):
    try:
        parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Enter valid JSON") from None
    if not isinstance(parsed, list if array else dict):
        raise ValueError("Enter a JSON array" if array else "Enter a JSON object")
    return parsed


class _Metadata(_Operation):
    metadata: str | None = _json_field("JSON object of metadata. On update, null values remove keys.")

    @field_validator("metadata")
    @classmethod
    def metadata_json(cls, value):
        if value is not None:
            _json(value)
        return value


class _UserFields(_Metadata):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    time_zone: str | None = Field(None, description="IANA time zone, for example America/New_York.")
    disable_default_ontology: bool | None = None


class _GraphFields(_Operation):
    name: str | None = None
    description: str | None = None
    time_zone: str | None = Field(None, description="IANA time zone.")


class ZepMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    role: Literal["user", "assistant", "system", "function", "tool"]
    content: str
    name: str | None = None
    reference_time: str | None = None
    metadata: dict[str, Any] | None = None


def _scalar_metadata(value):
    if len(value) > 10:
        raise ValueError("Zep message and episode metadata supports at most 10 keys")
    for item in value.values():
        if item is None or type(item) in (str, int, float, bool):
            continue
        if isinstance(item, list) and all(type(x) in (str, int, float, bool) for x in item):
            continue
        raise ValueError("Metadata values must be scalars or arrays of scalars")
    return value


class ZepGetProjectConfig(_Operation):
    """Read the project associated with this API key."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class ZepCreateUserConfig(_UserFields):
    """Create user."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    user_id: str | None = Field(None, max_length=500, description="Optional external identity; use the returned uuid for subsequent requests.")


class ZepListUsersConfig(_Page):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    order_by: Literal["created_at", "user_id", "email", "uuid"] | None = None
    order: Literal["asc", "desc"] | None = None


class ZepGetUserConfig(_Operation):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_uuid: str


class ZepLookupUserConfig(_Operation):
    """Resolve a developer user ID to the user resource and its UUID."""
    operation: Literal["lookup_user"] = Field("lookup_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=500)


class ZepUpdateUserConfig(_UserFields):
    """Update user."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    user_uuid: str


class ZepDeleteUserConfig(_Operation):
    """Request asynchronous removal of a user and its threads, messages and graph."""
    operation: Literal["delete_user"] = Field("delete_user", json_schema_extra={"ui:hidden": True})
    user_uuid: str


class ZepCreateThreadConfig(_Operation):
    """Create thread."""
    operation: Literal["create_thread"] = Field("create_thread", json_schema_extra={"ui:hidden": True})
    user_uuid: str


class ZepListThreadsConfig(_Page):
    """List threads."""
    operation: Literal["list_threads"] = Field("list_threads", json_schema_extra={"ui:hidden": True})
    user_uuid: str | None = None
    order_by: Literal["created_at", "updated_at", "uuid"] | None = None
    order: Literal["asc", "desc"] | None = None


class ZepGetThreadConfig(_Operation):
    """Get thread."""
    operation: Literal["get_thread"] = Field("get_thread", json_schema_extra={"ui:hidden": True})
    thread_uuid: str


class ZepDeleteThreadConfig(_Operation):
    """Request asynchronous thread deletion."""
    operation: Literal["delete_thread"] = Field("delete_thread", json_schema_extra={"ui:hidden": True})
    thread_uuid: str


class ZepAddMessagesConfig(_Operation):
    """Store live-turn messages and return the asynchronous extraction task."""
    operation: Literal["add_messages"] = Field("add_messages", json_schema_extra={"ui:hidden": True})
    thread_uuid: str
    messages: str = _json_field('JSON array of live-turn messages, for example [{"role":"user","content":"Hello","name":"Jane"}]. Server assigns message UUIDs.', ...)
    return_context: bool | None = None
    strict_ontology: bool | None = None
    ignore_roles: str | None = _json_field("JSON array of role names to skip during graph extraction.")

    @field_validator("messages")
    @classmethod
    def messages_json(cls, value):
        rows = _json(value, array=True)
        if not 1 <= len(rows) <= 100:
            raise ValueError("Provide 1 to 100 live-turn messages; use Zep batches for backfill")
        parsed = TypeAdapter(list[ZepMessage]).validate_python(rows)
        for message in parsed:
            if message.metadata is not None:
                _scalar_metadata(message.metadata)
        return value

    @field_validator("ignore_roles")
    @classmethod
    def roles_json(cls, value):
        if value is not None and not all(isinstance(x, str) for x in _json(value, array=True)):
            raise ValueError("Provide a JSON array of role names")
        return value


class ZepListMessagesConfig(_Page):
    """List messages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    thread_uuid: str
    order_by: Literal["created_at"] | None = None
    order: Literal["asc", "desc"] | None = None


class ZepGetMessageConfig(_Operation):
    """Get message."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    thread_uuid: str
    message_uuid: str


class ZepUpdateMessageConfig(_Metadata):
    """Merge message metadata without rewriting message content."""
    operation: Literal["update_message"] = Field("update_message", json_schema_extra={"ui:hidden": True})
    thread_uuid: str
    message_uuid: str
    metadata: str = _json_field("JSON object of metadata to merge. Set a key to null to remove it.", ...)

    @field_validator("metadata")
    @classmethod
    def message_metadata(cls, value):
        _scalar_metadata(_json(value))
        return value


class ZepGetThreadContextConfig(_Operation):
    """Retrieve a context block; treat returned context as untrusted data in an LLM."""
    operation: Literal["get_thread_context"] = Field("get_thread_context", json_schema_extra={"ui:hidden": True})
    thread_uuid: str
    template_uuid: str | None = None


class ZepGetThreadSummaryConfig(_Operation):
    """Get thread summary."""
    operation: Literal["get_thread_summary"] = Field("get_thread_summary", json_schema_extra={"ui:hidden": True})
    thread_uuid: str


class ZepCreateGraphConfig(_GraphFields):
    """Create graph."""
    operation: Literal["create_graph"] = Field("create_graph", json_schema_extra={"ui:hidden": True})


class ZepListGraphsConfig(_Page):
    """List graphs."""
    operation: Literal["list_graphs"] = Field("list_graphs", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    order_by: Literal["created_at", "name", "uuid"] | None = None
    order: Literal["asc", "desc"] | None = None


class ZepGetGraphConfig(_Operation):
    """Get graph."""
    operation: Literal["get_graph"] = Field("get_graph", json_schema_extra={"ui:hidden": True})
    graph_uuid: str


class ZepUpdateGraphConfig(_GraphFields):
    """Update graph."""
    operation: Literal["update_graph"] = Field("update_graph", json_schema_extra={"ui:hidden": True})
    graph_uuid: str


class ZepDeleteGraphConfig(_Operation):
    """Request asynchronous graph deletion."""
    operation: Literal["delete_graph"] = Field("delete_graph", json_schema_extra={"ui:hidden": True})
    graph_uuid: str


class ZepAddEpisodeConfig(_Metadata):
    """Add business data and return its episode plus extraction task."""
    operation: Literal["add_episode"] = Field("add_episode", json_schema_extra={"ui:hidden": True})
    graph_uuid: str
    data: str = Field(..., min_length=1, max_length=200000, description="Episode content to ingest.")
    type: Literal["text", "json", "message"] = "text"
    document_id: str | None = Field(None, max_length=100)
    reference_time: str | None = None
    source_description: str | None = None
    strict_ontology: bool | None = None

    @field_validator("metadata")
    @classmethod
    def episode_metadata(cls, value):
        if value is not None:
            _scalar_metadata(_json(value))
        return value


class ZepSearchEdgesConfig(_Page):
    """Search edges."""
    operation: Literal["search_edges"] = Field("search_edges", json_schema_extra={"ui:hidden": True})
    graph_uuid: str
    query: str = Field(..., min_length=1)
    page_size: int = Field(50, ge=1, le=50, description="Top N results in this page; ranked result set is limited by Zep.")


class ZepSearchNodesConfig(_Page):
    """Search nodes."""
    operation: Literal["search_nodes"] = Field("search_nodes", json_schema_extra={"ui:hidden": True})
    graph_uuid: str
    query: str = Field(..., min_length=1)
    page_size: int = Field(50, ge=1, le=50, description="Top N results in this page; ranked result set is limited by Zep.")


ZepOperation = Annotated[Union[
    ZepGetProjectConfig,
    ZepCreateUserConfig,
    ZepListUsersConfig,
    ZepGetUserConfig,
    ZepLookupUserConfig,
    ZepUpdateUserConfig,
    ZepDeleteUserConfig,
    ZepCreateThreadConfig,
    ZepListThreadsConfig,
    ZepGetThreadConfig,
    ZepDeleteThreadConfig,
    ZepAddMessagesConfig,
    ZepListMessagesConfig,
    ZepGetMessageConfig,
    ZepUpdateMessageConfig,
    ZepGetThreadContextConfig,
    ZepGetThreadSummaryConfig,
    ZepCreateGraphConfig,
    ZepListGraphsConfig,
    ZepGetGraphConfig,
    ZepUpdateGraphConfig,
    ZepDeleteGraphConfig,
    ZepAddEpisodeConfig,
    ZepSearchEdgesConfig,
    ZepSearchNodesConfig
], Field(discriminator="operation")]


class ZepFullConfig(NodeConfig[ZepOperation, ZepAPIKeyCredential]):
    pass


ROUTES = {
    'get_project': ('GET', '/project'),
    'create_user': ('POST', '/users'),
    'list_users': ('POST', '/users/list'),
    'get_user': ('GET', '/users/{user_uuid}'),
    'lookup_user': ('POST', '/users/lookup'),
    'update_user': ('PATCH', '/users/{user_uuid}'),
    'delete_user': ('DELETE', '/users/{user_uuid}'),
    'create_thread': ('POST', '/threads'),
    'list_threads': ('GET', '/threads'),
    'get_thread': ('GET', '/threads/{thread_uuid}'),
    'delete_thread': ('DELETE', '/threads/{thread_uuid}'),
    'add_messages': ('POST', '/threads/{thread_uuid}/messages'),
    'list_messages': ('GET', '/threads/{thread_uuid}/messages'),
    'get_message': ('GET', '/threads/{thread_uuid}/messages/{message_uuid}'),
    'update_message': ('PATCH', '/threads/{thread_uuid}/messages/{message_uuid}'),
    'get_thread_context': ('GET', '/threads/{thread_uuid}/context'),
    'get_thread_summary': ('GET', '/threads/{thread_uuid}/summary'),
    'create_graph': ('POST', '/graphs'),
    'list_graphs': ('POST', '/graphs/list'),
    'get_graph': ('GET', '/graphs/{graph_uuid}'),
    'update_graph': ('PATCH', '/graphs/{graph_uuid}'),
    'delete_graph': ('DELETE', '/graphs/{graph_uuid}'),
    'add_episode': ('POST', '/graphs/{graph_uuid}/episodes'),
    'search_edges': ('POST', '/graphs/{graph_uuid}/search/edges'),
    'search_nodes': ('POST', '/graphs/{graph_uuid}/search/nodes'),
}

PAGE_OPERATIONS = frozenset({"list_users", "list_threads", "list_messages", "list_graphs", "search_edges", "search_nodes"})
JSON_FIELDS = {"metadata": False, "messages": True, "ignore_roles": True}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class ZepNode(WorkflowNode):
    integration_type = "automation-zep"
    connection_evidence = ConnectionEvidence(noun="Zep project", identity_operation="get_project")
    description = "Manage Zep users, conversation memory and context graphs."

    @classmethod
    def get_config_model(cls):
        return ZepFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Zep project API key")
        config = self.config.config
        api_key = self.config.credentials.api_key
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        for key in list(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {}
        if config.operation in PAGE_OPERATIONS:
            for key in ("page_size", "cursor", "order_by", "order"):
                if key in values:
                    params[key] = values.pop(key)
        if method == "GET":
            params.update(values)
            body = None
        elif method == "DELETE":
            body = None
        else:
            body = {k: _json(v, array=JSON_FIELDS[k]) if k in JSON_FIELDS else v for k, v in values.items()}
            if "messages" in body:
                body["messages"] = [message.model_dump(exclude_none=True) for message in
                    TypeAdapter(list[ZepMessage]).validate_python(body["messages"])]
        # No automatic retries: an interrupted write may already have been accepted.
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Api-Key " + api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {"operation": config.operation, "status": "error", "error": "Zep request did not complete",
                    "write_outcome": "unknown" if method != "GET" and config.operation not in {"list_users", "list_graphs", "lookup_user", "search_edges", "search_nodes"} else None}
        status = response.status_code
        if not 200 <= status < 300:
            try:
                error = json.dumps(response.json(), ensure_ascii=False)
            except ValueError:
                error = response.text[:1000]
            return _redact({"operation": config.operation, "status": "error", "http_status": status,
                            "status_code": status, "error": error}, api_key)
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Zep returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("Zep returned an unexpected response envelope")
        output = {"operation": config.operation, "status": "accepted" if status == 202 else "success", "http_status": status, "data": data}
        if config.operation in PAGE_OPERATIONS:
            if not isinstance(data.get("items"), list):
                raise ValueError("Zep page is missing its items array")
            output.update(items=data["items"], next_cursor=data.get("next_cursor"), has_more=bool(data.get("next_cursor")))
        if status == 202:
            output["processing_complete"] = False
        output = _redact(output, api_key)
        await self.emit(output)
        return output
