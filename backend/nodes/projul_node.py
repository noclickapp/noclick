"""Projul AI Connect v1.6: account-scoped reads and guarded construction workflows.

Contract: https://connect.projul.com/docs/connect.v1.yaml
Every exposed operation sends exactly one documented request. List results are
one page; replay next_cursor as after with the same filters. Writes never retry
automatically. Customer creation may match and append to an existing customer;
estimate meetings may advance a lead and queue worker reminders.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    EmailStr,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://connect.projul.com"


class ProjulAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Projul API Key",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://connect.projul.com/docs",
            "x-credential-instructions": "Paste a Projul AI Connect API key created by your Projul administrator. A Read key supports reads; choose ReadWrite for creates and updates. NoClick sends it only to connect.projul.com.",
        },
    )
    credential_type: Literal["projul_api_key"] = Field(
        "projul_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def optional_unset(cls, values):
        # A name required by another operation may arrive as an empty string
        # from the shared config lens. For an optional field it means unset.
        if not isinstance(values, dict):
            return values
        return {
            key: None
            if value == ""
            and key in cls.model_fields
            and not cls.model_fields[key].is_required()
            else value
            for key, value in values.items()
        }

    @model_validator(mode="after")
    def check_relationships(self):
        data = self.model_dump(exclude_none=True)
        if data.get("parent_id"):
            prefix = {
                "project": "prj",
                "task": "tsk",
                "customer": "cus",
                "estimate": "est",
            }.get(data.get("parent_type"))
            if not prefix or not re.fullmatch(
                prefix + r"_[0-9A-Za-z]{22}", data["parent_id"]
            ):
                raise ValueError("parent_id must match parent_type")
        return self


class ProjulGetAccountConfig(_Input):
    """Describe the presenting API key."""

    operation: Literal["get_account"] = Field(
        "get_account", json_schema_extra={"ui:hidden": True}
    )


class ProjulListCustomersConfig(_Input):
    """List clients."""

    operation: Literal["list_customers"] = Field(
        "list_customers", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=100, description="Rows per page.")
    after: str | None = Field(
        None,
        description="The opaque cursor from the previous page's `next_cursor`. Pass it back unchanged and with the same filters and sort. A cursor replayed under different filters, tampered with, or malformed is `400 invalid_cursor`. Cursors do not expire, but they are disposable navigation state: if one is rejected, start the list again.",
    )
    sort: Literal[
        "created_at", "-created_at", "updated_at", "-updated_at"
    ] | None = Field(None, description="Sort field. A leading `-` sorts descending.")
    updated_since: datetime | None = Field(
        None,
        description="Only rows updated at or after this instant. The intended incremental-sync filter.",
    )
    external_customer_id: str | None = Field(
        None,
        max_length=50,
        description="Restrict to the clients whose `external_customer_id` (the app's Client Number) is an EXACT match for this value. The intended way to find the Projul client you created for a row in your own system. A value that matches nothing returns an empty page, never an error.",
    )
    external_ref: str | None = Field(
        None,
        max_length=255,
        description="Restrict to the clients whose `external_ref` (your own reference, distinct from the app's Client Number) is an EXACT match for this value. The intended way to find the Projul client you created for a row in your own system. A value that matches nothing returns an empty page, never an error.",
    )
    name: str | None = Field(
        None,
        description="Restrict to the clients whose name matches this value. The match is the client's first and last name joined with a single space (for example `Dana Whitfield`), compared case-insensitively and ignoring leading and trailing spaces. It is a whole-name match, not a substring search, and does not consider the company name. A value that matches nothing returns an empty page, never an error. A value of only spaces is `400 invalid_request`.",
    )
    email: EmailStr | None = Field(
        None,
        description="Restrict to the clients that carry this email address on the client record or on any of its contacts. The match is case-insensitive and ignores leading and trailing spaces. A value that matches nothing returns an empty page, never an error. A value of only spaces is `400 invalid_request`.",
    )
    phone: str | None = Field(
        None,
        description="Restrict to the clients that carry this phone number on the client record or on any of its contacts. The value you send is reduced to its digits. The stored number is compared with its spaces, dashes, parentheses, plus signs, dots and slashes removed, and an 11-digit number's leading `1` (the US and Canada country code) is dropped, so `+1 208 555 0134`, `(208) 555-0134` and `2085550134` are all the same number. A number stored with any other character in it will not match: a note in the field such as `555-0134 (cell)` or `555-0134 x12`, or an unusual dash or space pasted in from another system. Store numbers plainly. Only the number is compared; a phone's `extension` field is not considered. Numbers are not unique: a spouse or an office line can sit on several clients, so the page can hold more than one row, newest first. A value with fewer than 7 digits in it is `400 invalid_request`. A value that matches nothing returns an empty page, never an error.",
    )
    company_name: str | None = Field(
        None,
        description="Restrict to the clients whose `company_name` matches this value, compared case-insensitively and ignoring leading and trailing spaces. It is a whole-value match, not a substring search, and does not consider the person's name; combine it with `name` to pin down one person at a company. A value that matches nothing returns an empty page, never an error. A value of only spaces is `400 invalid_request`.",
    )
    include_archived: StrictBool | None = Field(
        None,
        description="`true` also lists archived clients, each carrying `status: Archived`, so a search can find a returning client and unarchive it instead of creating a duplicate. Deleted clients are never listed. An archived client still `404`s on `GET /v1/customers/{customer_id}` and cannot be linked to a new project or estimate until it is unarchived. Any value other than `true` or `false` is `400 invalid_request`.",
    )


class ProjulGetCustomerConfig(_Input):
    """Retrieve a client."""

    operation: Literal["get_customer"] = Field(
        "get_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(
        ..., pattern="^cus_[0-9A-Za-z]{22}$", description="The client's opaque id."
    )


class CustomerEmail(_Input):
    email: Union[str, None] = Field(...)
    type: Union[str, None] = Field(...)


class CustomerPhone(_Input):
    number: Union[str, None] = Field(...)
    type: Union[str, None] = Field(...)
    extension: Union[str, None] = Field(None)


class CustomerAddress(_Input):
    street1: Union[str, None] = Field(...)
    city: Union[str, None] = Field(...)
    state: Union[str, None] = Field(...)
    postal_code: Union[str, None] = Field(...)
    latitude: Union[float, None] = Field(...)
    longitude: Union[float, None] = Field(...)


class ProjulCreateCustomerConfig(_Input):
    """Create or match a client; matching may append contact details to an existing client."""

    operation: Literal["create_customer"] = Field(
        "create_customer", json_schema_extra={"ui:hidden": True}
    )
    idempotency_key: str = Field(
        ...,
        pattern="^[\\x20-\\x7E]{1,200}$",
        description="Reuse the same key and body for safe replay (24 hours).",
    )
    first_name: Union[str, None] = Field(None)
    last_name: Union[str, None] = Field(None)
    company_name: Union[str, None] = Field(None)
    display_company_name: Union[StrictBool, None] = Field(None)
    description: Union[str, None] = Field(None)
    external_customer_id: Union[str, None] = Field(
        None,
        max_length=50,
        description="Your own identifier for this client (Projul calls it the Client Number). At most 50 characters; longer is `422 validation_failed`. Not unique and not a matching key.",
    )
    external_ref: Union[str, None] = Field(
        None,
        max_length=255,
        description="Your own reference for this client, distinct from `external_customer_id` (Projul's Client Number). At most 255 characters; longer is `422 validation_failed`. Not unique and not a matching key.",
    )
    emails: Union[list[CustomerEmail], None] = Field(
        None, description="The first entry is the one used for matching and appending."
    )
    phones: Union[list[CustomerPhone], None] = Field(
        None, description="The first entry is the one used for matching and appending."
    )
    address: Union[CustomerAddress, None] = Field(None)

    @model_validator(mode="after")
    def require_name(self):
        if not any(
            v and v.strip()
            for v in (self.first_name, self.last_name, self.company_name)
        ):
            raise ValueError("Supply a first name, last name or company name")
        return self


class ProjulUpdateCustomerConfig(_Input):
    """Update a client."""

    operation: Literal["update_customer"] = Field(
        "update_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(
        ..., pattern="^cus_[0-9A-Za-z]{22}$", description="The client's opaque id."
    )
    if_match: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        description="Version from the most recent resource read; stale versions are refused.",
    )
    first_name: Union[str, None] = Field(None)
    last_name: Union[str, None] = Field(None)
    company_name: Union[str, None] = Field(None)
    display_company_name: Union[StrictBool, None] = Field(None)
    description: Union[str, None] = Field(None)
    external_customer_id: Union[str, None] = Field(
        None,
        max_length=50,
        description="Your own identifier for this client (Projul calls it the Client Number). At most 50 characters; longer is `422 validation_failed`. Not unique and not a matching key.",
    )
    external_ref: Union[str, None] = Field(
        None,
        max_length=255,
        description="Your own reference for this client, distinct from `external_customer_id` (Projul's Client Number). At most 255 characters; longer is `422 validation_failed`. Send `null` to clear it.",
    )
    emails: Union[list[CustomerEmail], None] = Field(None)
    phones: Union[list[CustomerPhone], None] = Field(None)
    address: Union[CustomerAddress, None] = Field(None)

    @model_validator(mode="after")
    def require_change(self):
        if not any(
            name in self.model_fields_set
            and (
                getattr(self, name) is not None
                or name in NULLABLE_BODY_FIELDS[self.operation]
            )
            for name in [
                "first_name",
                "last_name",
                "company_name",
                "display_company_name",
                "description",
                "external_customer_id",
                "external_ref",
                "emails",
                "phones",
                "address",
            ]
        ):
            raise ValueError("Supply at least one field to update")
        return self


class ProjulArchiveCustomerConfig(_Input):
    """Archive a client."""

    operation: Literal["archive_customer"] = Field(
        "archive_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(
        ..., pattern="^cus_[0-9A-Za-z]{22}$", description="The client's opaque id."
    )
    if_match: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        description="Version from the most recent resource read; stale versions are refused.",
    )


class ProjulUnarchiveCustomerConfig(_Input):
    """Unarchive a client."""

    operation: Literal["unarchive_customer"] = Field(
        "unarchive_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(
        ..., pattern="^cus_[0-9A-Za-z]{22}$", description="The client's opaque id."
    )
    if_match: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        description="Version from the most recent resource read; stale versions are refused.",
    )


class ProjulListProjectsConfig(_Input):
    """List projects and leads."""

    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=100, description="Rows per page.")
    after: str | None = Field(
        None,
        description="The opaque cursor from the previous page's `next_cursor`. Pass it back unchanged and with the same filters and sort. A cursor replayed under different filters, tampered with, or malformed is `400 invalid_cursor`. Cursors do not expire, but they are disposable navigation state: if one is rejected, start the list again.",
    )
    sort: Literal[
        "created_at", "-created_at", "updated_at", "-updated_at"
    ] | None = Field(None, description="Sort field. A leading `-` sorts descending.")
    updated_since: datetime | None = Field(
        None,
        description="Only rows updated at or after this instant. The intended incremental-sync filter.",
    )
    status: list[
        Literal[
            "new_lead",
            "lead_pending_contact",
            "lead_pending_schedule",
            "lead_pending_estimate",
            "lead_pending_estimate_creation",
            "lead_pending_estimate_to_be_sent",
            "lead_pending_estimate_revision",
            "lead_pending_sale",
            "project_sold",
            "lead_rejected",
            "project_completed",
            "project_terminated",
        ]
    ] | None = Field(
        None,
        description="Restrict to these statuses. Repeat the parameter to pass several (`?status=new_lead&status=lead_pending_sale`).",
    )
    stage: Literal["lead", "active", "archived"] | None = Field(
        None,
        description='Restrict to one stage. The stable way to ask for "all leads" or "all archived work".',
    )
    customer_id: str | None = Field(
        None,
        pattern="^cus_[0-9A-Za-z]{22}$",
        description="Restrict to the projects of one client.",
    )
    external_ref: str | None = Field(
        None,
        max_length=255,
        description="Restrict to the projects whose `external_ref` is an EXACT match for this value. The intended way to find the Projul project you created for a row in your own system. A value that matches nothing returns an empty page, never an error.",
    )
    project_number: str | None = Field(
        None,
        max_length=255,
        description="Restrict to the projects whose `project_number` matches this value. The number is compared as ONE whole value, exactly as the Projul app shows it and this API returns it, including any prefix or suffix the tenant's numbering rules add: `P-1042` matches `P-1042`, and `1042` does not. The comparison is case-insensitive and ignores leading and trailing spaces. The intended way to find the project named on a document or in an email. Projul does not guarantee the formatted number is unique, so read the page rather than assuming one row. A value that matches nothing returns an empty page, never an error. A value of only spaces is `400 invalid_request`.",
    )
    name: str | None = Field(
        None,
        max_length=255,
        description="Restrict to the projects whose `name` matches this value, compared case-insensitively and ignoring leading and trailing spaces. It is a whole-name match, not a substring search. Project names are not unique, so read the page rather than assuming one row; combine it with `customer_id` to pin down one client's job. A value of only spaces is `400 invalid_request`. A value that matches nothing returns an empty page, never an error. It matches a project's own name only: a project with no name of its own, which reads with the name the Projul app shows for it, is found by `customer_id` instead.",
    )


class ProjulGetProjectConfig(_Input):
    """Retrieve a project."""

    operation: Literal["get_project"] = Field(
        "get_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ...,
        pattern="^prj_[0-9A-Za-z]{22}$",
        description="The project's opaque id. A lead's id is a project id.",
    )


class CustomerCreateRequest(_Input):
    first_name: Union[str, None] = Field(None)
    last_name: Union[str, None] = Field(None)
    company_name: Union[str, None] = Field(None)
    display_company_name: Union[StrictBool, None] = Field(None)
    description: Union[str, None] = Field(None)
    external_customer_id: Union[str, None] = Field(None, max_length=50)
    external_ref: Union[str, None] = Field(None, max_length=255)
    emails: Union[list[CustomerEmail], None] = Field(None)
    phones: Union[list[CustomerPhone], None] = Field(None)
    address: Union[CustomerAddress, None] = Field(None)

    @model_validator(mode="after")
    def require_name(self):
        if not any(
            v and v.strip()
            for v in (self.first_name, self.last_name, self.company_name)
        ):
            raise ValueError("Supply a first name, last name or company name")
        return self


class ProjectAddressWrite(_Input):
    street1: Union[str, None] = Field(None)
    city: Union[str, None] = Field(None)
    state: Union[str, None] = Field(None)
    postal_code: Union[str, None] = Field(None)
    country: Union[str, None] = Field(None)


class ProjulCreateProjectConfig(_Input):
    """Create a project or a lead."""

    operation: Literal["create_project"] = Field(
        "create_project", json_schema_extra={"ui:hidden": True}
    )
    idempotency_key: str = Field(
        ...,
        pattern="^[\\x20-\\x7E]{1,200}$",
        description="Reuse the same key and body for safe replay (24 hours).",
    )
    name: str = Field(..., min_length=1)
    status: Literal[
        "new_lead",
        "lead_pending_contact",
        "lead_pending_schedule",
        "lead_pending_estimate",
        "lead_pending_estimate_creation",
        "lead_pending_estimate_to_be_sent",
        "lead_pending_estimate_revision",
        "lead_pending_sale",
        "project_sold",
        "lead_rejected",
        "project_completed",
        "project_terminated",
    ] = Field(...)
    customer_id: Union[str, None] = Field(
        None,
        pattern="^cus_[0-9A-Za-z]{22}$",
        description="An existing client to link. The client row is not modified. Mutually exclusive with `customer`.",
    )
    customer: Union[CustomerCreateRequest, None] = Field(
        None,
        description="An inline client, deduplicated exactly as `POST /v1/customers` does: a matching existing client is linked rather than duplicated. Mutually exclusive with `customer_id`.",
    )
    address: Union[ProjectAddressWrite, None] = Field(None)
    start_date: Union[date, None] = Field(
        None,
        description="The planned start, a calendar day (`YYYY-MM-DD`) in the company's time zone. Setting it schedules the client's project start reminder emails (a week before, the day before and on the day) if the account has those reminders turned on in Projul; reminders whose time has already passed are not sent, so a start date in the past sends nothing.",
    )
    completion_date: Union[date, None] = Field(
        None,
        description="The planned completion, a calendar day (`YYYY-MM-DD`) in the company's time zone, not before `start_date`.",
    )
    external_ref: Union[str, None] = Field(
        None,
        max_length=255,
        description="Your own identifier for this project, carried from whatever system owns it. Not unique and not a matching key. At most 255 characters; longer is `422 validation_failed`.",
    )
    description: Union[str, None] = Field(
        None,
        description="The project's notes (Projul's \"Project Notes\"). Rich text, stored and rendered by the Projul app as **HTML**. No length limit.",
    )
    sale_probability: Union[str, None] = Field(
        None,
        description='Likelihood of winning the job, as a percent from `"0"` to `"100"`, inclusive. Outside that range the write is `422 validation_failed` with an `out_of_range` error on `/sale_probability`.',
    )

    @model_validator(mode="after")
    def require_customer(self):
        if bool(self.customer_id) == bool(self.customer):
            raise ValueError("Supply exactly one of customer_id or customer")
        return self


class ProjulUpdateProjectConfig(_Input):
    """Update a project."""

    operation: Literal["update_project"] = Field(
        "update_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ...,
        pattern="^prj_[0-9A-Za-z]{22}$",
        description="The project's opaque id. A lead's id is a project id.",
    )
    if_match: str = Field(
        ...,
        pattern="^[0-9a-f]{32}$",
        description="Version from the most recent resource read; stale versions are refused.",
    )
    name: Union[str, None] = Field(
        None,
        description="The project's own name. For a project with no name of its own, sending the `name` it reads with, or `null`, keeps it without one; any other value becomes its name.",
    )
    status: Literal[
        "new_lead",
        "lead_pending_contact",
        "lead_pending_schedule",
        "lead_pending_estimate",
        "lead_pending_estimate_creation",
        "lead_pending_estimate_to_be_sent",
        "lead_pending_estimate_revision",
        "lead_pending_sale",
        "project_sold",
        "lead_rejected",
        "project_completed",
        "project_terminated",
    ] | None = Field(None)
    address: Union[ProjectAddressWrite, None] = Field(None)
    start_date: Union[date, None] = Field(
        None,
        description="The planned start, a calendar day (`YYYY-MM-DD`) in the company's time zone. Send `null` to clear it. Setting or changing it schedules the client's project start reminder emails (a week before, the day before and on the day) if the account has those reminders turned on in Projul; reminders whose time has already passed are not sent, so a start date in the past sends nothing.",
    )
    completion_date: Union[date, None] = Field(
        None,
        description="The planned completion, a calendar day (`YYYY-MM-DD`) in the company's time zone, not before `start_date`. Send `null` to clear it.",
    )
    external_ref: Union[str, None] = Field(
        None,
        max_length=255,
        description="Your own identifier for this project, carried from whatever system owns it. Not unique and not a matching key. At most 255 characters; longer is `422 validation_failed`.",
    )
    description: Union[str, None] = Field(
        None,
        description="The project's notes (Projul's \"Project Notes\"). Rich text, stored and rendered by the Projul app as **HTML**. No length limit. Send `null` to clear it.",
    )
    sale_probability: Union[str, None] = Field(
        None,
        description='Likelihood of winning the job, as a percent from `"0"` to `"100"`, inclusive. Outside that range the write is `422 validation_failed` with an `out_of_range` error on `/sale_probability`.',
    )

    @model_validator(mode="after")
    def require_change(self):
        if not any(
            name in self.model_fields_set
            and (
                getattr(self, name) is not None
                or name in NULLABLE_BODY_FIELDS[self.operation]
            )
            for name in [
                "name",
                "status",
                "address",
                "start_date",
                "completion_date",
                "external_ref",
                "description",
                "sale_probability",
            ]
        ):
            raise ValueError("Supply at least one field to update")
        return self


class ProjulListTasksConfig(_Input):
    """List tasks."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=100, description="Rows per page.")
    after: str | None = Field(
        None,
        description="The opaque cursor from the previous page's `next_cursor`. Pass it back unchanged and with the same filters and sort. A cursor replayed under different filters, tampered with, or malformed is `400 invalid_cursor`. Cursors do not expire, but they are disposable navigation state: if one is rejected, start the list again.",
    )
    sort: Literal[
        "created_at", "-created_at", "updated_at", "-updated_at"
    ] | None = Field(None, description="Sort field. A leading `-` sorts descending.")
    updated_since: datetime | None = Field(
        None,
        description="Only rows updated at or after this instant. The intended incremental-sync filter.",
    )
    project_id: str | None = Field(
        None,
        pattern="^prj_[0-9A-Za-z]{22}$",
        description="Restrict to the tasks of one project. A lead's id is a project id.",
    )
    task_type: list[
        Literal[
            "Task",
            "Deadline",
            "FollowUpReminder",
            "EstimateMeeting",
            "Event",
            "Meeting",
            "TimeOff",
            "AbsentWorker",
            "Step",
            "EstimateToWrite",
        ]
    ] | None = Field(
        None,
        description="Restrict to these task types. Repeat the parameter to pass several (`?task_type=Task&task_type=Deadline`).",
    )
    status: list[
        Literal[
            "Active",
            "Archived",
            "OnHold",
            "CompletedSuccessfully",
            "CompletedFailed",
            "Rejected",
            "Expired",
            "Cancelled",
        ]
    ] | None = Field(
        None,
        description="Restrict to these statuses. Repeat the parameter to pass several (`?status=Active&status=OnHold`).",
    )
    external_ref: str | None = Field(
        None,
        max_length=255,
        description="Restrict to the tasks whose `external_ref` is an EXACT match for this value. The intended way to find the Projul task you created for a row in your own system. A value that matches nothing returns an empty page, never an error.",
    )
    name: str | None = Field(
        None,
        description='Restrict to the tasks whose `name` matches this value, compared case-insensitively and ignoring leading and trailing spaces. It is a whole-name match, not a substring search. Task names are not unique (each project can have its own "Site walk"), so combine it with `project_id` and read the page rather than assuming one row. A repeating task is ONE row however often it repeats, and adding `scheduled_from`/`scheduled_to` drops it unless its stored window falls in the range. A value that matches nothing returns an empty page, never an error. A value of only spaces is `400 invalid_request`.',
    )
    scheduled_from: datetime | None = Field(
        None,
        description="Restrict to tasks that have a scheduled window starting at or after this instant. This filters on the schedule (the `assignments` window start), NOT on when the task row was last changed. Use it with `scheduled_to` to bound a date range; a task matches when one of its windows starts inside the range. A repeating task matches only on its stored window, never on the occurrences its rule produces, so a series that falls inside a later range is not returned. There is no `is_recurring` filter: list without the schedule filters, keep the rows whose `is_recurring` is true, and work out their dates from `recurring_rule`.",
    )
    scheduled_to: datetime | None = Field(
        None,
        description="Restrict to tasks that have a scheduled window starting at or before this instant. This filters on the schedule (the `assignments` window start), NOT on when the task row was last changed. Use it with `scheduled_from` to bound a date range. Like `scheduled_from`, it never matches the occurrences of a repeating task, only its stored window.",
    )
    assignee: str | None = Field(
        None,
        pattern="^user_[0-9A-Za-z]{22}$",
        description="Restrict to tasks that have this person on one of their schedule windows. Pass the person's `user_` id (from a task's `assignments[].user_ids`). A value that matches nothing returns an empty page, never an error.",
    )


