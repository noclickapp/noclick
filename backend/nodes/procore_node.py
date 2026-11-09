"""Procore company, project, directory and project-management automation.

Each action makes one request to the published REST contract. Lists return
one page; next_page comes from Procore's Link header, never fetched here.
The resource-event trigger registers a hook and subscription through the API.
"""
import hmac
import secrets
from datetime import date as Date
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.procore_operations import PROCORE_OPERATIONS
from nodes.scopes.procore import PROCORE_SCOPES

API_BASE = "https://api.procore.com"


def _op(name, category):
    return Field(name, json_schema_extra={"ui:hidden": True,
        "x-display-name": name.replace("_", " ").title(),
        "x-category": category, "x-is-trigger": False})


class ProcoreOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Procore Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "procore",
        "x-oauth-scopes": PROCORE_SCOPES.declared_scopes(),
        "x-credential-url": "https://developers.procore.com/documentation/content/oauth-installed-apps",
        "x-credential-instructions": "Connect your Procore account. Access follows your company and project permissions. For manual connection, paste a production OAuth access token; tokens expire after 90 minutes. Supply a refresh token and expiry to renew through the configured Procore app.",
    })
    credential_type: Literal["procore_oauth"] = Field("procore_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry", description="ISO 8601 token expiry, when supplying a refresh token.")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def native_metadata(cls, value):
        # The platform stores credential attachments beside operation fields.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "credentialIds"}
        return value


class _Company(_Input):
    company_id: int = Field(..., gt=0, title="Company ID", description="Company to act in; also sent as Procore-Company-Id.")


class _Project(_Company):
    project_id: int = Field(..., gt=0, title="Project ID")


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(100, ge=1, le=100, title="Results Per Page")


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = _op("get_current_user", "Account")


class ListCompanies(_Page):
    operation: Literal["list_companies"] = _op("list_companies", "Account")


class ListProjects(_Company, _Page):
    operation: Literal["list_projects"] = _op("list_projects", "Projects")
    name: Optional[str] = None
    status: Optional[Literal["All", "Active", "Inactive"]] = None


class GetProject(_Project):
    operation: Literal["get_project"] = _op("get_project", "Projects")


class CreateProject(_Company):
    operation: Literal["create_project"] = _op("create_project", "Projects")
    name: str = Field(..., min_length=1, title="Project Name")
    description: Optional[str] = None
    project_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    start_date: Optional[Date] = None
    completion_date: Optional[Date] = None


class UpdateProject(_Project):
    operation: Literal["update_project"] = _op("update_project", "Projects")
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    active: Optional[bool] = None
    project_number: Optional[str] = None
    start_date: Optional[Date] = None
    completion_date: Optional[Date] = None


class ListVendors(_Company, _Page):
    operation: Literal["list_vendors"] = _op("list_vendors", "Directory")
    search: Optional[str] = None


class GetVendor(_Company):
    operation: Literal["get_vendor"] = _op("get_vendor", "Directory")
    vendor_id: int = Field(..., gt=0, title="Vendor ID")


class CreateVendor(_Company):
    operation: Literal["create_vendor"] = _op("create_vendor", "Directory")
    name: str = Field(..., min_length=1, title="Vendor Name")
    email_address: Optional[str] = None
    business_phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    website: Optional[str] = None


class UpdateVendor(CreateVendor):
    operation: Literal["update_vendor"] = _op("update_vendor", "Directory")
    vendor_id: int = Field(..., gt=0, title="Vendor ID")


class ListProjectUsers(_Project, _Page):
    operation: Literal["list_project_users"] = _op("list_project_users", "Directory")
    search: Optional[str] = None


class ListRFIs(_Project, _Page):
    operation: Literal["list_rfis"] = _op("list_rfis", "RFIs")
    search: Optional[str] = None
    status: Optional[Literal["open", "closed", "draft", "closed_with_revision", "closed_draft"]] = None


