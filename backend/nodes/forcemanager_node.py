"""ForceManager (Sage Sales Management) v4 CRM operations.

Contract: https://developer.forcemanager.com/openapi.json, version 4.0.0.
A supplied session key is used only against the fixed production API origin.
Each operation makes exactly one request; pagination is explicit and zero-based.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.forcemanager.com/api/v4"


class ForcemanagerSessionKeyCredential(BaseModel):
    model_config = ConfigDict(title="ForceManager Session Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.forcemanager.com/#tag/authentication/POST/login",
            "x-credential-instructions": "Paste an existing session token from the ForceManager v4 POST /login response. Obtain it with your public API key as username and private API key as password; an admin finds these under Settings > Integrations > API key. NoClick sends the token as X-Session-Key to the production API. If it expires, obtain a new token and replace it here.",
        })
    credential_type: Literal["forcemanager_session_key"] = Field("forcemanager_session_key", json_schema_extra={"ui:hidden": True})
    session_key: str = Field(..., title="Session key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("session_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="Session key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the session key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    page: int = Field(0, ge=0, le=1000000, description="Zero-based page. Request the next page until items is empty.")
    count: int = Field(50, ge=1, le=1000, description="Maximum records per page, sent in the documented Count header.")
    where: str | None = Field(None, max_length=2000, description="Documented ForceManager SQL-style filter, e.g. name LIKE 'Acme%'.")
    order: str | None = Field(None, max_length=200, description="Attribute to order results by.")
    lang: Literal["en", "es", "pt", "it", "fr", "de", "ru"] | None = None


class _Record(_Input):
    record_id: int = Field(..., gt=0, description="Integer ID of the selected ForceManager record.")


class ListAccountsConfig(_List):
    """List Accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class GetAccountConfig(_Record):
    """Get Account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class CreateAccountConfig(_Input):
    """Create Account."""
    operation: Literal["create_account"] = Field("create_account", json_schema_extra={"ui:hidden": True})
    address1: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager address1.')
    address2: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager address2.')
    branchId: int = Field(..., description='ForceManager branch Id.')
    city: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager city.')
    comment: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comment.')
    countryId: int | None = Field(None, description='ForceManager country Id.')
    email: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager email.')
    fax: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager fax.')
    geocoded: StrictBool | None = Field(None, description='ForceManager geocoded.')
    geocodingAccuracy: int | None = Field(None, description='ForceManager geocoding Accuracy.')
    latitude: float | None = Field(None, description='ForceManager latitude.')
    longitude: float | None = Field(None, description='ForceManager longitude.')
    name: str = Field(..., min_length=1, max_length=10000, description='ForceManager name.')
    permissionLevel: int | None = Field(None, description='ForceManager permission Level.')
    phone: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager phone.')
    phone2: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager phone2.')
    phone3: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager phone3.')
    postcode: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager postcode.')
    public: StrictBool | None = Field(None, description='ForceManager public.')
    rateId: int | None = Field(None, description='ForceManager rate Id.')
    readOnly: StrictBool | None = Field(None, description='ForceManager read Only.')
    region: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager region.')
    salesRepId1: int = Field(..., description='ForceManager sales Rep Id1.')
    segmentId: int | None = Field(None, description='ForceManager segment Id.')
    statusId: int | None = Field(None, description='ForceManager status Id.')
    typeId: int | None = Field(None, description='ForceManager type Id.')
    vatNumber: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager vat Number.')
    website: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager website.')


class UpdateAccountConfig(_Record):
    """Update Account."""
    operation: Literal["update_account"] = Field("update_account", json_schema_extra={"ui:hidden": True})
    address1: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager address1.')
    phone3: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager phone3.')
    website: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager website.')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "record_id"}):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteAccountConfig(_Record):
    """Delete Account."""
    operation: Literal["delete_account"] = Field("delete_account", json_schema_extra={"ui:hidden": True})


class ListContactsConfig(_List):
    """List Contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class GetContactConfig(_Record):
    """Get Contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class CreateContactConfig(_Input):
    """Create Contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    accountId: int = Field(..., description='ForceManager account Id.')
    address1: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager address1.')
    city: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager city.')
    comment: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comment.')
    countryId: int | None = Field(None, description='ForceManager country Id.')
    email: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager email.')
    fax: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager fax.')
    firstName: str = Field(..., min_length=1, max_length=10000, description='ForceManager first Name.')
    gender: int | None = Field(None, description='ForceManager gender.')
    lastName: str = Field(..., min_length=1, max_length=10000, description='ForceManager last Name.')
    linkedin: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager linkedin.')
    permissionLevel: int | None = Field(None, description='ForceManager permission Level.')
    phone1: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager phone1.')
    phone2: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager phone2.')
    postcode: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager postcode.')
    readOnly: StrictBool | None = Field(None, description='ForceManager read Only.')
    region: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager region.')
    salesRepId: int = Field(..., description='ForceManager sales Rep Id.')
    skype: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager skype.')
    typeId: int | None = Field(None, description='ForceManager type Id.')
    birthday: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager birthday.')


