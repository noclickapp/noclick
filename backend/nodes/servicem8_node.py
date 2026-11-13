"""ServiceM8 jobs, clients, scheduling, notes, tasks and recorded payments.

REST operations follow the provider's published API 1.0 contract. Object-change
webhooks use the separately published Webhooks API and its JSON delivery example.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

API_ROOT = "https://api.servicem8.com"
TYPE = "servicem8_api_key"
AUTH_DOCS = "https://developer.servicem8.com/docs/authentication"
WEBHOOK_DOCS = "https://developer.servicem8.com/docs/webhooks-overview"


class ServiceM8Credential(BaseModel):
    model_config = ConfigDict(title="ServiceM8 API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": AUTH_DOCS,
        "x-credential-instructions": "In ServiceM8, open Settings → API Keys and create an API key. Paste the key here. API access requires a supported paid plan and the Business Owner role to create keys.",
    })
    credential_type: Literal["servicem8_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})


def text(title, *, required=False, maximum=None, multiline=False, description=""):
    return (str if required else str | None, Field(
        ... if required else None, title=title, min_length=1, max_length=maximum,
        description=description, json_schema_extra={"ui:widget": "textarea"} if multiline else {}))


def identifier(title, *, required=False, picker=None):
    extra = {"x-dynamic-options": {"field_name": picker, "allow_custom": True}} if picker else {}
    return (UUID if required else UUID | None, Field(... if required else None, title=title, json_schema_extra=extra))


FILTER = {"filter": text("Filter", description="Unencoded ServiceM8 $filter expression, e.g. active eq 1. Uses eq, ne, gt, lt and up to ten conditions joined with and. https://developer.servicem8.com/docs/filtering")}
JOB_ID = {"job_uuid": identifier("Job", required=True, picker="job_uuid")}
CLIENT_ID = {"company_uuid": identifier("Client", required=True, picker="company_uuid")}
CONTACT_ID = {"contact_uuid": identifier("Client Contact", required=True, picker="contact_uuid")}
ACTIVITY_ID = {"activity_uuid": identifier("Job Activity", required=True, picker="activity_uuid")}
TASK_ID = {"task_uuid": identifier("Task", required=True, picker="task_uuid")}
JOB_FIELDS = {
    "status": (Literal["Quote", "Work Order", "Unsuccessful", "Completed"], Field(..., title="Job Status")),
    "company_uuid": identifier("Client", picker="company_uuid"),
    "job_description": text("Job Description", multiline=True),
    "job_address": text("Job Address", maximum=500),
    "billing_address": text("Billing Address", maximum=500),
    "work_done_description": text("Work Done", multiline=True),
    "purchase_order_number": text("Purchase Order Number", maximum=100),
    "category_uuid": identifier("Category UUID"),
}
CLIENT_FIELDS = {"name": text("Client Name", required=True, maximum=100),
                 "address": text("Address", maximum=500), "billing_address": text("Billing Address", maximum=500),
                 "website": text("Website"), "abn_number": text("ABN")}
CONTACT_FIELDS = {"company_uuid": identifier("Client", required=True, picker="company_uuid"),
                  "first": text("First Name"), "last": text("Last Name"), "email": text("Email"),
                  "phone": text("Phone"), "mobile": text("Mobile"), "type": text("Contact Type", description="For example BILLING.")}
ACTIVITY_FIELDS = {"job_uuid": identifier("Job", required=True, picker="job_uuid"),
                   "staff_uuid": identifier("Staff Member", required=True, picker="staff_uuid"),
                   "start_date": text("Start Time", required=True, description="Account local time: YYYY-MM-DD HH:MM:SS."),
                   "end_date": text("End Time", required=True, description="Account local time: YYYY-MM-DD HH:MM:SS."),
                   "activity_was_scheduled": (Literal["0", "1"], Field("1", title="Scheduled Activity"))}
TASK_FIELDS = {"name": text("Task Name", required=True), "task_details": text("Details", multiline=True),
               "due_date": text("Due Date", description="YYYY-MM-DD."),
               "related_object": text("Related Object", description="ServiceM8 object class, e.g. job."),
               "related_object_uuid": identifier("Related Record UUID"),
               "assigned_to_staff_uuid": identifier("Assigned Staff", picker="staff_uuid"),
               "task_complete": (Literal["0", "1"] | None, Field(None, title="Completed"))}


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: dict
    path_field: str | None = None


OPERATIONS = {
    "get_account": Operation("Get Account", "GET", "/vendor.json", {}),
    "list_jobs": Operation("List Jobs", "GET", "/job.json", FILTER),
    "get_job": Operation("Get Job", "GET", "/job/{uuid}.json", JOB_ID, "job_uuid"),
    "create_job": Operation("Create Job", "POST", "/job.json", JOB_FIELDS),
    "update_job": Operation("Update Job", "POST", "/job/{uuid}.json", {**JOB_ID, **JOB_FIELDS}, "job_uuid"),
    "list_clients": Operation("List Clients", "GET", "/company.json", FILTER),
    "get_client": Operation("Get Client", "GET", "/company/{uuid}.json", CLIENT_ID, "company_uuid"),
    "create_client": Operation("Create Client", "POST", "/company.json", CLIENT_FIELDS),
    "update_client": Operation("Update Client", "POST", "/company/{uuid}.json", {**CLIENT_ID, **CLIENT_FIELDS}, "company_uuid"),
    "list_contacts": Operation("List Client Contacts", "GET", "/companycontact.json", FILTER),
    "get_contact": Operation("Get Client Contact", "GET", "/companycontact/{uuid}.json", CONTACT_ID, "contact_uuid"),
    "create_contact": Operation("Create Client Contact", "POST", "/companycontact.json", CONTACT_FIELDS),
    "update_contact": Operation("Update Client Contact", "POST", "/companycontact/{uuid}.json", {**CONTACT_ID, **CONTACT_FIELDS}, "contact_uuid"),
    "list_notes": Operation("List Notes", "GET", "/note.json", FILTER),
    "create_note": Operation("Create Note", "POST", "/note.json", {
        "related_object": text("Related Object", required=True, description="For example job."),
        "related_object_uuid": identifier("Related Record UUID", required=True),
        "note": text("Note", required=True, multiline=True)}),
    "list_job_activities": Operation("List Job Activities", "GET", "/jobactivity.json", FILTER),
    "create_job_activity": Operation("Schedule Job Activity", "POST", "/jobactivity.json", ACTIVITY_FIELDS),
    "update_job_activity": Operation("Update Job Activity", "POST", "/jobactivity/{uuid}.json", {**ACTIVITY_ID, **ACTIVITY_FIELDS}, "activity_uuid"),
    "list_job_payments": Operation("List Job Payments", "GET", "/jobpayment.json", FILTER),
    "create_job_payment": Operation("Record Job Payment", "POST", "/jobpayment.json", {
        **JOB_ID, "amount": text("Payment Amount", required=True, description="Amount in account currency; records a payment, does not charge a card."),
        "method": text("Payment Method", required=True, description="For example Cash or Credit Card."),
        "timestamp": text("Payment Time", description="Account local time: YYYY-MM-DD HH:MM:SS."),
        "note": text("Payment Note"), "actioned_by_uuid": identifier("Actioned by Staff", picker="staff_uuid")}),
    "list_tasks": Operation("List Tasks", "GET", "/task.json", FILTER),
    "create_task": Operation("Create Task", "POST", "/task.json", TASK_FIELDS),
    "update_task": Operation("Update Task", "POST", "/task/{uuid}.json", {**TASK_ID, **TASK_FIELDS}, "task_uuid"),
    "list_staff": Operation("List Staff", "GET", "/staff.json", FILTER),
}


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


CONFIG_MODELS = {}
for name, spec in OPERATIONS.items():
    CONFIG_MODELS[name] = create_model(
        "ServiceM8" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=_Input,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-display-name": spec.label,
            "x-category": "Account" if name == "get_account" else "Actions"})),
        **spec.fields,
    )


class ServiceM8JobChangedConfig(WebhookTriggerConfigBase):
    """Receive object changes, including the job UUID and names of changed fields."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_job_changed"] = Field("on_job_changed", title="Job Changed", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "Job Changed", "x-category": "Triggers"})
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with ServiceM8 automatically.",
                                   json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


