"""Front Core API workflow node with OAuth and API-token authentication."""

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.front_operations import OPERATIONS, Operation
from nodes.scopes.front import FRONT_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


class FrontOAuthCredential(BaseModel):
    credential_type: Literal["front_oauth"] = Field("front_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    model_config = ConfigDict(json_schema_extra={
        "title": "Front OAuth", "x-credential-type": "oauth", "x-oauth-provider": "front",
        "x-oauth-scopes": FRONT_SCOPES.declared_scopes(),
        "x-credential-url": "https://dev.frontapp.com/docs/create-and-manage-apps",
    })


class FrontApiTokenCredential(BaseModel):
    credential_type: Literal["front_api_token"] = Field("front_api_token", json_schema_extra={"ui:hidden": True})
    token: str = Field(..., title="API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={
        "title": "Front API Token", "x-credential-type": "api_key",
        "x-credential-url": "https://dev.frontapp.com/docs/create-and-revoke-api-tokens",
    })


FrontCredential = Union[FrontOAuthCredential, FrontApiTokenCredential]


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for field in re.findall(r"\{([^}]+)\}", op.path):
        fields[field] = (str, Field(..., title=field.replace("_", " ").title()))
    for field in op.required_query_fields:
        if field not in fields:
            fields[field] = (str, Field(..., title=field.replace("_", " ").title()))
    fields["query_json"] = (Optional[str], Field(
        None, title="Query Parameters JSON",
        description="Optional Front API query parameters as a JSON object",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    if op.has_body:
        fields["body_json"] = (str, Field(
            ..., title="Request JSON",
            description="JSON body using Front API field names",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    return create_model(
        "Front" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(name, title=op.label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": op.category,
            "x-is-trigger": False, "x-display-name": op.label,
        })),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class FrontOnNewOrUpdatedConversationConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_conversation"] = Field(
        "on_new_or_updated_conversation", title="On New or Updated Conversation",
        json_schema_extra={"const": "on_new_or_updated_conversation", "ui:hidden": True,
                           "x-category": "Triggers", "x-is-trigger": True,
                           "x-display-name": "On New or Updated Conversation"})


FrontConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) +
                             (FrontOnNewOrUpdatedConversationConfig,)], Discriminator("operation")]


class FrontNodeConfig(NodeConfig[FrontConfig, FrontCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class FrontNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-front"
    credential_provider_labels = {"front": "Front"}
    scope_registry = FRONT_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_token_identity", noun="account")
    edit_examples = [
        "List Front conversations", "Create a Front contact",
        "Reply to a Front conversation", "List Front inboxes", "Get Front analytics",
    ]

    @classmethod
    def get_config_model(cls):
        return FrontNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.front_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="front")

    @staticmethod
    def _parse_object(raw: Optional[str], label: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _serialize_param(value: Any) -> str:
        if isinstance(value, (dict, list, bool)):
            return json.dumps(value, separators=(",", ":"))
        return "" if value is None else str(value)

    async def _access_token(self, credential: FrontCredential) -> str:
        if isinstance(credential, FrontApiTokenCredential):
            return credential.token
        if not credential.refresh_token:
            return credential.access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.front_oauth import refresh_access_token
        return await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential.model_dump(), refresh=refresh_access_token,
            provider="front", caller_path="execute")

    @staticmethod
    async def _request(method: str, path: str, token: str,
                       params: dict[str, str], body: Optional[dict[str, Any]]) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, f"https://api2.frontapp.com{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params or None, json=body)
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") if isinstance(payload, dict) else None
            except ValueError:
                detail = None
            raise ValueError(f"Front API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or response.content[:1] in (b"{", b"["):
            try:
                return response.json()
            except ValueError as exc:
                raise ValueError(f"Front returned invalid JSON ({response.status_code})") from exc
        return {"file": BinaryOutput(
            data=response.content,
            content_type=content_type.split(";", 1)[0].strip() or "application/octet-stream",
            filename="front-attachment")}

    @classmethod
    def supports_test_event(cls) -> bool:
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        conversations = output.get("conversations") if isinstance(output, dict) else None
        if not isinstance(conversations, list):
            return super().resolve_agent_event(output)
        if not conversations:
            return None
        lines = []
        for item in conversations[:10]:
            recipient = item.get("recipient") or {}
            sender = recipient.get("handle") or "Unknown recipient"
            lines.append(f"- {item.get('subject') or 'Untitled conversation'} "
                         f"({item['id']}, {item.get('status')}) — {sender}")
        return {"text": "Front: new or updated conversations in your shared inbox:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_conversations(self, token):
        conversations = []
        params = {"limit": "100", "sort_by": "date", "sort_order": "desc"}
        for _ in range(20):
            data = await self._request("GET", "/conversations", token, params, None)
            if not isinstance(data, dict) or not isinstance(data.get("_results"), list):
                raise ValueError("Front returned an invalid conversation list")
            for item in data["_results"]:
                if not isinstance(item, dict) or not item.get("id"):
                    raise ValueError("Front returned a conversation without an ID")
                conversations.append(item)
            next_url = (data.get("_pagination") or {}).get("next")
            if not next_url:
                break
            # Only copy the opaque token, never send credentials to a response URL.
            page_tokens = parse_qs(urlsplit(next_url).query).get("page_token")
            if not page_tokens:
                raise ValueError("Front pagination link has no page token")
            params = {**params, "page_token": page_tokens[0]}
        else:
            raise ValueError("Front polling exceeds 2,000 conversations; narrow the workflow scope")
        fresh = await self._filter_unseen(
            conversations, lambda item: f"{item['id']}:{item.get('updated_at', item.get('created_at', ''))}")
        return {"conversations": fresh, "new_or_updated_conversation_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, FrontNodeConfig):
            raise ValueError("Front configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Front account or API token")
        config = self.config.config
        self.scope_registry.require(config.operation)
        if isinstance(config, FrontOnNewOrUpdatedConversationConfig):
            return await self._poll_conversations(await self._access_token(credential))
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        path_values = {}
        for field in re.findall(r"\{([^}]+)\}", path):
            path_values[field] = values.pop(field)
            path = path.replace("{" + field + "}", quote(str(path_values[field]), safe=""))
        params = self._parse_object(values.pop("query_json", None), "Query Parameters JSON")
        for field in op.required_query_fields:
            params[field] = values.pop(field, path_values.get(field))
        serialized = {key: self._serialize_param(value) for key, value in params.items()}
        body = self._parse_object(values.pop("body_json", None), "Request JSON") if op.has_body else None
        token = await self._access_token(credential)
        data = await self._request(op.method, path, token, serialized, body)
        return {"status": "success", "operation": config.operation, "data": data}
