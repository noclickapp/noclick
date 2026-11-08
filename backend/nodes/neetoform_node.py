"""NeetoForm v2 form, submission and webhook automation with a workspace API key.

Every operation sends one documented request. Workspace form titles provide
connection evidence without creating data or sending email.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Enter a single NeetoForm resource ID")
    return value


class NeetoformAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Neetoform API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://apidocs.neetoform.com/api/authentication",
        "x-credential-instructions": "In your workspace Admin panel, open API keys, add a General key, and copy it. Paste the key and the workspace subdomain from your workspace URL. Zapier keys are only for Zapier. NoClick sends the key to this workspace's NeetoForm API and checks it by listing your forms.",
    })
    credential_type: Literal["neetoform_api_key"] = Field("neetoform_api_key", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Workspace subdomain", description="The part before .neetoform.com in your workspace URL, for example acme.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def workspace(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter the workspace subdomain")
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Enter only the workspace subdomain, without a URL or dots")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if not value or len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header prefix or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k not in {"credentialIds", "form_id__label"}}
        return value


class _Page(_Input):
    page_number: int = Field(1, ge=1, description="One page per run. Increase this to retrieve the next page.")
    page_size: int = Field(30, ge=1, le=100, description="Results per page.")


class _Form(_Input):
    form_id: str = Field(..., title="Form", json_schema_extra={"x-dynamic-options": {
        "field_name": "form_id", "searchable": True, "allow_custom": True,
    }})
    _id = field_validator("form_id", mode="before")(_identifier)


class ListForms(_Page):
    """List workspace forms with optional title and status filters."""
    operation: Literal["list_forms"] = "list_forms"
    status: Literal["active", "archived", "favorite"] | None = None
    search: str | None = Field(None, max_length=1000)
    order: Literal["asc", "desc"] = "asc"


class GetForm(_Form):
    operation: Literal["get_form"] = "get_form"


class CreateForm(_Input):
    """Create an unpublished draft for an active workspace member."""
    operation: Literal["create_form"] = "create_form"
    title: str = Field(..., min_length=1, max_length=80)
    created_by_email: str = Field(..., pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", description="Email of an active workspace member. Required when using an API key.")
    style: Literal["single_page", "one_question_at_a_time"] = "single_page"


class UpdateForm(_Form):
    operation: Literal["update_form"] = "update_form"
    title: str = Field(..., min_length=1, max_length=80)


class DeleteForm(_Form):
    """Move a form to the trash; restore it from the NeetoForm app."""
    operation: Literal["delete_form"] = "delete_form"


class UpdateForms(_Input):
    """Change forms together. Enable/disable replaces existing submission limits and deadlines."""
    operation: Literal["update_forms"] = "update_forms"
    ids: list[str] = Field(..., min_length=1, max_length=100)
    action: Literal["archive", "unarchive", "enable", "disable", "favorite", "unfavorite"]

    @field_validator("ids")
    @classmethod
    def identifiers(cls, values):
        return [_identifier(value) for value in values]


class CountForms(_Input):
    operation: Literal["count_forms"] = "count_forms"


class GetFormOutline(_Form):
    operation: Literal["get_form_outline"] = "get_form_outline"
    draft: bool = Field(False, description="Include unpublished changes; required for a form never published.")


class CloneForm(_Form):
    """Copy the published form as a new unpublished draft without submissions."""
    operation: Literal["clone_form"] = "clone_form"


class PublishForm(_Form):
    """Publish the draft and make its changes visible to respondents."""
    operation: Literal["publish_form"] = "publish_form"


class ResetForm(_Form):
    """Discard draft changes and return to the published version."""
    operation: Literal["reset_form"] = "reset_form"


class ListSubmissions(_Form, _Page):
    """List answers; join responses to questions by slug, not position."""
    operation: Literal["list_submissions"] = "list_submissions"
    status: Literal["completed", "incomplete", "all"] = "completed"
    search: str | None = Field(None, max_length=1000)
    order: Literal["asc", "desc"] = "asc"
    submitted_after: str | None = Field(None, description="Inclusive ISO 8601 date-time or YYYY-MM-DD (UTC midnight).")
    submitted_before: str | None = Field(None, description="Exclusive ISO 8601 date-time or YYYY-MM-DD (UTC midnight).")

    @field_validator("submitted_after", "submitted_before")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class _Submission(_Form):
    submission_id: str = Field(..., description="Submission ID returned by List submissions.")
    _submission = field_validator("submission_id", mode="before")(_identifier)


class GetSubmission(_Submission):
    operation: Literal["get_submission"] = "get_submission"


class DeleteSubmission(_Submission):
    """Move a submission to the trash; restore it from the NeetoForm app."""
    operation: Literal["delete_submission"] = "delete_submission"


class DeleteSubmissions(_Form):
    """Trash the selected submissions; the provider skips unknown or already trashed IDs."""
    operation: Literal["delete_submissions"] = "delete_submissions"
    ids: list[str] = Field(..., min_length=1, max_length=100)
    _ids = field_validator("ids")(UpdateForms.identifiers.__func__)


class GetFormInsights(_Form):
    operation: Literal["get_form_insights"] = "get_form_insights"
    start_date: str | None = Field(None, description="First date, YYYY-MM-DD. Supply both dates or neither.")
    end_date: str | None = Field(None, description="Last date inclusive, YYYY-MM-DD.")
    time_zone: str | None = Field(None, max_length=100, description="IANA time zone, for example Asia/Kolkata.")

    @model_validator(mode="after")
    def date_range(self):
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("Supply both start_date and end_date")
        if self.start_date and date.fromisoformat(self.start_date) > date.fromisoformat(self.end_date):
            raise ValueError("The end date must be on or after the start date")
        return self


class ListFormWebhooks(_Form, _Page):
    operation: Literal["list_form_webhooks"] = "list_form_webhooks"


class ListWorkspaceWebhooks(_Page):
    operation: Literal["list_workspace_webhooks"] = "list_workspace_webhooks"


class _WebhookCreate(_Input):
    endpoint: str = Field(..., max_length=4096, description="Public HTTPS URL that receives submission events.")
    events: list[Literal["submit"]] = Field(default_factory=lambda: ["submit"], min_length=1, max_length=1)
    secret: str | None = Field(None, max_length=4096, description="Optional signing secret for webhook deliveries.", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("endpoint")
    @classmethod
    def webhook_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or any(c.isspace() for c in value):
            raise ValueError("Enter a public HTTPS webhook URL without credentials or a fragment")
        return value


class CreateFormWebhook(_Form, _WebhookCreate):
    """Register a callback that receives this form's submission events."""
    operation: Literal["create_form_webhook"] = "create_form_webhook"