ServiceM8Config = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ServiceM8JobChangedConfig,)], Field(discriminator="operation")]


class ServiceM8NodeConfig(NodeConfig[ServiceM8Config, ServiceM8Credential]):
    pass


class ServiceM8Node(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-servicem8"
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="account")
    webhook_signing_secret_not_issued = True
    edit_examples = ["Create a ServiceM8 job", "Update a client's address", "Schedule a job for a staff member", "Record a job payment", "Run when a ServiceM8 job changes"]

    @classmethod
    def get_config_model(cls):
        return ServiceM8NodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, form=None):
        key = ServiceM8Credential.model_validate(credential).api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, API_ROOT + path,
                headers={"X-API-Key": key, "Accept": "application/json"},
                params=params, **({"data": form} if form is not None else {"json": body} if body is not None else {}))
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            if response.is_success:
                raise ValueError("ServiceM8 returned an unreadable JSON response") from None
            payload = None
        if not response.is_success or (isinstance(payload, dict) and (payload.get("errorCode", 0) != 0 or payload.get("success") is False)):
            message = payload.get("message") if isinstance(payload, dict) else response.text
            message = str(message or "Request failed").replace(key, "[redacted]")[:2000]
            raise ValueError(f"ServiceM8 API {response.status_code}: {message}")
        return payload, response.headers.get("x-record-uuid")

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, ServiceM8JobChangedConfig):
            return self.no_event_output("on_job_changed")
        if self.config.credentials is None:
            raise ValueError("Connect a ServiceM8 API key")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        route = spec.path
        if spec.path_field:
            route = route.replace("{uuid}", values.pop(spec.path_field))
        params = {"$filter": values["filter"]} if "filter" in values else None
        data, record_uuid = await self._request(self.config.credentials.model_dump(), spec.method,
            "/api_1.0" + route, params=params, body=values if spec.method == "POST" else None)
        if spec.method == "GET":
            expected = dict if spec.path_field else list
            if not isinstance(data, expected):
                raise ValueError("ServiceM8 returned an unexpected record shape")
        return {"status": "success", "operation": op.operation, "data": data,
                **({"record_uuid": record_uuid} if record_uuid else {})}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        route = {"job_uuid": "job", "company_uuid": "company", "contact_uuid": "companycontact", "staff_uuid": "staff", "task_uuid": "task", "activity_uuid": "jobactivity"}.get(field_name)
        if not route:
            return []
        data, _ = await cls._request(credential_data, "GET", f"/api_1.0/{route}.json", params={"$filter": "active eq 1"})
        if not isinstance(data, list):
            raise ValueError("ServiceM8 returned an unexpected list shape")
        options = []
        for row in data:
            if not isinstance(row, dict) or not row.get("uuid"):
                continue
            label = row.get("name") or row.get("job_description") or " ".join(str(row.get(k) or "") for k in ("first", "last")).strip() or row.get("start_date") or row["uuid"]
            if not search or search.casefold() in str(label).casefold():
                options.append({"value": row["uuid"], "label": str(label)})
        return options

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        # ServiceM8's POST returns success only. The documented unique_id groups
        # subscriptions; teardown discovers the provider UUID before deleting.
        unique_id = "noclick-" + str(node_id)
        await cls._request(credential, "POST", "/webhook_subscriptions/object", form={
            "object": "job", "fields": "uuid,status,job_description,job_address,company_uuid,badges,generated_job_id,completion_date",
            "callback_url": webhook_url, "unique_id": unique_id})
        return {"external_webhook_id": unique_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get("external_webhook_id") or not config.get("webhook_url"):
            return
        rows, _ = await cls._request(credential, "GET", "/webhook_subscriptions", params={"status": "all"})
        if not isinstance(rows, list):
            raise ValueError("ServiceM8 did not return its webhook subscriptions")
        for row in rows:
            if (row.get("unique_id") == config["external_webhook_id"] and row.get("callback_url") == config["webhook_url"]
                    and row.get("type") == "object" and row.get("object") == "job"):
                subscription_uuid = str(UUID(row["uuid"]))
                await cls._request(credential, "DELETE", "/webhook_subscriptions/" + subscription_uuid)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # The Webhooks API documents plain JSON, no signing header or shared
        # secret. API-key subscriptions do not use the OAuth challenge either.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        entries = payload.get("entry")
        return (payload.get("object") == "job" and isinstance(entries, list) and bool(entries)
                and isinstance(entries[0], dict) and bool(entries[0].get("uuid")))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # The delivered resource URL is data only; never fetch an event-supplied
        # URL. Agents can read the job by UUID through get_job.
        return payload

    @classmethod
    def resolve_agent_event(cls, output):
        if not cls.filter_trigger_payload(output, {}):
            return super().resolve_agent_event(output)
        entry = output["entry"][0]
        job_uuid = entry["uuid"]
        changed = entry.get("changed_fields") or []
        when = entry.get("time") or "not supplied"
        text = (f"ServiceM8 job changed: {job_uuid}\n"
                f"Changed fields: {', '.join(str(v) for v in changed)}\n"
                f"At: {when} UTC\n"
                "Actor and new field values are not included in ServiceM8 object-change deliveries.\n"
                f"Job: https://go.servicem8.com/OpenJob/{job_uuid}\n"
                f"To act: get_job job_uuid={job_uuid}; update_job job_uuid={job_uuid} with the current status and desired fields.")
        return {"text": text, "conversation_key": str(job_uuid), "title": "ServiceM8 job changed"}
