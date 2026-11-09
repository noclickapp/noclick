"""Arthur Online property management actions and scheduled new-record triggers.

The provider's v2 Postman collection supplies each route and saved response.
OAuth and an explicit entity ID bound every request to the connected account.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union, Any

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, create_model
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.oauth_refresh import freshen_oauth_credential, ensure_fresh_oauth_token
from nodes.arthur_online_operations import OPERATIONS
from nodes.scopes.arthur_online import ARTHUR_ONLINE_SCOPES
from nodes.oauth.arthur_online_oauth import OAUTH_PROVIDER
from utils.ssrf import guarded_async_client

BASE = "https://api.arthuronline.co.uk/v2"
DOCS = "https://documenter.getpostman.com/view/22554870/2s93sZ5YeM"


class ArthurOnlineOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Arthur Online OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "arthur-online",
        "x-oauth-scopes": ARTHUR_ONLINE_SCOPES.declared_scopes(),
        "x-credential-url": DOCS,
        "x-credential-instructions": "Connect Arthur Online with OAuth. Enter the Entity ID shown above your applications in Settings > OAuth Applications. Your NoClick instance must have an Arthur OAuth application configured.",
    })
    credential_type: Literal["arthur_online_oauth"] = Field("arthur_online_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    entity_id: str = Field(..., title="Entity ID", pattern=r"^[1-9][0-9]*$", description="The entity ID shown in Arthur Settings > OAuth Applications.")
    refresh_token: str | None = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token Expiry")
    scope: str | None = None
    token_type: str = "Bearer"
    name: str | None = None


def _date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use a date in YYYY-MM-DD format")
    date.fromisoformat(value)
    return value


Date = Annotated[str, BeforeValidator(_date)]
Identifier = Annotated[int, Field(ge=1)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _field(name, required):
    kind: Any = str
    kwargs = {}
    if name.endswith("_id") or name in {"page", "limit"}:
        kind = Identifier
        if name == "limit": kwargs["le"] = 100
    elif name == "expiry_date":
        kind = Date
    elif name == "market_rent":
        kind = Annotated[float, Field(ge=0, allow_inf_nan=False)]
    elif name == "tags":
        kind = list[str]
    return (kind if required else kind | None, Field(... if required else None,
        title="Search" if name == "_q" else name.replace('_', ' ').title(), **kwargs))


def _config(name, op):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={
        "const": name, "ui:hidden": True, "x-display-name": op["label"],
        "x-category": "Triggers" if name.startswith("on_") else "Property Management",
        "x-is-trigger": name.startswith("on_"),
    }))}
    for field in dict.fromkeys((*op["required"], *op["query"], *op["body"])):
        fields["search" if field == "_q" else field] = _field(field, field in op["required"])
    return create_model('ArthurOnline' + ''.join(w.title() for w in name.split('_')) + 'Config',
        __base__=PollTriggerConfigBase if name.startswith('on_') else _Input, **fields)


CONFIG_MODELS = {name: _config(name, op) for name, op in OPERATIONS.items()}
ArthurOnlineConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class ArthurOnlineNodeConfig(NodeConfig[ArthurOnlineConfig, ArthurOnlineOAuthCredential]):
    pass


class ArthurOnlineNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-arthur-online"
    scope_registry = ARTHUR_ONLINE_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_properties", noun="properties")

    @classmethod
    def get_config_model(cls):
        return ArthurOnlineNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            provider="arthur-online", additional_token_fields=OAUTH_PROVIDER.credential_fields)

    @staticmethod
    async def _request(token, entity_id, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "X-EntityID": entity_id,
                         "Accept": "application/json", "Cache-Control": "no-cache"})
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Arthur Online returned HTTP {response.status_code} without JSON") from None
        if not response.is_success or (isinstance(payload, dict) and (("error" in payload and payload["error"]) or (isinstance(payload.get("status"), int) and payload["status"] >= 400))):
            detail = payload.get("message") or payload.get("error") or "Request rejected" if isinstance(payload, dict) else "Request rejected"
            detail = str(detail).replace(token, "[redacted]")
            raise ValueError(f"Arthur Online HTTP {response.status_code}: {detail}")
        if not isinstance(payload, dict) or ("data" not in payload and not (payload.get("status") == 200 and "message" in payload)):
            raise ValueError("Arthur Online returned an incomplete response")
        return payload

    async def _poll(self, token, entity_id, config, op):
        records = []
        for page in range(1, 101):
            # Scan every page before deduplication, so detection does not depend
            # on a server's default sort order. Use its default first page.
            params = {"page": page} if page > 1 else {}
            payload = await self._request(token, entity_id, "GET", op["path"], params=params)
            rows = payload.get("data")
            pagination = payload.get("pagination")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
                raise ValueError("Arthur Online returned an invalid record list")
            if not isinstance(pagination, dict) or not isinstance(pagination.get("pageCount"), int):
                raise ValueError("Arthur Online returned incomplete pagination; poll state was not changed")
            records.extend(rows)
            if page >= pagination["pageCount"]:
                break
        else:
            raise ValueError("Arthur Online has over 100 pages; this poll cannot safely complete")
        fresh = await self._filter_unseen(records, lambda row: str(row["id"]))
        return {"operation": config.operation, "records": fresh, "new_record_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation", "").startswith("on_"):
            return bool(output.get("new_record_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        records = output.get("records") if isinstance(output, dict) else None
        if not isinstance(records, list) or not records:
            return None
        certificates = output.get("operation") == "on_new_certificate"
        lines = []
        for row in records[:10]:
            if certificates:
                location = row.get("property") or {}
                lines.append(f"- {row.get('type') or 'Certificate'} for {location.get('address') or 'unspecified property'}, expires {row.get('expiry_date') or 'unspecified'}, certificate ID {row['id']}, property ID {location.get('id')}")
            else:
                lines.append(f"- {row.get('ref') or 'Property'} at {row.get('full_address') or 'unspecified address'}, owner {row.get('property_owner_full_name') or 'unspecified'}, property ID {row['id']}, owner ID {row.get('property_owner_id')}")
        return {"text": f"Arthur Online: {len(records)} new {'certificate(s)' if certificates else 'property/properties'}:\n" + '\n'.join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Arthur Online account")
        credential = self.config.credentials.model_dump()
        token = await ensure_fresh_oauth_token(credential=credential,
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential), provider="arthur-online", caller_path="execute",
            additional_token_fields=OAUTH_PROVIDER.credential_fields)
        self.config.credentials = ArthurOnlineOAuthCredential.model_validate(credential)
        config = self.config.config
        self.scope_registry.require(config.operation)
        op = OPERATIONS[config.operation]
        if config.operation.startswith("on_"):
            return await self._poll(token, credential["entity_id"], config, op)
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "search" in values:
            values["_q"] = values.pop("search")
        path = op["path"]
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", str(values.pop(field)))
        params = {key: values[key] for key in op["query"] if key in values}
        body = {key: values[key] for key in op["body"] if key in values} if op["body"] else None
        payload = await self._request(token, credential["entity_id"], op["method"], path, params=params, body=body)
        return {"operation": config.operation, **payload}
