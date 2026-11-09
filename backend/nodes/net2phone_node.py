"""net2phone v1.10 operations from https://developer.net2phone.com/api-explorer/v1.

Accepts an existing v1 bearer access token as documented in Getting Started.
The user must replace expired tokens. v2 API keys are a different contract.
"""
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.net2phone import NET2PHONE_SCOPES

BASE = "https://api.n2p.io/v1"
ACCEPT = "application/vnd.integrate.v1.10.0+json"
DOCS = "https://developer.net2phone.com/api-explorer/v1"


class Net2PhoneAccessToken(BaseModel):
    model_config = ConfigDict(title="net2phone Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
        "x-credential-instructions": "Paste an existing net2phone v1 access token obtained through the provider's documented authentication flow. This is not a v2 API key. Access tokens expire; replace the token here when it expires. NoClick verifies it by reading your current user."})
    credential_type: Literal["net2phone_access_token"] = Field("net2phone_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class Net2PhoneOAuthCredential(BaseModel):
    model_config = ConfigDict(title="net2phone Account", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "net2phone",
            "x-oauth-scopes": NET2PHONE_SCOPES.declared_scopes(), "x-credential-url": DOCS})
    credential_type: Literal["net2phone_oauth"] = Field("net2phone_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token expiry")


Net2PhoneCredential = Union[Net2PhoneAccessToken, Net2PhoneOAuthCredential]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def text(title, required=False, **kwargs):
    return (str if required else Optional[str], Field(... if required else None, title=title, **kwargs))


def integer(title, required=False, **kwargs):
    return (int if required else Optional[int], Field(... if required else None, title=title, **kwargs))


CDR_FIELDS = {
    "start_date": text("Start date", True, description="Calls started after this ISO 8601 time; UTC if timezone omitted.", json_schema_extra={"format": "date-time"}),
    "end_date": text("End date", description="Provider end_date filter (ISO 8601).", json_schema_extra={"format": "date-time"}),
    "user": integer("User extension"),
    "cursor": text("Cursor", description="Use the cursor returned by the previous page."),
    "limit": integer("Page size (Gen P/X/U)", ge=1, le=100),
    "page_size": integer("Page size (Gen V)", ge=1, le=100),
    "type": (Optional[Literal["Incoming", "Outgoing", "On Net"]], Field(None, title="Call type")),
    "recording_available": (Optional[bool], Field(None, title="Only calls with recordings (Gen V)")),
    "min_duration": integer("Minimum seconds (Gen V)"),
    "max_duration": integer("Maximum seconds (Gen V)"),
    "phone_number": text("Phone number (Gen V)"),
}
SUBSCRIPTION_FIELDS = {
    "post_uri": text("Delivery URL", True, json_schema_extra={"format": "uri"}),
    "user": text("User", description="User extension; omit for all users."),
    "calls": (bool, Field(True, title="Call events")),
    "cdrs": (bool, Field(False, title="Call detail record events")),
    "recordings": (bool, Field(False, title="Recording events")),
    "expires_in": (int, Field(604800, ge=1, le=604800, title="Subscription lifetime in seconds")),
}
# Each action issues exactly one operation in the provider's contract.
OPERATIONS = {
    "get_current_user": ("Get Current User", "GET", "/users/current/", {}, "none"),
    "get_account": ("Get Current Account", "GET", "/accounts/current/", {}, "none"),
    "list_users": ("List Users", "GET", "/users/", {}, "none"),
    "get_user": ("Get User", "GET", "/users/{userId}/", {"userId": integer("User ID", True)}, "none"),
    "list_current_user_cdrs": ("List My Call Records", "GET", "/cdrs/users/current/", CDR_FIELDS, "query"),
    "list_user_cdrs": ("List User Call Records", "GET", "/cdrs/users/{userId}/", {**CDR_FIELDS, "userId": integer("User ID", True)}, "query"),
    "list_cdrs": ("List Call Records", "GET", "/cdrs/users/", CDR_FIELDS, "query"),
    "list_available_endpoints": ("List Available Endpoints", "GET", "/available/endpoint/", {}, "none"),
    "place_call": ("Place Call", "POST", "/calls/", {
        "to": text("Destination", True, description="E.164 phone number, extension, or (Gen V) SIP address."),
        "from_number": text("From", description="User ID, extension, phone number or SIP user, depending on account generation."),
        "auto_answer": (Optional[bool], Field(None, title="Auto answer (Gen V)")),
    }, "body"),
    "create_subscription": ("Create Webhook Subscription", "POST", "/subscriptions/", SUBSCRIPTION_FIELDS, "body"),
    "get_subscription": ("Get Webhook Subscription", "GET", "/subscriptions/{subscriptionId}/", {"subscriptionId": integer("Subscription ID", True)}, "none"),
    "delete_subscription": ("Delete Webhook Subscription", "DELETE", "/subscriptions/{subscriptionId}/", {"subscriptionId": integer("Subscription ID", True)}, "none"),
}
MODELS = {}
for name, (label, method, path, fields, location) in OPERATIONS.items():
    MODELS[name] = create_model("Net2Phone" + "".join(part.title() for part in name.split("_")), __base__=Input,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})), **fields)


