"""ezeep Printing API v1 management and documented print-job webhooks.

Contract: https://api2.ezeep.com/printing/v1/schema/
Webhook registration and payload: https://apidocs.ezeep.com/ezeepblue/api/rest_api/webhooks/README.html
This API manages printing resources; document submission belongs to ezeep's separate Print API.
"""
from __future__ import annotations

import base64
import hmac
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.ezeep_printing import EZEEP_PRINTING_SCOPES

BASE = "https://api2.ezeep.com"
TYPE = "ezeep_printing_oauth"
TOPICS = ("printjob_succeeded",)


def text(title, *, required=False, maximum=255):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1, max_length=maximum))


def identifier(title):
    return (UUID, Field(..., title=title))


PAGE = {
    "limit": (int, Field(100, ge=1, le=1000, title="Page Size")),
    "offset": (int, Field(0, ge=0, title="Offset")),
    "q": text("Search"),
}
GROUP_FIELDS = {
    "name": text("Name"), "description": (Optional[str], Field(None, max_length=255)),
    "local_printing_enabled": (Optional[bool], None), "myprinters_enabled": (Optional[bool], None),
}
PROFILE_FIELDS = {
    "name": text("Name"), "description": (Optional[str], Field(None, max_length=255)),
    "color": (Optional[Literal["MONOCHROME", "COLOR"]], None),
    "orientation": (Optional[Literal["LANDSCAPE", "PORTRAIT"]], None),
    "duplex": (Optional[Literal["DUPLEX_SIMPLEX", "DUPLEX_HORIZONTAL", "DUPLEX_VERTICAL"]], None),
    "paper_name": text("Paper Name"), "resolution": (Optional[int], None), "tray": text("Tray"),
    "selected_printers": (Optional[list[UUID]], Field(None, title="Printer IDs")),
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    fields: dict
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


OPERATIONS = {
    "get_current_user": Operation("GET", "/users/me/", "Account", {}),
    "list_printers": Operation("GET", "/printers/", "Printers", {
        **PAGE, "location": text("Location"), "connector_id": (Optional[UUID], None),
        "status": (Optional[Literal["ON", "OFF", "NOC"]], None),
    }, ("limit", "offset", "q", "location", "connector_id", "status")),
    "get_printer": Operation("GET", "/printers/{id}/", "Printers", {"id": identifier("Printer ID")}),
    "update_printer": Operation("PATCH", "/printers/{id}/", "Printers", {
        "id": identifier("Printer ID"), "name": text("Name"), "location": (Optional[str], Field(None, max_length=255)),
        "manual_driver_id": (Optional[UUID], None), "is_favorite": (Optional[bool], None),
    }, body=("name", "location", "manual_driver_id", "is_favorite")),
    "delete_printer": Operation("DELETE", "/printers/{id}/", "Printers", {"id": identifier("Printer ID")}),
    "get_printer_capabilities": Operation("GET", "/printers/{printer_id}/capabilities/", "Printers", {"printer_id": identifier("Printer ID")}),
    "list_print_jobs": Operation("GET", "/printjobs/", "Print Jobs", PAGE, ("limit", "offset", "q")),
    "get_print_job": Operation("GET", "/printjobs/{id}/", "Print Jobs", {"id": identifier("Print Job ID")}),
    "delete_print_job": Operation("DELETE", "/printjobs/{id}/", "Print Jobs", {"id": identifier("Print Job ID")}),
    "list_connectors": Operation("GET", "/connectors/", "Connectors", PAGE, ("limit", "offset", "q")),
    "get_connector": Operation("GET", "/connectors/{id}/", "Connectors", {"id": identifier("Connector ID")}),
    "update_connector": Operation("PATCH", "/connectors/{id}/", "Connectors", {
        "id": identifier("Connector ID"), "readable_name": text("Name"),
        "description": (Optional[str], Field(None, max_length=255)), "location": text("Location"),
    }, body=("readable_name", "description", "location")),
    "list_groups": Operation("GET", "/groups/", "Groups", PAGE, ("limit", "offset", "q")),
    "get_group": Operation("GET", "/groups/{id}/", "Groups", {"id": identifier("Group ID")}),
    "create_group": Operation("POST", "/groups/", "Groups", {**GROUP_FIELDS, "name": text("Name", required=True)}, body=tuple(GROUP_FIELDS)),
    "update_group": Operation("PATCH", "/groups/{id}/", "Groups", {"id": identifier("Group ID"), **GROUP_FIELDS}, body=tuple(GROUP_FIELDS)),
    "delete_group": Operation("DELETE", "/groups/{id}/", "Groups", {"id": identifier("Group ID")}),
    "list_users": Operation("GET", "/users/", "Users", PAGE, ("limit", "offset", "q")),
    "get_user": Operation("GET", "/users/{id}/", "Users", {"id": identifier("User ID")}),
    "list_printer_profiles": Operation("GET", "/printer_profiles/", "Printer Profiles", PAGE, ("limit", "offset", "q")),
    "get_printer_profile": Operation("GET", "/printer_profiles/{id}/", "Printer Profiles", {"id": identifier("Profile ID")}),
    "create_printer_profile": Operation("POST", "/printer_profiles/", "Printer Profiles", {**PROFILE_FIELDS, "name": text("Name", required=True)}, body=tuple(PROFILE_FIELDS)),
    "update_printer_profile": Operation("PATCH", "/printer_profiles/{id}/", "Printer Profiles", {"id": identifier("Profile ID"), **PROFILE_FIELDS}, body=tuple(PROFILE_FIELDS)),
    "delete_printer_profile": Operation("DELETE", "/printer_profiles/{id}/", "Printer Profiles", {"id": identifier("Profile ID")}),
}


class EzeepPrintingOAuthCredential(BaseModel):
    model_config = ConfigDict(title="ezeep Printing Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "ezeep-printing",
        "x-oauth-scopes": EZEEP_PRINTING_SCOPES.declared_scopes(),
        "x-credential-url": "https://apidocs.ezeep.com/ezeepblue/auth/README.html",
        "x-credential-instructions": "Connect your ezeep account with printing and webhooks permissions. For manual connection, paste an existing access token and refresh token from your production OAuth client. Access tokens last one hour.",
    })
    credential_type: Literal["ezeep_printing_oauth"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Token", key=True)
        if not value or len(value) > 16384 or any(c.isspace() for c in value):
            raise ValueError("Paste the token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def nonempty_update(self):
        spec = OPERATIONS[self.operation]
        if spec.method == "PATCH" and not any(getattr(self, key) is not None for key in spec.body):
            raise ValueError("Provide at least one field to update")
        return self


def _make_config(name, spec):
    return create_model("EzeepPrinting" + "".join(w.title() for w in name.split("_")) + "Config", __base__=_Input,
        __module__=__name__, operation=(Literal[name], Field(name, json_schema_extra={
            "ui:hidden": True, "x-display-name": name.replace("_", " ").title(),
            "x-category": spec.category, "x-is-trigger": False,
        })), **spec.fields)


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({m.__name__: m for m in CONFIG_MODELS.values()})


class EzeepPrintingOnPrintJobConfig(WebhookTriggerConfigBase):
    operation: Literal["on_print_job_succeeded"] = Field("on_print_job_succeeded", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Print Job Completed", "x-category": "Triggers"})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})


EzeepPrintingConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (EzeepPrintingOnPrintJobConfig,)], Field(discriminator="operation")]


class EzeepPrintingNodeConfig(NodeConfig[EzeepPrintingConfig, EzeepPrintingOAuthCredential]):
    pass


class EzeepPrintingNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-ezeep-printing"
    scope_registry = EZEEP_PRINTING_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_printers", identity_operation="get_current_user", noun="printers")
    edit_examples = ["List ezeep printers", "Update an ezeep printer location", "Create a printer profile", "Watch completed ezeep print jobs"]

    @classmethod
    def get_config_model(cls):
        return EzeepPrintingNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.ezeep_printing_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="ezeep-printing")

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        if not path.startswith(("/printing/v1/", "/webhooks/endpoints")) or ".." in path:
            raise ValueError("Invalid ezeep API path")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = response.text[:2000].replace(token, "[redacted]")
            if body and body.get("basic_password"):
                detail = detail.replace(body["basic_password"], "[redacted]")
            raise ValueError(f"ezeep API {response.status_code}: {detail}")
        if not response.content:
            return {}
        if len(response.content) > 5_000_000:
            raise ValueError("ezeep response exceeds the size limit")
        return response.json()

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, EzeepPrintingOnPrintJobConfig):
            return self.resolve_trigger_payload(inputs, op.model_dump()) or {"status": "success", "no_event": True}
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your ezeep account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.ezeep_printing_oauth import refresh_access_token
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data, refresh=refresh_access_token, provider="ezeep-printing", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, data.get(key))
        self.scope_registry.require(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = "/printing/v1" + spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", str(value))
        body = {k: values[k] for k in spec.body if k in values}
        payload = await self._request(token, spec.method, path,
            params={k: values[k] for k in spec.query if k in values} or None,
            body=body if spec.body else None)
        return {"status": "success", "operation": op.operation, "data": payload}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        cls.scope_registry.require("on_print_job_succeeded")
        # ezeep supports HTTP Basic, not a body HMAC. Keep the random password
        # in the platform's persisted signing-secret slot; never in credentials.
        password = secrets.token_urlsafe(32)
        result = await cls._request(credential["access_token"], "POST", "/webhooks/endpoints", body={
            "name": f"NoClick {node_id}", "url": webhook_url, "topics": list(TOPICS),
            "authentication_scheme": "basic", "basic_username": "noclick", "basic_password": password,
        })
        endpoint = str(UUID(result["endpoint_id"]))
        return {"external_webhook_id": endpoint, "signing_secret": password}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint = (config or {}).get("external_webhook_id")
        if endpoint and credential:
            await cls._request(credential["access_token"], "DELETE", "/webhooks/endpoints/" + str(UUID(str(endpoint))))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        expected = "Basic " + base64.b64encode(("noclick:" + secret).encode()).decode()
        actual = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        if not isinstance(actual, str):
            return False
        scheme, separator, value = actual.partition(" ")
        return bool(separator) and scheme.lower() == "basic" and hmac.compare_digest(value.encode(), expected[6:].encode())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if not isinstance(payload, dict) or payload.get("topic") not in TOPICS:
            return False
        return True

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "operation": "on_print_job_succeeded", "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output.get("data") if isinstance(output, dict) else None
        if not isinstance(payload, dict) or payload.get("topic") not in TOPICS:
            return None
        content = payload.get("content")
        job = content.get("printjob") if isinstance(content, dict) else None
        if not isinstance(job, dict) or not job.get("printjob_id"):
            return None
        who = job.get("user_name") or job.get("user_email") or job.get("user_id") or "An ezeep user"
        where = job.get("printer_name") or job.get("printer_id") or job.get("type")
        filename = job.get("filename") or "document"
        text = f"ezeep: {who}'s print job {job['status']}: {filename} on {where}."
        text += f"\nPrint job ID: {job['printjob_id']}; event ID: {payload['event_id']}; created: {payload['created']}."
        if job.get("printer_id"):
            text += f"\nPrinter ID: {job['printer_id']}."
        if job.get("user_id"):
            text += f" User ID: {job['user_id']}."
        return {"text": text, "conversation_key": str(job["printjob_id"])}