class GetRFI(_Project):
    operation: Literal["get_rfi"] = _op("get_rfi", "RFIs")
    rfi_id: int = Field(..., gt=0, title="RFI ID")


class CreateRFI(_Project):
    operation: Literal["create_rfi"] = _op("create_rfi", "RFIs")
    subject: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})
    rfi_manager_id: int = Field(..., gt=0, title="RFI Manager User ID")
    due_date: Optional[Date] = None
    draft: bool = Field(True, description="Create a draft by default. Clearing this can notify project participants.")
    assignee_ids: Optional[list[int]] = None


class UpdateRFI(_Project):
    operation: Literal["update_rfi"] = _op("update_rfi", "RFIs")
    rfi_id: int = Field(..., gt=0, title="RFI ID")
    subject: Optional[str] = Field(None, min_length=1)
    question: Optional[str] = Field(None, min_length=1)
    due_date: Optional[Date] = None
    draft: Optional[bool] = None
    assignee_ids: Optional[list[int]] = None


class ListSubmittals(_Project, _Page):
    operation: Literal["list_submittals"] = _op("list_submittals", "Submittals")
    search: Optional[str] = None


class GetSubmittal(_Project):
    operation: Literal["get_submittal"] = _op("get_submittal", "Submittals")
    submittal_id: int = Field(..., gt=0, title="Submittal ID")


class CreateSubmittal(_Project):
    operation: Literal["create_submittal"] = _op("create_submittal", "Submittals")
    number: str = Field(..., min_length=1, title="Submittal Number")
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    submittal_manager_id: Optional[int] = Field(None, gt=0)
    due_date: Optional[Date] = None
    send_emails: bool = Field(False, description="Notify participants when creating the submittal.")


class ListNotesLogs(_Project, _Page):
    operation: Literal["list_notes_logs"] = _op("list_notes_logs", "Daily Log")
    log_date: Optional[Date] = None


class CreateNotesLog(_Project):
    operation: Literal["create_notes_log"] = _op("create_notes_log", "Daily Log")
    date: Date = Field(..., title="Log Date")
    comment: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})
    is_issue_day: bool = False
    location_id: Optional[int] = Field(None, gt=0)


class ListLocations(_Project, _Page):
    operation: Literal["list_locations"] = _op("list_locations", "Locations")
    search: Optional[str] = None


class CreateLocation(_Project):
    operation: Literal["create_location"] = _op("create_location", "Locations")
    node_name: str = Field(..., min_length=1, title="Location Name")
    parent_id: Optional[int] = Field(None, gt=0, title="Parent Location ID")


