"""EveryAction 8 REST v4 operations, authenticated by an application API key.

Contract: https://docs.everyaction.com/reference/api-overview
Auth: https://docs.everyaction.com/reference/authentication
Each operation issues exactly one request. Lists return one provider page, including
its nextPageLink; the node never follows a provider-supplied URL or retries writes.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.securevan.com/v4"


class EveryActionAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="EveryAction API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.everyaction.com/docs/key-generation-and-usage",
        "x-credential-instructions": "Use an API key issued for this integration, requested through API Integrations in your CRM. Enter the assigned application name and the key without its |0 or |1 suffix; choose the database mode separately. My Campaign (1) is the usual EveryAction CRM. Available operations depend on your key's approved permissions and security tier.",
    })
    credential_type: Literal["everyaction_api_key"] = Field("everyaction_api_key", json_schema_extra={"ui:hidden": True})
    application_name: str = Field(..., min_length=1, title="Application name", description="Application name assigned with your API key.")
    api_key: str = Field(..., min_length=1, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    database_mode: Literal["1", "0"] = Field("1", title="Database mode", description="1: My Campaign / EveryAction CRM. 0: My Voters (requires permission).")

    @field_validator("application_name")
    @classmethod
    def application(cls, value):
        value = value.strip()
        if not value or any(c in value for c in ":\r\n"):
            raise ValueError("Enter the assigned application name without a colon or newline")
        return value

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or "|" in value or ":" in value:
            raise ValueError("Paste only the API key, without its |0 or |1 suffix or an Authorization header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


PersonID = Annotated[str, Field(min_length=1, pattern=r"^[0-9]+$", description="EveryAction VAN ID")]
ID = Annotated[int, Field(gt=0)]


class CheckConnection(Input):
    """Read the API key's own database, committee and user profiles."""
    operation: Literal["check_connection"] = "check_connection"


class GetPerson(Input):
    operation: Literal["get_person"] = "get_person"
    van_id: PersonID
    expand: Optional[str] = Field(None, description="Comma-separated: phones, emails, addresses, customFields, externalIds, recordedAddresses, preferences, suppressions, reportedDemographics, disclosureFieldValues.")


class FindPerson(Input):
    """Match a person by name; this POST is a read-only lookup."""
    operation: Literal["find_person"] = "find_person"
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    date_of_birth: Optional[date] = None


class FindOrCreatePerson(Input):
    """Match or create a contact using the documented name and birth-date fields."""
    operation: Literal["find_or_create_person"] = "find_or_create_person"
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    date_of_birth: Optional[date] = None


class UpdatePerson(Input):
    operation: Literal["update_person"] = "update_person"
    van_id: PersonID
    first_name: Optional[str] = Field(None, min_length=1)
    last_name: Optional[str] = Field(None, min_length=1)
    date_of_birth: Optional[date] = None

    @model_validator(mode="after")
    def has_change(self):
        if all(getattr(self, f) is None for f in ("first_name", "last_name", "date_of_birth")):
            raise ValueError("Provide at least one name or birth-date field to update")
        return self


class ListNotes(Input):
    operation: Literal["list_notes"] = "list_notes"
    van_id: PersonID


class CreateNote(Input):
    operation: Literal["create_note"] = "create_note"
    van_id: PersonID
    text: str = Field(..., min_length=1)
    is_view_restricted: bool = Field(False, description="Restrict this note to permitted users in the CRM context.")
    note_category_id: Optional[ID] = None


class UpdateNote(CreateNote):
    operation: Literal["update_note"] = "update_note"
    note_id: PersonID


class ListEvents(Input):
    """Return one event page; nextPageLink is retained in data."""
    operation: Literal["list_events"] = "list_events"
    starting_after: Optional[date] = None
    starting_before: Optional[date] = None
    event_type_ids: Optional[str] = Field(None, pattern=r"^[0-9]+(,[0-9]+)*$")
    top: int = Field(10, ge=1, le=200, description="Maximum events in this page ($top).")


class GetEvent(Input):
    operation: Literal["get_event"] = "get_event"
    event_id: ID


class ListSignups(Input):
    operation: Literal["list_signups"] = "list_signups"
    event_id: ID


class CreateSignup(Input):
    operation: Literal["create_signup"] = "create_signup"
    van_id: PersonID
    event_id: ID
    event_shift_id: ID
    role_id: ID
    status_id: ID
    location_id: Optional[ID] = None


class UpdateSignup(CreateSignup):
    operation: Literal["update_signup"] = "update_signup"
    event_signup_id: ID


class GetSignup(Input):
    operation: Literal["get_signup"] = "get_signup"
    event_signup_id: ID


class DeleteSignup(Input):
    operation: Literal["delete_signup"] = "delete_signup"
    event_signup_id: ID


class ListSavedLists(Input):
    operation: Literal["list_saved_lists"] = "list_saved_lists"
    folder_id: Optional[ID] = None


class GetSavedList(Input):
    operation: Literal["get_saved_list"] = "get_saved_list"
    saved_list_id: ID


class ListActivistCodes(Input):
    operation: Literal["list_activist_codes"] = "list_activist_codes"
    name: Optional[str] = None
    top: int = Field(200, ge=1, le=200)


class GetPersonActivistCodes(Input):
    operation: Literal["get_person_activist_codes"] = "get_person_activist_codes"
    van_id: PersonID


class ApplyCode(Input):
    """Apply an existing source code or tag to a person."""
    operation: Literal["apply_code"] = "apply_code"
    van_id: PersonID
    code_id: PersonID


