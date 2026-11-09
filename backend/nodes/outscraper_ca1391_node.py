"""Outscraper API 0.4.3: bounded jobs, account reads and signed completion events.

Contract: https://app.outscraper.cloud/api-docs-data.json
Signatures: https://outscraper.com/how-to-verify-webhook-request/
Completion triggers are one-shot jobs, not account-wide subscriptions. Loading
their webhook starts a billable async request; removal terminates that request.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.outscraper.cloud"
FAMILY = "outscraper_ca1391_api_key"


class OutscraperAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Outscraper API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.outscraper.cloud/api-key",
            "x-credential-instructions": "Paste your Outscraper API key. NoClick sends it in the X-API-KEY header and checks your account balance. Scraping and trigger activation can incur Outscraper charges.",
        })
    credential_type: Literal["outscraper_ca1391_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def text(title, *, required=False, description=""):
    return (str if required else Optional[str], Field(... if required else None,
        min_length=1, max_length=10000, title=title, description=description))


def number(title, default, *, minimum=0, maximum=10000):
    return (int, Field(default, ge=minimum, le=maximum, title=title))


def strings(title, *, required=False):
    return (list[str] if required else Optional[list[str]], Field(... if required else None,
        min_length=1 if required else 0, max_length=1000, title=title, json_schema_extra={"ui:widget": "list"}))


ASYNC = {"async_request": (bool, Field(True, title="Run asynchronously",
    description="Returns a request ID. Fetch results within four hours after completion. Synchronous requests can time out; they are not retried."))}
QUERY = {"query": text("Search query", required=True)}
BATCH = {"query": strings("Queries", required=True)}
REQUEST = {"requestId": text("Request ID", required=True)}
TASK = {"taskId": text("Task ID", required=True)}


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict
    body: bool = False


OPERATIONS = {
    "get_balance": Operation("Get Account Balance", "Account", "GET", "/profile/balance", {}),
    "list_requests": Operation("List Recent Requests", "Requests", "GET", "/requests", {
        "type": (Literal["running", "finished"], Field("running", title="Request status")),
        "skip": number("Skip", 0), "pageSize": number("Page size", 20, minimum=1, maximum=100)}),
    "get_request_results": Operation("Get Request Results", "Requests", "GET", "/requests/{requestId}", {
        **REQUEST, "flat": (bool, Field(False)), "convertFileResult": (bool, Field(True))}),
    "terminate_request": Operation("Terminate Request", "Requests", "DELETE", "/requests/{requestId}", REQUEST),
    "list_tasks": Operation("List Tasks", "Tasks", "GET", "/tasks", {
        "query": text("Tag search"), "lastId": text("Last task ID"),
        "pageSize": number("Page size", 10, minimum=1, maximum=100)}),
    "create_task": Operation("Create Task", "Tasks", "POST", "/tasks", {
        "service_name": text("Service ID", required=True, description="For example google_maps_service_v2 or google_maps_reviews_service_v3."),
        "queries": strings("Queries", required=True), "tags": strings("Tags"), "enrichments": strings("Enrichments")}, body=True),
    "get_task": Operation("Get Task", "Tasks", "GET", "/tasks/{taskId}", TASK),
    "restart_task": Operation("Restart Task", "Tasks", "PUT", "/tasks/{taskId}", TASK),
    "terminate_task": Operation("Terminate Task", "Tasks", "DELETE", "/tasks/{taskId}", TASK),
    "list_invoices": Operation("List Invoices", "Account", "GET", "/invoices", {"lastId": text("Last invoice ID")}),
    "get_failed_webhooks": Operation("Get Failed Webhook Calls", "Account", "GET", "/webhook-calls", {}),
    "search_google_maps": Operation("Search Google Maps Places", "Scraping", "GET", "/google-maps-search", {
        **QUERY, **ASYNC, "limit": number("Places per query", 25, minimum=1),
        "skipPlaces": number("Skip places", 0), "dropDuplicates": (bool, Field(False))}),
    "scrape_google_reviews": Operation("Scrape Google Maps Reviews", "Scraping", "GET", "/google-maps-reviews", {
        **QUERY, **ASYNC, "reviewsLimit": number("Reviews per place", 100, minimum=1),
        "limit": number("Places per query", 1, minimum=1),
        "sort": (Literal["most_relevant", "newest", "highest_rating", "lowest_rating"], Field("newest")),
        "cutoff": (Optional[int], Field(None, ge=0, description="Oldest review Unix timestamp to include."))}),
    "search_google": Operation("Search Google", "Scraping", "GET", "/google-search", {
        **QUERY, **ASYNC, "pagesPerQuery": number("Pages per query", 1, minimum=1, maximum=100), "skip": number("Skip", 0)}),
    "find_leads_contacts": Operation("Find Leads and Contacts", "Enrichment", "GET", "/leads-and-contacts", {
        **BATCH, **ASYNC, "contactsPerCompany": number("Contacts per company", 3, minimum=1, maximum=100)}),
    "verify_emails": Operation("Verify Email Addresses", "Enrichment", "GET", "/email-validator", {**BATCH, **ASYNC}),
    "find_emails": Operation("Find Email Addresses", "Enrichment", "GET", "/emails-finder", {**BATCH, **ASYNC}),
    "enrich_phones": Operation("Enrich Phone Numbers", "Enrichment", "GET", "/phones-enricher", {**BATCH, **ASYNC}),
    "get_company_insights": Operation("Get Company Insights", "Enrichment", "GET", "/company-insights", {**BATCH, **ASYNC}),
    "find_company_websites": Operation("Find Company Websites", "Enrichment", "GET", "/company-website-finder", {**BATCH, **ASYNC}),
    "scrape_trustpilot_reviews": Operation("Scrape Trustpilot Reviews", "Scraping", "GET", "/trustpilot-reviews", {
        **BATCH, **ASYNC, "limit": number("Reviews per query", 100, minimum=1), "skip": number("Skip", 0)}),
}


def make_config(name, spec):
    return create_model("Outscraper" + "".join(w.title() for w in name.split("_")) + "Config",
        __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-display-name": spec.label, "x-category": spec.category, "x-is-trigger": False})),
        **spec.fields)


MODELS = {name: make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in MODELS.values()})


class CompletionBase(WebhookTriggerConfigBase):
    webhook_url: Optional[str] = Field(None, title="Completion webhook",
        description="Activating this trigger submits one async job and may incur Outscraper charges. It fires once when that job finishes. Reconfigure to start another job; removal terminates the request.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class OutscraperOnGoogleMapsFinishedConfig(CompletionBase):
    operation: Literal["on_google_maps_finished"] = Field("on_google_maps_finished", title="On Google Maps Job Finished",
        json_schema_extra={"ui:hidden": True, "x-display-name": "On Google Maps Job Finished", "x-category": "Triggers", "x-is-trigger": True})
    query: str = Field(..., min_length=1, max_length=10000, title="Search query")
    limit: int = Field(25, ge=1, le=10000, title="Places per query")


class OutscraperOnEmailVerificationFinishedConfig(CompletionBase):
    operation: Literal["on_email_verification_finished"] = Field("on_email_verification_finished", title="On Email Verification Job Finished",
        json_schema_extra={"ui:hidden": True, "x-display-name": "On Email Verification Job Finished", "x-category": "Triggers", "x-is-trigger": True})
    query: list[str] = Field(..., min_length=1, max_length=1000, title="Email addresses", json_schema_extra={"ui:widget": "list"})


TRIGGERS = {
    "on_google_maps_finished": (OutscraperOnGoogleMapsFinishedConfig, "search_google_maps"),
    "on_email_verification_finished": (OutscraperOnEmailVerificationFinishedConfig, "verify_emails"),
}
OutscraperConfig = Annotated[Union[tuple(MODELS.values()) + tuple(v[0] for v in TRIGGERS.values())], Field(discriminator="operation")]


class OutscraperFullConfig(NodeConfig[OutscraperConfig, OutscraperAPIKeyCredential]):
    pass


class OutscraperError(ValueError):
    pass


def segment(value):
    if not isinstance(value, str) or not value or len(value) > 256 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value):
        raise ValueError("Use a single Outscraper resource ID")
    return value


class OutscraperNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-outscraper-ca1391"
    connection_evidence = ConnectionEvidence(operation="get_balance", noun="account balance", identity_operation="get_balance", identity_keys=("id",))
    webhook_replace_stale_endpoint = True

    @classmethod
    def get_config_model(cls):
        return OutscraperFullConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = OutscraperAPIKeyCredential.model_validate(credential)
        async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"X-API-KEY": credential.api_key, "Accept": "application/json"}, **({"json": body} if body is not None else {}))
        if response.is_error:
            # Preserve the provider's rejection for connect, but never echo the key.
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise OutscraperError(f"Outscraper HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            raise OutscraperError("Outscraper reported that the request failed with no results")
        data = response.json() if response.content else None
        if isinstance(data, dict) and data.get("status") in {"Failure", "FAILURE"}:
            raise OutscraperError("Outscraper reported that the request failed")
        return data

    @classmethod
    async def _perform(cls, credential, operation, config, *, webhook_url=None):
        spec = OPERATIONS[operation]
        values = dict(config)
        values.pop("operation", None)
        path = spec.path
        for key in ("requestId", "taskId"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(segment(values.pop(key)), safe=""))
        if "async_request" in values:
            values["async"] = values.pop("async_request")
        if webhook_url:
            values.update({"webhook": webhook_url, "async": True})
        # Batch query strings use repeated query keys (the provider's documented
        # batching convention); POST task arrays remain JSON arrays.
        return await cls._request(credential, spec.method, path,
            body=values if spec.body else None, params=None if spec.body else values)

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self.config
        if not isinstance(config, OutscraperFullConfig) or config.credentials is None:
            raise ValueError("Connect an Outscraper API key")
        op = config.config
        if op.operation in TRIGGERS:
            return self.no_event_output(op.operation)
        result = await self._perform(config.credentials, op.operation, op.model_dump(exclude_none=True))
        if op.operation == "get_balance" and (not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or type(result.get("balance")) not in (int, float)):
            raise ValueError("Outscraper returned an unexpected account balance response")
        return {"status": "success", "operation": op.operation, "data": result}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: config.get(key) for key in ("query", "limit") if key in config}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        if config.get("operation") not in TRIGGERS:
            raise ValueError("Choose an Outscraper completion trigger")
        model, action = TRIGGERS[config["operation"]]
        trigger = model.model_validate(config)
        raw = {key: getattr(trigger, key) for key in ("query", "limit") if hasattr(trigger, key)}
        raw["async_request"] = True
        raw = MODELS[action].model_validate(raw).model_dump(exclude_none=True)
        data = await cls._perform(credential, action, raw, webhook_url=webhook_url)
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError("Outscraper did not return a request ID; inspect the account before retrying")
        return {"external_webhook_id": segment(data["id"]),
            "signing_secret": OutscraperAPIKeyCredential.model_validate(credential).api_key}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        request_id = config.get("external_webhook_id")
        if request_id:
            if not credential:
                raise ValueError("The Outscraper key is required to terminate the request")
            await cls._perform(credential, "terminate_request", {"requestId": request_id})

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-hub-signature-256"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (config.get("operation") in TRIGGERS and payload.get("api_task") is True
            and payload.get("status") in {"SUCCESS", "FAILURE"}
            and bool(config.get("external_webhook_id"))
            and payload.get("id") == config["external_webhook_id"])

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not output.get("id") or output.get("api_task") is not True:
            return super().resolve_agent_event(output)
        request_id = output["id"]
        lines = [f"Outscraper job {request_id} finished with status {output.get('status')}.",
            f"Account user: {output.get('user_id')}.", f"Results: {output.get('results_location')}."]
        for usage in output.get("quota_usage") or []:
            lines.append(f"{usage.get('product_name')}: {usage.get('quantity')} units.")
        lines.append(f"Use get_request_results with requestId={request_id} to read the results within four hours of completion.")
        return {"text": "\n".join(lines), "title": "Outscraper job finished", "conversation_key": str(request_id)}
