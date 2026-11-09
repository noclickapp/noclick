"""ABC GymSales API v1.1.8: fixed, single-request lead-management operations.

Contract: https://login.gymsales.net/swagger/v1/gymsales_api_swagger.json
Basic auth uses an existing account's email/password. No sign-in or token exchange.
Lists return one page and retain the provider pagination; writes are never retried.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://login.gymsales.net/api/v1"


class ABCGymSalesCredential(BaseModel):
    model_config = ConfigDict(
        title="ABC GymSales Account",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://login.gymsales.net",
            "x-credential-instructions": "Enter the email and password of your existing ABC GymSales API-enabled account. The API documents HTTP Basic authentication. NoClick sends these only to login.gymsales.net and reads your accessible companies to check the connection.",
        },
    )
    credential_type: Literal["abcgymsales_basic"] = Field(
        "abcgymsales_basic", json_schema_extra={"ui:hidden": True}
    )
    email: str = Field(
        ...,
        min_length=3,
        max_length=320,
        title="Email",
        description="Email of the ABC GymSales API account.",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="Password",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip()
        if (
            "@" not in value
            or ":" in value
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError("Enter the email of your ABC GymSales account")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListCompaniesConfig(_Input):
    """Company - List. Returns one provider page."""

    operation: Literal["list_companies"] = Field(
        "list_companies", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(
        None, min_length=1, max_length=10000, description="Filter companies by name"
    )
    status_values: list[str] | None = Field(
        None, description="Filter companies by status (eg: active, inactive, free)"
    )
    country: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Filter companies by country (eg: US, IN)",
    )
    group_ids: list[int] | None = Field(
        None, description="Filter companies by group ID (eg: 3, 38 for FLG brands)"
    )
    region: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Filter companies by reporting region (exact match on company region field)",
    )
    external_ids: list[int] | None = Field(
        None,
        description="Filter companies by external ID (integration member id). Pass multiple values to match any of them.",
    )
    page: int = Field(1, ge=1, le=1000000, description="Page Number")
    per_page: int = Field(25, ge=1, le=1000, description="Page Size")
    exclude_status_values: list[str] | None = Field(
        None,
        description="Exclude companies with the given status(es). Pass multiple values to exclude more than one. Used by the Companies - Cancel Retool app to hide already-cancelled companies (eg: in-active).",
    )
    exclude_ids: list[int] | None = Field(
        None,
        description="Exclude companies with the given IDs. Pass multiple values to exclude more than one company.",
    )
    exclude_external_service_ids: list[int] | None = Field(
        None,
        description="Exclude companies whose external_service_id matches one of the given values. Companies with no external_service_id (NULL) are always included.",
    )


class GetCompanyConfig(_Input):
    """Company - Show. Uses one documented API operation."""

    operation: Literal["get_company"] = Field(
        "get_company", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., pattern=r"^[0-9]+$", min_length=1, max_length=32, description="Company ID"
    )


class ListCompanyGroupsConfig(_Input):
    """Company Group - List. Returns one provider page."""

    operation: Literal["list_company_groups"] = Field(
        "list_company_groups", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, ge=1, le=1000000, description="Page Number")
    per_page: int = Field(25, ge=1, le=1000, description="Page Size")


class ListTagsConfig(_Input):
    """Tag - List. Returns one provider page."""

    operation: Literal["list_tags"] = Field(
        "list_tags", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Filter tags by name (case-insensitive partial match)",
    )
    page: int = Field(1, ge=1, le=1000000, description="Page Number")
    per_page: int = Field(25, ge=1, le=1000, description="Page Size")


class SearchPeopleConfig(_Input):
    """Person - Search. Returns one provider page."""

    operation: Literal["search_people"] = Field(
        "search_people", json_schema_extra={"ui:hidden": True}
    )
    all_matches: bool | None = Field(
        None, description="Return all matches (array) instead of a single best match"
    )
    company_id: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Company ID to search within (ignored if all_locations=true)",
    )
    first_name: str | None = Field(
        None, min_length=1, max_length=10000, description="First name of the person"
    )
    last_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Last name of the person"
    )
    full_name: str | None = Field(
        None, min_length=1, max_length=10000, description="full_name"
    )
    phone_home: str | None = Field(
        None, min_length=1, max_length=10000, description="Phone home of the person"
    )
    phone_mobile: str | None = Field(
        None, min_length=1, max_length=10000, description="Phone mobile of the person"
    )
    email: str | None = Field(
        None, min_length=1, max_length=10000, description="Email address of the person"
    )
    all_locations: bool | None = Field(
        None, description="Search across all locations the current user belongs to"
    )


class FuzzySearchPeopleConfig(_Input):
    """Person - Fuzzy. Returns one provider page."""

    operation: Literal["fuzzy_search_people"] = Field(
        "fuzzy_search_people", json_schema_extra={"ui:hidden": True}
    )
    company_id: str | None = Field(
        None, min_length=1, max_length=10000, description="Company ID to search within"
    )
    first_name: str | None = Field(
        None, min_length=1, max_length=10000, description="First name of the person"
    )
    last_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Last name of the person"
    )
    full_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Full name of the person"
    )
    phone_home: str | None = Field(
        None, min_length=1, max_length=10000, description="Phone home of the person"
    )
    phone_mobile: str | None = Field(
        None, min_length=1, max_length=10000, description="Phone mobile of the person"
    )
    email: str | None = Field(
        None, min_length=1, max_length=10000, description="Email address of the person"
    )
    page: int = Field(1, ge=1, le=1000000, description="Page Number")
    per_page: int = Field(25, ge=1, le=1000, description="Page Size")


class GetPersonConfig(_Input):
    """People - Show. Uses one documented API operation."""

    operation: Literal["get_person"] = Field(
        "get_person", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ...,
        pattern=r"^[0-9]+$",
        min_length=1,
        max_length=32,
        description="GymSales Person ID",
    )
    abcfin_company_id: bool | None = Field(
        None, description="Parameter to include abcfin company id of the person"
    )


class CreatePersonConfig(_Input):
    """People - Create. Uses one documented API operation."""

    operation: Literal["create_person"] = Field(
        "create_person", json_schema_extra={"ui:hidden": True}
    )
    company_id: str = Field(
        ..., min_length=1, max_length=10000, description="GymSales Company ID"
    )
    first_name: str = Field(
        ..., min_length=1, max_length=10000, description="Persons First Name"
    )
    external_id: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="The unique identifier for the person in your system. \n Warning: The external service must be configured for the club before using this parameter.",
    )
    last_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Persons Last Name"
    )
    address: str | None = Field(
        None, min_length=1, max_length=10000, description="Address"
    )
    city: str | None = Field(None, min_length=1, max_length=10000, description="City")
    state: str | None = Field(None, min_length=1, max_length=10000, description="State")
    zip: str | None = Field(
        None, min_length=1, max_length=10000, description="Zip / Postal Code"
    )
    phone_home: str | None = Field(
        None, min_length=1, max_length=10000, description="Home Phone"
    )
    phone_mobile: str | None = Field(
        None, min_length=1, max_length=10000, description="Mobile Phone"
    )
    phone_work: str | None = Field(
        None, min_length=1, max_length=10000, description="Work Phone"
    )
    email: str | None = Field(
        None, min_length=1, max_length=10000, description="Email Address"
    )
    tag_list: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Pass in a comma separated list of tags for the person",
    )
    contact_method_name: Literal[
        "Referral",
        "Internet",
        "Walk In",
        "Guest Visit",
        "Phone-in",
        "Outreach",
        "Former Member",
        "Corporate",
        "Renewal",
        "Events",
        "Other",
    ] | None = Field(
        None, description="Contact Method (which channel did the lead come through)"
    )
    source_name: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Marketing Source (If it exists in GymSales already we'll link to existing marketing source. If it does not exist, we'll create a new source.",
    )
    notes: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Notes to be added to the person",
    )
    gender: Literal["M", "F"] | None = Field(None, description="gender")
    birthday: date | None = Field(None, description="birthday")
    referred_by_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Full name of Referral"
    )
    referred_by_phone: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Mobile phone number of Referral",
    )
    referred_by_email: str | None = Field(
        None, min_length=1, max_length=10000, description="Email address of Referral"
    )
    sms_opted_out: bool | None = Field(
        None, description="Person is opted out of receiving SMS. Can be empty"
    )
    email_opted_out: bool | None = Field(
        None, description="Person is opted out of receiving e-mail. Can be empty"
    )
    salesperson_name: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="The full name or email of the sale person. Requires more than 3 characters. Can be empty",
    )
    interested_in_joining: bool | None = Field(
        None, description="Person is interested in joining"
    )
    new_visitor: bool | None = Field(None, description="new_visitor")
    status: Literal[
        "enquiry", "tour", "trial", "sale", "not_interested", "former_member", "guest"
    ] | None = Field(None, description="Person status")
    full_name: str | None = Field(
        None, min_length=1, max_length=10000, description="full_name"
    )
    created_at: datetime | None = Field(None, description="created_at")
    marketing_external_id: int | None = Field(None, description="marketing_external_id")
    salesperson_id: str | None = Field(
        None, min_length=1, max_length=10000, description="salesperson_id"
    )
    do_not_export: bool | None = Field(None, description="do_not_export")
    skip_automated_items: bool | None = Field(None, description="skip_automated_items")
    skip_create_appointments: bool | None = Field(
        None, description="skip_create_appointments"
    )
    check_dups: str | None = Field(
        None, min_length=1, max_length=10000, description="check_dups"
    )
    skip_dups: str | None = Field(
        None, min_length=1, max_length=10000, description="skip_dups"
    )
    outcome: str | None = Field(
        None, min_length=1, max_length=10000, description="outcome"
    )
    jonas_i4_export_sync: str | None = Field(
        None, min_length=1, max_length=10000, description="jonas_i4_export_sync"
    )
    membership_type: str | None = Field(
        None, min_length=1, max_length=10000, description="membership_type"
    )
    sales_amount: str | None = Field(
        None, min_length=1, max_length=10000, description="sales_amount"
    )
    membership_term: str | None = Field(
        None, min_length=1, max_length=10000, description="membership_term"
    )
    whatsapp_opted_out: bool | None = Field(
        None,
        description="Person is opted out of receiving WhatsApp messages. Can be empty",
    )
    do_not_call: bool | None = Field(
        None, description="Person has opted out of receiving phone calls. Can be empty"
    )


class UpdatePersonConfig(_Input):
    """People - Update. Uses one documented API operation."""

    operation: Literal["update_person"] = Field(
        "update_person", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., pattern=r"^[0-9]+$", min_length=1, max_length=32, description="Person's ID"
    )
    first_name: str = Field(
        ..., min_length=1, max_length=10000, description="Persons First Name"
    )
    company_id: str = Field(
        ..., min_length=1, max_length=10000, description="GymSales Company ID"
    )
    external_id: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="This is the Unique Identifier of the person from your system",
    )
    last_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Persons Last Name"
    )
    address: str | None = Field(
        None, min_length=1, max_length=10000, description="Address"
    )
    city: str | None = Field(None, min_length=1, max_length=10000, description="City")
    state: str | None = Field(None, min_length=1, max_length=10000, description="State")
    zip: str | None = Field(
        None, min_length=1, max_length=10000, description="Zip / Postal Code"
    )
    phone_home: str | None = Field(
        None, min_length=1, max_length=10000, description="Home Phone"
    )
    phone_mobile: str | None = Field(
        None, min_length=1, max_length=10000, description="Mobile Phone"
    )
    phone_work: str | None = Field(
        None, min_length=1, max_length=10000, description="Work Phone"
    )
    email: str | None = Field(
        None, min_length=1, max_length=10000, description="Email Address"
    )
    tag_list: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Pass in a comma separated list of tags for the person",
    )
    contact_method_name: Literal[
        "Referrals",
        "Internet",
        "Walk In",
        "Guest Register",
        "Phone-in",
        "Outreach",
        "Ex Member",
        "Corporate",
        "Other",
    ] | None = Field(
        None, description="Contact Method (which channel did the lead come through)"
    )
    source_name: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Marketing Source (If it exists in GymSales already we'll link to existing marketing source. If it does not exist, we'll create a new source.",
    )
    notes: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Notes to be added to the person",
    )
    gender: Literal["M", "F"] | None = Field(None, description="gender")
    birthday: date | None = Field(None, description="birthday")
    referred_by_name: str | None = Field(
        None, min_length=1, max_length=10000, description="Full name of Referral"
    )
    referred_by_phone: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="Mobile phone number of Referral",
    )
    referred_by_email: str | None = Field(
        None, min_length=1, max_length=10000, description="Email address of Referral"
    )
    status: Literal[
        "enquiry", "tour", "trial", "sale", "not_interested", "former_member", "guest"
    ] | None = Field(None, description="Person status")
    sms_opted_out: bool | None = Field(
        None, description="Person is opted out of receiving SMS. Can be empty"
    )
    email_opted_out: bool | None = Field(
        None, description="Person is opted out of receiving e-mail. Can be empty"
    )
    do_not_call: bool | None = Field(
        None, description="Person is opted out of receiving Calls. Can be empty"
    )
    salesperson_name: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="The full name or email of the sale person. Requires more than 3 characters. Can be empty",
    )
    interested_in_joining: bool | None = Field(
        None, description="Person is interested in joining"
    )
    new_visitor: bool | None = Field(None, description="new_visitor")
    full_name: str | None = Field(
        None, min_length=1, max_length=10000, description="full_name"
    )
    created_at: datetime | None = Field(None, description="created_at")
    marketing_external_id: int | None = Field(None, description="marketing_external_id")
    salesperson_id: int | None = Field(None, description="salesperson_id")
    do_not_export: bool | None = Field(None, description="do_not_export")
    outcome: str | None = Field(
        None, min_length=1, max_length=10000, description="outcome"
    )
    membership_type: str | None = Field(
        None, min_length=1, max_length=10000, description="membership_type"
    )
    sales_amount: str | None = Field(
        None, min_length=1, max_length=10000, description="sales_amount"
    )
    membership_term: str | None = Field(
        None, min_length=1, max_length=10000, description="membership_term"
    )
    whatsapp_opted_out: bool | None = Field(
        None,
        description="Person is opted out of receiving whatsapp messages. Can be empty",
    )


class ListNotesConfig(_Input):
    """Note - List. Returns one provider page."""

    operation: Literal["list_notes"] = Field(
        "list_notes", json_schema_extra={"ui:hidden": True}
    )
    person_id: str = Field(
        ...,
        pattern=r"^[0-9]+$",
        min_length=1,
        max_length=32,
        description="Gymsales Person ID",
    )
    page: str = Field("1", max_length=10000, description="Page Number to return")
    per_page: str = Field(
        "25",
        max_length=10000,
        description="Number of records to be returned per page. Leave this blank to return all notes.",
    )


class CreateNoteConfig(_Input):
    """Note -  create. Uses one documented API operation."""

    operation: Literal["create_note"] = Field(
        "create_note", json_schema_extra={"ui:hidden": True}
    )
    person_id: str = Field(
        ..., pattern=r"^[0-9]+$", min_length=1, max_length=32, description="Person ID"
    )
    description: str = Field(
        ..., min_length=1, max_length=10000, description="description"
    )
    created_at: datetime | None = Field(None, description="created_at")


class ListActivitiesConfig(_Input):
    """Person - Get Activities. Returns one provider page."""

    operation: Literal["list_activities"] = Field(
        "list_activities", json_schema_extra={"ui:hidden": True}
    )
    person_id: str = Field(
        ...,
        pattern=r"^[0-9]+$",
        min_length=1,
        max_length=32,
        description="id of the person record to retrieve the activities",
    )
    complete: bool | None = Field(
        None,
        description="parameter to filter the records based on complete - true/false",
    )
    page: str = Field("1", max_length=10000, description="Page Number to return")
    per_page: str = Field(
        "25",
        max_length=10000,
        description="Number of records to be returned per page. Leaving this blank will return first 1000 activities.",
    )


class CreateActivityConfig(_Input):
    """Person - Create Event. Uses one documented API operation."""

    operation: Literal["create_activity"] = Field(
        "create_activity", json_schema_extra={"ui:hidden": True}
    )
    person_id: str = Field(
        ...,
        pattern=r"^[0-9]+$",
        min_length=1,
        max_length=32,
        description="id of person record that will have the appt",
    )
    type: Literal["Task", "Event"] = Field(
        ...,
        description="Task or Event - you would want to use Event for\xa0appointments",
    )
    kind_code: Literal["tour", "walk-in", "non-sales-appointment"] = Field(
        ..., description="tour,\xa0walk-in, or\xa0non-sales-appointment"
    )
    start: datetime = Field(..., description="UTC start time of the event")
    complete: bool | None = Field(
        None, description="only use if the event has already been completed"
    )
    duration: int | None = Field(
        None,
        description="duration of event, if left blank it will default to 60 mins or whatever the company's defined default value is",
    )
    name: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="label/description of the event",
    )
    outcome: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        description="no_sale,\xa0no_show,\xa0sale,\xa0trial\xa0 only use if the event has already been completed",
    )
    created_at: datetime | None = Field(None, description="created_at")
    description: str | None = Field(
        None, min_length=1, max_length=10000, description="description"
    )
    completed_at: datetime | None = Field(
        None,
        description="UTC completed time of the event - optional when was the outcome set",
    )


class ListExternalDuplicatesConfig(_Input):
    """Person - Get External Duplicates. Returns one provider page."""

    operation: Literal["list_external_duplicates"] = Field(
        "list_external_duplicates", json_schema_extra={"ui:hidden": True}
    )
    person_id: str = Field(
        ...,
        pattern=r"^[0-9]+$",
        min_length=1,
        max_length=32,
        description="ID of the person record to retrieve the external duplicates",
    )
    page: int = Field(1, ge=1, le=1000000, description="Page Number to return")
    per_page: int = Field(
        25,
        ge=1,
        le=1000,
        description="Number of records to be returned per page. Leaving this blank will return first 1000 external duplicates.",
    )


class AddTagConfig(_Input):
    """Person - Add Tag. Uses one documented API operation."""

    operation: Literal["add_tag"] = Field(
        "add_tag", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., pattern=r"^[0-9]+$", min_length=1, max_length=32, description="ID"
    )
    tag_name: str = Field(..., min_length=1, max_length=10000, description="tag_name")


class RemoveTagConfig(_Input):
    """Person - Remove Tag. Uses one documented API operation."""

    operation: Literal["remove_tag"] = Field(
        "remove_tag", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., pattern=r"^[0-9]+$", min_length=1, max_length=32, description="ID"
    )
    tag_name: str = Field(..., min_length=1, max_length=10000, description="tag_name")


class EmailOptOutConfig(_Input):
    """Person - Email Opt Out. Uses one documented API operation."""

    operation: Literal["email_opt_out"] = Field(
        "email_opt_out", json_schema_extra={"ui:hidden": True}
    )
    email: str = Field(..., min_length=1, max_length=10000, description="email")
    company_id: int = Field(..., description="company_id")


class SmsOptOutConfig(_Input):
    """Person - Sms Opt Out. Uses one documented API operation."""

    operation: Literal["sms_opt_out"] = Field(
        "sms_opt_out", json_schema_extra={"ui:hidden": True}
    )
    phone_mobile: str = Field(
        ..., min_length=1, max_length=10000, description="phone_mobile"
    )
    company_id: int = Field(..., description="company_id")


class SetDoNotCallConfig(_Input):
    """Person - Do Not Call. Uses one documented API operation."""

    operation: Literal["set_do_not_call"] = Field(
        "set_do_not_call", json_schema_extra={"ui:hidden": True}
    )
    person_id: str = Field(
        ..., min_length=1, max_length=10000, description="ID of the person"
    )
    do_not_call: bool = Field(..., description="Boolean flag to set/unset do_not_call")


class ExtendTrialConfig(_Input):
    """Person - Extend Trial. Uses one documented API operation."""

    operation: Literal["extend_trial"] = Field(
        "extend_trial", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., pattern=r"^[0-9]+$", min_length=1, max_length=32, description="ID"
    )
    trial_end_at: datetime = Field(..., description="trial_end_at")


class GetSalespersonReportConfig(_Input):
    """Reports - Salesperson. Uses one documented API operation."""

    operation: Literal["get_salesperson_report"] = Field(
        "get_salesperson_report", json_schema_extra={"ui:hidden": True}
    )
    date_from: date | None = Field(None, description="date_from")
    date_into: datetime | None = Field(None, description="date_into")
    report_type: Literal[
        "single_club",
        "multi_club_detail",
        "multi_club_summary",
        "multi_club_salesperson",
    ] | None = Field(None, description="Report Type")


GymSalesOperation = Annotated[
    Union[
        ListCompaniesConfig,
        GetCompanyConfig,
        ListCompanyGroupsConfig,
        ListTagsConfig,
        SearchPeopleConfig,
        FuzzySearchPeopleConfig,
        GetPersonConfig,
        CreatePersonConfig,
        UpdatePersonConfig,
        ListNotesConfig,
        CreateNoteConfig,
        ListActivitiesConfig,
        CreateActivityConfig,
        ListExternalDuplicatesConfig,
        AddTagConfig,
        RemoveTagConfig,
        EmailOptOutConfig,
        SmsOptOutConfig,
        SetDoNotCallConfig,
        ExtendTrialConfig,
        GetSalespersonReportConfig,
    ],
    Field(discriminator="operation"),
]


class ABCGymSalesFullConfig(NodeConfig[GymSalesOperation, ABCGymSalesCredential]):
    pass


ROUTES = {
    "list_companies": {
        "method": "GET",
        "path": "/companies/",
        "path_fields": {},
        "query_fields": {
            "name": "name",
            "status_values": "status[]",
            "country": "country",
            "group_ids": "group_id[]",
            "region": "region",
            "external_ids": "external_id[]",
            "page": "page",
            "per_page": "per_page",
            "exclude_status_values": "exclude_status[]",
            "exclude_ids": "exclude_ids[]",
            "exclude_external_service_ids": "exclude_external_service_id[]",
        },
        "form_fields": {},
    },
    "get_company": {
        "method": "GET",
        "path": "/companies/{id}",
        "path_fields": {"id": "id"},
        "query_fields": {},
        "form_fields": {},
    },
    "list_company_groups": {
        "method": "GET",
        "path": "/company_groups",
        "path_fields": {},
        "query_fields": {"page": "page", "per_page": "per_page"},
        "form_fields": {},
    },
    "list_tags": {
        "method": "GET",
        "path": "/tags",
        "path_fields": {},
        "query_fields": {"name": "name", "page": "page", "per_page": "per_page"},
        "form_fields": {},
    },
    "search_people": {
        "method": "GET",
        "path": "/people/search",
        "path_fields": {},
        "query_fields": {
            "all_matches": "all_matches",
            "company_id": "company_id",
            "first_name": "first_name",
            "last_name": "last_name",
            "full_name": "full_name",
            "phone_home": "phone_home",
            "phone_mobile": "phone_mobile",
            "email": "email",
            "all_locations": "all_locations",
        },
        "form_fields": {},
    },
    "fuzzy_search_people": {
        "method": "GET",
        "path": "/people/fuzzy",
        "path_fields": {},
        "query_fields": {
            "company_id": "company_id",
            "first_name": "first_name",
            "last_name": "last_name",
            "full_name": "full_name",
            "phone_home": "phone_home",
            "phone_mobile": "phone_mobile",
            "email": "email",
            "page": "page",
            "per_page": "per_page",
        },
        "form_fields": {},
    },
    "get_person": {
        "method": "GET",
        "path": "/people/{id}",
        "path_fields": {"id": "id"},
        "query_fields": {"abcfin_company_id": "abcfin_company_id"},
        "form_fields": {},
    },
    "create_person": {
        "method": "POST",
        "path": "/people",
        "path_fields": {},
        "query_fields": {},
        "form_fields": {
            "company_id": "company_id",
            "first_name": "first_name",
            "external_id": "external_id",
            "last_name": "last_name",
            "address": "address",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "phone_home": "phone_home",
            "phone_mobile": "phone_mobile",
            "phone_work": "phone_work",
            "email": "email",
            "tag_list": "tag_list",
            "contact_method_name": "contact_method_name",
            "source_name": "source_name",
            "notes": "notes",
            "gender": "gender",
            "birthday": "birthday",
            "referred_by_name": "referred_by_name",
            "referred_by_phone": "referred_by_phone",
            "referred_by_email": "referred_by_email",
            "sms_opted_out": "sms_opted_out",
            "email_opted_out": "email_opted_out",
            "salesperson_name": "salesperson_name",
            "interested_in_joining": "interested_in_joining",
            "new_visitor": "new_visitor",
            "status": "status",
            "full_name": "full_name",
            "created_at": "created_at",
            "marketing_external_id": "marketing_external_id",
            "salesperson_id": "salesperson_id",
            "do_not_export": "do_not_export",
            "skip_automated_items": "skip_automated_items",
            "skip_create_appointments": "skip_create_appointments",
            "check_dups": "check_dups",
            "skip_dups": "skip_dups",
            "outcome": "outcome",
            "jonas_i4_export_sync": "jonas_i4_export_sync",
            "membership_type": "membership_type",
            "sales_amount": "sales_amount",
            "membership_term": "membership_term",
            "whatsapp_opted_out": "whatsapp_opted_out",
            "do_not_call": "do_not_call",
        },
    },
    "update_person": {
        "method": "PUT",
        "path": "/people/{id}",
        "path_fields": {"id": "id"},
        "query_fields": {},
        "form_fields": {
            "first_name": "first_name",
            "company_id": "company_id",
            "external_id": "external_id",
            "last_name": "last_name",
            "address": "address",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "phone_home": "phone_home",
            "phone_mobile": "phone_mobile",
            "phone_work": "phone_work",
            "email": "email",
            "tag_list": "tag_list",
            "contact_method_name": "contact_method_name",
            "source_name": "source_name",
            "notes": "notes",
            "gender": "gender",
            "birthday": "birthday",
            "referred_by_name": "referred_by_name",
            "referred_by_phone": "referred_by_phone",
            "referred_by_email": "referred_by_email",
            "status": "status",
            "sms_opted_out": "sms_opted_out",
            "email_opted_out": "email_opted_out",
            "do_not_call": "do_not_call",
            "salesperson_name": "salesperson_name",
            "interested_in_joining": "interested_in_joining",
            "new_visitor": "new_visitor",
            "full_name": "full_name",
            "created_at": "created_at",
            "marketing_external_id": "marketing_external_id",
            "salesperson_id": "salesperson_id",
            "do_not_export": "do_not_export",
            "outcome": "outcome",
            "membership_type": "membership_type",
            "sales_amount": "sales_amount",
            "membership_term": "membership_term",
            "whatsapp_opted_out": "whatsapp_opted_out",
        },
    },
    "list_notes": {
        "method": "GET",
        "path": "/people/{person_id}/notes",
        "path_fields": {"person_id": "person_id"},
        "query_fields": {"page": "page", "per_page": "per_page"},
        "form_fields": {},
    },
    "create_note": {
        "method": "POST",
        "path": "/people/{person_id}/notes",
        "path_fields": {"person_id": "person_id"},
        "query_fields": {},
        "form_fields": {"description": "description", "created_at": "created_at"},
    },
    "list_activities": {
        "method": "GET",
        "path": "/people/{person_id}/activities",
        "path_fields": {"person_id": "person_id"},
        "query_fields": {
            "complete": "complete",
            "page": "page",
            "per_page": "per_page",
        },
        "form_fields": {},
    },
    "create_activity": {
        "method": "POST",
        "path": "/people/{person_id}/activities",
        "path_fields": {"person_id": "person_id"},
        "query_fields": {},
        "form_fields": {
            "type": "type",
            "kind_code": "kind_code",
            "start": "start",
            "complete": "complete",
            "duration": "duration",
            "name": "name",
            "outcome": "outcome",
            "created_at": "created_at",
            "description": "description",
            "completed_at": "completed_at",
        },
    },
    "list_external_duplicates": {
        "method": "GET",
        "path": "/people/{person_id}/external_duplicates",
        "path_fields": {"person_id": "person_id"},
        "query_fields": {"page": "page", "per_page": "per_page"},
        "form_fields": {},
    },
    "add_tag": {
        "method": "PUT",
        "path": "/people/{id}/add_tag",
        "path_fields": {"id": "id"},
        "query_fields": {},
        "form_fields": {"tag_name": "tag_name"},
    },
    "remove_tag": {
        "method": "PUT",
        "path": "/people/{id}/remove_tag",
        "path_fields": {"id": "id"},
        "query_fields": {},
        "form_fields": {"tag_name": "tag_name"},
    },
    "email_opt_out": {
        "method": "PUT",
        "path": "/people/email_opt_out",
        "path_fields": {},
        "query_fields": {},
        "form_fields": {"email": "email", "company_id": "company_id"},
    },
    "sms_opt_out": {
        "method": "PUT",
        "path": "/people/sms_opt_out",
        "path_fields": {},
        "query_fields": {},
        "form_fields": {"phone_mobile": "phone_mobile", "company_id": "company_id"},
    },
    "set_do_not_call": {
        "method": "PUT",
        "path": "/people/do_not_call",
        "path_fields": {},
        "query_fields": {},
        "form_fields": {"person_id": "person_id", "do_not_call": "do_not_call"},
    },
    "extend_trial": {
        "method": "PUT",
        "path": "/people/{id}/extend_trial",
        "path_fields": {"id": "id"},
        "query_fields": {},
        "form_fields": {"trial_end_at": "trial_end_at"},
    },
    "get_salesperson_report": {
        "method": "GET",
        "path": "/reports/salesperson",
        "path_fields": {},
        "query_fields": {
            "date_from": "date_from",
            "date_into": "date_into",
            "report_type": "report_type",
        },
        "form_fields": {},
    },
}


def _wire(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class ABCGymSalesNode(WorkflowNode):
    integration_type = "automation-abcgymsales"
    connection_evidence = ConnectionEvidence(
        noun="companies", operation="list_companies"
    )

    @classmethod
    def get_config_model(cls):
        return ABCGymSalesFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an ABC GymSales account")
        config, credential = self.config.config, self.config.credentials
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for field, wire in route["path_fields"].items():
            path = path.replace("{" + wire + "}", quote(str(values[field]), safe=""))
        query = []
        for field, wire in route["query_fields"].items():
            value = values.get(field)
            if value is not None:
                query.extend(
                    (wire, _wire(item))
                    for item in (value if isinstance(value, list) else [value])
                )
        form = {
            wire: _wire(values[field])
            for field, wire in route["form_fields"].items()
            if field in values
        }
        headers = {"Accept": "application/json"}
        if route["method"] != "GET":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        # No redirects, user-provided host, or write retries. Fixed provider origin.
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                route["method"],
                BASE_URL + path,
                params=query,
                content=urlencode(form) if form else None,
                headers=headers,
                auth=httpx.BasicAuth(credential.email, credential.password),
            )

        def redact(text):
            for secret in (credential.password, credential.email):
                text = text.replace(secret, "[redacted]")
            return text

        if response.is_error or response.is_redirect:
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": redact(response.text[:2000]),
                "operation": config.operation,
            }
        if response.status_code == 204:
            return {
                "status": "success",
                "http_status": 204,
                "data": None,
                "operation": config.operation,
            }
        if len(response.content) > 10_000_000:
            raise ValueError(
                "ABC GymSales response exceeds 10 MB; request a smaller page"
            )
        try:
            data = response.json()
        except ValueError:
            raise ValueError("ABC GymSales returned an invalid JSON response") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("ABC GymSales returned an unexpected response shape")
        if isinstance(data, dict) and (data.get("errors") or data.get("error")):
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": redact(str(data.get("errors") or data.get("error"))[:2000]),
                "operation": config.operation,
            }
        result = {
            "status": "success",
            "http_status": response.status_code,
            "operation": config.operation,
            "data": data,
        }
        if isinstance(data, dict) and isinstance(data.get("collection"), list):
            result["items"] = data["collection"]
            result["pagination"] = data.get("pagination")
        elif isinstance(data, list):
            result["items"] = data
        return result