class ProjulGetTaskConfig(_Input):
    """Retrieve a task."""

    operation: Literal["get_task"] = Field(
        "get_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ..., pattern="^tsk_[0-9A-Za-z]{22}$", description="The task's opaque id."
    )


class TaskAssignmentWrite(_Input):
    id: str | None = Field(None, pattern="^asgn_[0-9A-Za-z]{22}$")
    user_ids: list[
        Annotated[str, Field(pattern=r"^user_[0-9A-Za-z]{22}$")]
    ] | None = Field(None)
    team_ids: list[
        Annotated[str, Field(pattern=r"^tag_[0-9A-Za-z]{22}$")]
    ] | None = Field(None)
    starts_at: Union[datetime, None] = Field(None)
    ends_at: Union[datetime, None] = Field(None)
    is_tentative: StrictBool | None = Field(None)


class TaskStepWrite(_Input):
    id: str | None = Field(None, pattern="^step_[0-9A-Za-z]{22}$")
    description: Union[str, None] = Field(None)
    completed: StrictBool | None = Field(None)


class ProjulCreateTaskConfig(_Input):
    """Create a task. EstimateMeeting may advance a lead and queue worker reminders."""

    operation: Literal["create_task"] = Field(
        "create_task", json_schema_extra={"ui:hidden": True}
    )
    idempotency_key: str = Field(
        ...,
        pattern="^[\\x20-\\x7E]{1,200}$",
        description="Reuse the same key and body for safe replay (24 hours).",
    )
    name: Union[str, None] = Field(None, description="The task name.")
    description: Union[str, None] = Field(
        None, description="The task body. Rich text — HTML is stored as sent."
    )
    details: Union[str, None] = Field(
        None,
        description="The meeting-notes field. A separate field from `description`.",
    )
    project_id: Union[str, None] = Field(
        None,
        pattern="^prj_[0-9A-Za-z]{22}$",
        description="The owning project. A lead IS a project, so scheduling on a lead means naming that project here. Unknown or other-tenant ids are `422 validation_failed`.",
    )
    task_type: Literal[
        "Task",
        "Deadline",
        "FollowUpReminder",
        "EstimateMeeting",
        "Event",
        "Meeting",
        "TimeOff",
        "AbsentWorker",
        "Step",
        "EstimateToWrite",
    ] = Field(...)
    status: Union[
        Literal[
            "Active",
            "Archived",
            "OnHold",
            "CompletedSuccessfully",
            "CompletedFailed",
            "Rejected",
            "Expired",
            "Cancelled",
        ],
        None,
    ] = Field(None, description="Defaults to `Active`.")
    assignments: list[TaskAssignmentWrite] | None = Field(
        None, description="The schedule windows. Omit for an unscheduled task."
    )
    steps: list[TaskStepWrite] | None = Field(
        None, description="The checklist, in order. Not allowed on a repeating task."
    )
    external_ref: Union[str, None] = Field(
        None,
        max_length=255,
        description="Your own identifier for this task, carried from whatever system owns it. Not interpreted by Projul and not unique.",
    )


