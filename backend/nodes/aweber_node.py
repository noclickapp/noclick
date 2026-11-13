"""AWeber 1.0 automation node, covering the public REST operation catalog.

The operation metadata is generated from AWeber's official OpenAPI document.
Operation-specific Pydantic models give FlowCanvas required path, query, and body
fields, while one request runner keeps authentication and response handling
consistent across the 53 public resource actions.
"""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from pydantic import AfterValidator, BaseModel, ConfigDict, Discriminator, Field, create_model
from jsonschema import FormatChecker
from jsonschema.exceptions import FormatError

from nodes.aweber_operations import OPERATIONS
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.aweber import AWEBER_SCOPES as AWEBER_SCOPE_REGISTRY


AWEBER_API_BASE = "https://api.aweber.com/1.0"
AWEBER_SCOPES = sorted(AWEBER_SCOPE_REGISTRY.declared_scopes())


class AWeberOAuthCredential(BaseModel):
    """AWeber authorization-code credential with a rotating refresh token."""

    credential_type: Literal["aweber_oauth"] = Field(
        "aweber_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Expires At")
    scope: Optional[str] = Field(None, title="Scopes")

    model_config = ConfigDict(json_schema_extra={
        "title": "Aweber OAuth",
        "x-credential-type": "oauth",
        "x-oauth-provider": "aweber",
        "x-oauth-scopes": AWEBER_SCOPES,
        "x-credential-url": "https://labs.aweber.com/apps",
    })


# AWeber's own MCP server: agents get its tools through a person's AWeber sign-in.
AweberMcpCredential = mcp_credential("aweber", "https://mcp.aweber.com/mcp", app="AWeber")
AWeberCredential = Union[AWeberOAuthCredential, AweberMcpCredential]


_TYPE = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": Dict[str, Any],
    "array": List[Any],
}