class UpdateContactConfig(_Record):
    """Update Contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    address1: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager address1.')
    city: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager city.')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "record_id"}):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteContactConfig(_Record):
    """Delete Contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class ListOpportunitiesConfig(_List):
    """List Opportunities."""
    operation: Literal["list_opportunities"] = Field("list_opportunities", json_schema_extra={"ui:hidden": True})


class GetOpportunityConfig(_Record):
    """Get Opportunity."""
    operation: Literal["get_opportunity"] = Field("get_opportunity", json_schema_extra={"ui:hidden": True})


class CreateOpportunityConfig(_Input):
    """Create Opportunity."""
    operation: Literal["create_opportunity"] = Field("create_opportunity", json_schema_extra={"ui:hidden": True})
    accountId1: int | None = Field(None, description='ForceManager account Id1.')
    address1: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager address1.')
    branchId: int = Field(..., description='ForceManager branch Id.')
    city: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager city.')
    comments: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comments.')
    currencyId: int | None = Field(None, description='ForceManager currency Id.')
    geocoded: StrictBool | None = Field(None, description='ForceManager geocoded.')
    geocodingAccuracy: int | None = Field(None, description='ForceManager geocoding Accuracy.')
    latitude: float | None = Field(None, description='ForceManager latitude.')
    longitude: float | None = Field(None, description='ForceManager longitude.')
    lostDate: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager lost Date.')
    permissionLevel: int | None = Field(None, description='ForceManager permission Level.')
    postcode: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager postcode.')
    readOnly: StrictBool | None = Field(None, description='ForceManager read Only.')
    reference: str = Field(..., min_length=1, max_length=10000, description='ForceManager reference.')
    salesProbability: int = Field(..., description='ForceManager sales Probability.')
    salesRepId: int = Field(..., description='ForceManager sales Rep Id.')
    statusId: int = Field(..., description='ForceManager status Id.')
    total: int | None = Field(None, description='ForceManager total.')


class UpdateOpportunityConfig(_Record):
    """Update Opportunity."""
    operation: Literal["update_opportunity"] = Field("update_opportunity", json_schema_extra={"ui:hidden": True})
    salesProbability: int = Field(..., description='ForceManager sales Probability.')
    total: float | None = Field(None, description='ForceManager total.')
    comments: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comments.')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "record_id"}):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteOpportunityConfig(_Record):
    """Delete Opportunity."""
    operation: Literal["delete_opportunity"] = Field("delete_opportunity", json_schema_extra={"ui:hidden": True})


class ListActivitiesConfig(_List):
    """List Activities."""
    operation: Literal["list_activities"] = Field("list_activities", json_schema_extra={"ui:hidden": True})


class GetActivityConfig(_Record):
    """Get Activity."""
    operation: Literal["get_activity"] = Field("get_activity", json_schema_extra={"ui:hidden": True})


