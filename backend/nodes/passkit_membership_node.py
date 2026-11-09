"""PassKit Membership REST operations, pinned to the Members 1.0-rc contract.

REST authentication: https://help.passkit.com/en/articles/5743688-using-long-lived-api-tokens
Regions: https://help.passkit.com/en/articles/10720707-sdk-and-api-configuration-settings
Lists are newline-delimited gRPC gateway result envelopes, not JSON arrays.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class PassKitMembershipTokenCredential(BaseModel):
    model_config = ConfigDict(title="PassKit Membership API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.passkit.com/en/articles/5743688-using-long-lived-api-tokens",
            "x-credential-instructions": "In your PassKit project, open Settings → Pass APIs and generate a long-lived API token. Paste the token without the Bearer prefix. This token grants full, permanent account API access; keep it private and revoke it in PassKit when no longer needed. Select your account's API region from Developer Tools → API Region. NoClick lists your membership programs to check the connection.",
        })
    credential_type: Literal["passkit_membership_api_token"] = Field("passkit_membership_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})
    region: Literal["eu", "us"] = Field("eu", title="API region", description="Europe (pub1) or United States (pub2); use the region shown in PassKit Developer Tools.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without an Authorization header or Bearer prefix")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    limit: int = Field(25, ge=1, le=1000, description="Page size. REST supports at most 1000 records; use offset for subsequent pages.")
    offset: int = Field(0, ge=0, le=2147483647)
    order_by: str | None = Field(None, max_length=100, description="PassKit field to order by, for example created.")
    order_asc: bool | None = None
    filter_field: str | None = Field(None, max_length=100, description="One optional filter field; set filter_value too.")
    filter_value: str | None = Field(None, max_length=1000)
    filter_operator: Literal["eq", "gt", "lt", "gte", "lte", "like"] = "eq"


class ListPrograms(Page):
    operation: Literal["list_programs"] = "list_programs"


class GetProgram(Input):
    operation: Literal["get_program"] = "get_program"
    program_id: Identifier


class GetEnrolmentUrl(Input):
    operation: Literal["get_enrolment_url"] = "get_enrolment_url"
    program_id: Identifier


class ListTiers(Page):
    operation: Literal["list_tiers"] = "list_tiers"
    program_id: Identifier


class GetTier(Input):
    operation: Literal["get_tier"] = "get_tier"
    program_id: Identifier
    tier_id: Identifier


class ListMembers(Page):
    operation: Literal["list_members"] = "list_members"
    program_id: Identifier


class CountMembers(Page):
    operation: Literal["count_members"] = "count_members"
    program_id: Identifier


class GetMember(Input):
    operation: Literal["get_member"] = "get_member"
    member_id: Identifier


class GetMemberByExternalId(Input):
    operation: Literal["get_member_by_external_id"] = "get_member_by_external_id"
    program_id: Identifier
    external_id: str = Field(..., min_length=1, max_length=256)

    @field_validator("external_id")
    @classmethod
    def external_identifier(cls, value):
        if value in {".", ".."}:
            raise ValueError("An external member ID cannot be a dot path segment")
        return value


class Person(Input):
    forename: str | None = None
    surname: str | None = None
    display_name: str | None = None
    email_address: str | None = None
    mobile_number: str | None = Field(None, pattern=r"^\+[0-9]+$")


class MemberDetails(Person):
    program_id: Identifier
    tier_id: Identifier
    meta_data: dict[str, str] | None = None
    opt_out: bool | None = None
    grouping_identifier: str | None = None


class EnrolMember(MemberDetails):
    """Issue a membership card. Program distribution settings may send email/SMS."""
    operation: Literal["enrol_member"] = "enrol_member"
    external_id: str | None = Field(None, max_length=256)


class UpdateMember(MemberDetails):
    """Patch supplied member fields. PassKit ignores falsey values in PATCH mode."""
    operation: Literal["update_member"] = "update_member"
    member_id: Identifier


class DeleteMember(Input):
    """Delete the selected membership record; deletion can invalidate its pass."""
    operation: Literal["delete_member"] = "delete_member"
    member_id: Identifier
    program_id: Identifier
    tier_id: Identifier


class UpdatePerson(Person):
    operation: Literal["update_person"] = "update_person"
    member_id: Identifier


class EarnPoints(Input):
    operation: Literal["earn_points"] = "earn_points"
    member_id: Identifier
    points: float = Field(..., ge=0, allow_inf_nan=False)


class BurnPoints(Input):
    operation: Literal["burn_points"] = "burn_points"
    member_id: Identifier
    points: float = Field(..., ge=0, allow_inf_nan=False)


class SetPoints(Input):
    operation: Literal["set_points"] = "set_points"
    member_id: Identifier
    points: float = Field(..., allow_inf_nan=False, description="New absolute primary point balance. Zero explicitly resets the balance.")


class ChangeTier(Input):
    operation: Literal["change_tier"] = "change_tier"
    member_id: Identifier
    tier_id: Identifier


class UpdateExpiry(Input):
    operation: Literal["update_expiry"] = "update_expiry"
    member_id: Identifier
    expiry_date: str = Field(..., description="RFC3339 expiry timestamp including timezone.", json_schema_extra={"format": "date-time"})

    @field_validator("expiry_date")
    @classmethod
    def timestamp(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or "T" not in value:
            raise ValueError("Use an RFC3339 timestamp including timezone")
        return value


class CheckIn(Input):
    operation: Literal["check_in"] = "check_in"
    member_id: Identifier
    notes: str | None = Field(None, max_length=5000)
    external_event_id: str | None = Field(None, max_length=256)


class CheckOut(Input):
    operation: Literal["check_out"] = "check_out"
    member_id: Identifier
    notes: str | None = Field(None, max_length=5000)
    external_event_id: str | None = Field(None, max_length=256)


Operation = Annotated[Union[ListPrograms, GetProgram, GetEnrolmentUrl, ListTiers, GetTier,
    ListMembers, CountMembers, GetMember, GetMemberByExternalId, EnrolMember, UpdateMember,
    DeleteMember, UpdatePerson, EarnPoints, BurnPoints, SetPoints, ChangeTier, UpdateExpiry,
    CheckIn, CheckOut], Field(discriminator="operation")]


class PassKitMembershipConfig(NodeConfig[Operation, PassKitMembershipTokenCredential]):
    pass


PERSON_FIELDS = {"forename": "forename", "surname": "surname", "display_name": "displayName",
                 "email_address": "emailAddress", "mobile_number": "mobileNumber"}


def _person(op):
    return {wire: getattr(op, name) for name, wire in PERSON_FIELDS.items() if getattr(op, name) is not None}


def _filters(op):
    result = {"limit": op.limit, "offset": op.offset}
    if op.order_by is not None:
        result["orderBy"] = op.order_by
    if op.order_asc is not None:
        result["orderAsc"] = op.order_asc
    if (op.filter_field is None) != (op.filter_value is None):
        raise ValueError("Supply both a filter field and value")
    if op.filter_field is not None:
        result["filterGroups"] = [{"condition": "AND", "fieldFilters": [{
            "filterField": op.filter_field, "filterValue": op.filter_value, "filterOperator": op.filter_operator}]}]
    return result


def request_for(op):
    """Every operation maps to one fixed method/path in the pinned contract."""
    name = op.operation
    enc = lambda value: quote(value, safe="")
    if name == "list_programs":
        return "POST", "/members/programs/list", _filters(op)
    if name in {"get_program", "get_enrolment_url"}:
        prefix = "/members/program/" if name == "get_program" else "/members/enrol/url/program/"
        return "GET", prefix + enc(op.program_id), None
    if name == "get_tier":
        return "GET", f"/members/tier/{enc(op.program_id)}/{enc(op.tier_id)}", None
    if name == "list_tiers":
        return "POST", "/members/tiers/list", {"programId": op.program_id, "filters": _filters(op)}
    if name in {"list_members", "count_members"}:
        prefix = "/members/member/list/" if name == "list_members" else "/members/count/"
        return "POST", prefix + enc(op.program_id), {"filters": _filters(op)}
    if name == "get_member":
        return "GET", "/members/member/id/" + enc(op.member_id), None
    if name == "get_member_by_external_id":
        return "GET", f"/members/member/externalId/{enc(op.program_id)}/{enc(op.external_id)}", None
    if name in {"enrol_member", "update_member", "delete_member"}:
        body = {"programId": op.program_id, "tierId": op.tier_id}
        if name != "enrol_member":
            body["id"] = op.member_id
        if name == "enrol_member" and op.external_id is not None:
            body["externalId"] = op.external_id
        if name != "delete_member":
            person = _person(op)
            if person:
                body["person"] = person
            for field, wire in [("meta_data", "metaData"), ("opt_out", "optOut"), ("grouping_identifier", "groupingIdentifier")]:
                if getattr(op, field) is not None:
                    body[wire] = getattr(op, field)
        if name == "update_member":
            body["operation"] = "OPERATION_PATCH"
        return {"enrol_member": "POST", "update_member": "PUT", "delete_member": "DELETE"}[name], "/members/member", body
    if name == "update_person":
        person = _person(op)
        if not person:
            raise ValueError("Supply at least one personal information field")
        return "PATCH", "/members/member/person", {"id": op.member_id, "person": person}
    if name in {"earn_points", "burn_points", "set_points"}:
        body = {"id": op.member_id, "points": op.points}
        if name == "set_points" and op.points == 0:
            body["resetPoints"] = True
        return "PUT", "/members/member/points/" + name.split("_")[0], body
    if name == "change_tier":
        return "PUT", "/members/member/tier", {"memberId": op.member_id, "tierId": op.tier_id}
    if name == "update_expiry":
        return "PUT", "/members/member/updateExpiry", {"id": op.member_id, "expiryDate": op.expiry_date}
    if name in {"check_in", "check_out"}:
        body = {"memberId": op.member_id}
        for field, wire in [("notes", "notes"), ("external_event_id", "externalEventId")]:
            if getattr(op, field) is not None:
                body[wire] = getattr(op, field)
        return "POST", "/members/member/" + {"check_in": "checkIn", "check_out": "checkOut"}[name], body
    raise ValueError("Unknown PassKit Membership operation")


def _error(body):
    if not isinstance(body, dict):
        raise ValueError("PassKit returned an unexpected response shape")
    error = body.get("error")
    if error and (not isinstance(error, dict) or error.get("code") not in (None, 0, "0")):
        raise ValueError("PassKit stream error: " + str(error.get("message", "request failed") if isinstance(error, dict) else error))
    if body.get("code") not in (None, 0, "0"):
        raise ValueError("PassKit error: " + str(body.get("message", "request failed")))


def parse_response(response, *, listing):
    if listing:
        items = []
        for line in response.text.splitlines():
            if not line.strip():
                continue
            envelope = json.loads(line)
            _error(envelope)
            if "result" not in envelope or not isinstance(envelope["result"], dict):
                raise ValueError("PassKit list response is missing its result envelope")
            items.append(envelope["result"])
        return items
    body = response.json()
    _error(body)
    return body


class PassKitMembershipNode(WorkflowNode):
    integration_type = "automation-passkit-membership"
    connection_evidence = ConnectionEvidence(operation="list_programs", noun="membership programs", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return PassKitMembershipConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a PassKit Membership API token")
        credential = self.config.credentials
        op = self.config.config
        method, path, body = request_for(op)
        base = {"eu": "https://api.pub1.passkit.io", "us": "https://api.pub2.passkit.io"}[credential.region]
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, base + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if response.is_error:
                raise ValueError(f"PassKit HTTP {response.status_code}: {response.text[:2000]}")
            listing = op.operation in {"list_programs", "list_tiers", "list_members"}
            data = parse_response(response, listing=listing)
        except (httpx.HTTPError, ValueError) as exc:
            # Never leak the pasted token if the upstream echoes request headers.
            raise ValueError(str(exc).replace(credential.api_token, "[redacted]")) from None
        output = {"data": data}
        if listing:
            output.update({"count": len(data), "offset": op.offset, "limit": op.limit,
                           "next_offset": op.offset + len(data) if len(data) == op.limit else None})
        await self.emit(output)
        return output