class Net2PhoneOnCallEvent(WebhookTriggerConfigBase):
    operation: Literal["on_call_event"] = Field("on_call_event", title="On Call Event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Call Event"})
    user: Optional[str] = Field(None, title="User", description="Omit to subscribe to calls for all users.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})
    subscription_expires_at: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})


Net2PhoneConfig = Annotated[Union[tuple(MODELS.values()) + (Net2PhoneOnCallEvent,)], Field(discriminator="operation")]


class Net2PhoneNodeConfig(NodeConfig[Net2PhoneConfig, Net2PhoneCredential]):
    pass


class Net2PhoneNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-net2phone"
    credential_provider_labels = {"net2phone": "net2phone Account"}
    scope_registry = NET2PHONE_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_current_user", identity_operation="get_current_user", noun="user", label_keys=("email", "username", "user"))
    webhook_signing_secret_not_issued = True
    webhook_replace_stale_endpoint = True
    edit_examples = ["Place a phone call", "Read my recent calls", "Start a workflow when a call changes state"]

    @classmethod
    def get_config_model(cls):
        return Net2PhoneNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_data.get("credential_type") != "net2phone_oauth" or not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.net2phone_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="net2phone")

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        token = Net2PhoneAccessToken.model_validate({"access_token": credential.get("access_token")}).access_token
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": ACCEPT})
        if response.is_error:
            try:
                detail = response.json().get("message", "Request failed")
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"net2phone API {response.status_code}: {str(detail).replace(token, '[redacted]')[:1000]}")
        # Calls return 201 with no body; subscription deletion returns 204.
        return response.json() if response.content else {"http_status": response.status_code}

    async def execute(self, inputs: dict[str, Any]):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a net2phone access token")
        op = self.config.config
        self.scope_registry.require(op.operation)
        credential_data = self.config.credentials.model_dump()
        if isinstance(self.config.credentials, Net2PhoneOAuthCredential) and credential_data.get("refresh_token"):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.net2phone_oauth import refresh_access_token
            await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=credential_data, refresh=refresh_access_token,
                provider="net2phone", caller_path="execute")
        if isinstance(op, Net2PhoneOnCallEvent):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload") or inputs
            return {"status": "success", "operation": op.operation, "data": payload}
        _, method, path, _, location = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        if "from_number" in values:
            values["from"] = values.pop("from_number")
        data = await self._request(credential_data, method, path,
            params=values if location == "query" else None, body=values if location == "body" else None)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        body = {"post_uri": webhook_url, "calls": True, "cdrs": False, "recordings": False, "expires_in": 604800}
        if config.get("user"):
            body["user"] = config["user"]
        result = await cls._request(credential, "POST", "/subscriptions/", body=body)
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            raise ValueError("net2phone did not return a subscription ID")
        return {"external_webhook_id": str(result["id"]), "subscription_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=604800)).isoformat()}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if identifier is not None and credential:
            if not str(identifier).isdigit():
                raise ValueError("Invalid net2phone subscription ID")
            await cls._request(credential, "DELETE", f"/subscriptions/{identifier}/")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"user": config.get("user")}

    @classmethod
    def webhook_registration_stale(cls, config, webhook_data):
        expiry = config.get("subscription_expires_at")
        if not expiry:
            return True
        try:
            return datetime.now(timezone.utc) + timedelta(minutes=10) >= datetime.fromisoformat(expiry)
        except (ValueError, TypeError):
            return True

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # v1 specifies no signature or signing secret. The URL is a capability.
        return True

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": "on_call_event", "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output.get("data", output)
        # The documented examples are flat; the schema also describes calls.
        call = payload.get("calls", payload)
        source, target = call.get("from") or {}, call.get("to") or {}
        call_id = source.get("call_id") or target.get("call_id")
        if not call_id:
            return None
        state = target.get("state") or source.get("state") or "changed"
        text = f"net2phone call {state}: {source.get('name') or source.get('id') or 'caller'} to {target.get('id') or 'recipient'}."
        text += f"\nAccount: {source.get('domain') or target.get('domain') or 'external'}. Started: {call.get('time_start')}. Duration: {call.get('duration')} seconds."
        text += f"\nCall IDs: from={source.get('call_id')}, to={target.get('call_id')}. Users: from={source.get('user')}, to={target.get('user')}."
        return {"text": text, "conversation_key": str(call_id), "title": f"Call {state}"}