class CreateActivityConfig(_Input):
    """Create Activity."""
    operation: Literal["create_activity"] = Field("create_activity", json_schema_extra={"ui:hidden": True})
    accountId: int = Field(..., description='ForceManager account Id.')
    date: str = Field(..., min_length=1, max_length=10000, description='ForceManager date.')
    checkin: StrictBool | None = Field(None, description='ForceManager checkin.')
    checkinTypeId: int | None = Field(None, description='ForceManager checkin Type Id.')
    comment: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comment.')
    opportunityId: int | None = Field(None, description='ForceManager opportunity Id.')
    permissionLevel: int | None = Field(None, description='ForceManager permission Level.')
    salesRepId: int = Field(..., description='ForceManager sales Rep Id.')
    typeId: int = Field(..., description='ForceManager type Id.')


class UpdateActivityConfig(_Record):
    """Update Activity."""
    operation: Literal["update_activity"] = Field("update_activity", json_schema_extra={"ui:hidden": True})
    comment: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comment.')
    geocoded: StrictBool | None = Field(None, description='ForceManager geocoded.')
    geocodingAccuracy: int | None = Field(None, description='ForceManager geocoding Accuracy.')
    latitude: float | None = Field(None, description='ForceManager latitude.')
    longitude: float | None = Field(None, description='ForceManager longitude.')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "record_id"}):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteActivityConfig(_Record):
    """Delete Activity."""
    operation: Literal["delete_activity"] = Field("delete_activity", json_schema_extra={"ui:hidden": True})


class ListCalendarEventsConfig(_List):
    """List Calendar."""
    operation: Literal["list_calendar_events"] = Field("list_calendar_events", json_schema_extra={"ui:hidden": True})


class GetCalendarEventConfig(_Record):
    """Get Calendar."""
    operation: Literal["get_calendar_event"] = Field("get_calendar_event", json_schema_extra={"ui:hidden": True})


class CreateCalendarEventConfig(_Input):
    """Create Calendar."""
    operation: Literal["create_calendar_event"] = Field("create_calendar_event", json_schema_extra={"ui:hidden": True})
    accountId: int | None = Field(None, description='ForceManager account Id.')
    allDay: StrictBool | None = Field(None, description='ForceManager all Day.')
    branchId: int | None = Field(None, description='ForceManager branch Id.')
    comment: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager comment.')
    contactId: int | None = Field(None, description='ForceManager contact Id.')
    endDate: str = Field(..., min_length=1, max_length=10000, description='ForceManager end Date.')
    salesRepId: int | None = Field(None, description='ForceManager sales Rep Id.')
    sendNotification: StrictBool | None = Field(None, description='ForceManager send Notification.')
    startDate: str = Field(..., min_length=1, max_length=10000, description='ForceManager start Date.')
    startHour: str = Field(..., min_length=1, max_length=10000, description='ForceManager start Hour.')
    subject: str = Field(..., min_length=1, max_length=10000, description='ForceManager subject.')
    task: StrictBool | None = Field(None, description='ForceManager task.')
    typeId: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager type Id.')


class UpdateCalendarEventConfig(_Record):
    """Update Calendar."""
    operation: Literal["update_calendar_event"] = Field("update_calendar_event", json_schema_extra={"ui:hidden": True})
    salesRepId: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager sales Rep Id.')
    sendNotification: StrictBool | None = Field(None, description='ForceManager send Notification.')
    startDate: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager start Date.')
    startHour: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager start Hour.')
    subject: str | None = Field(None, min_length=1, max_length=10000, description='ForceManager subject.')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "record_id"}):
            raise ValueError("Provide at least one field to update")
        return self


class DeleteCalendarEventConfig(_Record):
    """Delete Calendar."""
    operation: Literal["delete_calendar_event"] = Field("delete_calendar_event", json_schema_extra={"ui:hidden": True})