class CreateWorkspaceWebhook(_WebhookCreate):
    """Register a callback that receives submission events across the workspace."""
    operation: Literal["create_workspace_webhook"] = "create_workspace_webhook"


class _Webhook(_Input):
    webhook_id: str
    _webhook = field_validator("webhook_id", mode="before")(_identifier)


class GetWebhook(_Webhook):
    operation: Literal["get_webhook"] = "get_webhook"


class DeleteWebhook(_Webhook):
    """Delete a webhook and its delivery history."""
    operation: Literal["delete_webhook"] = "delete_webhook"


class ListQuestions(_Form):
    operation: Literal["list_questions"] = "list_questions"


class GetQuestion(_Form):
    operation: Literal["get_question"] = "get_question"
    question_id: str
    _question = field_validator("question_id", mode="before")(_identifier)


NeetoformConfig = Annotated[Union[
    ListForms, GetForm, CreateForm, UpdateForm, DeleteForm, UpdateForms,
    CountForms, GetFormOutline, CloneForm, PublishForm, ResetForm,
    ListSubmissions, GetSubmission, DeleteSubmission, DeleteSubmissions, GetFormInsights,
    ListFormWebhooks, ListWorkspaceWebhooks, CreateFormWebhook, CreateWorkspaceWebhook,
    GetWebhook, DeleteWebhook, ListQuestions, GetQuestion,
], Field(discriminator="operation")]


class NeetoformNodeConfig(NodeConfig[NeetoformConfig, NeetoformAPIKeyCredential]):
    pass


def _request_parts(config):
    op = config.operation
    values = config.model_dump(exclude_none=True)
    form = "/forms/" + quote(config.form_id, safe="") if isinstance(config, _Form) else None
    if op == "list_forms":
        return "GET", "/forms", {k: v for k, v in values.items() if k != "operation"}, None
    if op == "create_form":
        return "POST", "/forms", {}, {"form": {k: values[k] for k in ("title", "created_by_email", "style")}}
    if op == "update_forms":
        return "PATCH", "/forms/bulk_update", {}, {"ids": config.ids, "operation": config.action}
    if op == "count_forms":
        return "GET", "/forms/counts", {}, None
    if op in {"get_form", "update_form", "delete_form"}:
        return {"get_form": "GET", "update_form": "PATCH", "delete_form": "DELETE"}[op], form, {}, {"form": {"title": config.title}} if op == "update_form" else None
    if op == "get_form_outline":
        return "GET", form + "/outline", {"draft": str(config.draft).lower()}, None
    if op in {"clone_form", "publish_form", "reset_form"}:
        return "POST" if op == "clone_form" else "PATCH", form + "/" + op.split("_")[0], {}, None
    if op == "list_submissions":
        return "GET", form + "/submissions", {k: v for k, v in values.items() if k not in {"operation", "form_id"}}, None
    if op in {"get_submission", "delete_submission"}:
        return "GET" if op == "get_submission" else "DELETE", form + "/submissions/" + quote(config.submission_id, safe=""), {}, None
    if op == "delete_submissions":
        return "DELETE", form + "/submissions/bulk_destroy", {}, {"ids": config.ids}
    if op == "get_form_insights":
        return "GET", form + "/insights", {k: v for k, v in values.items() if k not in {"operation", "form_id"}}, None
    if op in {"list_form_webhooks", "list_workspace_webhooks"}:
        return "GET", (form or "") + "/webhooks", {"page_number": config.page_number, "page_size": config.page_size}, None
    if op in {"create_form_webhook", "create_workspace_webhook"}:
        return "POST", (form or "") + "/webhooks", {}, {"webhook": {k: values[k] for k in ("endpoint", "events", "secret") if k in values}}
    if op in {"get_webhook", "delete_webhook"}:
        return "GET" if op == "get_webhook" else "DELETE", "/webhooks/" + quote(config.webhook_id, safe=""), {}, None
    if op in {"list_questions", "get_question"}:
        return "GET", form + "/questions" + ("/" + quote(config.question_id, safe="") if op == "get_question" else ""), {}, None
    raise ValueError("Unsupported NeetoForm operation")