class ProjulUpdateTaskConfig(_Input):
    """Update a task."""

    operation: Literal["update_task"] = Field(
        "update_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ..., pattern="^tsk_[0-9A-Za-z]{22}$", description="The task's opaque id."
    )
    if_match: str = Field(
        ...,
        pattern="^[0-9a-f]{32}$",
        description="Version from the most recent resource read; stale versions are refused.",
    )
    name: Union[str, None] = Field(None, description="The task name.")
    description: Union[str, None] = Field(
        None, description="The task body. Rich text — HTML is stored as sent."
    )
    details: Union[str, None] = Field(None, description="The meeting-notes field.")
    project_id: Union[str, None] = Field(
        None,
        pattern="^prj_[0-9A-Za-z]{22}$",
        description="The owning project, or `null` to detach the task from its project.",
    )
    status: Union[
        Literal[
            "Active",
            "Archived",
            "OnHold",
            "CompletedSuccessfully",
            "CompletedFailed",
            "Rejected",
            "Expired",
            "Cancelled",
        ],
        None,
    ] = Field(None, description="The task's status.")
    assignments: list[TaskAssignmentWrite] | None = Field(
        None,
        description="The schedule, merged by assignment id: restate a window by its `id` to change only the members you send, omit the `id` to add one, leave a window out to remove it; `[]` clears the schedule. Requires `If-Match`.",
    )
    steps: list[TaskStepWrite] | None = Field(
        None,
        description="The checklist, merged by step id. Requires `If-Match`; refused on a repeating task.",
    )
    external_ref: Union[str, None] = Field(
        None,
        max_length=255,
        description="Your own identifier for this task. Omitted leaves it untouched; explicit `null` clears it. Not interpreted by Projul and not unique.",
    )

    @model_validator(mode="after")
    def require_change(self):
        if not any(
            name in self.model_fields_set
            and (
                getattr(self, name) is not None
                or name in NULLABLE_BODY_FIELDS[self.operation]
            )
            for name in [
                "name",
                "description",
                "details",
                "project_id",
                "status",
                "assignments",
                "steps",
                "external_ref",
            ]
        ):
            raise ValueError("Supply at least one field to update")
        return self


