"""Practice Better v1 client, booking, program and billing automation.

Each operation maps to one published REST operation and sends one request.
An existing Bearer access token is entered by hand; tokens are never refreshed here.
Contract: https://api-docs.practicebetter.io/swagger.json
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.practicebetter.io"
CREDENTIAL_TYPE = "practice_better_access_token"
HIDDEN = {"ui:hidden": True}
ResourceID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]


class PracticeBetterAccessToken(BaseModel):
    model_config = ConfigDict(title="Practice Better Access Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api-docs.practicebetter.io/#/operations/OAuth2_grant",
            "x-credential-instructions": "Paste an existing Practice Better access_token obtained from the documented client-credentials grant at POST /oauth2/token. Paste only the token, without Bearer. Tokens expire: replace the saved token when it expires. NoClick does not obtain or refresh tokens. The token needs read access for the connection check, plus write access for mutations; your account permissions must also allow each operation. Listing your services proves read access, not every write permission.",
        })
    credential_type: Literal["practice_better_access_token"] = Field(CREDENTIAL_TYPE, json_schema_extra=HIDDEN)
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if not isinstance(value, str) or not re.fullmatch(r"[!-~]+", value):
            raise ValueError("Paste the access token without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Fetch one page, between 1 and 100 items. The result retains count and hasMore.")
    before_id: ResourceID | None = Field(None, description="Fetch before this ID for descending lists. Use the last item's ID from the previous page.")
    after_id: ResourceID | None = Field(None, description="Fetch after this ID for ascending lists. Services and packages are rank ordered; use the provider's cursor direction.")

    @model_validator(mode="after")
    def one_cursor(self):
        if self.before_id and self.after_id:
            raise ValueError("Provide only one cursor direction")
        return self


class GetProfile(_Input):
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra=HIDDEN)


class ListClients(_Page):
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra=HIDDEN)
    details: bool = False
    modified_gte: datetime | None = None
    modified_lte: datetime | None = None


class GetClient(_Input):
    operation: Literal["get_client"] = Field("get_client", json_schema_extra=HIDDEN)
    record_id: ResourceID


class CreateClient(_Input):
    operation: Literal["create_client"] = Field("create_client", json_schema_extra=HIDDEN)
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    email_address: str = Field(..., min_length=1, max_length=320)
    mobile_phone: str | None = Field(None, max_length=20)
    send_invitation: bool = Field(False, description="Send an email inviting this client to Practice Better.")
    is_active: bool = Field(True, description="Allow the client access to the Client Portal.")
    parent_record_id: ResourceID | None = None


class ListSessions(_Page):
    operation: Literal["list_sessions"] = Field("list_sessions", json_schema_extra=HIDDEN)
    date_gte: datetime | None = None
    date_lte: datetime | None = None
    group: bool | None = None


class GetSession(_Input):
    operation: Literal["get_session"] = Field("get_session", json_schema_extra=HIDDEN)
    session_id: ResourceID


class BookSession(_Input):
    operation: Literal["book_session"] = Field("book_session", json_schema_extra=HIDDEN)
    record_id: ResourceID
    service_id: ResourceID
    service_type: Literal["face", "phone", "virtual"] = "face"
    session_date: datetime
    duration: int | None = Field(None, ge=1, description="Duration in seconds; omitted uses the service duration.")
    time_zone: str | None = Field(None, description="Windows timezone name, for example Pacific Standard Time.")
    launch_application: Literal["zoom", "system", "other"] | None = None
    notify: bool = Field(False, description="Send the client a booking confirmation.")
    ignore_conflict: bool = Field(False, description="Explicitly override conflicts in the practitioner's calendar.")
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def virtual_medium(self):
        if self.service_type == "virtual" and self.launch_application is None:
            raise ValueError("Virtual sessions require a launch application")
        if self.session_date.utcoffset() is None:
            raise ValueError("Provide a session date with a timezone offset")
        return self


class CancelSession(_Input):
    operation: Literal["cancel_session"] = Field("cancel_session", json_schema_extra=HIDDEN)
    session_id: ResourceID
    notify: bool = Field(False, description="Send this client the cancellation notification.")
    notes: str | None = Field(None, max_length=500)


class RescheduleSession(_Input):
    operation: Literal["reschedule_session"] = Field("reschedule_session", json_schema_extra=HIDDEN)
    session_id: ResourceID
    session_date: datetime = Field(..., description="New date and time with timezone offset. Clears client confirmation and may notify the client; detaches recurring sessions.")
    duration: int | None = Field(None, ge=1, description="New duration in seconds.")
    ignore_conflict: bool = False

    @field_validator("session_date")
    @classmethod
    def timezone(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Provide a session date with a timezone offset")
        return value


class DeleteSession(_Input):
    operation: Literal["delete_session"] = Field("delete_session", json_schema_extra=HIDDEN)
    session_id: ResourceID = Field(..., description="Delete this session rather than retaining a cancelled record.")


class ListServices(_Page):
    operation: Literal["list_services"] = Field("list_services", json_schema_extra=HIDDEN)


class ListPackages(_Page):
    operation: Literal["list_packages"] = Field("list_packages", json_schema_extra=HIDDEN)


class ListPrograms(_Page):
    operation: Literal["list_programs"] = Field("list_programs", json_schema_extra=HIDDEN)


class GetProgram(_Input):
    operation: Literal["get_program"] = Field("get_program", json_schema_extra=HIDDEN)
    course_id: ResourceID


class ListEnrollments(_Page):
    operation: Literal["list_enrollments"] = Field("list_enrollments", json_schema_extra=HIDDEN)
    course_id: ResourceID


class GetEnrollment(_Input):
    operation: Literal["get_enrollment"] = Field("get_enrollment", json_schema_extra=HIDDEN)
    course_id: ResourceID
    record_id: ResourceID


class RegisterClients(_Input):
    operation: Literal["register_clients"] = Field("register_clients", json_schema_extra=HIDDEN)
    course_id: ResourceID
    record_ids: list[ResourceID] = Field(..., min_length=1, max_length=20,
        description="Enroll up to 20 clients. May send the program's configured welcome email. Existing enrollments are skipped; HTTP success does not prove each client enrolled.")


class UnregisterClient(_Input):
    operation: Literal["unregister_client"] = Field("unregister_client", json_schema_extra=HIDDEN)
    course_id: ResourceID
    record_id: ResourceID


class ListTags(_Page):
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra=HIDDEN)


class GetTag(_Input):
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra=HIDDEN)
    tag_id: ResourceID


class CreateTag(_Input):
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra=HIDDEN)
    name: str = Field(..., min_length=1, max_length=50,
        description="Create or overwrite the tag matching this name, ignoring case and spaces. Only ASCII letters, digits, spaces, dot, dash and underscore are retained by the provider.")
    notes: str | None = Field(None, max_length=100)


class DeleteTag(_Input):
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra=HIDDEN)
    tag_id: ResourceID = Field(..., description="Removes the tag from related entities; tags used by team permissions cannot be deleted.")


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra=HIDDEN)
    invoicedate_gte: datetime | None = None
    invoicedate_lte: datetime | None = None


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra=HIDDEN)
    invoice_id: ResourceID


PracticeBetterOperation = Annotated[Union[
    GetProfile, ListClients, GetClient, CreateClient, ListSessions, GetSession,
    BookSession, CancelSession, RescheduleSession, DeleteSession, ListServices,
    ListPackages, ListPrograms, GetProgram, ListEnrollments, GetEnrollment,
    RegisterClients, UnregisterClient, ListTags, GetTag, CreateTag, DeleteTag,
    ListInvoices, GetInvoice,
], Field(discriminator="operation")]


class PracticeBetterConfig(NodeConfig[PracticeBetterOperation, PracticeBetterAccessToken]):
    model_config = ConfigDict(title="Practice Better Configuration", hide_input_in_errors=True)


# Fixed routes from the published v1 contract. No arbitrary URL or method inputs.
OPERATIONS = {
    "get_profile": ("GET", "/consultant/profile"),
    "list_clients": ("GET", "/consultant/records"),
    "get_client": ("GET", "/consultant/records/{record_id}"),
    "create_client": ("POST", "/consultant/records"),
    "list_sessions": ("GET", "/consultant/sessions"),
    "get_session": ("GET", "/consultant/sessions/{session_id}"),
    "book_session": ("POST", "/consultant/sessions"),
    "cancel_session": ("POST", "/consultant/sessions/{session_id}/cancel"),
    "reschedule_session": ("PUT", "/consultant/sessions/{session_id}/date"),
    "delete_session": ("DELETE", "/consultant/sessions/{session_id}"),
    "list_services": ("GET", "/consultant/services"),
    "list_packages": ("GET", "/consultant/packages"),
    "list_programs": ("GET", "/consultant/courses"),
    "get_program": ("GET", "/consultant/courses/{course_id}"),
    "list_enrollments": ("GET", "/consultant/courses/{course_id}/enrollments"),
    "get_enrollment": ("GET", "/consultant/courses/{course_id}/enrollments/{record_id}"),
    "register_clients": ("POST", "/consultant/courses/{course_id}/enrollments"),
    "unregister_client": ("DELETE", "/consultant/courses/{course_id}/enrollments"),
    "list_tags": ("GET", "/tags"),
    "get_tag": ("GET", "/tags/{tag_id}"),
    "create_tag": ("POST", "/tags"),
    "delete_tag": ("DELETE", "/tags/{tag_id}"),
    "list_invoices": ("GET", "/consultant/payments/invoices"),
    "get_invoice": ("GET", "/consultant/payments/invoices/{invoice_id}"),
}


def _request(op):
    method, route = OPERATIONS[op.operation]
    values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    route = route.format(**{key: quote(str(value), safe="") for key, value in values.items()})
    params, body = {}, None
    if isinstance(op, _Page):
        params = {k: v for k, v in values.items() if k != "course_id"}
    elif isinstance(op, CreateClient):
        profile = {"firstName": op.first_name, "lastName": op.last_name, "emailAddress": op.email_address}
        if op.mobile_phone is not None:
            profile["mobilePhone"] = op.mobile_phone
        body = {"profile": profile, "sendInvitation": op.send_invitation, "isActive": op.is_active}
        if op.parent_record_id is not None:
            body["parentRecordId"] = op.parent_record_id
    elif isinstance(op, BookSession):
        body = {"clientRecordId": op.record_id, "serviceId": op.service_id,
            "serviceType": op.service_type, "sessionDate": values["session_date"],
            "notify": op.notify, "ignoreConflict": op.ignore_conflict}
        for key, target in {"duration": "duration", "time_zone": "timeZone", "notes": "notes"}.items():
            if key in values:
                body[target] = values[key]
        if op.service_type == "virtual" and op.launch_application:
            body["telehealthSettings"] = {"launchApplication": op.launch_application}
    elif isinstance(op, CancelSession):
        body = {k: v for k, v in values.items() if k != "session_id"}
    elif isinstance(op, RescheduleSession):
        body = {"sessionDate": values["session_date"], "ignoreConflict": op.ignore_conflict}
        if op.duration is not None:
            body["duration"] = op.duration
    elif isinstance(op, RegisterClients):
        body = {"clientRecordIds": op.record_ids}
    elif isinstance(op, UnregisterClient):
        params = {"recordId": op.record_id}
    elif isinstance(op, CreateTag):
        body = values
    return method, route, params, body


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(token, "[redacted]"): _redact(v, token) for k, v in value.items()}
    return value


class PracticeBetterNode(WorkflowNode):
    integration_type = "automation-practice-better"
    connection_evidence = ConnectionEvidence(noun="services", operation="list_services",
        identity_operation="get_profile", identity_keys=("emailAddress", "id"))

    @classmethod
    def get_config_model(cls):
        return PracticeBetterConfig

    @staticmethod
    def _config_view(config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Connect a Practice Better access token")
        data = runtime_config_view(config_data, PracticeBetterConfig)
        if isinstance(data.get("config"), dict):
            data["config"] = {k: v for k, v in data["config"].items() if k != "credentialIds"}
        return data

    @classmethod
    def parse_config(cls, config_data):
        return super().parse_config(cls._config_view(config_data))

    @classmethod
    def validate_config(cls, config_data):
        try:
            data = cls._config_view(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Practice Better access token")
        token = self.config.credentials.access_token
        op = self.config.config
        method, route, params, body = _request(op)
        kwargs = {"params": params}
        if body is not None:
            kwargs["json"] = body
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("Practice Better request could not be confirmed. A write may have completed; inspect before retrying.") from None
        if not 200 <= response.status_code < 300:
            # Preserve definitive provider rejections for the shared connect verdict.
            message = _redact(response.text, token)[:2000]
            result = {"status": "error", "success": False, "http_status": response.status_code, "status_code": response.status_code,
                "error": message or f"Practice Better returned HTTP {response.status_code}"}
        else:
            data = None
            if response.content:
                try:
                    data = response.json()
                except ValueError:
                    raise ValueError("Practice Better returned an unreadable response; inspect writes before retrying.") from None
                if not isinstance(data, dict):
                    raise ValueError("Practice Better returned an unexpected response shape")
            if isinstance(op, _Page) and (not isinstance(data, dict) or not isinstance(data.get("items"), list)):
                raise ValueError("Practice Better returned an unexpected collection")
            result = {"status": "accepted" if response.status_code == 202 else "success",
                "success": True, "http_status": response.status_code, "operation": op.operation, "data": data}
            if isinstance(op, RegisterClients):
                result["enrollment_results_verified"] = False
        result = _redact(result, token)
        await self.emit(result)
        return result
