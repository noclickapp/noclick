"""Native Mindbody Public API v6 metadata and client management.

Developer keys and supplied staff authorization remain distinct. Client writes
default to the documented validation mode and never book or charge a client.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

API_ROOT = "https://api.mindbodyonline.com/public/v6"
FAMILY = "mindbody_api_key"
NODE_TYPE = "automation-mindbody"
_MISSING = object()
_REQUEST_CONTEXT: ContextVar[Any] = ContextVar("mindbody_request_context", default=None)
def _options(field_name):
    return {"x-dynamic-options": {"field_name": field_name, "searchable": True, "allow_custom": True}}


def _operation(name, title, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True,
        "x-display-name": title, "x-category": category, "x-is-trigger": False})


class MindbodyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mindbody Public API", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developers.mindbodyonline.com/",
            "x-credential-instructions": "Supply a developer API key activated for this Site ID. Protected client reads, appointments and client writes also require an authorized staff user's complete Authorization header value. No login, token issue, renewal or activation request is made. Public metadata does not establish staff identity or account ownership."})
    credential_type: Literal["mindbody_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: StrictStr = Field(..., title="Developer API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    site_id: StrictInt = Field(..., title="Site ID", description="The activated business site. Mindbody's documented developer test site is -99; no environment is inferred from a key.")
    user_authorization: Optional[StrictStr] = Field(None, title="Staff Authorization", max_length=8192, repr=False,
        description="The complete Authorization header value accepted for this staff user. It is sent verbatim; no Bearer prefix is added.", json_schema_extra={"ui:widget": "password"})
    user_expires_at: Optional[StrictStr] = Field(None, title="Staff Token Expiry", description="Optional UTC/offset ISO timestamp from the token issuer. Expired supplied tokens require replacement.")

    @field_validator("api_key", "user_authorization", mode="before")
    @classmethod
    def secret(cls, value):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("Enter a single-line credential value")
        value = clean_secret(value, field_name="Mindbody credential")
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Credential value must be nonempty and single-line")
        return value

    @field_validator("site_id", mode="before")
    @classmethod
    def site(cls, value):
        if isinstance(value, str) and re.fullmatch(r"-99|[1-9][0-9]{0,9}", value):
            value = int(value)
        if type(value) is not int:
            raise ValueError("Use an integer Site ID")
        if value != -99 and value <= 0:
            raise ValueError("Use a positive Site ID or the documented -99 developer site")
        return value

    @field_validator("user_expires_at")
    @classmethod
    def expiry(cls, value):
        if value is not None:
            _timestamp(value, aware=True)
        return value


def _timestamp(value, *, aware=False):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if aware and (parsed.tzinfo is None or parsed.utcoffset() is None):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Use an ISO date and time" + (" with timezone" if aware else "")) from None
    return parsed


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("staff_id", "location_id", "home_location_id", "program_id", "limit", "offset", mode="before", check_fields=False)
    @classmethod
    def numeric_form_values(cls, value, info):
        # The real combobox saves string values. Convert decimal form IDs only;
        # booleans, floats and arbitrary strings retain strict validation.
        if info.field_name in {"staff_id", "location_id", "home_location_id", "program_id", "limit", "offset"}:
            if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
                return int(value)
        return value


class _Page(_Input):
    limit: StrictInt = Field(25, ge=1, le=100, title="Page Size")
    offset: StrictInt = Field(0, ge=0, title="Offset", description="Advance using next_offset from this same query; changing filters starts a new query.")


class MindbodyCheckConnectionConfig(_Input):
    operation: Literal["check_connection"] = _operation("check_connection", "Check Protected Client Access", "Connection")


class MindbodySitesConfig(_Page):
    operation: Literal["list_sites"] = _operation("list_sites", "List Bound Site", "Sites")


class MindbodyLocationsConfig(_Page):
    operation: Literal["list_locations"] = _operation("list_locations", "List Locations", "Sites")


class MindbodyStaffConfig(_Page):
    operation: Literal["list_staff"] = _operation("list_staff", "List Staff Metadata", "Staff")
    staff_id: Optional[StrictInt] = Field(None, ge=1, title="Staff ID", json_schema_extra=_options("staff_id"))


class MindbodyClientsConfig(_Page):
    operation: Literal["list_clients"] = _operation("list_clients", "List Clients", "Clients")
    search: Optional[StrictStr] = Field(None, max_length=200, description="Client name or email search, within this staff user's access.")
    include_inactive: StrictBool = Field(False, title="Include Inactive")
    is_prospect: Optional[StrictBool] = Field(None, title="Prospect Filter")


class MindbodyGetClientConfig(_Input):
    operation: Literal["get_client"] = _operation("get_client", "Get Client", "Clients")
    client_id: StrictStr = Field(..., min_length=1, max_length=200, title="Client ID")


class MindbodyRequiredFieldsConfig(_Input):
    operation: Literal["get_required_client_fields"] = _operation("get_required_client_fields", "Get Required Client Fields", "Clients")


class _Window(_Page):
    start: StrictStr = Field(..., title="Start Date and Time", description="ISO local site date/time, or an offset timestamp accepted by the API.")
    end: StrictStr = Field(..., title="End Date and Time")
    location_id: Optional[StrictInt] = Field(None, ge=1, title="Location ID", json_schema_extra=_options("location_id"))
    staff_id: Optional[StrictInt] = Field(None, ge=1, title="Staff ID", json_schema_extra=_options("staff_id"))

    @model_validator(mode="after")
    def window(self):
        first, last = _timestamp(self.start), _timestamp(self.end)
        try:
            delta = last - first
        except TypeError:
            raise ValueError("Use matching timezone forms for Start and End") from None
        if not 0 <= delta.total_seconds() <= 31 * 86400:
            raise ValueError("The requested date window must be ordered and at most 31 days")
        return self


class MindbodyClassesConfig(_Window):
    operation: Literal["list_classes"] = _operation("list_classes", "List Classes", "Classes")
    hide_canceled: StrictBool = Field(True, title="Hide Canceled Classes")


class MindbodyAppointmentsConfig(_Window):
    operation: Literal["list_appointments"] = _operation("list_appointments", "List Staff Appointments", "Appointments")


class MindbodyProgramsConfig(_Page):
    operation: Literal["list_programs"] = _operation("list_programs", "List Programs", "Sites")


class MindbodySessionTypesConfig(_Page):
    operation: Literal["list_session_types"] = _operation("list_session_types", "List Session Types", "Sites")
    program_id: Optional[StrictInt] = Field(None, ge=1, title="Program ID", json_schema_extra=_options("program_id"))


class _Write(_Input):
    test: StrictBool = Field(True, title="Validate Only", description="True validates without adding/updating client data. False performs the documented client write and may trigger business workflows.")
    transaction_key: Optional[StrictStr] = Field(None, min_length=1, max_length=50, title="Transaction Correlation Key",
        description="An optional correlation value for provider webhooks; this is not an idempotency key. The node never retries a write.")

    @field_validator("transaction_key")
    @classmethod
    def correlation(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("Use a single-line alphanumeric correlation key")
        return value


class _Profile(_Write):
    first_name: Optional[StrictStr] = Field(None, min_length=1, max_length=100)
    last_name: Optional[StrictStr] = Field(None, min_length=1, max_length=100)
    email: Optional[StrictStr] = Field(None, min_length=1, max_length=254)
    mobile_phone: Optional[StrictStr] = Field(None, min_length=1, max_length=50)
    active: StrictBool = Field(..., title="Active", description="Explicitly preserve or change active state. Mindbody can otherwise reactivate an inactive client on update.")

    def profile(self):
        return {wire: getattr(self, field) for field, wire in {"first_name": "FirstName", "last_name": "LastName", "email": "Email", "mobile_phone": "MobilePhone", "active": "Active"}.items() if getattr(self, field) is not None}


class MindbodyCreateClientConfig(_Profile):
    operation: Literal["create_client"] = _operation("create_client", "Create Client (Validation Default)", "Clients")
    first_name: StrictStr = Field(..., min_length=1, max_length=100)
    last_name: StrictStr = Field(..., min_length=1, max_length=100)
    home_location_id: Optional[StrictInt] = Field(None, ge=1, title="Home Location ID", json_schema_extra=_options("home_location_id"))
    emergency_name: Optional[StrictStr] = Field(None, min_length=1, max_length=200)
    emergency_email: Optional[StrictStr] = Field(None, min_length=1, max_length=254)
    emergency_phone: Optional[StrictStr] = Field(None, min_length=1, max_length=50)
    emergency_relationship: Optional[StrictStr] = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def emergency(self):
        values = [self.emergency_name, self.emergency_email, self.emergency_phone, self.emergency_relationship]
        if any(v is not None for v in values) and any(v is None for v in values):
            raise ValueError("Supply all four emergency-contact fields together")
        return self


class MindbodyUpdateClientConfig(_Profile):
    operation: Literal["update_client"] = _operation("update_client", "Update Client Profile (Cross Region)", "Clients")
    client_id: StrictStr = Field(..., min_length=1, max_length=200, title="Client ID")

    @model_validator(mode="after")
    def selected(self):
        if all(v is None for v in (self.first_name, self.last_name, self.email, self.mobile_phone)):
            raise ValueError("Choose at least one profile field")
        return self


class MindbodyPreferencesConfig(_Write):
    operation: Literal["update_client_preferences"] = _operation("update_client_preferences", "Update Client Preferences", "Clients")
    client_id: StrictStr = Field(..., min_length=1, max_length=200)
    active: StrictBool = Field(..., description="Explicit client active state; update can otherwise reactivate an inactive client.")
    account_emails: Optional[StrictBool] = Field(None, title="Account Emails")
    account_texts: Optional[StrictBool] = Field(None, title="Account Texts")
    promotional_emails: Optional[StrictBool] = Field(None, title="Promotional Emails")
    promotional_texts: Optional[StrictBool] = Field(None, title="Promotional Texts")
    schedule_emails: Optional[StrictBool] = Field(None, title="Schedule Emails")
    schedule_texts: Optional[StrictBool] = Field(None, title="Schedule Texts")

    @model_validator(mode="after")
    def selected(self):
        if all(getattr(self, field) is None for field in PREFERENCE_FIELDS):
            raise ValueError("Choose at least one preference; Default sends no change")
        return self


PREFERENCE_FIELDS = {"account_emails": "SendAccountEmails", "account_texts": "SendAccountTexts",
    "promotional_emails": "SendPromotionalEmails", "promotional_texts": "SendPromotionalTexts",
    "schedule_emails": "SendScheduleEmails", "schedule_texts": "SendScheduleTexts"}
MindbodyConfig = Annotated[Union[MindbodyCheckConnectionConfig, MindbodySitesConfig, MindbodyLocationsConfig,
    MindbodyStaffConfig, MindbodyClientsConfig, MindbodyGetClientConfig, MindbodyRequiredFieldsConfig,
    MindbodyClassesConfig, MindbodyAppointmentsConfig, MindbodyProgramsConfig, MindbodySessionTypesConfig,
    MindbodyCreateClientConfig, MindbodyUpdateClientConfig, MindbodyPreferencesConfig], Field(discriminator="operation")]


class MindbodyFullConfig(NodeConfig[MindbodyConfig, MindbodyAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


READS = {"list_sites": ("site/sites", "Sites"), "list_locations": ("site/locations", "Locations"),
    "list_staff": ("staff/staff", "StaffMembers"), "list_clients": ("client/clients", "Clients"),
    "get_client": ("client/clients", "Clients"), "check_connection": ("client/clients", "Clients"),
    "list_classes": ("class/classes", "Classes"), "list_appointments": ("appointment/staffappointments", "Appointments"),
    "list_programs": ("site/programs", "Programs"), "list_session_types": ("site/sessiontypes", "SessionTypes")}
# Each object is projected separately. Embedded visits, cards, notes, alerts,
# health/formula data, compensation, streaming links and arbitrary nested blobs are excluded.
FIELDS = {"Sites": ("Id", "Name", "Description"), "Locations": ("Id", "Name"),
    "StaffMembers": ("Id", "FirstName", "LastName", "DisplayName"),
    "Clients": ("Id", "UniqueId", "FirstName", "LastName", "Active", "IsProspect", "LastModifiedDateTime", *PREFERENCE_FIELDS.values()),
    "Classes": ("Id", "ClassScheduleId", "StartDateTime", "EndDateTime", "IsCanceled", "Active", "MaxCapacity", "TotalBooked"),
    "Appointments": ("Id", "Status", "StartDateTime", "EndDateTime", "Duration", "ProgramId", "SessionTypeId", "LocationId", "StaffId"),
    "Programs": ("Id", "Name", "ScheduleType"), "SessionTypes": ("Id", "Name", "ProgramId")}


def _project(item, envelope):
    if not isinstance(item, dict):
        raise ValueError("Expected a metadata object")
    if isinstance(item.get("Id"), bool) or not isinstance(item.get("Id"), (str, int)) or item["Id"] == "":
        raise ValueError("Metadata object lacks its ID")
    return {key: item[key] for key in FIELDS[envelope] if key in item and (item[key] is None or type(item[key]) in {str, int, float, bool})}


def _page(body, envelope, limit, offset):
    rows = body.get(envelope)
    page = body.get("PaginationResponse")
    if not isinstance(rows, list) or len(rows) > limit or not isinstance(page, dict):
        raise ValueError("Unexpected paginated response")
    names = ("RequestedLimit", "RequestedOffset", "PageSize", "TotalResults")
    if any(type(page.get(name)) is not int or page[name] < 0 for name in names):
        raise ValueError("Invalid pagination metadata")
    if page["RequestedLimit"] != limit or page["RequestedOffset"] != offset or page["PageSize"] != len(rows):
        raise ValueError("Pagination does not match this request")
    total = page["TotalResults"]
    if rows and total < offset + len(rows) or not rows and total > offset:
        raise ValueError("Incomplete pagination response")
    more = offset + len(rows) < total
    return {"items": [_project(row, envelope) for row in rows], "total_count": total,
        "has_more": more, "next_offset": offset + len(rows) if more else None}


def _credential_id(data: dict) -> Optional[str]:
    ids = []
    selected = data.get("credential_id")
    if selected is not None and selected != "":
        ids.append(selected)
    for scope in (data, data.get("config", {})):
        mapping = scope.get("credentialIds", {}) if isinstance(scope, dict) else {}
        if not isinstance(mapping, dict):
            raise ValueError("Credential attachment is invalid")
        for family, value in mapping.items():
            if family == "credential_type":
                continue
            if value is not None and value != "":
                if family != FAMILY:
                    raise ValueError("Attach only a Mindbody credential")
                ids.append(value)
    if not ids:
        return None
    if any(not isinstance(value, str) or "{{" in value for value in ids) or len(set(ids)) != 1:
        raise ValueError("Choose one saved Mindbody credential")
    try:
        UUID(ids[0])
    except ValueError:
        raise ValueError("Credential attachment is invalid") from None
    return ids[0]


def _guard(data: dict):
    cid = _credential_id(data)
    credentials = data.get("credentials")
    if credentials is None:
        return
    if not isinstance(credentials, dict):
        raise ValueError("Mindbody credential data is invalid")
    tag = credentials.get("credential_type", _MISSING)
    if tag is not _MISSING and tag != FAMILY:
        raise ValueError("This credential is not a Mindbody API key")
    if cid and tag is _MISSING:
        raise ValueError("Saved Mindbody credentials require their original family")


def _native_config_view(data):
    if not isinstance(data.get("config"), dict):
        return data
    # The actual save lens includes attachments and picker display labels in
    # config. Validate their original attachments before omitting UI-only keys.
    ui_keys = {"credentialIds", "staff_id__label", "location_id__label", "home_location_id__label", "program_id__label"}
    return {**data, "config": {key: value for key, value in data["config"].items() if key not in ui_keys}}


class CredentialValidationUnavailable(ValueError):
    """The saved Mindbody credential is unavailable or changed."""


class CredentialValidationUnverified(ValueError):
    """Protected Mindbody access has not been established."""


@dataclass(frozen=True)
class _MindbodyCredentialContext:
    credential_id: str
    user_id: str
    organization_id: Optional[str]
    pool: Any = field(repr=False, compare=False)
    credential: dict = field(repr=False)
    workflow_id: Optional[str] = None

    @classmethod
    async def create(cls, *, credential_id, user_id, pool, workflow_id=None):
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            org_id = await get_user_org_context(conn, user_id)
        credential = await cls._load(credential_id, user_id, pool, org_id, workflow_id)
        return cls(credential_id, user_id, org_id, pool, credential, workflow_id)

    @staticmethod
    async def _load(credential_id, user_id, pool, org_id, workflow_id):
        from utils.credentials import resolve_credential_with_owner_fallback
        credential = await resolve_credential_with_owner_fallback(
            credential_id, user_id, pool, org_id=org_id, workflow_id=workflow_id)
        if not credential or credential.get("credential_type") != FAMILY:
            raise CredentialValidationUnavailable("Credential is unavailable or access denied")
        return credential

    async def revalidate(self):
        current = await type(self).create(credential_id=self.credential_id,
            user_id=self.user_id, pool=self.pool, workflow_id=self.workflow_id)
        if current.organization_id != self.organization_id or current.credential != self.credential:
            raise CredentialValidationUnavailable("Mindbody credential changed; retry the operation")
        return current.credential

    async def load_current_credential(self):
        return await self.revalidate()


@dataclass(frozen=True)
class _LookupAuthority:
    context: _MindbodyCredentialContext


class MindbodyNode(WorkflowNode):
    integration_type = "automation-mindbody"
    credential_provider_labels = {"mindbody": "Mindbody Account"}
    connection_evidence = ConnectionEvidence(noun="Mindbody access", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return MindbodyFullConfig

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(_native_config_view(config_data))

    @classmethod
    def parse_config(cls, config_data):
        _guard(config_data)
        return super().parse_config(_native_config_view(config_data))

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_id is None:
            _guard({"credentials": credential_data})
            return credential_data
        if pool is None or user_id is None:
            raise CredentialValidationUnavailable("Trusted current lookup context required")
        context = await _MindbodyCredentialContext.create(credential_id=credential_id, user_id=user_id, pool=pool)
        current = await context.load_current_credential()
        _guard({"credentials": current, "credential_id": credential_id})
        return {**current, "_mindbody_lookup_authority": _LookupAuthority(context)}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        operations = {"location_id": "list_locations", "home_location_id": "list_locations", "staff_id": "list_staff", "program_id": "list_programs"}
        if field_name not in operations:
            raise ValueError("Unsupported Mindbody option field")
        ticket = credential_data.get("_mindbody_lookup_authority") if isinstance(credential_data, dict) else None
        if not isinstance(ticket, _LookupAuthority):
            raise CredentialValidationUnavailable("A current saved Mindbody credential is required for choices")
        authority = ticket.context
        await authority.revalidate()
        if page_token is None:
            offset = 0
        elif isinstance(page_token, str) and re.fullmatch(r"0|[1-9][0-9]{0,8}", page_token):
            offset = int(page_token)
        else:
            raise ValueError("Invalid Mindbody options offset")
        # The API has no documented name filter for these endpoints. Search is
        # applied to this bounded page, without claiming a complete search.
        from nodes.core.registry import NodeFactory
        instance = NodeFactory.create_node(node_id="mindbody-options", node_type=NODE_TYPE, node_data={"credential_id": authority.credential_id,
            "credentials": credential_data, "config": {"operation": operations[field_name], "limit": 100, "offset": offset},
            "_approval_pool": authority.pool}, user_id=authority.user_id, organization_id=authority.organization_id)
        result = await instance.run({})
        await authority.revalidate()
        if result.get("status") != "success":
            raise ValueError("Mindbody choices were not completed; check access or approval")
        options = []
        for item in result["items"]:
            label = item.get("Name") or item.get("DisplayName") or " ".join(str(item.get(part) or "") for part in ("FirstName", "LastName")).strip() or str(item["Id"])
            if search is None or str(search).casefold() in label.casefold():
                options.append({"value": str(item["Id"]), "label": label})
        return {"options": options, "next_page_token": str(result["next_offset"]) if result["has_more"] else None,
            "search_scope": "current_page"}

    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging's post-connect hook supplies only decrypted form data, without
        # the saved credential identity needed for admission. The explicit node
        # operation checks protected access through WorkflowNode.run instead.
        _guard({"credentials": credential_data})
        return {"valid": None, "message": "Run Check Protected Client Access to verify this connection."}

    async def _resolve_current_context(self, cid):
        if not self.user_id:
            raise CredentialValidationUnavailable("Trusted current user context required")
        from utils.database_pool import get_native_pool
        pool = self.node_data.get("_approval_pool") or get_native_pool()
        return await _MindbodyCredentialContext.create(credential_id=cid,
            user_id=self.user_id, pool=pool, workflow_id=self.workflow_id)

    async def _current(self):
        _guard(self.node_data)
        cid = _credential_id(self.node_data)
        if cid is None:
            if not self.config or not self.config.credentials:
                raise ValueError("Supply a Mindbody credential")
            return None, self.config.credentials
        context = await self._resolve_current_context(cid)
        raw = await context.load_current_credential()
        _guard({"credentials": raw, "credential_id": cid})
        return context, MindbodyAPIKeyCredential.model_validate(raw)

    async def _revalidate(self, context):
        await context.revalidate()
        current = await self._resolve_current_context(context.credential_id)
        if current.organization_id != context.organization_id or current.credential != context.credential:
            raise CredentialValidationUnavailable("Credential authority changed; retry validation")

    async def run(self, inputs):
        context, credentials = await self._current()
        if context is not None:
            # Nested saved attachments must reach the same native admission seam.
            self.node_data["credential_id"] = context.credential_id
        # The ticket stays task-local; a config/metadata label cannot bypass admit_node.
        token = _REQUEST_CONTEXT.set((self, context, credentials))
        try:
            result = await super().run(inputs)
            if context is not None:
                await self._revalidate(context)
            return result
        finally:
            _REQUEST_CONTEXT.reset(token)

    async def execute(self, inputs):
        ticket = _REQUEST_CONTEXT.get()
        if ticket is None or ticket[0] is not self:
            if _credential_id(self.node_data) is not None:
                return await self.run(inputs)
            # Direct execution with an unsaved credential has no stored policy
            # to admit. Saved attachments always enter WorkflowNode.run above.
            _guard(self.node_data)
            if not self.config or not self.config.credentials:
                raise ValueError("Supply a Mindbody credential")
            token = _REQUEST_CONTEXT.set((self, None, self.config.credentials))
            try:
                return await self.execute(inputs)
            finally:
                _REQUEST_CONTEXT.reset(token)
        _, context, credentials = ticket
        if context is not None:
            await self._revalidate(context)
        config = self.config.config
        operation = config.operation
        protected = operation in {"check_connection", "get_client", "list_clients", "list_appointments", "create_client", "update_client", "update_client_preferences"}
        if protected and not credentials.user_authorization:
            raise CredentialValidationUnverified("This operation requires supplied staff authorization with the business's applicable permissions")
        if credentials.user_authorization and credentials.user_expires_at and _timestamp(credentials.user_expires_at, aware=True) <= datetime.now(timezone.utc):
            raise CredentialValidationUnverified("The supplied staff token has expired; replace it before retrying")
        headers = {"Api-Key": credentials.api_key, "SiteId": str(credentials.site_id), "Accept": "application/json"}
        if credentials.user_authorization:
            headers["Authorization"] = credentials.user_authorization
        write = isinstance(config, _Write)
        output = {"operation": operation, "site_id": credentials.site_id, "staff_identity_verified": False, "ownership_verified": False}
        params, payload = {}, None
        if write:
            headers["Content-Type"] = "application/json"
            transaction = config.transaction_key or uuid4().hex
            headers["Transaction-Key"] = transaction
            output.update(transaction_key=transaction, validate_only=config.test, write_verified=False)
            if isinstance(config, MindbodyCreateClientConfig):
                path = "client/addclient"
                payload = {**config.profile(), "Test": config.test}
                if config.home_location_id is not None:
                    payload["HomeLocation"] = {"Id": config.home_location_id}
                for field, wire in {"emergency_name": "EmergencyContactInfoName", "emergency_email": "EmergencyContactInfoEmail", "emergency_phone": "EmergencyContactInfoPhone", "emergency_relationship": "EmergencyContactInfoRelationship"}.items():
                    if getattr(config, field) is not None:
                        payload[wire] = getattr(config, field)
                output["cross_region_effects_possible"] = True
            else:
                path = "client/updateclient"
                client = {"Id": config.client_id, "Active": config.active}
                if isinstance(config, MindbodyUpdateClientConfig):
                    client.update(config.profile())
                    output["cross_region_effects_possible"] = True
                else:
                    client.update({wire: getattr(config, field) for field, wire in PREFERENCE_FIELDS.items() if getattr(config, field) is not None})
                payload = {"Client": client, "Test": config.test, "CrossRegionalUpdate": False}
                output["client_id"] = config.client_id
        elif operation == "get_required_client_fields":
            path = "client/requiredclientfields"
        else:
            path, envelope = READS[operation]
            limit = config.limit if isinstance(config, _Page) else 1
            offset = config.offset if isinstance(config, _Page) else 0
            params = {"request.limit": limit, "request.offset": offset}
            if operation == "list_sites":
                params["request.siteIds"] = str(credentials.site_id)
            if isinstance(config, MindbodyStaffConfig) and config.staff_id is not None:
                params["request.staffIds"] = str(config.staff_id)
            if isinstance(config, MindbodyClientsConfig):
                params["request.includeInactive"] = str(config.include_inactive).lower()
                if config.search is not None:
                    params["request.searchText"] = config.search
                if config.is_prospect is not None:
                    params["request.isProspect"] = str(config.is_prospect).lower()
            if isinstance(config, MindbodyGetClientConfig):
                params.update({"request.clientIDs": config.client_id, "request.includeInactive": "true"})
            if isinstance(config, _Window):
                suffix = "DateTime" if isinstance(config, MindbodyClassesConfig) else "Date"
                params["request.start" + suffix] = config.start
                params["request.end" + suffix] = config.end
                for field, wire in {"location_id": "request.locationIds", "staff_id": "request.staffIds"}.items():
                    if getattr(config, field) is not None:
                        params[wire] = str(getattr(config, field))
                if isinstance(config, MindbodyClassesConfig):
                    params["request.hideCanceledClasses"] = str(config.hide_canceled).lower()
            if isinstance(config, MindbodySessionTypesConfig) and config.program_id is not None:
                params["request.programIDs"] = str(config.program_id)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("POST" if write else "GET", API_ROOT + "/" + path, headers=headers, params=params, json=payload) if write else await client.get(API_ROOT + "/" + path, headers=headers, params=params)
            if context is not None:
                await self._revalidate(context)
            output["http_status"] = response.status_code
            if response.status_code != 200:
                output.update(status="error", error=f"Mindbody request was not confirmed (HTTP {response.status_code})")
                if write:
                    output["write_outcome_unknown"] = 200 <= response.status_code < 400 or response.status_code >= 500
                retry = response.headers.get("Retry-After", "")
                if retry.isdigit() and len(retry) <= 8:
                    output["retry_after_seconds"] = int(retry)
                return output
            if len(response.content) > 2_000_000:
                raise ValueError("Response exceeds this node's 2 MB bound")
            body = response.json()
            if not isinstance(body, dict) or body.get("Error") is not None or body.get("Errors"):
                raise ValueError("Unexpected response or provider error")
            if write:
                record = body.get("Client")
                if not isinstance(record, dict):
                    raise ValueError("Missing client write response")
                if not config.test:
                    item = _project(record, "Clients")
                    if isinstance(config, (MindbodyUpdateClientConfig, MindbodyPreferencesConfig)) and item["Id"] != config.client_id:
                        raise ValueError("Write response client does not match this request")
                    output["client"] = item
                # Test mode can return a preview without a persistent ID. Do not
                # turn a validation preview into evidence of an inserted client.
                return {**output, "status": "validated" if config.test else "success", "write_outcome_unknown": False}
            if operation == "get_required_client_fields":
                fields = body.get("RequiredClientFields")
                if not isinstance(fields, list) or len(fields) > 100 or any(not isinstance(field, str) for field in fields):
                    raise ValueError("Unexpected required-field response")
                return {**output, "status": "success", "required_fields": fields}
            page = _page(body, envelope, limit, offset)
            if operation == "list_sites" and any(str(item["Id"]) != str(credentials.site_id) for item in page["items"]):
                raise ValueError("Site response crossed the saved site boundary")
            if operation == "get_client":
                if page["has_more"] or any(item["Id"] != config.client_id for item in page["items"]):
                    raise ValueError("Client response does not match the requested ID")
                return {**output, "status": "success", "found": bool(page["items"]), "client": page["items"][0] if page["items"] else None}
            if operation == "check_connection":
                return {**output, "status": "success", "protected_client_read": True, "accessible_client_count": page["total_count"], "message": "Protected client listing was accepted for this site; empty results and this response do not establish staff identity or account ownership."}
            return {**output, "status": "success", **page}
        except CredentialValidationUnavailable:
            raise
        except (httpx.HTTPError, ValueError):
            return {**output, "status": "error", "error": "Mindbody response could not be confirmed; no automatic retry was made.", **({"write_outcome_unknown": True} if write else {})}