def _validate_response(operation, payload):
    key, kind = {
        "list_forms": ("forms", list), "get_form": ("id", str),
        "create_form": ("form", dict), "update_form": ("form", dict),
        "delete_form": ("form_ids", list), "update_forms": ("forms", list),
        "count_forms": ("total", int), "get_form_outline": ("outline", str),
        "clone_form": ("form", dict), "publish_form": ("form", dict), "reset_form": ("form", dict),
        "list_submissions": ("submissions", list), "get_submission": ("id", str),
        "delete_submission": ("trashed_count", int), "delete_submissions": ("trashed_count", int),
        "get_form_insights": ("visit_count", int),
        "list_form_webhooks": ("webhooks", list), "list_workspace_webhooks": ("webhooks", list),
        "create_form_webhook": ("webhook", dict), "create_workspace_webhook": ("webhook", dict),
        "get_webhook": ("webhook", dict), "delete_webhook": ("notice", str),
        "list_questions": ("questions", list), "get_question": ("question", dict),
    }[operation]
    if type(payload.get(key)) is not kind:
        raise ValueError("NeetoForm returned an unexpected response shape")
    if kind is list and key != "form_ids" and any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in payload[key]):
        raise ValueError("NeetoForm returned an invalid resource list")


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class NeetoformNode(WorkflowNode):
    integration_type = "automation-neetoform"
    connection_evidence = ConnectionEvidence(noun="forms", operation="list_forms")

    @classmethod
    def get_config_model(cls):
        return NeetoformNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != "form_id":
            raise ValueError("Unknown NeetoForm choice field")
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", page_token)):
            raise ValueError("Use the returned page token")
        config = {"operation": "list_forms", "page_number": int(page_token or "1"), "search": search}
        parsed = cls.parse_config({"config": config, "credentials": credential_data})
        node = cls(node_id="neetoform-options", node_type=cls.integration_type, node_data={}, config=parsed)
        result = await node.execute({})
        if result["status"] != "success":
            raise ValueError(result.get("error", "NeetoForm choices could not be loaded"))
        pagination = result.get("pagination", {})
        current = pagination.get("current_page_number", config["page_number"])
        total = pagination.get("total_pages", current)
        return {"options": [{"value": row["id"], "label": row.get("title") or row["id"]} for row in result["forms"]],
                "next_page_token": str(current + 1) if current < total else None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a NeetoForm workspace API key")
        credential = self.config.credentials
        config = self.config.config
        method, path, params, body = _request_parts(config)
        secrets = [credential.api_key, getattr(config, "secret", None)]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, f"https://{credential.subdomain}.neetoform.com/api/external/v2" + path,
                                         headers={"X-Api-Key": credential.api_key, "Accept": "application/json"}, params=params,
                                         **({"json": body} if body is not None else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 10 * 1024 * 1024:
                            raise ValueError("NeetoForm response is too large; use a smaller page size")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("NeetoForm returned an unexpected response representation") from None
                    if not isinstance(payload, dict):
                        raise ValueError("NeetoForm returned an unexpected response shape")
                    if not 200 <= response.status_code < 300 or payload.get("error") or payload.get("errors"):
                        output = {"status": "error", "http_status": response.status_code,
                                  "error": payload.get("error") or payload.get("errors") or "NeetoForm request failed"}
                    else:
                        expected = 201 if config.operation in {"create_form", "clone_form", "create_form_webhook", "create_workspace_webhook"} else 200
                        media = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        if response.status_code != expected or media != "application/json":
                            raise ValueError("NeetoForm did not return the documented JSON completion")
                        _validate_response(config.operation, payload)
                        output = {**payload, "status": "success"}
        except httpx.HTTPError:
            raise ValueError("NeetoForm request did not complete; check the provider before retrying a write") from None
        output = _redact(output, secrets)
        await self.emit(output)
        return output
