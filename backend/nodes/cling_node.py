"""Cling company API: https://api.cling.se/openApiSpec (1.0.0).

Company API keys are pasted by the person. The document-accepted webhook
format and optional authentication are documented at
https://developer.cling.se/api/partner/webhooks.html and
https://developer.cling.se/api/document/webhooks.html.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.cling.se"


class ClingAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cling API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.cling.se/api/introduction/getting-started.html",
        "x-credential-instructions": "Paste an existing company API key from Cling. It inherits the permissions of the company user who created it. NoClick sends it in the apiKey header to api.cling.se.",
    })
    credential_type: Literal["cling_api_key"] = Field("cling_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def text(title, required=False, description=""):
    return (str if required else str | None, Field(... if required else None, title=title, min_length=1, description=description))


def identifier(resource, numeric=False):
    return {resource + "_id": (int if numeric else str, Field(..., title=resource.replace('_', ' ').title() + " ID", **({"ge": 1} if numeric else {"min_length": 1, "max_length": 256, "pattern": r"^[A-Za-z0-9_-]+$"})))}


PAGE = {"skip": (int, Field(0, ge=0, title="Skip")), "limit": (int, Field(20, ge=1, le=100, title="Page Size")), "sort": text("Sort", description="Property to sort on, prefixed with - for descending.")}
RANGE = {"start": (int, Field(0, ge=0, title="Start")), "end": (int, Field(20, ge=1, title="End", description="Exclusive end offset; must exceed start.")), "sort": text("Sort Property"), "order": (Literal["ASC", "DESC"], Field("ASC", title="Sort Order")), "where": text("Filter", description="Cling expression, for example or(status=active,status=completed).")}
DOC = identifier("document")
CUSTOMER = identifier("customer", True)
PROJECT = identifier("project", True)
TEMPLATE = identifier("template")
# One entry = one published HTTP operation. Response bodies are preserved.
OPERATIONS = {
    "list_documents": ("GET", "/document", {**PAGE, "status": text("Status"), "filter": text("Advanced Filter", description='JSON filter, e.g. {"status":{"$in":["draft","sent"]}}')}, "Documents"),
    "get_document": ("GET", "/document/{document_id}", DOC, "Documents"),
    "create_document": ("POST", "/document", {
        "template_id": text("Template ID", True), "customer_id": (int, Field(..., ge=1, title="Customer ID")),
        "name": text("Document Title", True), "language": text("Language"), "currency": text("Currency"),
    }, "Documents"),
    "update_document": ("PUT", "/document/{document_id}", {**DOC, "status": text("Status", True)}, "Documents"),
    "delete_document": ("DELETE", "/document/{document_id}", DOC, "Documents"),
    "restore_document": ("PATCH", "/document/{document_id}", DOC, "Documents"),
    "send_document": ("POST", "/document/{document_id}/send", DOC, "Documents"),
    "list_customers": ("GET", "/endCustomer", RANGE, "Customers"),
    "get_customer": ("GET", "/endCustomer/{customer_id}", CUSTOMER, "Customers"),
    "create_customer": ("POST", "/endCustomer", {"name": text("Name", True), "customer_type": (Literal["individual", "company"], Field("individual", title="Customer Type")), "email": text("Email")}, "Customers"),
    "update_customer": ("PUT", "/endCustomer/{customer_id}", {**CUSTOMER, "street": text("Street", True)}, "Customers"),
    "delete_customer": ("DELETE", "/endCustomer/{customer_id}", CUSTOMER, "Customers"),
    "restore_customer": ("PATCH", "/endCustomer/{customer_id}", CUSTOMER, "Customers"),
    "list_projects": ("GET", "/project", RANGE, "Projects"),
    "get_project": ("GET", "/project/{project_id}", PROJECT, "Projects"),
    "create_project": ("POST", "/project", {"name": text("Name", True)}, "Projects"),
    "update_project": ("PUT", "/project/{project_id}", {**PROJECT, "status": text("Status", True)}, "Projects"),
    "delete_project": ("DELETE", "/project/{project_id}", PROJECT, "Projects"),
    "restore_project": ("PATCH", "/project/{project_id}", PROJECT, "Projects"),
    "list_templates": ("GET", "/template", {**PAGE, "language": text("Language")}, "Templates"),
    "get_template": ("GET", "/template/{template_id}", TEMPLATE, "Templates"),
}


def _model(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Cling" + label.replace(" ", "") + "Config", __module__=__name__, __base__=_Input,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": spec[3], "x-is-trigger": False})), **spec[2])


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ClingOnDocumentAcceptedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_document_accepted"] = Field("on_document_accepted", title="On Document Accepted", json_schema_extra={
        "const": "on_document_accepted", "ui:hidden": True, "x-display-name": "On Document Accepted", "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: str | None = Field(None, title="Webhook URL", description="Cling delivers document.accepted events here automatically. Cling's default deliveries are unsigned; keep this URL private.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


ClingConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ClingOnDocumentAcceptedConfig,)], Discriminator("operation")]


class ClingNodeConfig(NodeConfig[ClingConfig, ClingAPIKeyCredential]):
    pass


class ClingNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-cling"
    connection_evidence = ConnectionEvidence(operation="list_documents", noun="documents")
    webhook_signing_secret_not_issued = True
    edit_examples = ["Create a Cling document from a template", "Send a Cling document", "When a Cling document is accepted", "Create a Cling customer"]

    @classmethod
    def get_config_model(cls):
        return ClingNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"apiKey": api_key, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            try:
                data = response.json()
                detail = data.get("message") or data.get("error") if isinstance(data, dict) else None
            except ValueError:
                detail = None
            detail = str(detail or response.text or "request failed").replace(api_key, "[redacted]")[:1000]
            raise ValueError(f"Cling API error {response.status_code}: {detail}")
        return response.json() if response.content else None

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        op = self.config.config
        if isinstance(op, ClingOnDocumentAcceptedConfig):
            return self.no_event_output("on_document_accepted", "Waiting for a Cling document acceptance")
        if self.config.credentials is None:
            raise ValueError("Connect a Cling API key")
        name = op.operation
        method, path, _, _ = OPERATIONS[name]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params, body = None, None
        if method == "GET":
            if name in {"list_customers", "list_projects"}:
                if values["end"] <= values["start"]:
                    raise ValueError("End must exceed start")
                values = {"_" + k: v for k, v in values.items()}
            params = values or None
        elif name == "create_document":
            body = {"templateId": values.pop("template_id"), "data": {"name": values.pop("name")},
                "clients": [{"endCustomerId": values.pop("customer_id"), "documentRole": "signee", "deliveryTypes": ["email"], "answerMethod": {"accept": "button", "deny": "button"}}], **values}
        elif name == "create_customer":
            body = {"customerType": values.pop("customer_type"), **values}
        elif values:
            body = values
        data = await self._request(self.config.credentials.api_key, method, path, params=params, body=body)
        return {"status": "success", "operation": name, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        key = ClingAPIKeyCredential.model_validate(credential).api_key
        data = await cls._request(key, "POST", "/webhookSubscription", body={
            "type": "document.accepted", "isActive": True, "url": webhook_url,
            "includePaths": ["id", "status", "companyId", "data.name"],
        })
        if not isinstance(data, dict) or type(data.get("id")) is not int:
            raise ValueError("Cling did not return a webhook subscription ID")
        return {"external_webhook_id": str(data["id"])}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get("external_webhook_id"):
            return
        identifier = str(config["external_webhook_id"])
        if not re.fullmatch(r"[0-9]+", identifier):
            raise ValueError("Invalid Cling webhook subscription ID")
        await cls._request(ClingAPIKeyCredential.model_validate(credential).api_key, "DELETE", "/webhookSubscription/" + identifier)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # authType/authData are optional; the default documented delivery has no
        # signature. The platform's unique per-trigger URL is the capability.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") == "document.accepted" and bool(payload.get("typeId"))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("type") != "document.accepted":
            return None
        document = output.get("data")
        if not isinstance(document, dict) or not output.get("typeId"):
            return None
        fields = document.get("data")
        title = fields.get("name") if isinstance(fields, dict) else None
        identifier = str(output["typeId"])
        return {"text": f"Cling document accepted: {title or identifier}\nCompany: {output.get('companyId')}\nDocument ID: {identifier}\nStatus: {document.get('status')}\nAt: {output.get('createdAt')}\nUse get_document with document_id={identifier} to read the agreement. The delivery does not identify the signer.",
            "conversation_key": identifier, "title": str(title or identifier)}