class OnResourceEvent(_Company, WebhookTriggerConfigBase):
    operation: Literal["on_resource_event"] = Field("on_resource_event", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Resource Event", "x-category": "Triggers", "x-is-trigger": True})
    project_id: Optional[int] = Field(None, gt=0, title="Project ID", description="Limit events to this project; leave empty for company-level events.")
    resource_name: str = Field("RFIs", title="Resource Name", description="Exact supported Procore webhook resource name, for example RFIs. See https://developers.procore.com/documentation/webhooks-api. Requires Webhooks API Standard permission.")
    event_type: Literal["create", "update", "delete"] = Field("update", title="Event")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with Procore automatically", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

    @field_validator("resource_name")
    @classmethod
    def resource(cls, value):
        if not value.strip():
            raise ValueError("Choose a Procore webhook resource")
        return value.strip()


ProcoreConfig = Annotated[Union[
    OnResourceEvent,
    GetCurrentUser,
    ListCompanies,
    ListProjects,
    GetProject,
    CreateProject,
    UpdateProject,
    ListVendors,
    GetVendor,
    CreateVendor,
    UpdateVendor,
    ListProjectUsers,
    ListRFIs,
    GetRFI,
    CreateRFI,
    UpdateRFI,
    ListSubmittals,
    GetSubmittal,
    CreateSubmittal,
    ListNotesLogs,
    CreateNotesLog,
    ListLocations,
    CreateLocation,
], Field(discriminator="operation")]


class ProcoreNodeConfig(NodeConfig[ProcoreConfig, ProcoreOAuthCredential]):
    pass


class ProcoreNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-procore"
    webhook_replace_stale_endpoint = True
    scope_registry = PROCORE_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return ProcoreNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.procore_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="procore")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: (config or {}).get(key) for key in ("company_id", "project_id", "resource_name", "event_type")}

    @staticmethod
    def _hook_path(config):
        company_id = int(config["company_id"])
        if company_id <= 0:
            raise ValueError("Company ID must be positive")
        path = f"/rest/v2.0/companies/{company_id}"
        if config.get("project_id") is not None:
            project_id = int(config["project_id"])
            if project_id <= 0:
                raise ValueError("Project ID must be positive")
            path += f"/projects/{project_id}"
        return path + "/webhooks/hooks"

    @classmethod
    async def _webhook_request(cls, credential, config, method, path, body=None):
        if not credential or not credential.get("access_token"):
            raise ValueError("Connect Procore before activating this trigger")
        headers = {"Authorization": f"Bearer {credential['access_token']}",
                   "Procore-Company-Id": str(config["company_id"]), "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, API_BASE + path, headers=headers, json=body)
        if method == "DELETE" and response.status_code == 404:
            return {}
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Procore webhook API {response.status_code}")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        # The v2 API registers the documented v2.0 delivery format.
        # Procore forwards our Authorization secret, rather than signing a body.
        op = OnResourceEvent.model_validate(config)
        path = cls._hook_path(config)
        secret = secrets.token_urlsafe(32)
        data = await cls._webhook_request(credential, config, "POST", path, {
            "payload_version": "v2.0", "namespace": "noclick", "destination_url": webhook_url,
            "destination_headers": {"Authorization": f"Bearer {secret}"}})
        hook_id = (data.get("data") or {}).get("id")
        if not isinstance(hook_id, (str, int)) or not str(hook_id):
            raise ValueError("Procore did not return a webhook ID")
        hook_path = f"{path}/{quote(str(hook_id), safe='')}"
        try:
            await cls._webhook_request(credential, config, "POST", f"{hook_path}/triggers", {
                "resource_name": op.resource_name, "event_type": op.event_type})
        except Exception:
            await cls._webhook_request(credential, config, "DELETE", hook_path)
            raise
        # Keep the original scope with the ID so changing company/project can
        # still remove the old hook before the mixin creates its replacement.
        external_id = f"{op.company_id}:{op.project_id or ''}:{hook_id}"
        return {"external_webhook_id": external_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        hook_id = (config or {}).get("external_webhook_id")
        if not hook_id:
            return
        parts = str(hook_id).split(":", 2)
        if len(parts) == 3:
            company_id, project_id, hook_id = parts
            config = {**config, "company_id": company_id, "project_id": project_id or None}
        if not isinstance(hook_id, (str, int)) or not str(hook_id):
            raise ValueError("Invalid Procore webhook ID")
        await cls._webhook_request(credential, config, "DELETE", f"{cls._hook_path(config)}/{quote(str(hook_id), safe='')}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://developers.procore.com/documentation/content/webhooks-api
        secret = (config or {}).get("signing_secret")
        actual = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        return bool(secret and isinstance(actual, str) and hmac.compare_digest(
            actual.encode(), f"Bearer {secret}".encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (payload.get("api_version") == "v2.0"
                and payload.get("resource_name") == str(config.get("resource_name") or "RFIs").strip()
                and payload.get("event_type") == config.get("event_type", "update")
                and str(payload.get("company_id")) == str(config.get("company_id"))
                and (config.get("project_id") is None or str(payload.get("project_id")) == str(config["project_id"])))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not output.get("resource_id") or not output.get("resource_name"):
            return super().resolve_agent_event(output)
        resource, rid = output["resource_name"], output["resource_id"]
        company, project = output.get("company_id"), output.get("project_id")
        kind = output.get("event_type")
        text = (f"Procore {resource} {kind}: resource {rid}.\n"
                f"Company {company}, project {project}; initiated by user {output.get('user_id')} "
                f"at {output.get('timestamp')}.\nEvent ID: {output.get('id')}.\n"
                "This notification contains resource identifiers; fetch the record for its content. "
                "Deleted records may no longer be available.")
        operation = {"RFIs": ("get_rfi", "rfi_id"), "Submittals": ("get_submittal", "submittal_id")}.get(resource)
        if operation and kind != "delete":
            text += f"\nTo read it: {operation[0]} company_id={company} project_id={project} {operation[1]}={rid}."
        return {"text": text, "conversation_key": f"{company}:{project}:{resource}:{rid}", "title": f"Procore {resource} {rid}"}

    async def _token(self, credential):
        data = credential.model_dump(exclude_none=True)
        if data.get("refresh_token"):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.procore_oauth import refresh_access_token
            await ensure_fresh_oauth_token(credential=data,
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                refresh=refresh_access_token, provider="procore", caller_path="execute")
            for key in ("access_token", "refresh_token", "expires_at"):
                if key in data:
                    setattr(credential, key, data[key])
        return data["access_token"]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Procore account")
        self.scope_registry.require(op.operation)
        if isinstance(op, OnResourceEvent):
            return self.no_event_output(op.operation)
        method, template, wrapper = PROCORE_OPERATIONS[op.operation]
        fields = op.model_dump(mode="json", exclude_none=True)
        path = template.format(**fields)
        company_id = fields.pop("company_id", None)
        for key in ("operation", "project_id", "vendor_id", "rfi_id", "submittal_id"):
            fields.pop(key, None)
        params, body = {}, None
        if method == "GET":
            params = fields
            if op.operation in {"list_projects", "get_project", "list_vendors", "get_vendor"}:
                params["company_id"] = company_id
            mappings = {"name": "filters[name]", "status": "filters[by_status]"} if op.operation == "list_projects" else {"status": "filters[status]"}
            if op.operation in {"list_vendors", "list_project_users", "list_locations"}:
                mappings["search"] = "filters[search]"
            if op.operation == "list_submittals":
                mappings["search"] = "filters[query]"
            params = {mappings.get(k, k): v for k, v in params.items()}
        else:
            if op.operation == "create_submittal":
                params["send_emails"] = fields.pop("send_emails")
            if op.operation in {"create_rfi", "update_rfi"} and "question" in fields:
                fields["question"] = {"body": fields["question"]}
            body = {wrapper: fields}
            if wrapper in {"project", "vendor"}:
                body["company_id"] = company_id
            if not fields:
                raise ValueError("Supply at least one field to update")
        token = await self._token(credential)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if company_id is not None:
            headers["Procore-Company-Id"] = str(company_id)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, API_BASE + path, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            detail = response.text[:2000].replace(token, "[redacted]")
            raise ValueError(f"Procore API {response.status_code}: {detail}")
        data = response.json()
        if not isinstance(data, (dict, list)) or (isinstance(data, dict) and ("error" in data or "errors" in data)):
            raise ValueError("Procore returned an unexpected response")
        result = {"status": "success", "operation": op.operation, "data": data}
        if op.operation.startswith("list_"):
            if not isinstance(data, list):
                raise ValueError("Expected a Procore list response")
            next_page = None
            if "next" in response.links:
                # Expose only a page number; never follow a provider URL with credentials.
                parts = urlsplit(response.links["next"]["url"])
                page = parse_qs(parts.query).get("page", [""])[0]
                if page.isdigit() and int(page) > op.page and parts.path == path:
                    next_page = int(page)
            result.update(page=op.page, per_page=op.per_page, next_page=next_page)
        return result