def _title(name: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", name.replace("_", " ").replace(".", " ")).title()


def _schema_field(schema: Dict[str, Any], required: bool, **kwargs):
    """Preserve the provider's primitive constraints in the config editor."""
    kind = _TYPE.get(schema.get("type"), Any)
    if schema.get("enum"):
        kind = Literal[tuple(schema["enum"])]
    default = ... if required else None
    if "default" in schema:
        candidate = schema["default"]
        # AWeber's broadcast spec has array defaults on string-encoded fields.
        if schema.get("type") != "string" or isinstance(candidate, str):
            default = candidate
    format_ = schema.get("format")
    if format_:
        extra = dict(kwargs.pop("json_schema_extra", None) or {})
        kwargs["json_schema_extra"] = {**extra, "format": format_}
        if schema.get("type") == "string":
            def validate_format(value):
                try:
                    FormatChecker().check(value, format_)
                except FormatError as exc:
                    raise ValueError(f"Expected AWeber {format_} value") from exc
                return value
            kind = Annotated[kind, AfterValidator(validate_format)]
    allowed = {"minimum", "maximum"} if schema.get("type") in ("integer", "number") else (
        {"minLength", "maxLength", "pattern"} if schema.get("type") == "string" else
        {"minItems", "maxItems"} if schema.get("type") == "array" else set())
    constraints = {target: schema[source] for source, target in (
        ("minimum", "ge"), ("maximum", "le"), ("minLength", "min_length"),
        ("maxLength", "max_length"), ("pattern", "pattern"),
        ("minItems", "min_length"), ("maxItems", "max_length"),
    ) if source in schema and source in allowed}
    return (kind if required or default is not None else Optional[kind],
            Field(default, **constraints, **kwargs))


def _operation_model(spec: Dict[str, Any]) -> type[BaseModel]:
    operation = spec["id"]
    fields: Dict[str, Any] = {
        "operation": (
            Literal[operation],
            Field(operation, title=spec["summary"], json_schema_extra={
                "const": operation,
                "ui:hidden": True,
                "x-category": spec["category"],
                "x-display-name": spec["summary"],
                "x-is-trigger": False,
            }),
        ),
    }
    for param in re.findall(r"\{([^}]+)\}", spec["path"]):
        extra = None
        if param in ("accountId", "listId"):
            extra = {"x-dynamic-options": {
                "field_name": param,
                "placeholder": f"Select {_title(param).lower()}...",
                "searchable": True,
                "allow_custom": True,
                **({"depends_on": "accountId"} if param == "listId" else {}),
            }}
        fields[param] = _schema_field(spec["path_parameters"][param], True,
                                     title=_title(param), json_schema_extra=extra)
    for query in spec["query"]:
        key = query["name"].replace(".", "_")
        fields[key] = _schema_field(
            query["schema"], query["required"], title=_title(query["name"]),
            description=f"AWeber query parameter: {query['name']}",
        )
    for body in spec["body"]:
        name = body["name"]
        key = "body_" + name.replace(".", "_")
        enum = body.get("enum")
        if name == "ws.op" and enum and len(enum) == 1:
            fields[key] = (Literal[enum[0]], Field(enum[0], json_schema_extra={"ui:hidden": True}))
            continue
        fields[key] = _schema_field(
            body["schema"], body["required"], title=_title(name),
            description=f"AWeber request body field: {name}",
        )
    fields["extra_query"] = (
        Optional[Dict[str, Any]],
        Field(None, title="Additional Query Parameters", description="Optional AWeber query parameters as JSON"),
    )
    fields["extra_body"] = (
        Optional[Dict[str, Any]],
        Field(None, title="Additional Body Fields", description="Optional AWeber request fields as JSON"),
    )
    return create_model(
        "AWeber" + "".join(piece.title() for piece in operation.split("_")) + "Config",
        __module__=__name__,
        **fields,
    )


_OPERATION_MODELS = [_operation_model(spec) for spec in OPERATIONS]
_OPERATION_BY_ID = {spec["id"]: spec for spec in OPERATIONS}
for _model in _OPERATION_MODELS:
    globals()[_model.__name__] = _model


class AWeberOnNewSubscriberConfig(PollTriggerConfigBase):
    """Poll the documented creation-ordered subscriber collection for one list."""

    operation: Literal["on_new_subscriber"] = Field("on_new_subscriber", json_schema_extra={
        "const": "on_new_subscriber", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Subscriber",
    })
    accountId: int = Field(..., title="Account", json_schema_extra={"x-dynamic-options": {
        "field_name": "accountId", "searchable": True, "allow_custom": True,
    }})
    listId: int = Field(..., title="List", json_schema_extra={"x-dynamic-options": {
        "field_name": "listId", "depends_on": "accountId", "searchable": True, "allow_custom": True,
    }})


AWeberConfig = Annotated[Union[tuple(_OPERATION_MODELS) + (AWeberOnNewSubscriberConfig,)],
                         Discriminator("operation")]



class AWeberNodeConfig(NodeConfig[AWeberConfig, AWeberCredential]):
    """AWeber action and OAuth credential."""


def _form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


class AWeberNode(ScheduledPollTriggerMixin, WorkflowNode):
    """AWeber subscriber, list, campaign, broadcast, and analytics actions."""

    integration_type = "automation-aweber"
    credential_provider_labels = {"aweber": "AWeber Account"}

    edit_examples = [
        "Add a subscriber to my AWeber list",
        "Find subscribers by email and update their tags",
        "Draft an AWeber broadcast and inspect its statistics",
        "List my landing pages and campaigns",
    ]
    connection_evidence = ConnectionEvidence(field="accountId", noun="accounts")
    scope_registry = AWEBER_SCOPE_REGISTRY

    @classmethod
    def get_config_model(cls):
        return AWeberNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.aweber_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="aweber",
        )

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None, page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in {"accountId", "listId"}:
            return {"options": []}
        token = (credential_data or {}).get("access_token")
        if not token:
            return {"options": []}
        if field_name == "accountId":
            path = "/accounts"
        else:
            ctx = context or {}
            config = ctx.get("config") if isinstance(ctx.get("config"), dict) else ctx
            account_id = config.get("accountId")
            if not account_id:
                return {"options": []}
            path = f"/accounts/{quote(str(account_id), safe='')}/lists"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                AWEBER_API_BASE + path,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params={"ws.size": 100},
            )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("entries", []) if isinstance(payload, dict) else []
        return {"options": [
            {"label": str(row.get("name") or row.get("company") or row.get("id")), "value": str(row["id"])}
            for row in rows if isinstance(row, dict) and row.get("id") is not None
            and (not search or search.lower() in str(row.get("name") or row.get("company") or row["id"]).lower())
        ]}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, AWeberNodeConfig):
            raise ValueError("AWeber configuration is required")
        credential = self.config.credentials
        if not credential or not credential.access_token:
            raise ValueError("Connect an AWeber account first")
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.aweber_oauth import refresh_access_token

            credential_data = credential.model_dump()
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=credential_data,
                refresh=refresh_access_token,
                provider="aweber",
                caller_path="execute",
            )
            credential.access_token = credential_data["access_token"]
            credential.expires_at = credential_data.get("expires_at")
            credential.refresh_token = credential_data.get("refresh_token")
        config = self.config.config
        self.scope_registry.require(config.operation)
        if isinstance(config, AWeberOnNewSubscriberConfig):
            return await self._poll_subscribers(credential.access_token, config)
        spec = _OPERATION_BY_ID[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        for name in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        split = urlsplit(path)
        params: Dict[str, Any] = dict(parse_qsl(split.query))
        for param in spec["query"]:
            field = param["name"].replace(".", "_")
            if field in values:
                params[param["name"]] = values[field]
        params.update(values.get("extra_query") or {})
        # The ws.op subresource is part of the selected action, not user input.
        fixed_op = dict(parse_qsl(split.query)).get("ws.op")
        if fixed_op:
            params["ws.op"] = fixed_op
        body = {field["name"]: values["body_" + field["name"].replace(".", "_")]
                for field in spec["body"]
                if "body_" + field["name"].replace(".", "_") in values}
        body.update(values.get("extra_body") or {})
        for field in spec["body"]:
            if field["name"] == "ws.op" and field.get("enum") and len(field["enum"]) == 1:
                body["ws.op"] = field["enum"][0]
        request_args: Dict[str, Any] = {}
        if spec["content_type"] == "application/json":
            request_args["json"] = body
        elif spec["content_type"] == "application/x-www-form-urlencoded":
            request_args["data"] = {name: _form_value(value) for name, value in body.items()}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    spec["method"], spec.get("server", AWEBER_API_BASE) + split.path,
                    headers={"Authorization": f"Bearer {credential.access_token}", "Accept": "application/json"},
                    params=params or None, **request_args,
                )
            except httpx.RequestError as exc:
                return {"status": "error", "action": config.operation, "error": str(exc),
                        "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}
        try:
            payload: Any = response.json() if response.content else {}
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            message = payload.get("error", payload) if isinstance(payload, dict) else payload
            return {"status": "error", "action": config.operation, "status_code": response.status_code,
                    "error": message, "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}
        if response.headers.get("location"):
            payload = {"result": payload, "location": response.headers["location"]}
        return {"status": "success", "action": config.operation, "status_code": response.status_code,
                "data": payload, "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}

    @classmethod
    def should_propagate_output(cls, output: Dict[str, Any], config: Dict[str, Any]) -> bool:
        if config.get("operation") == "on_new_subscriber":
            return bool(output.get("new_subscriber_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        subscribers = output.get("subscribers") if isinstance(output, dict) else None
        if not isinstance(subscribers, list):
            return super().resolve_agent_event(output)
        if not subscribers:
            return None
        lines = []
        for row in subscribers[:10]:
            label = row.get("name") or row.get("email") or f"Subscriber {row['id']}"
            email = f" <{row['email']}>" if row.get("email") else ""
            when = f", subscribed {row['subscribed_at']}" if row.get("subscribed_at") else ""
            lines.append(f"- {label}{email} (subscriber {row['id']}{when})")
        if len(subscribers) > 10:
            lines.append(f"- … and {len(subscribers) - 10} more")
        return {"text": f"AWeber: {len(subscribers)} new subscriber(s) in list {output['list_id']} "
                        f"of account {output['account_id']}:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_subscribers(self, token: str, config: AWeberOnNewSubscriberConfig) -> Dict[str, Any]:
        # AWeber documents creation ordering and ws.start/ws.size pagination:
        # https://api.aweber.com/subscribers.yaml
        rows = []
        path = f"/accounts/{config.accountId}/lists/{config.listId}/subscribers"
        async with httpx.AsyncClient(timeout=30.0) as client:
            for offset in range(0, 10000, 100):
                response = await client.request(
                    "GET", AWEBER_API_BASE + path,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params={"ws.start": offset, "ws.size": 100, "sort_order": "desc"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
                    raise ValueError("AWeber returned no subscriber collection")
                page = payload["entries"]
                if any(not isinstance(row, dict) or row.get("id") is None for row in page):
                    raise ValueError("AWeber returned a subscriber without an id")
                rows.extend(page)
                if len(page) < 100:
                    break
            else:
                raise ValueError("AWeber list exceeds 10,000 subscribers; choose a smaller list to monitor")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
        return {"subscribers": fresh, "new_subscriber_count": len(fresh),
                "account_id": config.accountId, "list_id": config.listId}
