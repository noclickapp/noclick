"""Cardclan Integration API reads and personalized card workflows.

Each operation makes one request to the published v1 contract using a pasted
Integration Key. Writes are never retried automatically.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.cardclan.io/api"


class CardclanIntegrationKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cardclan Integration Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.cardclan.io",
            "x-credential-instructions": "In Cardclan Settings, click Generate Integration Key and paste the key here. Use an Integration Key, which is different from a regular Cardclan API key. NoClick validates it by reading the associated user ID.",
        })
    credential_type: Literal["cardclan_integration_key"] = Field("cardclan_integration_key", json_schema_extra={"ui:hidden": True})
    integration_key: str = Field(..., title="Integration key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("integration_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Integration key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Integration Key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("workspace_id", "card_id", "integration_id", "user_id", "email_account", mode="before", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value)):
            raise ValueError("Use a Cardclan ID without a URL or path")
        return value


class ValidateAuthentication(_Input):
    operation: Literal["validate_authentication"] = Field("validate_authentication", title="Validate Authentication", json_schema_extra={"ui:hidden": True})


class ListWorkspaces(_Input):
    operation: Literal["list_workspaces"] = Field("list_workspaces", title="List Workspaces", json_schema_extra={"ui:hidden": True})


class ListCards(_Input):
    operation: Literal["list_cards"] = Field("list_cards", title="List Workspace Cards", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID", description="Use an ID returned by List Workspaces.")


class ListEmailAccounts(_Input):
    operation: Literal["list_email_accounts"] = Field("list_email_accounts", title="List Email Accounts", json_schema_extra={"ui:hidden": True})


class _Personalize(_Input):
    card_id: str = Field(..., title="Card ID")
    integration_id: str = Field(..., title="Integration Config ID")
    merge_tags: str = Field(..., title="Recipient Merge Tags", description='JSON array of recipients, each with name and email plus any custom string merge tags. Example: [{"name":"John Doe","email":"john@example.com"}].', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})

    @field_validator("merge_tags")
    @classmethod
    def recipients(cls, value):
        try:
            rows = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("Enter a JSON array of recipient merge tags") from None
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise ValueError("Provide between 1 and 1000 recipients")
        for row in rows:
            if not isinstance(row, dict) or not row.get("name") or not row.get("email") or any(not isinstance(v, str) for v in row.values()):
                raise ValueError("Each recipient requires name and email; all merge tag values must be strings")
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", row["email"]):
                raise ValueError("Each recipient requires a valid email address")
        return value


class SendCard(_Personalize):
    operation: Literal["send_card"] = Field("send_card", title="Send Personalized Card", description="Sends email to the supplied recipients. Inspect Cardclan before retrying an uncertain result.", json_schema_extra={"ui:hidden": True})
    email_account: str | None = Field(None, title="Email Account", description="An email account ID from List Email Accounts, or CardClan for the default sender. Omit to use the provider default.")


class GetCardUrl(_Personalize):
    operation: Literal["get_card_url"] = Field("get_card_url", title="Generate Personalized Card URL", description="Creates a personalized card URL without sending email.", json_schema_extra={"ui:hidden": True})


class CreateConfig(_Input):
    operation: Literal["create_config"] = Field("create_config", title="Create Integration Config", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., title="User ID", description="Returned by Validate Authentication.")
    workspace_id: str = Field(..., title="Workspace ID")
    card_id: str = Field(..., title="Card ID")


class GetConfig(_Input):
    operation: Literal["get_config"] = Field("get_config", title="Get Integration Config", json_schema_extra={"ui:hidden": True})
    integration_id: str = Field(..., title="Integration Config ID")


class GetConfigByCard(_Input):
    operation: Literal["get_config_by_card"] = Field("get_config_by_card", title="Get Config by Card", json_schema_extra={"ui:hidden": True})
    card_id: str = Field(..., title="Card ID")


class ListWorkflowCards(_Input):
    operation: Literal["list_workflow_cards"] = Field("list_workflow_cards", title="List Cards with Workflows", json_schema_extra={"ui:hidden": True})


class GetCardDetails(_Input):
    operation: Literal["get_card_details"] = Field("get_card_details", title="Get Card Details", json_schema_extra={"ui:hidden": True})
    card_id: str = Field(..., title="Card ID")


CardclanOperation = Annotated[Union[ValidateAuthentication, ListWorkspaces, ListCards, ListEmailAccounts,
    SendCard, GetCardUrl, CreateConfig, GetConfig, GetConfigByCard, ListWorkflowCards, GetCardDetails], Field(discriminator="operation")]


class CardclanNodeConfig(NodeConfig[CardclanOperation, CardclanIntegrationKeyCredential]):
    pass


# Method, contract route, successful status. No caller-controlled URL is accepted.
ROUTES = {
    "validate_authentication": ("GET", "/integration/auth/validate", 200),
    "list_workspaces": ("GET", "/integration/workspaces", 200),
    "list_cards": ("POST", "/integration/cards", 200),
    "list_email_accounts": ("GET", "/integration/email-accounts", 200),
    "send_card": ("POST", "/integration/send-card", 201),
    "get_card_url": ("POST", "/integration/get-card-url", 201),
    "create_config": ("POST", "/integration/config", 201),
    "get_config": ("GET", "/integration/config", 200),
    "get_config_by_card": ("GET", "/integration/config/by-card", 200),
    "list_workflow_cards": ("GET", "/integration/workflow-cards", 200),
    "get_card_details": ("GET", "/integration/card-details/{cardId}", 200),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class CardclanNode(WorkflowNode):
    integration_type = "automation-cardclan"
    connection_evidence = ConnectionEvidence(noun="Cardclan account", identity_operation="validate_authentication", identity_keys=("user_id",))

    @classmethod
    def get_config_model(cls):
        return CardclanNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Cardclan Integration Key")
        cfg = self.config.config
        secret = self.config.credentials.integration_key
        method, route, expected_status = ROUTES[cfg.operation]
        params, body = {}, None
        if isinstance(cfg, ListCards):
            params["workspace"] = cfg.workspace_id
        elif isinstance(cfg, GetConfig):
            params["integrationId"] = cfg.integration_id
        elif isinstance(cfg, GetConfigByCard):
            params["cardId"] = cfg.card_id
        elif isinstance(cfg, GetCardDetails):
            route = route.replace("{cardId}", quote(cfg.card_id, safe=""))
        elif isinstance(cfg, _Personalize):
            body = {"card": cfg.card_id, "integrationId": cfg.integration_id, "mergeTags": json.loads(cfg.merge_tags)}
            if isinstance(cfg, SendCard) and cfg.email_account is not None:
                body["emailAccount"] = cfg.email_account
        elif isinstance(cfg, CreateConfig):
            body = {"userId": cfg.user_id, "workspaceId": cfg.workspace_id, "cardId": cfg.card_id}
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        kwargs = {"headers": headers, "params": params}
        if body is not None:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Cardclan request did not complete. Inspect Cardclan before retrying a write.") from None
        try:
            payload = response.json() if len(response.content) <= 2_000_000 else None
        except ValueError:
            payload = None
        if response.status_code != expected_status:
            message = payload.get("message") or payload.get("error") if isinstance(payload, dict) else None
            message = message if isinstance(message, str) else "Cardclan did not return the documented success status"
            return {"status": "error", "error": _redact(message[:2000], secret), "status_code": response.status_code, "http_status": response.status_code}
        if (not isinstance(payload, (dict, list)) or response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"):
            raise ValueError("Cardclan returned an unexpected response. Inspect Cardclan before retrying a write.")
        if isinstance(payload, dict) and (payload.get("error") or payload.get("success") is False or payload.get("status") is False):
            return {"status": "error", "error": _redact(str(payload.get("message") or payload.get("error") or "Cardclan rejected the operation"), secret)}
        list_response = isinstance(cfg, (ListWorkspaces, ListCards, ListEmailAccounts, GetConfig))
        if list_response:
            if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                raise ValueError("Cardclan returned an unexpected list response")
        elif not isinstance(payload, dict):
            raise ValueError("Cardclan did not confirm the operation with an object response")
        if isinstance(cfg, ValidateAuthentication):
            if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("user_id"), str) or not payload["user_id"]:
                raise ValueError("Cardclan did not confirm an account identity")
        if isinstance(cfg, SendCard) and (not isinstance(payload, dict) or payload.get("status") is not True):
            raise ValueError("Cardclan did not confirm sending. Inspect Cardclan before retrying.")
        return {"status": "success", "operation": cfg.operation, "data": _redact(payload, secret), "http_status": response.status_code}
