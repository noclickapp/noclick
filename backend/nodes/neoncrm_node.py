"""Native Neon CRM 2.12 account, contact, legacy-event and activity workflows.
Uses documented typed REST operations with organization-bound Basic authentication.
Only projected metadata leaves this node; payment and communication endpoints are absent.
"""
from __future__ import annotations

import hashlib
import json
import re
from base64 import b64encode
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, WrapValidator, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "neoncrm_api_key"
ORIGINS = {"production": "https://api.neoncrm.com/v2", "trial": "https://trial.neoncrm.com/v2"}
API_VERSION = "2.12"
MAX_BODY = 4 * 1024 * 1024


def _pending(value, handler):
    if isinstance(value, str) and "{{" in value:
        return value
    return handler(value)


ID = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"), WrapValidator(_pending)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Page = Annotated[int, Field(ge=0, le=1000000), WrapValidator(_pending)]
Size = Annotated[int, Field(ge=1, le=200), WrapValidator(_pending)]


def _resource(resource):
    return {"x-resource-type": "neoncrm_" + resource}


class NeonCRMAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Neon CRM API Key", extra="ignore", json_schema_extra={
        "x-credential-url": "https://developer.neoncrm.com/authentication/",
        "x-credential-instructions": "Use an existing organization ID and the API key of a system user with API Access. Choose Trial only for a trial instance; constituent OAuth is not system-user authorization."
    })
    credential_type: Literal["neoncrm_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    org_id: str = Field(..., title="Organization ID", min_length=1, max_length=128)
    api_key: str = Field(..., title="API Key", min_length=1, max_length=512, json_schema_extra={"ui:widget": "password"})
    instance: Literal["production", "trial"] = Field("production", title="Instance", description="Production also covers sandbox instances.")

    @field_validator("org_id", "api_key", mode="before")
    @classmethod
    def _literal(cls, value, info):
        if not isinstance(value, str) or "{{" in value:
            raise ValueError("Supply literal text for Neon CRM authentication.")
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value) or (info.field_name == "org_id" and ":" in value):
            raise ValueError("Neon CRM authentication must be printable text without spaces.")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _sparse(cls, data):
        if isinstance(data, dict):
            return {k: v.strip() if isinstance(v, str) and k != "operation" else v for k, v in data.items() if v is not None and not (isinstance(v, str) and not v.strip())}
        return data


class _Page(_Config):
    current_page: Page = Field(0, title="Page", description="Zero-based; returns one bounded page.")
    page_size: Size = Field(20, title="Page Size")


class _Account(_Config):
    account_id: ID = Field(..., title="Account ID", json_schema_extra=_resource("account_id"))


class _AccountPage(_Account):
    current_page: Page = Field(0, title="Page", description="Company-contact pagination exposes currentPage only.")


class _Person(_Config):
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")
    email: Optional[Text] = Field(None, title="Email", description="Stores contact information; does not request a system email.")


class _Company(_Config):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(..., title="Company Name")


class _PersonAccount(_Person, _Account):
    pass


class _CompanyAccount(_Company, _Account):
    pass


class _Contact(_Account):
    contact_id: ID = Field(..., title="Contact ID", json_schema_extra=_resource("contact_id"))


class _CreateContact(_Person, _Account):
    department: Optional[Text] = Field(None, title="Department")
    job_title: Optional[Text] = Field(None, title="Job Title")


class _PatchContact(_Contact):
    first_name: Optional[Text] = Field(None, title="First Name")
    last_name: Optional[Text] = Field(None, title="Last Name")
    email: Optional[Text] = Field(None, title="Email")
    department: Optional[Text] = Field(None, title="Department")
    job_title: Optional[Text] = Field(None, title="Job Title")

    @model_validator(mode="after")
    def _change(self):
        if not any(getattr(self, f) is not None for f in ("first_name", "last_name", "email", "department", "job_title")):
            raise ValueError("Provide a contact field to update.")
        return self


class _ActivityID(_Config):
    activity_id: ID = Field(..., title="Activity ID", json_schema_extra=_resource("activity_id"))


