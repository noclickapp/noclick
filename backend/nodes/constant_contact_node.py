"""Constant Contact V3 account, contacts, campaigns, and reporting actions.

Routes, parameters, and scopes follow the official V3 schema and the current
provider A/B-test documentation cited in constant_contact_operations.py.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.constant_contact_operations import OPERATIONS, Operation
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.constant_contact import CONSTANT_CONTACT_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

API_BASE = "https://api.cc.email/v3"


class ConstantContactOAuthCredential(BaseModel):
    credential_type: Literal["constant_contact_oauth"] = Field(
        "constant_contact_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")
    model_config = ConfigDict(json_schema_extra={
        "title": "Constant Contact OAuth", "x-credential-type": "oauth", "x-oauth-provider": "constant_contact",
        "x-oauth-scopes": CONSTANT_CONTACT_SCOPES.declared_scopes(),
        "x-credential-url": "https://app.constantcontact.com/pages/dma/portal",
    })


def _model_field(name: str, required: bool = True) -> tuple[Any, Any]:
    if name == "payload_json":
        return str, Field(..., title="Request JSON",
                          description="The JSON request body using Constant Contact V3 field names",
                          json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    if name == "query_json":
        return Optional[str], Field(None, title="Query Parameters JSON",
                                    description='Optional filters and pagination, for example {"limit": 20}',
                                    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    return str, Field(..., title=name.replace("_", " ").title())


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    extra: dict[str, Any] = {"const": name, "ui:hidden": True,
                             "x-category": op.category, "x-is-trigger": False,
                             "x-display-name": op.label}
    if op.method == "POST" and name.startswith(("create_", "post_", "add_")):
        extra.update({"x-creates-resource": True,
                      "x-resource-type": "constant_contact_" + name.removeprefix("create_")})
    fields: dict[str, tuple[Any, Any]] = {}
    for key in (*op.path_fields, *op.required_query_fields):
        fields[key] = _model_field(key)
    if op.body_required:
        fields["payload_json"] = _model_field("payload_json")
    fields["query_json"] = _model_field("query_json", False)
    return create_model(
        "ConstantContact" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(name, title=op.label, json_schema_extra=extra)),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ConstantContactOnNewContactConfig(PollTriggerConfigBase):
    operation: Literal["on_new_contact"] = Field(
        "on_new_contact", title="On New Contact",
        json_schema_extra={"const": "on_new_contact", "ui:hidden": True,
                           "x-category": "Triggers", "x-is-trigger": True,
                           "x-display-name": "On New Contact"},
    )
    list_id: Optional[str] = Field(None, title="List ID",
                                   description="Optional list to monitor; leave blank for all contacts")


ConstantContactConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values()) + (ConstantContactOnNewContactConfig,)],
    Discriminator("operation"),
]


class ConstantContactNodeConfig(NodeConfig[ConstantContactConfig, ConstantContactOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class ConstantContactNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-constant-contact"
    connection_evidence = ConnectionEvidence(
        operation="get_lists", noun="contact lists", identity_operation="get_account_by_id",
        identity_keys=("organization_name", "contact_email", "encoded_account_id"))
    scope_registry = CONSTANT_CONTACT_SCOPES
    edit_examples = [
        "Create a Constant Contact contact", "Add contacts to a list",
        "Schedule an email campaign", "Read campaign open and click reports",
    ]

    @classmethod
    def get_config_model(cls):
        return ConstantContactNodeConfig

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        if config.get("operation") == "on_new_contact":
            return bool(output.get("new_contact_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        contacts = output.get("contacts") if isinstance(output, dict) else None
        if not isinstance(contacts, list):
            return super().resolve_agent_event(output)
        if not contacts:
            return None
        lines = []
        for contact in contacts[:10]:
            name = " ".join(filter(None, (contact.get("first_name"), contact.get("last_name"))))
            email = (contact.get("email_address") or {}).get("address")
            lines.append(f"- {name or email or 'Contact'} ({email or 'no email'}; contact_id {contact.get('contact_id')})")
        return {"text": f"Constant Contact: {len(contacts)} new contact(s):\n" + "\n".join(lines),
                "conversation_key": None}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.constant_contact_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="constant_contact")

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, API_BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        if response.is_error:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = payload.get("error_message") or payload.get("message") or payload.get("error")
                elif isinstance(payload, list):
                    detail = "; ".join(str(item.get("error_message") or item) for item in payload[:3])
                else:
                    detail = None
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Constant Contact API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Constant Contact returned a non-JSON response ({response.status_code})") from exc

    @staticmethod
    def _parse_object(raw: str, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    async def _poll_contacts(self, token: str, list_id: Optional[str]) -> dict[str, Any]:
        contacts: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "created_after": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "limit": 500,
        }
        if list_id:
            params["lists"] = list_id
        for _ in range(10):
            page = await self._request(token, "GET", "/contacts", params=params)
            rows = page.get("contacts") if isinstance(page, dict) else None
            if not isinstance(rows, list):
                raise ValueError("Constant Contact contacts response was not a list")
            contacts.extend(row for row in rows if isinstance(row, dict))
            next_link = (page.get("_links") or {}).get("next") or {}
            href = next_link.get("href") if isinstance(next_link, dict) else None
            if not href:
                break
            parsed = urlparse(urljoin(API_BASE + "/contacts", href))
            if parsed.scheme != "https" or parsed.netloc != "api.cc.email" or parsed.path != "/v3/contacts":
                raise ValueError("Constant Contact returned an invalid contacts page link")
            params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        else:
            raise ValueError("More than 5,000 recent contacts match this trigger; narrow it to a list")
        fresh = await self._filter_unseen(
            contacts, lambda row: str(row["contact_id"]) if row.get("contact_id") else None)
        return {"contacts": fresh, "new_contact_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ConstantContactNodeConfig):
            raise ValueError("Constant Contact configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Constant Contact account")
        config = self.config.config
        name = config.operation
        self.scope_registry.require(name)
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.constant_contact_oauth import refresh_access_token
        credential_data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential_data, refresh=refresh_access_token,
            provider="constant_contact", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at", "scope"):
            setattr(credential, key, credential_data.get(key))
        if isinstance(config, ConstantContactOnNewContactConfig):
            return await self._poll_contacts(token, config.list_id)
        op = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for field in op.path_fields:
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        params = self._parse_object(values.pop("query_json"), "Query Parameters JSON") if "query_json" in values else {}
        for field in op.required_query_fields:
            params[field] = values.pop(field)
        body = self._parse_object(values.pop("payload_json"), "Request JSON") if op.body_required else None
        data = await self._request(token, op.method, path, params=params or None, body=body)
        return {"status": "success", "operation": name, "data": data}