OPERATIONS = {'list_accounts': ('GET', '/accounts'), 'get_account': ('GET', '/accounts/{ID}'), 'create_account': ('POST', '/accounts'), 'update_account': ('PUT', '/accounts/{ID}'), 'delete_account': ('DELETE', '/accounts/{ID}'), 'list_contacts': ('GET', '/contacts'), 'get_contact': ('GET', '/contacts/{ID}'), 'create_contact': ('POST', '/contacts'), 'update_contact': ('PUT', '/contacts/{ID}'), 'delete_contact': ('DELETE', '/contacts/{ID}'), 'list_opportunities': ('GET', '/opportunities'), 'get_opportunity': ('GET', '/opportunities/{ID}'), 'create_opportunity': ('POST', '/opportunities'), 'update_opportunity': ('PUT', '/opportunities/{ID}'), 'delete_opportunity': ('DELETE', '/opportunities/{ID}'), 'list_activities': ('GET', '/activities'), 'get_activity': ('GET', '/activities/{ID}'), 'create_activity': ('POST', '/activities'), 'update_activity': ('PUT', '/activities/{ID}'), 'delete_activity': ('DELETE', '/activities/{ID}'), 'list_calendar_events': ('GET', '/calendar'), 'get_calendar_event': ('GET', '/calendar/{ID}'), 'create_calendar_event': ('POST', '/calendar'), 'update_calendar_event': ('PUT', '/calendar/{ID}'), 'delete_calendar_event': ('DELETE', '/calendar/{ID}')}

ForcemanagerOperation = Annotated[Union[
    ListAccountsConfig,
    GetAccountConfig,
    CreateAccountConfig,
    UpdateAccountConfig,
    DeleteAccountConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    ListOpportunitiesConfig,
    GetOpportunityConfig,
    CreateOpportunityConfig,
    UpdateOpportunityConfig,
    DeleteOpportunityConfig,
    ListActivitiesConfig,
    GetActivityConfig,
    CreateActivityConfig,
    UpdateActivityConfig,
    DeleteActivityConfig,
    ListCalendarEventsConfig,
    GetCalendarEventConfig,
    CreateCalendarEventConfig,
    UpdateCalendarEventConfig,
    DeleteCalendarEventConfig
], Field(discriminator="operation")]


class ForcemanagerConfig(NodeConfig[ForcemanagerOperation, ForcemanagerSessionKeyCredential]):
    pass


class ForcemanagerNode(WorkflowNode):
    integration_type = "automation-forcemanager"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="accounts", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ForcemanagerConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a ForceManager session key")
        config = self.config.config
        credential = self.config.credentials
        method, path = OPERATIONS[config.operation]
        if "{ID}" in path:
            path = path.replace("{ID}", str(config.record_id))
        headers = {"X-Session-Key": credential.session_key, "Accept": "application/json", "Content-Type": "application/json"}
        params = {}
        body = None
        if isinstance(config, _List):
            headers["Count"] = str(config.count)
            params = {k: v for k, v in config.model_dump(exclude_none=True).items() if k in {"page", "where", "order", "lang"}}
        elif method in {"POST", "PUT"}:
            body = config.model_dump(exclude_none=True, exclude={"operation", "record_id"})
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body)
            if response.status_code != 200:
                return {**output, "status": "error", "http_status": response.status_code,
                        "error": "ForceManager rejected the request"}
            if len(response.content) > 5000000 or response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Expected a bounded JSON response")
            data = response.json()
            if isinstance(data, dict) and any(k.lower() in {"error", "errors", "errorcode"} for k in data):
                raise ValueError("ForceManager returned an error")
            if isinstance(config, _List):
                if not isinstance(data, list) or any(not isinstance(row, dict) or type(row.get("id")) is not int for row in data):
                    raise ValueError("Expected ForceManager records")
                return {**output, "status": "success", "items": data, "page": config.page,
                        "next_page": config.page + 1 if data else None}
            if method == "GET":
                if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] != config.record_id:
                    raise ValueError("Response does not identify the requested record")
                return {**output, "status": "success", "data": data}
            expected = {"POST": "entity created", "PUT": "entity updated", "DELETE": "entity deleted"}[method]
            if not isinstance(data, dict) or data.get("Message") != expected:
                raise ValueError("Missing ForceManager mutation acknowledgement")
            if method == "POST" and (type(data.get("id")) is not int or data["id"] <= 0):
                raise ValueError("Missing created record ID")
            return {**output, "status": "success", "data": data}
        except (ValueError, httpx.HTTPError, SSRFError):
            return {**output, "status": "error", "error": "ForceManager request could not be confirmed"}
