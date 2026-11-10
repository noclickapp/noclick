"""EVE Swagger Interface character and market automations.

Wire contract: https://esi.evetech.net/meta/openapi.json, 2020-01-01.
Mail polling uses the documented 50 most recent headers, not an invented webhook.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.evetech_operations import OPERATIONS
from nodes.scopes.evetech import EVETECH_SCOPES


class EvetechOAuthCredential(BaseModel):
    model_config = ConfigDict(title="EVE Swagger Interface OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "evetech",
            "x-oauth-scopes": EVETECH_SCOPES.declared_scopes(),
            "x-credential-url": "https://developers.eveonline.com/applications",
            "x-credential-instructions": "Enter your numeric character ID and choose that same character during EVE sign-in. For manual connect, paste that character's existing EVE SSO access token. Private operations are authorized by EVE for that character only.",
        })
    credential_type: Literal["evetech_oauth"] = Field("evetech_oauth", json_schema_extra={"ui:hidden": True})
    character_id: str = Field(..., title="Character ID", pattern=r"^[1-9][0-9]{0,18}$")
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")


class Recipient(BaseModel):
    recipient_id: int = Field(..., gt=0)
    recipient_type: Literal["alliance", "character", "corporation", "mailing_list"]


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def mail_changes(self):
        if getattr(self, "operation", None) == "update_mail":
            if self.labels is None and self.read is None:
                raise ValueError("Set labels or the read flag")
            if self.labels is not None and len(self.labels) != len(set(self.labels)):
                raise ValueError("Mail labels must be unique")
        return self


# Explicit human inputs: all path IDs are positive integers, never arbitrary URLs.
ID = Annotated[int, Field(gt=0)]
FIELDS = {
    "region_id": (ID, Field(..., title="Region ID")),
    "corporation_id": (ID, Field(..., title="Corporation ID")),
    "type_id": (ID, Field(..., title="Item Type ID")),
    "mail_id": (ID, Field(..., title="Mail ID")),
    "event_id": (ID, Field(..., title="Calendar Event ID")),
    "destination_id": (ID, Field(..., title="Destination ID")),
    "order_type": (Literal["all", "buy", "sell"], Field("all", title="Order Type")),
    "page": (int, Field(1, ge=1, title="Page")),
    "from_id": (Optional[ID], Field(None, title="Transactions Before ID")),
    "last_mail_id": (Optional[ID], Field(None, title="Mail Before ID")),
    "from_event": (Optional[ID], Field(None, title="Events After ID")),
    "approved_cost": (int, Field(0, ge=0, title="Approved CSPA Cost")),
    "subject": (str, Field(..., max_length=1000, title="Subject")),
    "body": (str, Field(..., max_length=10000, title="Mail Body")),
    "recipients": (list[Recipient], Field(..., min_length=1, max_length=50, title="Recipients")),
    "labels": (Optional[list[int]], Field(None, max_length=25, title="Replacement Label IDs", description="Replaces all existing labels; an empty list removes them.")),
    "read": (Optional[bool], Field(None, title="Mark as Read")),
    "response": (Literal["accepted", "declined", "tentative"], Field(..., title="Response")),
    "add_to_beginning": (bool, Field(False, title="Add to Beginning")),
    "clear_other_waypoints": (bool, Field(False, title="Clear Other Waypoints")),
}


def _config(name, spec):
    fields = {}
    for key in FIELDS:
        if key in spec["query"] or key in spec["body"] or "{" + key + "}" in spec["path"]:
            fields[key] = FIELDS[key]
    if name == "list_market_orders":
        fields["type_id"] = (Optional[ID], Field(None, title="Item Type ID"))
    fields["operation"] = (Literal[name], Field(name, json_schema_extra={
        "ui:hidden": True, "x-display-name": spec["summary"],
        "x-method-kind": "read" if spec["method"] == "GET" else "write",
    }))
    return create_model("Evetech" + "".join(x.title() for x in name.split("_")) + "Config", __base__=OperationConfig, **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items() if name != "on_new_mail"}


class EvetechOnNewMailConfig(PollTriggerConfigBase):
    """Watch the 50 most recent mail headers. Choose an interval with fewer than 50 incoming mails between polls; the first poll establishes a baseline."""
    operation: Literal["on_new_mail"] = Field("on_new_mail", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On New Mail", "x-method-kind": "read",
    })
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True},
        title="New EVE Mail", extra="forbid")


EvetechConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (EvetechOnNewMailConfig,)], Field(discriminator="operation")]


class EvetechNodeConfig(NodeConfig[EvetechConfig, EvetechOAuthCredential]):
    model_config = ConfigDict(title="EVE Swagger Interface Node Configuration")


class EvetechNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-evetech"
    scope_registry = EVETECH_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_mail", noun="mail", label_keys=("subject", "mail_id"))
    edit_examples = ["Read market orders in The Forge", "Send EVE mail to a character", "Watch for new EVE mail", "Read my character wallet"]

    @classmethod
    def get_config_model(cls):
        return EvetechNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.evetech_oauth import OAUTH_PROVIDER
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="evetech")

    async def _token(self, credential):
        if not credential.refresh_token:
            return credential.access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.evetech_oauth import OAUTH_PROVIDER
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=OAUTH_PROVIDER.bind_refresh(data), provider="evetech",
            additional_token_fields=OAUTH_PROVIDER.credential_fields, caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at", "character_id"):
            setattr(credential, key, data.get(key))
        return token

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_mail_count")) if config.get("operation") == "on_new_mail" else True

    @classmethod
    def resolve_agent_event(cls, output):
        mails = output.get("mails") if isinstance(output, dict) else None
        if not isinstance(mails, list):
            return super().resolve_agent_event(output)
        if not mails:
            return None
        lines = [f"- {m.get('subject') or 'Untitled mail'} from character {m.get('from')} at {m.get('timestamp')} (mail {m['mail_id']})" for m in mails[:10]]
        return {"text": f"EVE character {output.get('character_id')} received {len(mails)} new mail(s):\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an EVE character")
        name = config.operation
        self.scope_registry.require(name)
        token = await self._token(credential)
        spec = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"].replace("{character_id}", quote(credential.character_id, safe=""))
        for key in tuple(values):
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values} if spec["body"] else None
        # No automatic retries: sending mail and UI writes may have succeeded.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(spec["method"], "https://esi.evetech.net" + path,
                params=params, json=body, headers={"Authorization": f"Bearer {token}",
                    "Accept": "application/json", "X-Compatibility-Date": "2020-01-01",
                    "User-Agent": "NoClick EVE integration (https://noclick.com)"})
        if response.status_code >= 300:
            try:
                error = response.json().get("error", "request failed")
            except (ValueError, AttributeError):
                error = "request failed"
            raise ValueError(f"EVE API error {response.status_code}: {str(error).replace(token, '[redacted]')}")
        data = response.json() if response.content else None
        if name == "on_new_mail":
            if not isinstance(data, list) or any(not isinstance(m, dict) or not isinstance(m.get("mail_id"), int) for m in data):
                raise ValueError("EVE returned invalid mail headers")
            # The endpoint returns the 50 most recent messages. Poll often enough
            # that fewer than 50 mails arrive between ticks (ESI caches for 30s).
            fresh = await self._filter_unseen(data, lambda m: str(m["mail_id"]))
            return {"mails": fresh, "new_mail_count": len(fresh), "character_id": credential.character_id}
        result = {"data": data, "http_status": response.status_code}
        if response.headers.get("X-Pages"):
            result["total_pages"] = int(response.headers["X-Pages"])
        if name == "list_mail" and isinstance(data, list) and len(data) == 50:
            result["next_last_mail_id"] = min(m["mail_id"] for m in data)
        return result