class GetContribution(Input):
    operation: Literal["get_contribution"] = "get_contribution"
    contribution_id: ID


EveryActionOperation = Annotated[Union[
    CheckConnection, GetPerson, FindPerson, FindOrCreatePerson, UpdatePerson,
    ListNotes, CreateNote, UpdateNote, ListEvents, GetEvent, ListSignups,
    CreateSignup, UpdateSignup, GetSignup, DeleteSignup, ListSavedLists,
    GetSavedList, ListActivistCodes, GetPersonActivistCodes, ApplyCode, GetContribution,
], Field(discriminator="operation")]


class EveryActionNodeConfig(NodeConfig[EveryActionOperation, EveryActionAPIKeyCredential]):
    pass


def _request_parts(op):
    """Map each supported operation to one published REST operation."""
    action = op.operation
    params, body = {}, None
    if action == "check_connection":
        method, path = "GET", "/apiKeyProfiles"
    elif action in {"get_person", "update_person", "find_person", "find_or_create_person"}:
        method = "GET" if action == "get_person" else "POST"
        path = "/people/" + ("find" if action == "find_person" else "findOrCreate" if action == "find_or_create_person" else op.van_id)
        if method == "GET":
            params["$expand"] = op.expand
        else:
            body = {wire: value.isoformat() if isinstance(value, date) else value
                    for field, wire in (("first_name", "firstName"), ("last_name", "lastName"), ("date_of_birth", "dateOfBirth"))
                    if (value := getattr(op, field)) is not None}
    elif action in {"list_notes", "create_note", "update_note"}:
        method = {"list_notes": "GET", "create_note": "POST", "update_note": "PUT"}[action]
        path = f"/people/{op.van_id}/notes" + (f"/{op.note_id}" if action == "update_note" else "")
        if action != "list_notes":
            body = {"text": op.text, "isViewRestricted": op.is_view_restricted}
            if op.note_category_id is not None:
                body["category"] = {"noteCategoryId": op.note_category_id}
    elif action == "list_events":
        method, path = "GET", "/events"
        params = {"$top": op.top, "startingAfter": op.starting_after, "startingBefore": op.starting_before, "eventTypeIds": op.event_type_ids}
    elif action == "get_event":
        method, path = "GET", f"/events/{op.event_id}"
    elif action == "list_signups":
        method, path, params = "GET", "/signups", {"eventId": op.event_id}
    elif action in {"create_signup", "update_signup"}:
        method = "POST" if action == "create_signup" else "PUT"
        path = "/signups" + (f"/{op.event_signup_id}" if action == "update_signup" else "")
        body = {"person": {"vanId": op.van_id}, "event": {"eventId": op.event_id},
                "shift": {"eventShiftId": op.event_shift_id}, "role": {"roleId": op.role_id}, "status": {"statusId": op.status_id}}
        if op.location_id is not None:
            body["location"] = {"locationId": op.location_id}
        if action == "update_signup":
            body["eventSignupId"] = op.event_signup_id
    elif action in {"get_signup", "delete_signup"}:
        method, path = ("GET" if action == "get_signup" else "DELETE"), f"/signups/{op.event_signup_id}"
    elif action == "list_saved_lists":
        method, path, params = "GET", "/savedLists", {"folderId": op.folder_id}
    elif action == "get_saved_list":
        method, path = "GET", f"/savedLists/{op.saved_list_id}"
    elif action == "list_activist_codes":
        method, path, params = "GET", "/activistCodes", {"name": op.name, "$top": op.top}
    elif action == "get_person_activist_codes":
        method, path = "GET", f"/people/{op.van_id}/activistCodes"
    elif action == "apply_code":
        method, path, body = "POST", f"/people/{op.van_id}/codes", {"codeId": op.code_id}
    elif action == "get_contribution":
        method, path = "GET", f"/contributions/{op.contribution_id}"
    else:
        raise ValueError("Unsupported EveryAction operation")
    params = {k: v.isoformat() if isinstance(v, date) else v for k, v in params.items() if v is not None}
    return method, path, params, body


class EveryActionNode(WorkflowNode):
    integration_type = "automation-everyaction"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="API key profiles", label_keys=("committeeName", "databaseName", "username"))

    @classmethod
    def get_config_model(cls):
        return EveryActionNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an EveryAction API key")
        credential = self.config.credentials
        method, path, params, body = _request_parts(self.config.config)
        auth = httpx.BasicAuth(credential.application_name, f"{credential.api_key}|{credential.database_mode}")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.request(method, BASE + path, params=params, json=body, auth=auth, headers={"Accept": "application/json"})
            except httpx.RequestError:
                raise ValueError("EveryAction request could not be confirmed; inspect writes before retrying") from None
        # Keep provider error text for credential verification, but never expose the key.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        if response.status_code >= 300:
            try:
                error = response.json()
            except ValueError:
                error = "EveryAction returned a non-JSON error"
            result = {"status": "error", "http_status": response.status_code, "status_code": response.status_code, "error": redact(error)}
        else:
            try:
                data = None if response.status_code == 204 or not response.content else response.json()
            except ValueError:
                raise ValueError("EveryAction returned invalid JSON; inspect writes before retrying") from None
            if isinstance(data, dict) and data.get("errors"):
                result = {"status": "error", "http_status": response.status_code, "status_code": response.status_code, "error": redact(data["errors"])}
            else:
                result = {"status": "success", "http_status": response.status_code, "data": redact(data)}
        await self.emit(result)
        return result