class ProjulCompleteTaskConfig(_Input):
    """Complete or un-complete a task."""

    operation: Literal["complete_task"] = Field(
        "complete_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ..., pattern="^tsk_[0-9A-Za-z]{22}$", description="The task's opaque id."
    )
    if_match: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        description="Version from the most recent resource read; stale versions are refused.",
    )
    completed: StrictBool = Field(..., description="The state to set. Required.")
    recurrence_date: Union[date, None] = Field(
        None,
        description="Which occurrence to complete. Required on a repeating task, refused on a non-repeating one.",
    )


class ProjulListEstimatesConfig(_Input):
    """List estimates."""

    operation: Literal["list_estimates"] = Field(
        "list_estimates", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=100, description="Rows per page.")
    after: str | None = Field(
        None,
        description="The opaque cursor from the previous page's `next_cursor`. Pass it back unchanged and with the same filters and sort. A cursor replayed under different filters, tampered with, or malformed is `400 invalid_cursor`. Cursors do not expire, but they are disposable navigation state: if one is rejected, start the list again.",
    )
    sort: Literal[
        "created_at", "-created_at", "updated_at", "-updated_at"
    ] | None = Field(
        None,
        description="Sort field, over the estimate row itself. A leading `-` sorts descending.",
    )
    updated_since: datetime | None = Field(
        None,
        description="Only rows updated at or after this instant. The intended incremental-sync filter.",
    )
    status: list[
        Literal[
            "Draft",
            "PendingReview",
            "PendingSend",
            "PendingApproval",
            "Overdue",
            "RevisionRequested",
            "Rejected",
            "Approved",
            "CompletelyPaid",
            "ReviewRevisionRequested",
            "Closed",
        ]
    ] | None = Field(
        None,
        description='Restrict to estimates having **at least one live version** in one of these statuses. Repeat the parameter to pass several (`?status=Draft&status=Approved`). Status is per version, so this is an "any version matches" question — an approved estimate with a draft change order matches both.',
    )
    project_id: str | None = Field(
        None,
        pattern="^prj_[0-9A-Za-z]{22}$",
        description="Restrict to the estimates of one project.",
    )
    customer_id: str | None = Field(
        None,
        pattern="^cus_[0-9A-Za-z]{22}$",
        description="Restrict to the estimates of one client.",
    )
    external_ref: str | None = Field(
        None,
        max_length=255,
        description="Restrict to the estimates whose `external_ref` is an EXACT match for this value. The intended way to find the Projul estimate you created for a row in your own system. A value that matches nothing returns an empty page, never an error.",
    )


