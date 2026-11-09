"""BatchDialer public API: explicit single-request operations using a pasted API key.

Reference: https://developer.batchdialer.com/ (public API v1).
List operations return one provider page; callers choose the next page/cursor.
Writes are never retried automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.batchdialer.com/api"


class BatchDialerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="BatchDialer API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.batchdialer.com/",
            "x-credential-instructions": "Paste your BatchDialer API key. NoClick sends it in the X-ApiKey header to app.batchdialer.com. Your active campaigns are read to check the connection."})
    credential_type: Literal["batchdialer_api_key"] = Field("batchdialer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListCampaigns(Input):
    """List active campaigns."""
    operation: Literal["list_campaigns"] = "list_campaigns"


class CampaignFilter(Input):
    contacts: list[int | None] = Field(..., min_length=2, max_length=2, description="Contact count range [minimum, maximum], from 1 to 200000.")
    search: str | None = None
    status: Literal["active", "paused", "complete", "deleted", "draft"] | None = None
    externalid: str | None = None


class SearchCampaigns(Input):
    """Search campaigns, returning one numbered page."""
    operation: Literal["search_campaigns"] = "search_campaigns"
    sortfield: Literal["campaigns.id", "name", "mode", "campaigns.status", "contacts", "newleads", "redialscount", "voicemail", "abandon", "agents", "answered", "companydnccount", "dnrcount"] = "campaigns.id"
    sortdir: Literal["asc", "desc"] = "asc"
    page: int = Field(1, ge=1)
    pagelength: int = Field(25, ge=1, le=100)
    filter: CampaignFilter | None = None


class ListContactLists(Input):
    """List the account's contact lists."""
    operation: Literal["list_contact_lists"] = "list_contact_lists"


class ListContacts(Input):
    """List one page of contacts; BatchDialer documents filters in a GET JSON body."""
    operation: Literal["list_contacts"] = "list_contacts"
    page: int = Field(1, ge=1)
    pagelength: int = Field(100, ge=1, le=100)
    dateadded: datetime | None = Field(None, description="ISO 8601 timestamp; contacts added since this time.")
    datemodified: str | None = None
    datedeleted: str | None = None
    listid: int | None = Field(None, gt=0)
    campaignid: int | None = Field(None, gt=0)
    campaignids: list[int] | None = None


class PhoneNumber(Input):
    phonenumber: str = Field(..., min_length=1, max_length=32)


class CreateContact(Input):
    """Add one contact. The provider spells mailingpostacode without the second l."""
    operation: Literal["create_contact"] = "create_contact"
    firstname: str | None = None
    lastname: str | None = None
    address: str | None = None
    city: str | None = None
    postalcode: str | None = None
    mailingaddress: str | None = None
    mailingcity: str | None = None
    mailingstate: str | None = None
    mailingpostacode: str | None = None
    email: str | None = None
    score: int | None = None
    phonenumbers: list[PhoneNumber] = Field(..., min_length=1, max_length=5)


class ImportContact(Input):
    vendorcontactid: str | None = None
    phonecode: str | None = None
    title: str | None = None
    firstname: str | None = None
    middlename: str | None = None
    lastname: str | None = None
    addressline1: str | None = None
    city: str | None = None
    state: str | None = None
    postalcode: str | None = None
    mailingaddressline1: str | None = None
    mailingcity: str | None = None
    mailingstate: str | None = None
    mailingpostalcode: str | None = None
    country: str | None = None
    gender: str | None = None
    dateofbirth: str | None = None
    email: str | None = None
    phonenumber1: str = Field(..., min_length=1, max_length=32)
    phonenumber2: str | None = None
    phonenumber3: str | None = None
    phonenumber4: str | None = None
    phonenumber5: str | None = None


class ImportContacts(Input):
    """Synchronously import contacts into explicit campaigns; inspect ids, success and warnings."""
    operation: Literal["import_contacts"] = "import_contacts"
    campaignids: list[int] = Field(..., min_length=1, max_length=100)
    contacts: list[ImportContact] = Field(..., min_length=1, max_length=1000)


class GetContact(Input):
    """Read a contact by ID."""
    operation: Literal["get_contact"] = "get_contact"
    contact_id: int = Field(..., gt=0)


class UpdateContact(Input):
    """Update the supplied contact fields with BatchDialer's PUT endpoint."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: int = Field(..., gt=0)
    vendorcontactid: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postalcode: str | None = None
    comments: str | None = None
    score: int | None = None


    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set - {"operation", "contact_id"}:
            raise ValueError("Provide at least one contact field to update")
        return self


class DeleteContact(Input):
    """Delete one contact permanently by ID."""
    operation: Literal["delete_contact"] = "delete_contact"
    contact_id: int = Field(..., gt=0)


class GetVendorContactIDs(Input):
    """Look up external vendor IDs for BatchDialer contact IDs."""
    operation: Literal["get_vendor_contact_ids"] = "get_vendor_contact_ids"
    ids: list[int] = Field(..., min_length=1, max_length=1000)


class CallFilters(Input):
    disposition: str | None = None
    callDate: datetime | None = Field(None, description="RFC 3339 call date, for example 2026-02-20T00:00:00Z.")
    direction: Literal["inbound", "outbound"] | None = None


class ListRecentCalls(CallFilters):
    """Read one page of recent calls."""
    operation: Literal["list_recent_calls"] = "list_recent_calls"
    page: int = Field(1, ge=1)
    pagelength: int = Field(100, ge=1, le=100)


class ListRecentCallsV2(CallFilters):
    """Read a cursor page; pass the response's nextPage unchanged as next_page."""
    operation: Literal["list_recent_calls_v2"] = "list_recent_calls_v2"
    next_page: str | None = None
    pagelength: int = Field(100, ge=1, le=100)


