"""RunSignup race automation using pasted v2 API keys.

Each operation makes one request to a fixed published API operation. Reads return
one page, preserving the provider envelope in data. Writes are never retried.
API references: https://runsignup.com/API and https://runsignup.com/API/ApiKeys
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.runsignup.com/rest"
CREDENTIAL_TYPE = "runsignup_api_key"


class RunSignupAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="RunSignup API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://runsignup.com/API/ApiKeys",
            "x-credential-instructions": "Paste your RunSignup v2 API key and matching API secret. Legacy API keys and API caller registration tokens are different credentials. NoClick sends the key in rsu_api_key and the secret in X-RSU-API-SECRET to api.runsignup.com. The key needs permission for each selected race and action; connection verification names the key's entity and does not grant permissions."})
    credential_type: Literal["runsignup_api_key"] = Field("runsignup_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste a single API credential without whitespace")
        return value


ID = Annotated[int, Field(gt=0, le=9223372036854775807)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Race(_Input):
    race_id: ID = Field(..., title="Race ID")


class _Event(_Race):
    event_id: ID = Field(..., title="Event ID")


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="One page per execution. Increment to fetch subsequent pages.")
    results_per_page: int = Field(50, ge=1, le=100, title="Results per page")


class GetAPIKeyEntity(_Input):
    operation: Literal["get_api_key_entity"] = Field("get_api_key_entity", title="Get API Key Entity", json_schema_extra={"ui:hidden": True})


class ListRaces(_Page):
    operation: Literal["list_races"] = Field("list_races", title="List Races", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=500)
    start_date: str | None = Field(None, max_length=100, description="Provider date filter; defaults to today when omitted.")
    end_date: str | None = Field(None, max_length=100)
    modified_since: str | None = Field(None, max_length=100)


class GetRace(_Race):
    operation: Literal["get_race"] = Field("get_race", title="Get Race and Events", json_schema_extra={"ui:hidden": True})


class ListParticipants(_Event, _Page):
    operation: Literal["list_participants"] = Field("list_participants", title="List Race Participants", json_schema_extra={"ui:hidden": True})
    modified_after_timestamp: str | None = Field(None, max_length=100)
    after_registration_id: ID | None = None
    search_email: str | None = Field(None, max_length=320)
    search_bib: int | None = Field(None, ge=0)


class GetParticipantCounts(_Event):
    operation: Literal["get_participant_counts"] = Field("get_participant_counts", title="Get Participant Counts", json_schema_extra={"ui:hidden": True})


class ListRemovedParticipants(_Event, _Page):
    operation: Literal["list_removed_participants"] = Field("list_removed_participants", title="List Removed Participants", json_schema_extra={"ui:hidden": True})
    modified_after_timestamp: str | None = Field(None, max_length=100)
    after_registration_id: ID | None = None


class ListDonations(_Race, _Page):
    operation: Literal["list_donations"] = Field("list_donations", title="List Race Donations", json_schema_extra={"ui:hidden": True})
    since_ts: int | None = Field(None, ge=0)
    until_ts: int | None = Field(None, ge=0)
    after_donation_id: ID | None = None


class ListFundraisers(_Race):
    operation: Literal["list_fundraisers"] = Field("list_fundraisers", title="List Race Fundraisers", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000)
    num: int = Field(50, ge=1, le=100, title="Results per page")
    modified_after_ts: int | None = Field(None, ge=0)
    after_fundraiser_id: ID | None = None


class ListTeams(_Event, _Page):
    operation: Literal["list_teams"] = Field("list_teams", title="List Race Teams", json_schema_extra={"ui:hidden": True})
    modified_since: str | None = Field(None, max_length=100)


class ListCoupons(_Race):
    operation: Literal["list_coupons"] = Field("list_coupons", title="List Race Coupons", json_schema_extra={"ui:hidden": True})
    coupon_code: str | None = Field(None, max_length=500)
    created_since: str | None = Field(None, max_length=100)


class ListResultSets(_Event):
    operation: Literal["list_result_sets"] = Field("list_result_sets", title="List Result Sets", json_schema_extra={"ui:hidden": True})


class ListResults(_Event, _Page):
    operation: Literal["list_results"] = Field("list_results", title="List Race Results", json_schema_extra={"ui:hidden": True})
    individual_result_set_id: ID | None = None
    modified_after_timestamp: str | None = Field(None, max_length=100)
    registration_id: ID | None = None
    bib_num: int | None = Field(None, ge=0)


class ListVolunteerTasks(_Race):
    operation: Literal["list_volunteer_tasks"] = Field("list_volunteer_tasks", title="List Volunteer Tasks", json_schema_extra={"ui:hidden": True})


class UpdateRaceDescription(_Race):
    operation: Literal["update_race_description"] = Field("update_race_description", title="Update Race Description", json_schema_extra={"ui:hidden": True})
    description: str = Field(..., min_length=1, max_length=100000, description="Replaces the race description; HTML is supported by RunSignup.")


def _request_document(value, root, maximum):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Enter the provider's JSON request document") from None
    if not isinstance(parsed, dict) or set(parsed) != {root}:
        raise ValueError("The JSON document must contain only " + root)
    rows = parsed[root]
    if not isinstance(rows, list) or not 1 <= len(rows) <= maximum or any(not isinstance(r, dict) or not r for r in rows):
        raise ValueError("Supply a bounded nonempty array of request objects")
    return value


class UpsertParticipants(_Event):
    operation: Literal["upsert_participants"] = Field("upsert_participants", title="Add or Edit Participants", json_schema_extra={"ui:hidden": True})
    request: str = Field(..., min_length=1, max_length=100000, title="Participant request JSON",
        description="A participants array using the provider's documented request format. Include registration_id to edit. Omitted personal fields are retained; explicit null clears them. Safe Sync restrictions and per-participant errors apply. Inspect data for individual outcomes.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    restrict_potential_dup: Literal["T", "F"] = Field("T", title="Restrict potential duplicates")
    _request = field_validator("request")(lambda v: _request_document(v, "participants", 100))


class UpsertCoupons(_Race):
    operation: Literal["upsert_coupons"] = Field("upsert_coupons", title="Add or Edit Coupons", json_schema_extra={"ui:hidden": True})
    request: str = Field(..., min_length=1, max_length=100000, title="Coupon request JSON",
        description="A coupons array in RunSignup's documented format, up to 100 coupons. Null coupon_id creates; an existing ID edits. Shared coupons cannot be edited.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    _request = field_validator("request")(lambda v: _request_document(v, "coupons", 100))


class AssignBibChip(_Event):
    operation: Literal["assign_bib_chip"] = Field("assign_bib_chip", title="Assign Bib and Chip Numbers", json_schema_extra={"ui:hidden": True})
    request: str = Field(..., min_length=1, max_length=100000, title="Assignment request JSON",
        description="An assignments array of registration_id, bib_num and chip_num objects, using the provider's JSON format.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    _request = field_validator("request")(lambda v: _request_document(v, "assignments", 100))


Operation = Annotated[Union[GetAPIKeyEntity, ListRaces, GetRace, ListParticipants, GetParticipantCounts,
    ListRemovedParticipants, ListDonations, ListFundraisers, ListTeams, ListCoupons, ListResultSets,
    ListResults, ListVolunteerTasks, UpdateRaceDescription, UpsertParticipants, UpsertCoupons, AssignBibChip], Field(discriminator="operation")]


class RunSignupNodeConfig(NodeConfig[Operation, RunSignupAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Each entry is exactly one operation in the provider's published contract.
ROUTES = {
    "get_api_key_entity": ("GET", "/v2/auth-info/entity-info.json"),
    "list_races": ("GET", "/races"),
    "get_race": ("GET", "/race/{race_id}"),
    "list_participants": ("GET", "/race/{race_id}/participants"),
    "get_participant_counts": ("GET", "/race/{race_id}/participant-counts"),
    "list_removed_participants": ("GET", "/race/{race_id}/removed-participants"),
    "list_donations": ("GET", "/race/{race_id}/donations/list"),
    "list_fundraisers": ("GET", "/v2/race-fundraisers/get-race-fundraisers.json"),
    "list_teams": ("GET", "/race/{race_id}/teams"),
    "list_coupons": ("GET", "/race/{race_id}/coupons"),
    "list_result_sets": ("GET", "/race/{race_id}/results/get-result-sets"),
    "list_results": ("GET", "/race/{race_id}/results/get-results"),
    "list_volunteer_tasks": ("GET", "/v2/volunteers/get-race-volunteer-tasks.json"),
    "update_race_description": ("POST", "/race/{race_id}/race-description"),
    "upsert_participants": ("POST", "/race/{race_id}/participants"),
    "upsert_coupons": ("POST", "/race/{race_id}/coupons"),
    "assign_bib_chip": ("POST", "/race/{race_id}/assign-bib-chip"),
}


def _safe_payload(value, secrets):
    # Provider error strings can quote request URLs; never expose either credential.
    if isinstance(value, str):
        from urllib.parse import quote, quote_plus
        for secret in secrets:
            for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
                value = value.replace(variant, "[redacted]")
        return value
    if isinstance(value, list):
        return [_safe_payload(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: _safe_payload(v, secrets) for k, v in value.items() if k.lower() not in {"api_key", "api_secret", "rsu_api_key", "x-rsu-api-secret"}}
    return value


class RunSignupNode(WorkflowNode):
    integration_type = "automation-runsignup"
    connection_evidence = ConnectionEvidence(noun="RunSignup API key entity", identity_operation="get_api_key_entity")

    @classmethod
    def get_config_model(cls):
        return RunSignupNodeConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a RunSignup v2 API key and secret")
        config = self.config.config
        params = config.model_dump(exclude_none=True)
        operation = params.pop("operation")
        method, route = ROUTES[operation]
        if "{race_id}" in route:
            route = route.format(race_id=params.pop("race_id"))
        form = None
        if method == "POST":
            keys = {"description"} if operation == "update_race_description" else {"request", "restrict_potential_dup"}
            form = {k: params.pop(k) for k in keys if k in params}
            if "request" in form:
                form["request_format"] = "json"
        params.update({"rsu_api_key": credential.api_key})
        if operation != "get_api_key_entity":
            params["format"] = "json"
        headers = {"Accept": "application/json", "X-RSU-API-SECRET": credential.api_secret}
        secrets = (credential.api_key, credential.api_secret)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route, params=params, headers=headers,
                    **({"files": {k: (None, v) for k, v in form.items()}} if form is not None else {}))
        except (httpx.HTTPError, OSError):
            raise ValueError("RunSignup request did not complete; inspect the race before retrying a write") from None
        try:
            if len(response.content) > 10 * 1024 * 1024:
                raise ValueError()
            if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError()
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ValueError("RunSignup returned an unexpected response (HTTP " + str(response.status_code) + ")") from None
        data = _safe_payload(data, secrets)
        if response.status_code != 200 or isinstance(data, dict) and (data.get("error") or data.get("error_code") or data.get("success") is False):
            message = data.get("error") if isinstance(data, dict) else None
            if isinstance(message, dict):
                message = message.get("error_msg") or message.get("message")
            raise ValueError(message if isinstance(message, str) and message else "RunSignup rejected the request (HTTP " + str(response.status_code) + ")")
        result = {"status": "success", "data": data}
        if operation == "get_api_key_entity":
            if not isinstance(data, dict) or not data.get("entity_name") or not data.get("entity_type"):
                raise ValueError("RunSignup did not identify the API key entity")
            result.update({"name": data["entity_name"], "id": data.get("entity_specific_id")})
        if isinstance(config, _Page):
            result.update({"page": config.page, "results_per_page": config.results_per_page})
        elif operation == "list_fundraisers":
            result.update({"page": config.page, "results_per_page": config.num})
        return result