class ProjulGetEstimateConfig(_Input):
    """Retrieve an estimate."""

    operation: Literal["get_estimate"] = Field(
        "get_estimate", json_schema_extra={"ui:hidden": True}
    )
    estimate_id: str = Field(
        ..., pattern="^est_[0-9A-Za-z]{22}$", description="The estimate's opaque id."
    )


class ProjulListInvoicesConfig(_Input):
    """List invoices."""

    operation: Literal["list_invoices"] = Field(
        "list_invoices", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=100, description="Rows per page.")
    after: str | None = Field(
        None,
        description="The opaque cursor from the previous page's `next_cursor`. Pass it back unchanged and with the same filters and sort. A cursor replayed under different filters, tampered with, or malformed is `400 invalid_cursor`. Cursors do not expire, but they are disposable navigation state: if one is rejected, start the list again.",
    )
    updated_since: datetime | None = Field(
        None,
        description="Only rows updated at or after this instant. The intended incremental-sync filter.",
    )
    sort: Literal[
        "created_at", "-created_at", "updated_at", "-updated_at"
    ] | None = Field(None, description="Sort field. A leading `-` sorts descending.")
    number: str | None = Field(
        None,
        description="The invoice number exactly as Projul shows it, ignoring leading and trailing spaces. A value of only spaces is `400 invalid_request`.",
    )
    external_ref: str | None = Field(
        None,
        description="The external reference you set on the invoice, ignoring leading and trailing spaces. A value of only spaces is `400 invalid_request`.",
    )
    customer_id: str | None = Field(
        None, description="Only invoices billed to this client (`cus_` id)."
    )
    project_id: str | None = Field(
        None,
        description="Only invoices on this project (`prj_` id). A lead is a project.",
    )
    estimate_id: str | None = Field(
        None, description="Only invoices raised against this estimate (`est_` id)."
    )
    status: Literal[
        "draft",
        "pending_review",
        "revision_requested",
        "review_revision_requested",
        "pending_send",
        "pending_payment",
        "partial",
        "overdue",
        "paid",
        "pending_approval",
        "payment_submitted",
        "closed",
        "void",
    ] | None = Field(None, description="Only invoices whose stored status is this one.")
    is_overdue: StrictBool | None = Field(
        None,
        description="`true` for invoices with a balance still owed past their due date on the company's calendar day, `false` for the rest.",
    )


