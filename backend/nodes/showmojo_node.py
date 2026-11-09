"""ShowMojo account-token operations against the supported legacy API.

Requests map to the provider's published OpenAPI. Listing changes use scheduled
polling because Zapier's OAuth-only webhooks are reserved for Zapier.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://showmojo.com"


class ShowMojoTokenCredential(BaseModel):
    model_config = ConfigDict(title="ShowMojo API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://showmojo.com/settings/import",
            "x-credential-instructions": "Paste your account API token from ShowMojo Settings > Listing Import. Generating a new token immediately revokes the previous token. NoClick reads your listings to check the connection.",
        })
    credential_type: Literal["showmojo_api_token"] = Field("showmojo_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API token without the Authorization header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class ListingInput(Input):
    code: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    zip: str = Field(..., min_length=1)
    status: Literal["STATUS_ACTIVE", "STATUS_INACTIVE", "STATUS_DELETED"]
    unit: Optional[str] = None
    mls_id: Optional[str] = None
    title: Optional[str] = None
    rent: Optional[float] = None
    max_rent: Optional[float] = None
    bedrooms: Optional[int] = None
    full_bathrooms: Optional[int] = None
    partial_bathrooms: Optional[int] = None
    square_feet: Optional[int] = None
    highlights: Optional[str] = None
    housing_type: Optional[Literal["Apartment", "Condo", "Townhouse", "House", "Bedroom", "Commercial", "Land"]] = None
    general_type: Optional[Literal["RENT", "SALE"]] = None
    available_type: Optional[Literal["Don't show", "Immediate", "Date"]] = None
    available_date: Optional[str] = None
    security_deposit_type: Optional[Literal["DONT_SHOW", "SET_AMOUNT", "MULTIPLE_RENT", "RENT_PLUS_AMOUNT", "NO_DEPOSIT"]] = None
    security_deposit_value: Optional[float] = None
    listing_group_name: Optional[str] = None
    assign_to_property: Optional[str] = None
    images: Optional[list[str]] = None
    details: Optional[list[str]] = None


class ImportListings(Input):
    operation: Literal["import_listings"] = Field("import_listings", title="Import Listings", json_schema_extra={"ui:hidden": True})
    listings: list[ListingInput] = Field(..., min_length=1, max_length=100,
        description="Complete listing information. Matches code or address; creates if unmatched. Re-import REPLACES existing information. Wait for completion before another import.")


class ListListings(Input):
    operation: Literal["list_listings"] = Field("list_listings", title="List Listings", json_schema_extra={"ui:hidden": True})
    updated_since: Optional[str] = Field(None, description="ISO 8601 timestamp; includes changes to fields, fees and photos.")
    status: Optional[Literal["STATUS_ACTIVE", "STATUS_INACTIVE"]] = None
    fields: Optional[str] = Field(None, description="Comma-separated fields; omitted returns all fields.")
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=100)


class GetListing(Input):
    operation: Literal["get_listing"] = Field("get_listing", title="Get Listing", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", title="Listing UID")


class ListProperties(Input):
    operation: Literal["list_properties"] = Field("list_properties", title="List Properties", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=100)


class GetProperty(Input):
    operation: Literal["get_property"] = Field("get_property", title="Get Property", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", title="Property UID")


class ReportDates(Input):
    start_date: Optional[str] = Field(None, description="Account-local date: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS. Listing Performance ignores dates.")
    end_date: Optional[str] = Field(None, description="Account-local date: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.")


class NamedReport(ReportDates):
    operation: Literal["export_report_json"] = Field("export_report_json", title="Export Named Report (JSON)", json_schema_extra={"ui:hidden": True})
    report_name: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="Published report identifier, for example detailed_listing_data. Reports are not paginated.")
    acting_as_master_account: Optional[bool] = None


class NamedReportCSV(NamedReport):
    operation: Literal["export_report_csv"] = Field("export_report_csv", title="Export Named Report (CSV)", json_schema_extra={"ui:hidden": True})


class CustomReport(ReportDates):
    operation: Literal["export_custom_report_json"] = Field("export_custom_report_json", title="Export Custom Report (JSON)", json_schema_extra={"ui:hidden": True})
    report_id: int = Field(..., description="Saved custom report ID. Reports are not paginated.")


class CustomReportCSV(CustomReport):
    operation: Literal["export_custom_report_csv"] = Field("export_custom_report_csv", title="Export Custom Report (CSV)", json_schema_extra={"ui:hidden": True})


class AvailableTimes(Input):
    operation: Literal["get_available_tour_times"] = Field("get_available_tour_times", title="Get Available Tour Times", json_schema_extra={"ui:hidden": True})
    listing_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    startLocalDateTime: Optional[str] = Field(None, description="ISO 8601 date and time in the listing's local timezone.")
    endLocalDateTime: Optional[str] = None
    showing_type: Optional[Literal["in_person", "self_guided", "in_person,self_guided"]] = None


class ScreeningQuestions(Input):
    operation: Literal["get_screening_questions"] = Field("get_screening_questions", title="Get Screening Questions", json_schema_extra={"ui:hidden": True})
    listing_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class ScreeningAnswer(Input):
    question_id: int
    answer: str = Field(..., description="For options, match the provider's option text exactly.")


class ScheduleTour(Input):
    operation: Literal["schedule_tour"] = Field("schedule_tour", title="Schedule Tour", json_schema_extra={"ui:hidden": True})
    listing_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    showtime: str = Field(..., description="ISO 8601 date and time from available tour times.")
    can_contact_by_email: bool = Field(..., description="Prospect's consent to email contact.")
    can_contact_by_phone: Optional[bool] = None
    showing_type: Optional[Literal["in_person", "self_guided"]] = None
    lead_source: Optional[str] = None
    lead_id: Optional[str] = Field(None, description="Existing unscheduled lead UID; omit to create a new showing.")
    screening_answers: Optional[list[ScreeningAnswer]] = None


class OnListingChanged(PollTriggerConfigBase):
    operation: Literal["on_listing_changed"] = Field("on_listing_changed", title="New or Updated Listing",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    updated_since: Optional[str] = Field(None, description="Optional ISO 8601 lower bound. Existing results baseline when armed. Up to 10,000 listings per poll.")
    status: Optional[Literal["STATUS_ACTIVE", "STATUS_INACTIVE"]] = None


ShowMojoConfig = Annotated[Union[ImportListings, ListListings, GetListing, ListProperties,
    GetProperty, NamedReport, NamedReportCSV, CustomReport, CustomReportCSV,
    AvailableTimes, ScreeningQuestions, ScheduleTour, OnListingChanged], Field(discriminator="operation")]


class ShowMojoNodeConfig(NodeConfig[ShowMojoConfig, ShowMojoTokenCredential]):
    pass


class ShowMojoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-showmojo"
    connection_evidence = ConnectionEvidence(noun="listings", operation="list_listings", label_keys=("title", "address", "uid"))
    schedule_trigger_operations = {"on_listing_changed"}

    @classmethod
    def get_config_model(cls):
        return ShowMojoNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None, form=False, csv=False):
        headers = {"Authorization": "Token " + token, "Accept": "text/csv" if csv else "application/json"}
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params,
                    **({"data": body or {}} if form else {"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("ShowMojo request did not complete; inspect writes before retrying") from None
        if response.status_code >= 300:
            detail = response.text.replace(token, "[redacted]")[:1000]
            raise ValueError(f"ShowMojo returned HTTP {response.status_code}: {detail}")
        if csv:
            return response.text.replace(token, "[redacted]")
        try:
            data = response.json()
            # Provider error bodies may echo submitted secrets.
            def redact(value):
                if isinstance(value, str):
                    return value.replace(token, "[redacted]")
                if isinstance(value, list):
                    return [redact(item) for item in value]
                if isinstance(value, dict):
                    return {key: redact(item) for key, item in value.items()}
                return value
            if token in response.text:
                data = redact(data)
        except ValueError:
            raise ValueError("ShowMojo did not return JSON") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("ShowMojo returned an unexpected response")
        return data

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a ShowMojo account API token")
        op = self.config.config
        token = credential.api_token
        action = op.operation
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if action == "on_listing_changed":
            rows = []
            for page in range(1, 101):
                result = await self._request(token, "GET", "/api/v3/listings", params={
                    "page": page, "per_page": 100,
                    **({"updated_since": op.updated_since} if op.updated_since else {}),
                    **({"status": op.status} if op.status else {}),
                })
                if not isinstance(result, dict) or not isinstance(result.get("data"), list) or not isinstance(result.get("pagination"), dict):
                    raise ValueError("ShowMojo listing page is invalid; poll state was not advanced")
                rows.extend(result["data"])
                total_pages = result["pagination"].get("total_pages")
                if type(total_pages) is not int or total_pages < 0:
                    raise ValueError("ShowMojo pagination is invalid")
                if page >= total_pages:
                    break
            else:
                raise ValueError("More than 10,000 ShowMojo listings; narrow updated_since or status")
            if any(not isinstance(row, dict) or not row.get("uid") or not row.get("updated_at") for row in rows):
                raise ValueError("ShowMojo listing uid or updated_at missing; poll state was not advanced")
            fresh = await self._filter_unseen(rows, lambda row: str(row["uid"]) + ":" + str(row["updated_at"]))
            return {"listings": fresh, "new_or_updated_count": len(fresh)}
        if action == "import_listings":
            data = await self._request(token, "POST", "/api/v3/listings", body=values)
        elif action in {"list_listings", "list_properties"}:
            data = await self._request(token, "GET", "/api/v3/" + ("listings" if action == "list_listings" else "properties"), params=values)
        elif action in {"get_listing", "get_property"}:
            data = await self._request(token, "GET", "/api/v3/" + ("listings/" if action == "get_listing" else "properties/") + quote(values["uid"], safe=""))
        elif action.startswith("export_"):
            custom = action.startswith("export_custom_")
            report = "custom" if custom else quote(values.pop("report_name"), safe="")
            if not custom and report in {"custom", "custom.csv"}:
                raise ValueError("Use Export Custom Report for a saved custom report")
            is_csv = action.endswith("_csv")
            data = await self._request(token, "POST", "/api/v3/reports/" + report + (".csv" if is_csv else ""), body=values, form=True, csv=is_csv)
        elif action in {"get_available_tour_times", "get_screening_questions"}:
            listing_id = quote(values.pop("listing_id"), safe="")
            suffix = "available_times" if action == "get_available_tour_times" else "screening_questions"
            data = await self._request(token, "GET", "/api/v3/tours/" + listing_id + "/" + suffix, params=values)
        elif action == "schedule_tour":
            data = await self._request(token, "PUT", "/api/v3/tours/schedule", body={**values, "channel": "THIRD_PARTY"})
        else:
            raise ValueError("Unsupported ShowMojo operation")
        if isinstance(data, dict):
            if action == "schedule_tour" and data.get("success") is False:
                return {"status": "error", "success": False, "data": data}
            if action in {"get_available_tour_times", "get_screening_questions"} and data.get("errorCode"):
                return {"status": "error", "success": False, "data": data}
            if action.startswith("export_") and isinstance(data.get("response"), dict) and data["response"].get("status") == "error":
                return {"status": "error", "success": False, "data": data}
        partial_error = action == "import_listings" and isinstance(data, dict) and any(
            row.get("status") == "error" for row in data.get("response", []) if isinstance(row, dict))
        if partial_error:
            return {"status": "partial", "has_errors": True, "operation": action, "data": data}
        return {"status": "success", "success": True, "operation": action, "data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("listings") if isinstance(output, dict) else None
        if not rows:
            return None
        lines = [f"- {row.get('title') or row.get('address') or 'Listing'} at {row.get('address') or 'address unavailable'}; status {row.get('status')}; listing UID {row['uid']}; updated {row['updated_at']}" for row in rows[:20]]
        return {"text": f"ShowMojo: {len(rows)} new or updated account listing(s):\n" + "\n".join(lines), "conversation_key": None}
