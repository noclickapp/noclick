"""Payaca actions and signed event triggers against its published OpenAPI contract.

API dates are fixed so grant totals and webhook payloads keep their documented shape.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

API_BASE = "https://api.payaca.com/openapi"
API_VERSION = "2026-11-09"
DOCS = "https://docs.api.payaca.com/"


class PayacaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Payaca API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://web.payaca.com/companySettings/integrations-data/developer",
        "x-credential-instructions": "In Payaca, open Settings → Integrations & data → Developer, select Create API key, and paste the generated Client ID and Client Secret. Record the secret when it is created; Payaca cannot show it again.",
    })
    credential_type: Literal["payaca_api_key"] = Field("payaca_api_key", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, title="Client ID")
    client_secret: str = Field(..., min_length=1, title="Client Secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("client_id", "client_secret")
    @classmethod
    def basic_part(cls, value, info):
        value = value.strip()
        if (not value or any(ord(c) < 32 for c in value)
                or (info.field_name == "client_id" and ":" in value)):
            raise ValueError("Paste the generated client credential without a Basic header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name.endswith("_id") and value in (".", ".."):
            raise ValueError("Use a Payaca resource ID")
        return value


class Page(Input):
    offset: int = Field(0, ge=0, description="Skip this many records; use the returned page metadata for subsequent pages.")
    limit: int = Field(50, ge=1, le=100)


class Contact(Input):
    fullName: str = Field(..., min_length=1, title="Full name")
    email: Optional[EmailStr] = None
    phoneNumber: Optional[str] = None
    description: Optional[str] = None
    isPrimaryContact: Optional[bool] = None


class InvoiceAction(Input):
    type: Literal["send", "mark-as-sent"] = Field(..., description="Send emails the invoice; mark-as-sent does not send an email.")


class PayacaListCustomersConfig(Page):
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    contact_email: Optional[EmailStr] = None
    contact_phone_number: Optional[str] = None


class PayacaGetCustomerConfig(Input):
    operation: Literal["get_customer"] = Field("get_customer", title="Get Customer", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    customer_id: str = Field(..., min_length=1, title="Customer Id")


class PayacaCreateCustomerConfig(Input):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: Optional[str] = None
    contacts: list[Contact] = Field(..., min_length=1)


class PayacaUpdateCustomerConfig(Input):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Customer", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    customer_id: str = Field(..., min_length=1, title="Customer Id")
    custom_fields: dict[str, Any] = Field(..., title="Custom fields")


class PayacaAddCustomerAddressConfig(Input):
    operation: Literal["add_customer_address"] = Field("add_customer_address", title="Add Customer Address", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    customer_id: str = Field(..., min_length=1, title="Customer Id")
    address: str = Field(..., min_length=1, description="Full address, including postcode")
    is_billing_address: Optional[bool] = None


class PayacaListProjectsConfig(Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    customer_id: Optional[str] = None


class PayacaGetProjectConfig(Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")


class PayacaCreateProjectConfig(Input):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    customer_id: str = Field(..., min_length=1, title="Customer Id")
    reference: Optional[str] = None
    site_address: Optional[str] = None
    notes: Optional[list[str]] = None


class PayacaUpdateProjectConfig(Input):
    operation: Literal["update_project"] = Field("update_project", title="Update Project", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")
    custom_fields: dict[str, Any] = Field(..., title="Custom fields")


class PayacaChangeProjectPipelineConfig(Input):
    operation: Literal["change_project_pipeline"] = Field("change_project_pipeline", title="Change Project Pipeline", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")
    pipeline_id: str = Field(..., min_length=1)


class PayacaChangeProjectStageConfig(Input):
    operation: Literal["change_project_stage"] = Field("change_project_stage", title="Change Project Stage", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")
    pipeline_stage_id: str = Field(..., min_length=1)


class PayacaAddProjectTagsConfig(Input):
    operation: Literal["add_project_tags"] = Field("add_project_tags", title="Add Project Tags", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")
    tag_names: list[str] = Field(..., min_length=1, title="Tag names")


class PayacaRemoveProjectTagsConfig(Input):
    operation: Literal["remove_project_tags"] = Field("remove_project_tags", title="Remove Project Tags", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")
    tag_names: list[str] = Field(..., min_length=1, title="Tag names")


class PayacaListPipelinesConfig(Page):
    operation: Literal["list_pipelines"] = Field("list_pipelines", title="List Pipelines", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class PayacaListTagsConfig(Page):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class PayacaCreateTagConfig(Input):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., min_length=1, max_length=30)


class PayacaListItemsConfig(Page):
    operation: Literal["list_items"] = Field("list_items", title="List Items", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    search: Optional[str] = None


class PayacaGetInvoiceConfig(Input):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    invoice_id: str = Field(..., min_length=1, title="Invoice Id")


class PayacaCreateNextInvoiceConfig(Input):
    operation: Literal["create_next_invoice"] = Field("create_next_invoice", title="Create Next Invoice", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    project_id: str = Field(..., min_length=1, title="Project Id")
    due_in_days: Optional[int] = Field(None, gt=0)
    action: Optional[InvoiceAction] = Field(None, description="Omit to create without sending. Select send to email the customer.")


class PayacaGetScheduledEventConfig(Input):
    operation: Literal["get_scheduled_event"] = Field("get_scheduled_event", title="Get Scheduled Event", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    scheduled_event_id: str = Field(..., min_length=1, title="Scheduled Event Id")


EVENTS = ('changeProposal.accepted', 'changeProposal.sent', 'invoice.fullyPaid', 'invoice.voided', 'project.created', 'project.pipelineChanged', 'project.pipelineStageChanged', 'proposal.accepted', 'proposal.markedAsSent', 'proposal.sent', 'scheduledEvent.archived', 'scheduledEvent.assigned', 'scheduledEvent.created', 'scheduledEvent.edited', 'scheduledEvent.rescheduled', 'scheduledEvent.unassigned')


class PayacaOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Payaca Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Payaca Event"})
    event_type: Literal[*EVENTS] = Field("project.created", title="Event type")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with Payaca automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


PayacaConfig = Annotated[Union[PayacaListCustomersConfig, PayacaGetCustomerConfig, PayacaCreateCustomerConfig, PayacaUpdateCustomerConfig, PayacaAddCustomerAddressConfig, PayacaListProjectsConfig, PayacaGetProjectConfig, PayacaCreateProjectConfig, PayacaUpdateProjectConfig, PayacaChangeProjectPipelineConfig, PayacaChangeProjectStageConfig, PayacaAddProjectTagsConfig, PayacaRemoveProjectTagsConfig, PayacaListPipelinesConfig, PayacaListTagsConfig, PayacaCreateTagConfig, PayacaListItemsConfig, PayacaGetInvoiceConfig, PayacaCreateNextInvoiceConfig, PayacaGetScheduledEventConfig, PayacaOnEventConfig], Field(discriminator="operation")]


class PayacaFullConfig(NodeConfig[PayacaConfig, PayacaAPIKeyCredential]):
    pass


# Every action has one fixed method and path from the pinned OpenAPI document.
ROUTES = {'list_customers': ('GET',
                    '/customers',
                    None,
                    {'offset': 'offset',
                     'limit': 'limit',
                     'contact_email': 'contactEmail',
                     'contact_phone_number': 'contactPhoneNumber'},
                    {}),
 'get_customer': ('GET', '/customers/{id}', 'customer_id', {}, {}),
 'create_customer': ('POST', '/customers', None, {}, {'name': 'name', 'contacts': 'contacts'}),
 'update_customer': ('PATCH', '/customers/{id}', 'customer_id', {}, {'custom_fields': 'customFields'}),
 'add_customer_address': ('POST',
                          '/customers/{id}/addresses',
                          'customer_id',
                          {},
                          {'address': 'address', 'is_billing_address': 'isBillingAddress'}),
 'list_projects': ('GET',
                   '/projects',
                   None,
                   {'offset': 'offset', 'limit': 'limit', 'customer_id': 'customerId'},
                   {}),
 'get_project': ('GET', '/projects/{id}', 'project_id', {}, {}),
 'create_project': ('POST',
                    '/customers/{id}/projects',
                    'customer_id',
                    {},
                    {'reference': 'reference', 'site_address': 'siteAddress', 'notes': 'notes'}),
 'update_project': ('PATCH', '/projects/{id}', 'project_id', {}, {'custom_fields': 'customFields'}),
 'change_project_pipeline': ('POST',
                             '/projects/{id}/pipeline',
                             'project_id',
                             {},
                             {'pipeline_id': 'pipelineId'}),
 'change_project_stage': ('POST',
                          '/projects/{id}/pipeline-stage',
                          'project_id',
                          {},
                          {'pipeline_stage_id': 'pipelineStageId'}),
 'add_project_tags': ('POST', '/projects/{id}/tags', 'project_id', {}, {'tag_names': 'tagNames'}),
 'remove_project_tags': ('DELETE', '/projects/{id}/tags', 'project_id', {}, {'tag_names': 'tagNames'}),
 'list_pipelines': ('GET', '/pipelines', None, {'offset': 'offset', 'limit': 'limit'}, {}),
 'list_tags': ('GET', '/account/tags', None, {'offset': 'offset', 'limit': 'limit'}, {}),
 'create_tag': ('POST', '/account/tags', None, {}, {'name': 'name'}),
 'list_items': ('GET', '/items', None, {'offset': 'offset', 'limit': 'limit', 'search': 'search'}, {}),
 'get_invoice': ('GET', '/invoices/{id}', 'invoice_id', {}, {}),
 'create_next_invoice': ('POST',
                         '/projects/{id}/invoices/next',
                         'project_id',
                         {},
                         {'due_in_days': 'dueInDays', 'action': 'action'}),
 'get_scheduled_event': ('GET', '/scheduled-events/{id}', 'scheduled_event_id', {}, {})}


class PayacaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-payaca"
    connection_evidence = ConnectionEvidence(operation="list_customers", noun="customers")

    @classmethod
    def get_config_model(cls):
        return PayacaFullConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = PayacaAPIKeyCredential.model_validate(credential)
        auth = base64.b64encode(f"{credential.client_id}:{credential.client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, API_BASE + path, params=params, json=body, headers={
                "Authorization": f"Basic {auth}", "Accept": "application/json", "X-Payaca-API-Version": API_VERSION})
        if response.is_error:
            try:
                data = response.json()
                detail = data.get("message") or data.get("errors") or data.get("error")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Payaca API error {response.status_code}: {detail or 'request failed'}")
        if response.status_code == 204:
            return {"deleted": True}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Payaca returned an unexpected response")
        return data

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, PayacaOnEventConfig):
            return self.no_event_output(op.operation)
        if self.config.credentials is None:
            raise ValueError("Connect a Payaca API key")
        method, path, path_field, query, body_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        if path_field:
            path = path.replace("{id}", quote(values[path_field], safe=""))
        params = {target: values[source] for source, target in query.items() if source in values}
        body = {target: values[source] for source, target in body_fields.items() if source in values}
        data = await self._request(self.config.credentials.model_dump(), method, path,
            params=params or None, body=body if method in {"POST", "PATCH"} or body_fields else None)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        headers = payload.get("_webhook", {}).get("headers", {})
        event = next((v for k, v in headers.items() if k.lower() == "x-payaca-event"), None)
        return event == config.get("event_type", "project.created") and payload.get("eventName") == event

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": "on_event", "data": payload}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type", "project.created")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = PayacaOnEventConfig.model_validate(config).event_type
        secret = secrets.token_hex(32)
        data = await cls._request(credential, "POST", "/account/webhooks", body={
            "name": f"NoClick {node_id}"[:255], "url": webhook_url, "secret": secret,
            "events": [event], "apiVersion": API_VERSION})
        webhook = data.get("webhook")
        if not isinstance(webhook, dict) or not webhook.get("id"):
            raise ValueError("Payaca did not return a webhook ID")
        return {"external_webhook_id": str(webhook["id"]), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if not identifier:
            return
        if not credential:
            raise ValueError("Payaca credentials required to remove the webhook")
        await cls._request(credential, "DELETE", "/account/webhooks/" + quote(str(identifier), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-payaca-signature"), "")
        if (not isinstance(secret, str) or not secret or not isinstance(signature, str)
                or len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature)):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def resolve_agent_event(cls, output):
        data = output.get("data", {})
        if not isinstance(data, dict) or data.get("eventName") not in EVENTS:
            return None
        account = data.get("account", {})
        payload = data.get("payload", {})
        event = data["eventName"]
        resource_type = event.split(".")[0]
        # The contract calls scheduled-event payloads scheduledEvent, and all
        # other event families use their event prefix as the resource key too.
        record = payload.get(resource_type, {})
        identifier = record.get("id")
        label = record.get("name") if resource_type == "scheduledEvent" else record.get("reference")
        lines = [f"Payaca {event} in {account.get('companyName', 'Payaca')}",
                 f"Account ID: {account.get('id', '')}", f"At: {data.get('occurredAt', '')}",
                 f"{resource_type}: {label} (ID: {identifier})", "Event details:",
                 json.dumps(payload, ensure_ascii=False, default=str)]
        return {"text": "\n".join(lines), "conversation_key": f"{account.get('id', '')}:{resource_type}:{identifier}",
                "title": f"Payaca {event}"}