class DateRange(Input):
    from_: datetime = Field(..., alias="from", description="ISO 8601 timestamp")
    to: datetime

    @model_validator(mode="after")
    def ordered(self):
        if self.from_.tzinfo is None or self.to.tzinfo is None or self.from_ >= self.to:
            raise ValueError("Use timezone-aware timestamps with the end after the start")
        return self


class GetLeadCalls(Input):
    """Retrieve call history by external vendor contact ID."""
    operation: Literal["get_lead_calls"] = "get_lead_calls"
    vendor_contact_id: str = Field(..., min_length=1)
    date_range: DateRange | None = None
    sort_order: Literal["asc", "desc"] = "asc"


class GetTranscription(Input):
    """Read a call's JSON transcription segments."""
    operation: Literal["get_transcription"] = "get_transcription"
    cdr_id: int = Field(..., gt=0)


class GetAgentReport(Input):
    """Read agent performance with optional date, agent and campaign filters."""
    operation: Literal["get_agent_report"] = "get_agent_report"
    daterange: DateRange | None = None
    agentid: int | None = Field(None, gt=0)
    campaignid: int | None = Field(None, gt=0)


class FindAvailableNumbers(Input):
    """Find available phone numbers by state and/or area code."""
    operation: Literal["find_available_numbers"] = "find_available_numbers"
    state: str | None = Field(None, min_length=2, max_length=2)
    areacode: str | None = Field(None, pattern=r"^[0-9]{3}$")


    @model_validator(mode="after")
    def location(self):
        if not self.state and not self.areacode:
            raise ValueError("Provide a state or area code")
        return self


Operation = Annotated[Union[ListCampaigns, SearchCampaigns, ListContactLists, ListContacts,
    CreateContact, ImportContacts, GetContact, UpdateContact, DeleteContact, GetVendorContactIDs,
    ListRecentCalls, ListRecentCallsV2, GetLeadCalls, GetTranscription, GetAgentReport,
    FindAvailableNumbers], Field(discriminator="operation")]


class BatchDialerConfig(NodeConfig[Operation, BatchDialerAPIKeyCredential]):
    pass


# Every entry maps to exactly one operation in the pinned public API contract.
ROUTES = {
    "list_campaigns": ("GET", "/campaigns"),
    "search_campaigns": ("POST", "/campaigns/search"),
    "list_contact_lists": ("GET", "/lists"),
    "list_contacts": ("GET", "/contacts"),
    "create_contact": ("POST", "/contact"),
    "import_contacts": ("POST", "/contacts"),
    "get_contact": ("GET", "/contact/{contact_id}"),
    "update_contact": ("PUT", "/contact/{contact_id}"),
    "delete_contact": ("DELETE", "/contact/{contact_id}"),
    "get_vendor_contact_ids": ("GET", "/contacts/vendorcontactids"),
    "list_recent_calls": ("GET", "/cdrs"),
    "list_recent_calls_v2": ("GET", "/v2/cdrs"),
    "get_lead_calls": ("POST", "/cdrs/by-lead-id"),
    "get_transcription": ("GET", "/cdrs/{cdr_id}/transcription"),
    "get_agent_report": ("POST", "/report/public/agents"),
    "find_available_numbers": ("POST", "/dids/available"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class BatchDialerNode(WorkflowNode):
    integration_type = "automation-batchdialer"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns")

    @classmethod
    def get_config_model(cls):
        return BatchDialerConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a BatchDialer API key")
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, by_alias=True, exclude={"operation"})
        for name in ("contact_id", "cdr_id"):
            if name in values:
                path = path.replace("{" + name + "}", str(values.pop(name)))
        params = {}
        body = None
        if config.operation == "list_contacts":
            params = {k: values.pop(k) for k in ("page", "pagelength", "dateadded", "datemodified", "datedeleted") if k in values}
            body = values or None
        elif config.operation in {"list_recent_calls", "list_recent_calls_v2"}:
            params = values
        elif method in {"POST", "PUT"} or config.operation == "get_vendor_contact_ids":
            body = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"X-ApiKey": credential.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider text for definitive connection rejection, without leaking keys.
            message = _redact(response.text[:2000], credential.api_key)
            return {"status": "error", "http_status": response.status_code, "error": message or "BatchDialer rejected the request"}
        if len(response.content) > 10_000_000:
            raise ValueError("BatchDialer response exceeds 10 MB; use a smaller page")
        data = response.json()
        if isinstance(data, dict) and ((data.get("success") is False and data.get("msg")) or data.get("error")):
            return {"status": "error", "error": _redact(str(data.get("msg") or data.get("error")), credential.api_key), "data": _redact(data, credential.api_key)}
        output = {"status": "success", "data": _redact(data, credential.api_key)}
        if "X-Total-Count" in response.headers:
            output["total_count"] = response.headers["X-Total-Count"]
        await self.emit(output)
        return output