class ProjulGetInvoiceConfig(_Input):
    """Retrieve an invoice."""

    operation: Literal["get_invoice"] = Field(
        "get_invoice", json_schema_extra={"ui:hidden": True}
    )
    invoice_id: str = Field(
        ...,
        pattern="^inv_[0-9A-Za-z]{22}$",
        description="The invoice's opaque id (`inv_`).",
    )


class ProjulListMessagesConfig(_Input):
    """List messages."""

    operation: Literal["list_messages"] = Field(
        "list_messages", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(None, ge=1, le=100, description="Rows per page.")
    after: str | None = Field(
        None,
        description="The opaque cursor from the previous page's `next_cursor`. Pass it back unchanged and with the same filters and sort. A cursor replayed under different filters, tampered with, or malformed is `400 invalid_cursor`. Cursors do not expire, but they are disposable navigation state: if one is rejected, start the list again.",
    )
    sort: Literal[
        "created_at", "-created_at", "updated_at", "-updated_at"
    ] | None = Field(None, description="Sort field. A leading `-` sorts descending.")
    updated_since: datetime | None = Field(
        None,
        description="Only rows updated at or after this instant. The intended incremental-sync filter.",
    )
    parent_type: Literal["project", "task", "customer", "estimate"] | None = Field(
        None,
        description="Restrict to messages on one kind of record. `project` also returns that project's read-only client messages.",
    )
    parent_id: str | None = Field(
        None,
        description="Restrict to one record's messages. Requires `parent_type`, and the id must carry that record type's prefix. For an estimate this returns the estimate's whole message history, including messages recorded against an earlier version of it.",
    )


class ProjulGetMessageConfig(_Input):
    """Retrieve a message."""

    operation: Literal["get_message"] = Field(
        "get_message", json_schema_extra={"ui:hidden": True}
    )
    message_id: str = Field(
        ..., pattern="^msg_[0-9A-Za-z]{22}$", description="The message's opaque id."
    )


class ProjulCreateMessageConfig(_Input):
    """Add a message to a record."""

    operation: Literal["create_message"] = Field(
        "create_message", json_schema_extra={"ui:hidden": True}
    )
    idempotency_key: str = Field(
        ...,
        pattern="^[\\x20-\\x7E]{1,200}$",
        description="Reuse the same key and body for safe replay (24 hours).",
    )
    parent_type: Literal["project", "task", "customer", "estimate"] = Field(...)
    parent_id: str = Field(
        ...,
        description="The parent's opaque id, carrying that record type's own prefix.",
    )
    body: Union[str, None] = Field(None)
    body_html: Union[str, None] = Field(None)
    message_type: Union[str, None] = Field(
        None, description="Free text. Projul defines no vocabulary for it."
    )
    contact_method: Union[str, None] = Field(
        None,
        description="One of `phone`, `email`, `text`, `person`, or `null` to leave it unset. Matching is case-insensitive, and the labels the Projul UI shows for the same four (`Phone Call`, `Text Message`, `In Person`) are accepted and stored as the value above. Anything else is `422 validation_failed` with `invalid_enum`: Projul renders a communication record by matching these values exactly, so storing another spelling would file a record the app cannot display.",
    )
    contact_direction: Union[str, None] = Field(
        None,
        description="One of `in`, `out`, or `null`. `Inbound`/`Received` and `Outbound`/`Sent` are accepted as aliases, case-insensitively, and stored as `in`/`out`. Anything else is `422 validation_failed`. Leave it `null` for an in-person contact and report the outcome with `contact_success`.",
    )
    contact_success: Union[StrictBool, None] = Field(None)
    recorded_at: Union[datetime, None] = Field(None)

    @model_validator(mode="after")
    def require_body(self):
        if not (self.body or self.body_html):
            raise ValueError("Supply body or body_html")
        return self


ProjulConfig = Annotated[
    Union[
        ProjulGetAccountConfig,
        ProjulListCustomersConfig,
        ProjulGetCustomerConfig,
        ProjulCreateCustomerConfig,
        ProjulUpdateCustomerConfig,
        ProjulArchiveCustomerConfig,
        ProjulUnarchiveCustomerConfig,
        ProjulListProjectsConfig,
        ProjulGetProjectConfig,
        ProjulCreateProjectConfig,
        ProjulUpdateProjectConfig,
        ProjulListTasksConfig,
        ProjulGetTaskConfig,
        ProjulCreateTaskConfig,
        ProjulUpdateTaskConfig,
        ProjulCompleteTaskConfig,
        ProjulListEstimatesConfig,
        ProjulGetEstimateConfig,
        ProjulListInvoicesConfig,
        ProjulGetInvoiceConfig,
        ProjulListMessagesConfig,
        ProjulGetMessageConfig,
        ProjulCreateMessageConfig,
    ],
    Field(discriminator="operation"),
]


class ProjulFullConfig(NodeConfig[ProjulConfig, ProjulAPIKeyCredential]):
    pass


OPERATIONS = {
    "get_account": {
        "method": "GET",
        "path": "/v1/me",
        "path_fields": [],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "list_customers": {
        "method": "GET",
        "path": "/v1/customers",
        "path_fields": [],
        "query_fields": [
            "limit",
            "after",
            "sort",
            "updated_since",
            "external_customer_id",
            "external_ref",
            "name",
            "email",
            "phone",
            "company_name",
            "include_archived",
        ],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "get_customer": {
        "method": "GET",
        "path": "/v1/customers/{customer_id}",
        "path_fields": ["customer_id"],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "create_customer": {
        "method": "POST",
        "path": "/v1/customers",
        "path_fields": [],
        "query_fields": [],
        "headers": {"idempotency_key": "Idempotency-Key"},
        "body_fields": [
            "first_name",
            "last_name",
            "company_name",
            "display_company_name",
            "description",
            "external_customer_id",
            "external_ref",
            "emails",
            "phones",
            "address",
        ],
        "success": [200, 201],
    },
    "update_customer": {
        "method": "PATCH",
        "path": "/v1/customers/{customer_id}",
        "path_fields": ["customer_id"],
        "query_fields": [],
        "headers": {"if_match": "If-Match"},
        "body_fields": [
            "first_name",
            "last_name",
            "company_name",
            "display_company_name",
            "description",
            "external_customer_id",
            "external_ref",
            "emails",
            "phones",
            "address",
        ],
        "success": [200],
    },
    "archive_customer": {
        "method": "POST",
        "path": "/v1/customers/{customer_id}/archive",
        "path_fields": ["customer_id"],
        "query_fields": [],
        "headers": {"if_match": "If-Match"},
        "body_fields": [],
        "success": [200],
    },
    "unarchive_customer": {
        "method": "POST",
        "path": "/v1/customers/{customer_id}/unarchive",
        "path_fields": ["customer_id"],
        "query_fields": [],
        "headers": {"if_match": "If-Match"},
        "body_fields": [],
        "success": [200],
    },
    "list_projects": {
        "method": "GET",
        "path": "/v1/projects",
        "path_fields": [],
        "query_fields": [
            "limit",
            "after",
            "sort",
            "updated_since",
            "status",
            "stage",
            "customer_id",
            "external_ref",
            "project_number",
            "name",
        ],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "get_project": {
        "method": "GET",
        "path": "/v1/projects/{project_id}",
        "path_fields": ["project_id"],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "create_project": {
        "method": "POST",
        "path": "/v1/projects",
        "path_fields": [],
        "query_fields": [],
        "headers": {"idempotency_key": "Idempotency-Key"},
        "body_fields": [
            "name",
            "status",
            "customer_id",
            "customer",
            "address",
            "start_date",
            "completion_date",
            "external_ref",
            "description",
            "sale_probability",
        ],
        "success": [201],
    },
    "update_project": {
        "method": "PATCH",
        "path": "/v1/projects/{project_id}",
        "path_fields": ["project_id"],
        "query_fields": [],
        "headers": {"if_match": "If-Match"},
        "body_fields": [
            "name",
            "status",
            "address",
            "start_date",
            "completion_date",
            "external_ref",
            "description",
            "sale_probability",
        ],
        "success": [200],
    },
    "list_tasks": {
        "method": "GET",
        "path": "/v1/tasks",
        "path_fields": [],
        "query_fields": [
            "limit",
            "after",
            "sort",
            "updated_since",
            "project_id",
            "task_type",
            "status",
            "external_ref",
            "name",
            "scheduled_from",
            "scheduled_to",
            "assignee",
        ],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "get_task": {
        "method": "GET",
        "path": "/v1/tasks/{task_id}",
        "path_fields": ["task_id"],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "create_task": {
        "method": "POST",
        "path": "/v1/tasks",
        "path_fields": [],
        "query_fields": [],
        "headers": {"idempotency_key": "Idempotency-Key"},
        "body_fields": [
            "name",
            "description",
            "details",
            "project_id",
            "task_type",
            "status",
            "assignments",
            "steps",
            "external_ref",
        ],
        "success": [201],
    },
    "update_task": {
        "method": "PATCH",
        "path": "/v1/tasks/{task_id}",
        "path_fields": ["task_id"],
        "query_fields": [],
        "headers": {"if_match": "If-Match"},
        "body_fields": [
            "name",
            "description",
            "details",
            "project_id",
            "status",
            "assignments",
            "steps",
            "external_ref",
        ],
        "success": [200],
    },
    "complete_task": {
        "method": "POST",
        "path": "/v1/tasks/{task_id}/complete",
        "path_fields": ["task_id"],
        "query_fields": [],
        "headers": {"if_match": "If-Match"},
        "body_fields": ["completed", "recurrence_date"],
        "success": [200],
    },
    "list_estimates": {
        "method": "GET",
        "path": "/v1/estimates",
        "path_fields": [],
        "query_fields": [
            "limit",
            "after",
            "sort",
            "updated_since",
            "status",
            "project_id",
            "customer_id",
            "external_ref",
        ],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "get_estimate": {
        "method": "GET",
        "path": "/v1/estimates/{estimate_id}",
        "path_fields": ["estimate_id"],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "list_invoices": {
        "method": "GET",
        "path": "/v1/invoices",
        "path_fields": [],
        "query_fields": [
            "limit",
            "after",
            "updated_since",
            "sort",
            "number",
            "external_ref",
            "customer_id",
            "project_id",
            "estimate_id",
            "status",
            "is_overdue",
        ],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "get_invoice": {
        "method": "GET",
        "path": "/v1/invoices/{invoice_id}",
        "path_fields": ["invoice_id"],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "list_messages": {
        "method": "GET",
        "path": "/v1/messages",
        "path_fields": [],
        "query_fields": [
            "limit",
            "after",
            "sort",
            "updated_since",
            "parent_type",
            "parent_id",
        ],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "get_message": {
        "method": "GET",
        "path": "/v1/messages/{message_id}",
        "path_fields": ["message_id"],
        "query_fields": [],
        "headers": {},
        "body_fields": [],
        "success": [200],
    },
    "create_message": {
        "method": "POST",
        "path": "/v1/messages",
        "path_fields": [],
        "query_fields": [],
        "headers": {"idempotency_key": "Idempotency-Key"},
        "body_fields": [
            "parent_type",
            "parent_id",
            "body",
            "body_html",
            "message_type",
            "contact_method",
            "contact_direction",
            "contact_success",
            "recorded_at",
        ],
        "success": [201],
    },
}


NULLABLE_BODY_FIELDS = {
    "get_account": [],
    "list_customers": [],
    "get_customer": [],
    "create_customer": [
        "first_name",
        "last_name",
        "company_name",
        "display_company_name",
        "description",
        "external_customer_id",
        "external_ref",
        "emails",
        "phones",
        "address",
    ],
    "update_customer": [
        "first_name",
        "last_name",
        "company_name",
        "display_company_name",
        "description",
        "external_customer_id",
        "external_ref",
        "emails",
        "phones",
        "address",
    ],
    "archive_customer": [],
    "unarchive_customer": [],
    "list_projects": [],
    "get_project": [],
    "create_project": [
        "customer_id",
        "customer",
        "address",
        "start_date",
        "completion_date",
        "external_ref",
        "description",
        "sale_probability",
    ],
    "update_project": [
        "name",
        "address",
        "start_date",
        "completion_date",
        "external_ref",
        "description",
        "sale_probability",
    ],
    "list_tasks": [],
    "get_task": [],
    "create_task": [
        "name",
        "description",
        "details",
        "project_id",
        "status",
        "external_ref",
    ],
    "update_task": [
        "name",
        "description",
        "details",
        "project_id",
        "status",
        "external_ref",
    ],
    "complete_task": ["recurrence_date"],
    "list_estimates": [],
    "get_estimate": [],
    "list_invoices": [],
    "get_invoice": [],
    "list_messages": [],
    "get_message": [],
    "create_message": [
        "body",
        "body_html",
        "message_type",
        "contact_method",
        "contact_direction",
        "contact_success",
        "recorded_at",
    ],
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class ProjulNode(WorkflowNode):
    integration_type = "automation-projul"
    connection_evidence = ConnectionEvidence(
        noun="customers",
        operation="list_customers",
        identity_operation="get_account",
        label_keys=("company_name", "first_name", "last_name", "id"),
        identity_keys=("company_name", "key_name", "key_id"),
    )

    @classmethod
    def get_config_model(cls):
        return ProjulFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Projul API key")
        spec = OPERATIONS[config.operation]
        data = config.model_dump(mode="json", exclude_unset=True)
        path = spec["path"].format(**{k: data[k] for k in spec["path_fields"]})
        params = {
            k: data[k]
            for k in spec["query_fields"]
            if k in data and data[k] is not None
        }
        params = {
            k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()
        }
        headers = {
            "Authorization": "Bearer " + credential.api_key,
            "Accept": "application/json",
        }
        headers.update(
            {
                wire: data[k]
                for k, wire in spec["headers"].items()
                if k in data and data[k] is not None
            }
        )
        body = {
            k: data[k]
            for k in spec["body_fields"]
            if k in data
            and (data[k] is not None or k in NULLABLE_BODY_FIELDS[config.operation])
        }
        kwargs = {"json": body} if spec["body_fields"] else {}
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    spec["method"],
                    BASE + path,
                    params=params,
                    headers=headers,
                    **kwargs,
                )
            output["http_status"] = response.status_code
            if response.status_code not in spec["success"]:
                error = {"status": "error", "error": "Projul rejected the request"}
                try:
                    problem = response.json()
                    if isinstance(problem, dict):
                        error.update(
                            {
                                k: problem[k]
                                for k in ("code", "detail", "request_id")
                                if isinstance(problem.get(k), str)
                            }
                        )
                        error["error"] = error.get("detail", error["error"])
                except ValueError:
                    pass
                if response.headers.get("Retry-After"):
                    error["retry_after"] = response.headers["Retry-After"]
                return _redact({**output, **error}, credential.api_key)
            mime = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .lower()
                .strip()
            )
            if mime != "application/json" or len(response.content) > 10_000_000:
                raise ValueError("Expected bounded JSON")
            result = response.json()
            if not isinstance(result, dict) or "error" in result or "errors" in result:
                raise ValueError("Invalid response object")
            if config.operation.startswith("list_"):
                if (
                    not isinstance(result.get("data"), list)
                    or type(result.get("has_more")) is not bool
                    or "next_cursor" not in result
                ):
                    raise ValueError("Incomplete page")
                cursor = result["next_cursor"]
                if cursor is not None and not isinstance(cursor, str):
                    raise ValueError("Invalid cursor")
                if result["has_more"] and not cursor:
                    raise ValueError("Missing next cursor")
                if any(
                    not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    for row in result["data"]
                ):
                    raise ValueError("Invalid page row")
                output.update(result)
                output["complete"] = not result["has_more"]
            elif config.operation == "get_account":
                if not isinstance(result.get("key_id"), str) or result.get(
                    "access_level"
                ) not in ("Read", "ReadWrite"):
                    raise ValueError("Invalid account identity")
                output.update(result)
            else:
                if not isinstance(result.get("id"), str):
                    raise ValueError("Missing resource identity")
                if spec["path_fields"] and result["id"] != data[spec["path_fields"][0]]:
                    raise ValueError("Response does not match requested resource")
                output["data"] = result
            return _redact({**output, "status": "success"}, credential.api_key)
        except (ValueError, httpx.HTTPError, SSRFError):
            return {
                **output,
                "status": "error",
                "error": "Projul response could not be confirmed; inspect the resource before retrying a write",
            }