class _ActivityBody(_Config):
    subject: Text = Field(..., title="Subject")
    start_date: str = Field(..., title="Start Date", description="ISO 8601 date-time.")
    timezone_id: ID = Field(..., title="Timezone ID", description="Use List Timezones.", json_schema_extra=_resource("timezone_id"))
    status_id: ID = Field(..., title="Status ID", description="Use List Activity Statuses.", json_schema_extra=_resource("activity_status_id"))
    priority: Annotated[Literal["High", "Normal", "Low"], WrapValidator(_pending)] = Field("Normal", title="Priority")
    note: Optional[Text] = Field(None, title="Note")
    client_account_id: Optional[ID] = Field(None, title="Linked Account ID", json_schema_extra=_resource("account_id"))
    activity_type_id: Optional[ID] = Field(None, title="Activity Type ID", json_schema_extra=_resource("activity_type_id"))

    @field_validator("start_date")
    @classmethod
    def _date(cls, value):
        if "{{" in value:
            return value
        if "T" not in value:
            raise ValueError("Use an ISO 8601 date-time.")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class _ActivityUpdate(_ActivityBody, _ActivityID):
    pass


class _EventID(_Config):
    event_id: ID = Field(..., title="Legacy Event ID", json_schema_extra=_resource("event_id"))


class _Report(_Page):
    output_fields: list[Text] = Field(..., title="Output Fields", min_length=1, max_length=10, json_schema_extra={"ui:widget": "list"}, description="Exact standard field names from Activity Output Fields. Only selected columns are returned.")
    search_field: Optional[Text] = Field(None, title="Search Field", description="Exact standard field name from Activity Search Fields.")
    operator: Literal["EQUAL", "NOT_EQUAL", "BLANK", "NOT_BLANK", "LESS_THAN", "GREATER_THAN", "LESS_AND_EQUAL", "GREATER_AND_EQUAL", "CONTAIN", "NOT_CONTAIN"] = "EQUAL"
    value: Optional[Text] = Field(None, title="Search Value")

    @model_validator(mode="after")
    def _criteria(self):
        if len(set(self.output_fields)) != len(self.output_fields):
            raise ValueError("Output fields must be distinct.")
        if any(re.search(r"password|secret|token|credential|login|api.?key", field, re.I) for field in self.output_fields):
            raise ValueError("Authentication fields are not supported report columns.")
        if self.search_field and self.operator not in ("BLANK", "NOT_BLANK") and self.value is None:
            raise ValueError("This search operator requires a value.")
        if self.search_field is None and self.value is not None:
            raise ValueError("A search value requires a search field.")
        return self

class NeonCRMOrganizationConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["get_organization_profile"] = Field("get_organization_profile", title="Organization Profile", json_schema_extra={"const": "get_organization_profile", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMCurrentUserConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["get_current_user"] = Field("get_current_user", title="Current API User", json_schema_extra={"const": "get_current_user", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMAccountsConfig(_Page):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_accounts"] = Field("list_accounts", title="List Accounts", json_schema_extra={"const": "list_accounts", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMAccountConfig(_Account):
    """Reads documented organization-scoped metadata."""
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"const": "get_account", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMCreateIndividualConfig(_Person):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["create_individual_account"] = Field("create_individual_account", title="Create Individual Account", json_schema_extra={"const": "create_individual_account", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMCreateCompanyConfig(_Company):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["create_company_account"] = Field("create_company_account", title="Create Company Account", json_schema_extra={"const": "create_company_account", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMPatchIndividualConfig(_PersonAccount):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["update_individual_account"] = Field("update_individual_account", title="Update Individual Account", json_schema_extra={"const": "update_individual_account", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMPatchCompanyConfig(_CompanyAccount):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["update_company_account"] = Field("update_company_account", title="Update Company Account", json_schema_extra={"const": "update_company_account", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMContactsConfig(_AccountPage):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Company Contacts", json_schema_extra={"const": "list_contacts", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMContactConfig(_Contact):
    """Reads documented organization-scoped metadata."""
    operation: Literal["get_contact"] = Field("get_contact", title="Get Company Contact", json_schema_extra={"const": "get_contact", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMCreateContactConfig(_CreateContact):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["create_contact"] = Field("create_contact", title="Create Company Contact", json_schema_extra={"const": "create_contact", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMPatchContactConfig(_PatchContact):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["update_contact"] = Field("update_contact", title="Update Company Contact", json_schema_extra={"const": "update_contact", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMDeleteContactConfig(_Contact):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Company Contact", json_schema_extra={"const": "delete_contact", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMActivityConfig(_ActivityID):
    """Reads documented organization-scoped metadata."""
    operation: Literal["get_activity"] = Field("get_activity", title="Get Activity", json_schema_extra={"const": "get_activity", "ui:hidden": True, "x-operation-category": "read"})
    include_note: Annotated[bool, WrapValidator(_pending)] = Field(False, title="Include Note", description="Includes the activity's private note text in workflow output.")


class NeonCRMCreateActivityConfig(_ActivityBody):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["create_activity"] = Field("create_activity", title="Create Activity", json_schema_extra={"const": "create_activity", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMPatchActivityConfig(_ActivityUpdate):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["update_activity"] = Field("update_activity", title="Update Activity", json_schema_extra={"const": "update_activity", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMDeleteActivityConfig(_ActivityID):
    """Changes ordinary CRM records; organization automation may apply."""
    operation: Literal["delete_activity"] = Field("delete_activity", title="Delete Activity", json_schema_extra={"const": "delete_activity", "ui:hidden": True, "x-operation-category": "write"})


class NeonCRMEventsConfig(_Page):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_events"] = Field("list_events", title="List Legacy Events", json_schema_extra={"const": "list_events", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMEventConfig(_EventID):
    """Reads documented organization-scoped metadata."""
    operation: Literal["get_event"] = Field("get_event", title="Get Legacy Event", json_schema_extra={"const": "get_event", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMStatusesConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_activity_statuses"] = Field("list_activity_statuses", title="List Activity Statuses", json_schema_extra={"const": "list_activity_statuses", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMTypesConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_activity_types"] = Field("list_activity_types", title="List Activity Types", json_schema_extra={"const": "list_activity_types", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMTimezonesConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_timezones"] = Field("list_timezones", title="List Timezones", json_schema_extra={"const": "list_timezones", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMSearchFieldsConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_activity_search_fields"] = Field("list_activity_search_fields", title="Activity Search Fields", json_schema_extra={"const": "list_activity_search_fields", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMOutputFieldsConfig(_Config):
    """Reads documented organization-scoped metadata."""
    operation: Literal["list_activity_output_fields"] = Field("list_activity_output_fields", title="Activity Output Fields", json_schema_extra={"const": "list_activity_output_fields", "ui:hidden": True, "x-operation-category": "read"})


class NeonCRMSearchActivitiesConfig(_Report):
    """Reads documented organization-scoped metadata."""
    operation: Literal["search_activities"] = Field("search_activities", title="Search Activity Report", json_schema_extra={"const": "search_activities", "ui:hidden": True, "x-operation-category": "read"})


OP_MODELS = {
    "get_organization_profile": NeonCRMOrganizationConfig,
    "get_current_user": NeonCRMCurrentUserConfig,
    "list_accounts": NeonCRMAccountsConfig,
    "get_account": NeonCRMAccountConfig,
    "create_individual_account": NeonCRMCreateIndividualConfig,
    "create_company_account": NeonCRMCreateCompanyConfig,
    "update_individual_account": NeonCRMPatchIndividualConfig,
    "update_company_account": NeonCRMPatchCompanyConfig,
    "list_contacts": NeonCRMContactsConfig,
    "get_contact": NeonCRMContactConfig,
    "create_contact": NeonCRMCreateContactConfig,
    "update_contact": NeonCRMPatchContactConfig,
    "delete_contact": NeonCRMDeleteContactConfig,
    "get_activity": NeonCRMActivityConfig,
    "create_activity": NeonCRMCreateActivityConfig,
    "update_activity": NeonCRMPatchActivityConfig,
    "delete_activity": NeonCRMDeleteActivityConfig,
    "list_events": NeonCRMEventsConfig,
    "get_event": NeonCRMEventConfig,
    "list_activity_statuses": NeonCRMStatusesConfig,
    "list_activity_types": NeonCRMTypesConfig,
    "list_timezones": NeonCRMTimezonesConfig,
    "list_activity_search_fields": NeonCRMSearchFieldsConfig,
    "list_activity_output_fields": NeonCRMOutputFieldsConfig,
    "search_activities": NeonCRMSearchActivitiesConfig,
}
NEONCRM_SCOPES = ScopeRegistry("neoncrm", {op: ScopeRequirement(credential_types=(FAMILY,), note="The key inherits its Neon CRM system user's permissions; no OAuth scope strings apply.") for op in OP_MODELS})
NeonCRMConfig = Annotated[Union[NeonCRMOrganizationConfig, NeonCRMCurrentUserConfig, NeonCRMAccountsConfig, NeonCRMAccountConfig, NeonCRMCreateIndividualConfig, NeonCRMCreateCompanyConfig, NeonCRMPatchIndividualConfig, NeonCRMPatchCompanyConfig, NeonCRMContactsConfig, NeonCRMContactConfig, NeonCRMCreateContactConfig, NeonCRMPatchContactConfig, NeonCRMDeleteContactConfig, NeonCRMActivityConfig, NeonCRMCreateActivityConfig, NeonCRMPatchActivityConfig, NeonCRMDeleteActivityConfig, NeonCRMEventsConfig, NeonCRMEventConfig, NeonCRMStatusesConfig, NeonCRMTypesConfig, NeonCRMTimezonesConfig, NeonCRMSearchFieldsConfig, NeonCRMOutputFieldsConfig, NeonCRMSearchActivitiesConfig], Field(discriminator="operation")]


class NeonCRMFullConfig(NodeConfig):
    config: NeonCRMConfig
    credentials: Optional[NeonCRMAPIKeyCredential] = None


def _raw_guards(data):
    cred = data.get("credentials")
    if isinstance(cred, dict):
        tag = cred.get("credential_type")
        if tag is not None and tag != FAMILY:
            raise ValueError("Select a Neon CRM API key credential.")
        if tag is None and any(k in cred for k in ("id", "credential_id", "token_version", "updated_at")):
            raise ValueError("Stored Neon CRM credentials need an authoritative type tag.")
        for key in ("org_id", "api_key", "instance"):
            if key in cred and not isinstance(cred[key], str):
                raise ValueError("Neon CRM credential fields must be text.")
    cfg = data.get("config", {})
    if isinstance(cfg, dict) and cfg.get("operation") in OP_MODELS:
        fields = OP_MODELS[cfg["operation"]].model_fields
        for key, value in cfg.items():
            if key in fields and key.endswith("_id") and value is not None and not isinstance(value, str):
                raise ValueError("Neon CRM resource IDs must be text.")


def _has_reference(value):
    if isinstance(value, str):
        return "{{" in value
    if isinstance(value, dict):
        return any(_has_reference(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_reference(v) for v in value)
    return False


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Neon CRM returned an invalid resource ID.")
    text = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", text):
        raise ValueError("Neon CRM returned an invalid resource ID.")
    return text


def _project(value, fields):
    if not isinstance(value, dict):
        raise ValueError("Neon CRM returned an unexpected object.")
    out = {}
    for key in fields:
        v = value.get(key)
        if v is not None:
            if not isinstance(v, (str, int, float, bool)) or isinstance(v, str) and len(v) > 2000:
                raise ValueError("Neon CRM returned unexpected metadata.")
            out[key] = v
    return out


def _pagination(body, requested, count):
    p = body.get("pagination")
    if not isinstance(p, dict) or any(type(p.get(k)) is not int or p[k] < 0 for k in ("currentPage", "pageSize", "totalPages", "totalResults")):
        raise ValueError("Neon CRM returned unexpected pagination.")
    if p["currentPage"] != requested or not 1 <= p["pageSize"] <= 200 or count > p["pageSize"] or p["totalPages"] and requested >= p["totalPages"]:
        raise ValueError("Neon CRM returned inconsistent pagination.")
    out = {k: p[k] for k in ("currentPage", "pageSize", "totalPages", "totalResults")}
    out["next_page"] = requested + 1 if requested + 1 < p["totalPages"] else None
    return out


class NeonCRMNode(WorkflowNode):
    integration_type = "automation-neoncrm"
    scope_registry = NEONCRM_SCOPES
    connection_evidence = ConnectionEvidence(noun="organization", identity_operation="get_organization_profile", identity_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return NeonCRMFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guards(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _raw_guards(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    def _selected_id(self):
        selected = self.node_data.get("credentialIds") or self.node_data.get("credential_ids") or {}
        if not isinstance(selected, dict):
            raise ValueError("Invalid Neon CRM credential selection.")
        native = selected.get(FAMILY) or selected.get("default")
        explicit = self.node_data.get("credential_id")
        if selected.get(FAMILY) and selected.get("default") and selected[FAMILY] != selected["default"]:
            raise ValueError("Neon CRM credential selection is ambiguous.")
        if selected and native is None or native and explicit and native != explicit:
            raise ValueError("Select the native Neon CRM credential.")
        value = native or explicit
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Invalid Neon CRM credential ID.")
            UUID(value)
        return value

    async def _authority(self):
        arguments = self.config.config.model_dump(mode="json")
        if hasattr(self, "_arguments") and arguments != self._arguments:
            raise ValueError("Neon CRM operation arguments changed during execution.")
        # Staging resolves stored credentials before constructing the node.
        # API keys do not rotate; use the admitted credential model like Brex.
        cred = self.config.credentials
        if cred is None:
            raise ValueError("Connect a Neon CRM API key.")
        return cred, (self._selected_id(), self.user_id, self.organization_id, self.workflow_id,
                      cred.org_id, cred.instance, hashlib.sha256(cred.api_key.encode()).hexdigest())

    async def _request(self, method, path, *, params=None, body=None, write=False, statuses=(200,)):
        cred, stamp = await self._authority()
        if getattr(self, "_binding", stamp) != stamp:
            raise ValueError("Neon CRM credential context changed; run again with the current selection.")
        self._binding = stamp
        auth = httpx.BasicAuth(cred.org_id, cred.api_key)
        status = None
        dispatched = False
        try:
            async with guarded_async_client(timeout=25, follow_redirects=False, trust_env=False) as client:
                _, current = await self._authority()
                if current != stamp:
                    raise ValueError("Neon CRM credential context changed before the request.")
                dispatched = True
                async with client.stream(method, ORIGINS[cred.instance] + path, auth=auth, headers={"NEON-API-VERSION": API_VERSION, "Accept": "application/json"}, params=params, json=body) as response:
                    status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise ValueError("Neon CRM response exceeds the supported limit.")
                    _, current = await self._authority()
                    if current != stamp:
                        raise ValueError("Neon CRM credential context changed during the request.")
                    if status not in statuses:
                        if write and (status >= 500 or 300 <= status < 400):
                            raise ValueError("Neon CRM write outcome is unknown; read back before repeating.")
                        messages = {401: "Neon CRM rejected the API key.", 403: "Neon CRM user permissions do not allow this operation.", 404: "Neon CRM resource was not found.", 429: "Neon CRM API limit reached; try later."}
                        raise ValueError(messages.get(status, "Neon CRM rejected the request.") + " HTTP " + str(status))
                    if not raw and status in (201, 204):
                        return None, status
                    try:
                        data = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise ValueError("Neon CRM returned an unexpected response.") from None
                    if not isinstance(data, (dict, list)):
                        raise ValueError("Neon CRM returned an unexpected response.")
                    return data, status
        except (httpx.HTTPError, ValueError) as exc:
            if write and dispatched and (status is None or status in statuses):
                raise ValueError("Neon CRM write outcome is unknown; read back before repeating.") from None
            if isinstance(exc, httpx.HTTPError):
                raise ValueError("Neon CRM request could not be completed.") from None
            raise

    async def run(self, inputs):
        # The shared admission seam consumes credential_id. Normalize a native
        # map selection before reaching it, including direct factory callers.
        selected = self._selected_id()
        if selected is not None:
            self.node_data["credential_id"] = selected
        if isinstance(self.config, NeonCRMFullConfig):
            self._admitted_arguments = self.config.config.model_dump(mode="json")
        self._admitted_context = (selected, self.user_id, self.organization_id, self.workflow_id)
        return await super().run(inputs)

    async def execute(self, inputs):
        if not isinstance(self.config, NeonCRMFullConfig):
            raise ValueError("Configure the Neon CRM operation.")
        cfg = self.config.config
        if hasattr(self, "_admitted_context") and (self._selected_id(), self.user_id, self.organization_id, self.workflow_id) != self._admitted_context:
            raise ValueError("Neon CRM credential context changed after admission.")
        if hasattr(self, "_admitted_arguments") and cfg.model_dump(mode="json") != self._admitted_arguments:
            raise ValueError("Neon CRM operation arguments changed after admission.")
        if _has_reference(cfg.model_dump()):
            raise ValueError("Resolve Neon CRM field references before execution.")
        self._arguments = cfg.model_dump(mode="json")
        self._binding = (await self._authority())[1]
        self.scope_registry.enforce_credential_type(cfg.operation, FAMILY)
        write = cfg.operation.startswith(("create_", "update_", "delete_"))
        result = await self._execute(cfg)
        try:
            cred, stamp = await self._authority()
            if stamp != self._binding:
                raise ValueError("Neon CRM credential context changed.")
            secrets = (cred.api_key, b64encode((cred.org_id + ":" + cred.api_key).encode()).decode())
            def contains_secret(value):
                if isinstance(value, str):
                    return any(secret in value for secret in secrets)
                if isinstance(value, dict):
                    return any(contains_secret(k) or contains_secret(v) for k, v in value.items())
                if isinstance(value, list):
                    return any(contains_secret(v) for v in value)
                return False
            if contains_secret(result):
                raise ValueError("Neon CRM output contains authentication material and was withheld.")
            return {"success": True, "data": result}
        except ValueError:
            if write:
                raise ValueError("Neon CRM write was not verified; read back before repeating.") from None
            raise

    async def _execute(self, cfg):
        op = cfg.operation
        if op in ("get_organization_profile", "get_current_user"):
            path = "/properties/organizationProfile" if op == "get_organization_profile" else "/properties/currentSystemUser"
            data, _ = await self._request("GET", path)
            if op == "get_organization_profile":
                out = _project(data, ("orgId", "name"))
                cred, _ = await self._authority()
                if out.get("orgId") != cred.org_id or not out.get("name"):
                    raise ValueError("Neon CRM organization identity does not match the supplied organization.")
                return {"id": out["orgId"], "name": out["name"]}
            out = _project(data, ("id", "firstName", "middleName", "lastName"))
            out["id"] = _id(out.get("id"))
            out["name"] = " ".join(str(out[k]) for k in ("firstName", "middleName", "lastName") if out.get(k))
            return out
        catalogues = {"list_activity_statuses": "/properties/activityStatuses", "list_activity_types": "/properties/activityTypes", "list_timezones": "/properties/systemTimezones"}
        if op in catalogues:
            data, _ = await self._request("GET", catalogues[op])
            if not isinstance(data, list) or len(data) > 1000 or any(not isinstance(row, dict) for row in data):
                raise ValueError("Neon CRM returned an unsupported catalogue.")
            return [{"id": _id(row.get("id")), **_project(row, ("name",))} for row in data]
        if op in ("list_activity_search_fields", "list_activity_output_fields"):
            path = "/activities/search/" + ("searchFields" if op == "list_activity_search_fields" else "outputFields")
            data, _ = await self._request("GET", path)
            return self._report_fields(data, op == "list_activity_search_fields")
        if op == "search_activities":
            return await self._report(cfg)
        if op in ("list_accounts", "list_events", "list_contacts"):
            path, key = ("/accounts", "accounts") if op == "list_accounts" else ("/events", "events") if op == "list_events" else ("/accounts/" + cfg.account_id + "/contacts", "contacts")
            params = {"currentPage": cfg.current_page}
            if op != "list_contacts":
                params["pageSize"] = cfg.page_size
            data, status = await self._request("GET", path, params=params, statuses=(200, 222) if op == "list_contacts" else (200,))
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ValueError("Neon CRM returned an unexpected list.")
            rows = data[key]
            page = _pagination(data, cfg.current_page, len(rows))
            if op == "list_contacts":
                canonical = _id(data.get("accountId"))
                if status != 222 and canonical != cfg.account_id:
                    raise ValueError("Neon CRM returned contacts for another account.")
                projected = [self._contact(row, canonical) for row in rows]
            elif op == "list_accounts":
                projected = [dict(_project(row, ("firstName", "lastName", "companyName", "userType")), accountId=_id(row.get("accountId"))) for row in rows]
            else:
                projected = [dict(_project(row, ("name", "code", "capacity", "archived", "startDate", "startTime", "endDate", "endTime", "publishEvent", "enableEventRegistrationForm")), id=_id(row.get("id"))) for row in rows]
            ids = [row.get("contactId") or row.get("accountId") or row.get("id") for row in projected]
            if len(set(ids)) != len(ids):
                raise ValueError("Neon CRM returned duplicate page IDs.")
            return {"items": projected, "pagination": page, **({"requested_account_id": cfg.account_id, "account_id": canonical, "merged_account": status == 222} if op == "list_contacts" else {})}
        if op == "get_account":
            data, status = await self._request("GET", "/accounts/" + cfg.account_id, statuses=(200, 222))
            variants = [k for k in ("individualAccount", "companyAccount") if isinstance(data, dict) and isinstance(data.get(k), dict)]
            if len(variants) != 1:
                raise ValueError("Neon CRM returned an unexpected account.")
            row = data[variants[0]]
            canonical = _id(row.get("accountId"))
            if status != 222 and canonical != cfg.account_id:
                raise ValueError("Neon CRM returned another account.")
            out = _project(row, ("name", "noSolicitation", "email1OptOut"))
            if isinstance(row.get("primaryContact"), dict):
                out["primaryContact"] = _project(row["primaryContact"], ("firstName", "lastName", "preferredName", "department", "title"))
            return {variants[0]: out, "account_id": canonical, "requested_account_id": cfg.account_id, "merged_account": status == 222}
        if op == "get_contact":
            data, status = await self._request("GET", "/accounts/" + cfg.account_id + "/contacts/" + cfg.contact_id, statuses=(200, 222))
            out = self._contact(data, cfg.account_id)
            if out["contactId"] != cfg.contact_id:
                raise ValueError("Neon CRM returned another contact.")
            return {**out, "requested_account_id": cfg.account_id, "merged_account": status == 222}
        if op in ("get_activity", "get_event"):
            resource_id = cfg.activity_id if op == "get_activity" else cfg.event_id
            data, _ = await self._request("GET", ("/activities/" if op == "get_activity" else "/events/") + resource_id)
            if not isinstance(data, dict) or _id(data.get("id")) != resource_id:
                raise ValueError("Neon CRM returned another resource.")
            fields = ("subject", "priority") if op == "get_activity" else ("name", "summary", "code", "maximumAttendees", "publishEvent", "archived", "enableEventRegistrationForm")
            out = dict(_project(data, fields), id=resource_id)
            if op == "get_activity":
                if cfg.include_note:
                    out.update(_project(data, ("note",)))
                for key in ("status", "activityType", "customStatus"):
                    if isinstance(data.get(key), dict):
                        out[key] = _project(data[key], ("id", "name"))
                if isinstance(data.get("activityDates"), dict):
                    out["activityDates"] = _project(data["activityDates"], ("startDate", "endDate", "startTime", "endTime"))
            return out
        return await self._write(cfg)

    @staticmethod
    def _contact(data, account_id):
        out = _project(data, ("firstName", "middleName", "lastName", "preferredName", "department", "title", "primaryContact", "currentEmployer"))
        out["contactId"] = _id(data.get("contactId"))
        # Contact.accountId can describe a linked constituent. The company
        # namespace is the closed route/list wrapper, not an invented equality.
        if data.get("accountId") is not None:
            out["accountId"] = _id(data["accountId"])
        out["company_account_id"] = account_id
        return out

    @staticmethod
    def _report_fields(data, search):
        if not isinstance(data, dict) or not isinstance(data.get("standardFields"), list) or len(data["standardFields"]) > 1000:
            raise ValueError("Neon CRM returned unexpected reporting fields.")
        if not search:
            if any(not isinstance(v, str) or len(v) > 200 for v in data["standardFields"]):
                raise ValueError("Neon CRM returned unexpected reporting field names.")
            return {"standardFields": data["standardFields"]}
        rows = []
        for row in data["standardFields"]:
            item = _project(row, ("fieldName",))
            operators = row.get("operators")
            if not item.get("fieldName") or not isinstance(operators, list) or any(not isinstance(v, str) for v in operators) or len(operators) > 12:
                raise ValueError("Neon CRM returned unexpected reporting operators.")
            rows.append({**item, "operators": operators})
        return {"standardFields": rows}

    async def _report(self, cfg):
        fields, _ = await self._request("GET", "/activities/search/outputFields")
        allowed = self._report_fields(fields, False)["standardFields"]
        if any(f not in allowed for f in cfg.output_fields):
            raise ValueError("Choose documented standard Activity Output Fields.")
        criteria = []
        if cfg.search_field:
            fields, _ = await self._request("GET", "/activities/search/searchFields")
            allowed = self._report_fields(fields, True)["standardFields"]
            if not any(r["fieldName"] == cfg.search_field and cfg.operator in r["operators"] for r in allowed):
                raise ValueError("Choose a supported Activity Search Field and operator.")
            criteria = [{"field": cfg.search_field, "operator": cfg.operator}]
            if cfg.operator not in ("BLANK", "NOT_BLANK"):
                criteria[0]["value"] = cfg.value
        body = {"searchFields": criteria, "outputFields": cfg.output_fields, "pagination": {"currentPage": cfg.current_page, "pageSize": cfg.page_size}}
        data, _ = await self._request("POST", "/activities/search", body=body)
        if not isinstance(data, dict) or not isinstance(data.get("searchResults"), list):
            raise ValueError("Neon CRM returned unexpected report results.")
        rows = data["searchResults"]
        page = _pagination(data, cfg.current_page, len(rows))
        return {"items": [_project(row, cfg.output_fields) for row in rows], "pagination": page}

    async def _write(self, cfg):
        op = cfg.operation
        statuses = (200, 201)
        method, body, id_key = "POST", None, "id"
        if "individual_account" in op or "company_account" in op:
            individual = "individual" in op
            payload = {"primaryContact": {"firstName": cfg.first_name, "lastName": cfg.last_name}} if individual else {"name": cfg.name}
            if individual and cfg.email is not None:
                payload["primaryContact"]["email1"] = cfg.email
            # Documented account field: never request the system email/text action.
            if op.startswith("create_"):
                payload["sendSystemEmail"] = False
                payload["sendTextOptIn"] = False
            body = {("individualAccount" if individual else "companyAccount"): payload}
            path = "/accounts"
            if op.startswith("update_"):
                method, path, id_key, statuses = "PATCH", "/accounts/" + cfg.account_id, "accountId", (200, 204, 222)
        elif op in ("create_contact", "update_contact", "delete_contact"):
            path = "/accounts/" + cfg.account_id + "/contacts"
            id_key = "accountId"
            statuses = (200, 201, 222)
            if op != "delete_contact":
                body = {native: getattr(cfg, field) for field, native in (("first_name", "firstName"), ("last_name", "lastName"), ("email", "email1"), ("department", "department"), ("job_title", "title")) if getattr(cfg, field, None) is not None}
            if op != "create_contact":
                path += "/" + cfg.contact_id
                method = "DELETE" if op == "delete_contact" else "PATCH"
                statuses = (200, 204, 222)
        else:
            path = "/activities"
            if op == "delete_activity":
                method, path = "DELETE", path + "/" + cfg.activity_id
            else:
                body = {"subject": cfg.subject, "activityDates": {"startDate": cfg.start_date, "timeZone": {"id": cfg.timezone_id}}, "status": {"id": cfg.status_id}, "priority": cfg.priority}
                if cfg.note is not None:
                    body["note"] = cfg.note
                if cfg.client_account_id is not None:
                    body["clientAccount"] = [{"accountId": cfg.client_account_id}]
                if cfg.activity_type_id is not None:
                    body["activityType"] = {"id": cfg.activity_type_id}
                if op == "update_activity":
                    method, path = "PATCH", path + "/" + cfg.activity_id
        data, status = await self._request(method, path, body=body, write=True, statuses=statuses)
        try:
            return self._acknowledgement(cfg, data, status, id_key)
        except ValueError:
            raise ValueError("Neon CRM write outcome is unknown; read back before repeating.") from None

    @staticmethod
    def _acknowledgement(cfg, data, status, id_key):
        op = cfg.operation
        out = {"operation": op, "http_status": status, "write_acknowledged": True, "readback_verified": False}
        if data is not None:
            if not isinstance(data, dict):
                raise ValueError("Neon CRM returned an unexpected write acknowledgement.")
            if op in ("create_activity", "update_activity") and isinstance(data.get("ids"), list):
                if not data["ids"] or len(data["ids"]) > 200:
                    raise ValueError("Neon CRM returned unexpected activity IDs.")
                out["ids"] = [_id(v) for v in data["ids"]]
            else:
                out[id_key] = _id(data.get(id_key))
            if op == "create_contact":
                out["id"] = _id(data.get("id"))
            if hasattr(cfg, "account_id") and "accountId" in out:
                if "_account" in op and status != 222 and out["accountId"] != cfg.account_id:
                    raise ValueError("Neon CRM acknowledged another account.")
                out["requested_account_id"] = cfg.account_id
                out["merged_account"] = status == 222
            if op in ("update_activity", "delete_activity") and "id" in out and out["id"] != cfg.activity_id:
                raise ValueError("Neon CRM acknowledged another activity.")
        return out
