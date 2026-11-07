"""ClickFunnels V2 contacts, sales and course automation using a pasted API key.

Routes and envelopes follow the official OpenAPI 2.0.0 specification at
https://accounts.myclickfunnels.com/openapi.json. Account discovery uses accounts;
workspace requests use the workspace subdomain, as required by Getting Started.
"""
from __future__ import annotations

import json
import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import https_origin

JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class ClickFunnelsAPIKeyCredential(BaseModel):
    credential_type: Literal["clickfunnels_api_key"] = Field(
        "clickfunnels_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1,
                         json_schema_extra={"ui:widget": "password"})
    workspace_subdomain: str = Field(
        ..., title="Workspace Subdomain",
        description="Your workspace's myclickfunnels.com subdomain or dashboard URL.")

    model_config = ConfigDict(title="ClickFunnels API Key", json_schema_extra={
        "x-credential-url": "https://developers.myclickfunnels.com/docs/getting-started",
        "x-credential-instructions": "In Team Settings → Developer Portal, create a platform application and copy its API access token. Paste it here with your workspace subdomain. The key needs account read, contacts read/write, store read/write and courses read/write access.",
    })

    @field_validator("workspace_subdomain")
    @classmethod
    def normalize_workspace(cls, value: str) -> str:
        import re
        raw = value.strip().lower()
        if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", raw):
            slug = raw
        else:
            origin = https_origin(raw, field_name="Workspace Subdomain")
            suffix = ".myclickfunnels.com"
            if not origin.startswith("https://") or not origin.endswith(suffix):
                raise ValueError("Use your workspace's https://<subdomain>.myclickfunnels.com URL.")
            slug = origin[len("https://"):-len(suffix)]
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", slug) or slug in {"accounts", "agents", "developers", "www", "support"}:
            raise ValueError("Paste the workspace subdomain, not the accounts or developer portal host.")
        return slug


Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")]


class PageConfig(BaseModel):
    per_page: int = Field(20, ge=1, title="Page Size")
    after: str | None = Field(None, title="After Cursor", description="Pagination-Next cursor from the previous response.")


class ContactFields(BaseModel):
    email_address: str | None = Field(None, title="Email Address")
    first_name: str | None = Field(None, title="First Name")
    last_name: str | None = Field(None, title="Last Name")
    phone_number: str | None = Field(None, title="Phone Number")
    time_zone: str | None = Field(None, title="Time Zone")
    custom_attributes_json: str | None = Field(
        None, title="Custom Attributes", description='JSON object of custom field names and string values.',
        json_schema_extra=JSON_EDITOR)


def _json_object(value: str, title: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{title} must be valid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{title} must be a JSON object")
    return result


def _line_items(value: str, *, invoice: bool = False) -> list[dict[str, Any]]:
    try:
        rows = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Line Items must be valid JSON") from exc
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Line Items must be a nonempty JSON array of objects")
    for row in rows:
        for name in ("variant_id", "products_price_id", "quantity"):
            if type(row.get(name)) is not int or row[name] < 1:
                raise ValueError(f"Each line item needs a positive integer {name}")
        if invoice and not isinstance(row.get("amount"), str):
            raise ValueError("Each invoice line item needs an amount string")
    return rows


class ClickFunnelsListTeamsConfig(PageConfig):
    """List Teams."""
    operation: Literal["list_teams"] = Field(
        "list_teams", title="List Teams", json_schema_extra={
            "const": "list_teams", "ui:hidden": True, "x-category": "Account",
            "x-display-name": "List Teams", "x-is-trigger": False,
        })


class ClickFunnelsListWorkspacesConfig(PageConfig):
    """List Workspaces."""
    operation: Literal["list_workspaces"] = Field(
        "list_workspaces", title="List Workspaces", json_schema_extra={
            "const": "list_workspaces", "ui:hidden": True, "x-category": "Account",
            "x-display-name": "List Workspaces", "x-is-trigger": False,
        })
    team_id: Identifier = Field(..., title="Team ID", json_schema_extra={"x-dynamic-options": {"field_name": "team_id", "searchable": True, "allow_custom": True}})


class ClickFunnelsListContactsConfig(PageConfig):
    """List Contacts."""
    operation: Literal["list_contacts"] = Field(
        "list_contacts", title="List Contacts", json_schema_extra={
            "const": "list_contacts", "ui:hidden": True, "x-category": "Contacts",
            "x-display-name": "List Contacts", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")


class ClickFunnelsGetContactConfig(BaseModel):
    """Fetch Contact."""
    operation: Literal["get_contact"] = Field(
        "get_contact", title="Fetch Contact", json_schema_extra={
            "const": "get_contact", "ui:hidden": True, "x-category": "Contacts",
            "x-display-name": "Fetch Contact", "x-is-trigger": False,
        })
    contact_id: Identifier = Field(..., title="Contact ID")


class ClickFunnelsCreateContactConfig(ContactFields):
    """Create Contact."""
    operation: Literal["create_contact"] = Field(
        "create_contact", title="Create Contact", json_schema_extra={
            "const": "create_contact", "ui:hidden": True, "x-category": "Contacts",
            "x-display-name": "Create Contact", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")
    email_address: str = Field(..., title="Email Address", min_length=1)


class ClickFunnelsUpdateContactConfig(ContactFields):
    """Update Contact."""
    operation: Literal["update_contact"] = Field(
        "update_contact", title="Update Contact", json_schema_extra={
            "const": "update_contact", "ui:hidden": True, "x-category": "Contacts",
            "x-display-name": "Update Contact", "x-is-trigger": False,
        })
    contact_id: Identifier = Field(..., title="Contact ID")


class ClickFunnelsUpsertContactConfig(ContactFields):
    """Upsert a Contact."""
    operation: Literal["upsert_contact"] = Field(
        "upsert_contact", title="Upsert a Contact", json_schema_extra={
            "const": "upsert_contact", "ui:hidden": True, "x-category": "Contacts",
            "x-display-name": "Upsert a Contact", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")
    email_address: str = Field(..., title="Email Address", min_length=1)


class ClickFunnelsListContactTagsConfig(PageConfig):
    """List Tags."""
    operation: Literal["list_contact_tags"] = Field(
        "list_contact_tags", title="List Tags", json_schema_extra={
            "const": "list_contact_tags", "ui:hidden": True, "x-category": "Tags",
            "x-display-name": "List Tags", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")


class ClickFunnelsCreateContactTagConfig(BaseModel):
    """Create Tag."""
    operation: Literal["create_contact_tag"] = Field(
        "create_contact_tag", title="Create Tag", json_schema_extra={
            "const": "create_contact_tag", "ui:hidden": True, "x-category": "Tags",
            "x-display-name": "Create Tag", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")
    name: str = Field(..., min_length=1, title="Tag Name")
    color: str | None = Field(None, title="Color", description="Hex color, for example #FF5733.")


class ClickFunnelsApplyContactTagConfig(BaseModel):
    """Create Applied Tag."""
    operation: Literal["apply_contact_tag"] = Field(
        "apply_contact_tag", title="Create Applied Tag", json_schema_extra={
            "const": "apply_contact_tag", "ui:hidden": True, "x-category": "Tags",
            "x-display-name": "Create Applied Tag", "x-is-trigger": False,
        })
    contact_id: Identifier = Field(..., title="Contact ID")
    tag_id: int = Field(..., ge=1, title="Tag ID", description="Numeric tag ID, not its public ID.")


class ClickFunnelsRemoveContactTagConfig(BaseModel):
    """Remove Applied Tag."""
    operation: Literal["remove_contact_tag"] = Field(
        "remove_contact_tag", title="Remove Applied Tag", json_schema_extra={
            "const": "remove_contact_tag", "ui:hidden": True, "x-category": "Tags",
            "x-display-name": "Remove Applied Tag", "x-is-trigger": False,
        })
    applied_tag_id: Identifier = Field(..., title="Applied Tag ID")


class ClickFunnelsListOrdersConfig(PageConfig):
    """List Orders."""
    operation: Literal["list_orders"] = Field(
        "list_orders", title="List Orders", json_schema_extra={
            "const": "list_orders", "ui:hidden": True, "x-category": "Orders",
            "x-display-name": "List Orders", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")


class ClickFunnelsGetOrderConfig(BaseModel):
    """Fetch Order."""
    operation: Literal["get_order"] = Field(
        "get_order", title="Fetch Order", json_schema_extra={
            "const": "get_order", "ui:hidden": True, "x-category": "Orders",
            "x-display-name": "Fetch Order", "x-is-trigger": False,
        })
    order_id: Identifier = Field(..., title="Order ID")


class ClickFunnelsCreateOrderConfig(BaseModel):
    """Create External Order."""
    operation: Literal["create_order"] = Field(
        "create_order", title="Create External Order", json_schema_extra={
            "const": "create_order", "ui:hidden": True, "x-category": "Orders",
            "x-display-name": "Create External Order", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")
    order_type: Literal["one-time-order", "subscription-order"] = Field("one-time-order", title="Order Type")
    live_mode: bool = Field(..., title="Live Mode", description="Yes for production, No for test orders.")
    contact_id: int = Field(..., ge=1, title="Contact ID", description="Numeric contact ID.")
    line_items_json: str = Field(..., title="Line Items", description="JSON array with variant_id, products_price_id and quantity for each item.", json_schema_extra=JSON_EDITOR)
    external_id: str | None = Field(None, title="External ID")
    notes: str | None = Field(None, title="Notes")


class ClickFunnelsCreateInvoiceConfig(BaseModel):
    """Create External Invoice."""
    operation: Literal["create_invoice"] = Field(
        "create_invoice", title="Create External Invoice", json_schema_extra={
            "const": "create_invoice", "ui:hidden": True, "x-category": "Orders",
            "x-display-name": "Create External Invoice", "x-is-trigger": False,
        })
    order_id: Identifier = Field(..., title="Order ID")
    external_id: str = Field(..., min_length=1, title="External Invoice ID")
    status: Literal["unpaid", "paid", "voided", "refunded", "disputed", "past-due"] = Field(..., title="Status")
    paid_at: str | None = Field(None, title="Paid At", description="ISO 8601 timestamp; required when status is paid.")
    line_items_json: str = Field(..., title="Line Items", description="JSON array with amount, quantity, variant_id and products_price_id for each item.", json_schema_extra=JSON_EDITOR)

    @model_validator(mode="after")
    def require_paid_timestamp(self):
        if self.status == "paid" and not self.paid_at:
            raise ValueError("Paid At is required for a paid invoice")
        return self


class ClickFunnelsListTransactionsConfig(PageConfig):
    """List Transactions."""
    operation: Literal["list_transactions"] = Field(
        "list_transactions", title="List Transactions", json_schema_extra={
            "const": "list_transactions", "ui:hidden": True, "x-category": "Orders",
            "x-display-name": "List Transactions", "x-is-trigger": False,
        })
    order_id: Identifier = Field(..., title="Order ID")


class ClickFunnelsListCoursesConfig(PageConfig):
    """List Courses."""
    operation: Literal["list_courses"] = Field(
        "list_courses", title="List Courses", json_schema_extra={
            "const": "list_courses", "ui:hidden": True, "x-category": "Courses",
            "x-display-name": "List Courses", "x-is-trigger": False,
        })
    workspace_id: Identifier = Field(..., title="Workspace ID")


class ClickFunnelsListEnrollmentsConfig(PageConfig):
    """List Enrollments."""
    operation: Literal["list_enrollments"] = Field(
        "list_enrollments", title="List Enrollments", json_schema_extra={
            "const": "list_enrollments", "ui:hidden": True, "x-category": "Courses",
            "x-display-name": "List Enrollments", "x-is-trigger": False,
        })
    course_id: Identifier = Field(..., title="Course ID")


class ClickFunnelsCreateEnrollmentConfig(BaseModel):
    """Create Enrollment."""
    operation: Literal["create_enrollment"] = Field(
        "create_enrollment", title="Create Enrollment", json_schema_extra={
            "const": "create_enrollment", "ui:hidden": True, "x-category": "Courses",
            "x-display-name": "Create Enrollment", "x-is-trigger": False,
        })
    course_id: Identifier = Field(..., title="Course ID")
    contact_id: int = Field(..., ge=1, title="Contact ID", description="Numeric contact ID.")
    suspended: bool | None = Field(None, title="Suspended")
    suspension_reason: str | None = Field(None, title="Suspension Reason")


class ClickFunnelsUpdateEnrollmentConfig(BaseModel):
    """Update Enrollment."""
    operation: Literal["update_enrollment"] = Field(
        "update_enrollment", title="Update Enrollment", json_schema_extra={
            "const": "update_enrollment", "ui:hidden": True, "x-category": "Courses",
            "x-display-name": "Update Enrollment", "x-is-trigger": False,
        })
    enrollment_id: Identifier = Field(..., title="Enrollment ID")
    suspended: bool | None = Field(None, title="Suspended")
    suspension_reason: str | None = Field(None, title="Suspension Reason")


ClickFunnelsConfig = Annotated[
    Union[
        ClickFunnelsListTeamsConfig,
        ClickFunnelsListWorkspacesConfig,
        ClickFunnelsListContactsConfig,
        ClickFunnelsGetContactConfig,
        ClickFunnelsCreateContactConfig,
        ClickFunnelsUpdateContactConfig,
        ClickFunnelsUpsertContactConfig,
        ClickFunnelsListContactTagsConfig,
        ClickFunnelsCreateContactTagConfig,
        ClickFunnelsApplyContactTagConfig,
        ClickFunnelsRemoveContactTagConfig,
        ClickFunnelsListOrdersConfig,
        ClickFunnelsGetOrderConfig,
        ClickFunnelsCreateOrderConfig,
        ClickFunnelsCreateInvoiceConfig,
        ClickFunnelsListTransactionsConfig,
        ClickFunnelsListCoursesConfig,
        ClickFunnelsListEnrollmentsConfig,
        ClickFunnelsCreateEnrollmentConfig,
        ClickFunnelsUpdateEnrollmentConfig,
    ], Discriminator("operation"),
]


class ClickFunnelsNodeConfig(NodeConfig[ClickFunnelsConfig, ClickFunnelsAPIKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


# One entry per documented API operation: method, route, path fields, envelope, list key.
OPERATIONS = {
    'list_teams': ('GET', '/teams', {}, None, 'teams'),
    'list_workspaces': ('GET', '/teams/{team_id}/workspaces', {'team_id': 'team_id'}, None, 'workspaces'),
    'list_contacts': ('GET', '/workspaces/{workspace_id}/contacts', {'workspace_id': 'workspace_id'}, None, 'contacts'),
    'get_contact': ('GET', '/contacts/{id}', {'id': 'contact_id'}, None, None),
    'create_contact': ('POST', '/workspaces/{workspace_id}/contacts', {'workspace_id': 'workspace_id'}, 'contact', None),
    'update_contact': ('PUT', '/contacts/{id}', {'id': 'contact_id'}, 'contact', None),
    'upsert_contact': ('POST', '/workspaces/{workspace_id}/contacts/upsert', {'workspace_id': 'workspace_id'}, 'contact', None),
    'list_contact_tags': ('GET', '/workspaces/{workspace_id}/contacts/tags', {'workspace_id': 'workspace_id'}, None, 'tags'),
    'create_contact_tag': ('POST', '/workspaces/{workspace_id}/contacts/tags', {'workspace_id': 'workspace_id'}, 'contacts_tag', None),
    'apply_contact_tag': ('POST', '/contacts/{contact_id}/applied_tags', {'contact_id': 'contact_id'}, 'contacts_applied_tag', None),
    'remove_contact_tag': ('DELETE', '/contacts/applied_tags/{id}', {'id': 'applied_tag_id'}, None, None),
    'list_orders': ('GET', '/workspaces/{workspace_id}/orders', {'workspace_id': 'workspace_id'}, None, 'orders'),
    'get_order': ('GET', '/orders/{id}', {'id': 'order_id'}, None, None),
    'create_order': ('POST', '/workspaces/{workspace_id}/orders', {'workspace_id': 'workspace_id'}, 'order', None),
    'create_invoice': ('POST', '/orders/{order_id}/invoices', {'order_id': 'order_id'}, 'orders_invoice', None),
    'list_transactions': ('GET', '/orders/{order_id}/transactions', {'order_id': 'order_id'}, None, 'transactions'),
    'list_courses': ('GET', '/workspaces/{workspace_id}/courses', {'workspace_id': 'workspace_id'}, None, 'courses'),
    'list_enrollments': ('GET', '/courses/{course_id}/enrollments', {'course_id': 'course_id'}, None, 'enrollments'),
    'create_enrollment': ('POST', '/courses/{course_id}/enrollments', {'course_id': 'course_id'}, 'courses_enrollment', None),
    'update_enrollment': ('PUT', '/courses/enrollments/{id}', {'id': 'enrollment_id'}, 'courses_enrollment', None),
}


class ClickFunnelsNode(WorkflowNode):
    integration_type = "automation-clickfunnels"
    connection_evidence = ConnectionEvidence(field="team_id", noun="teams")
    edit_examples = ["Create a ClickFunnels lead", "Tag a ClickFunnels contact",
                     "Sync external purchases to ClickFunnels", "Enroll a customer in a course"]

    @classmethod
    def get_config_model(cls):
        return ClickFunnelsNodeConfig

    @staticmethod
    async def _request(credential: ClickFunnelsAPIKeyCredential, method: str, path: str,
                       *, params=None, body=None, account: bool = False):
        host = "accounts" if account else credential.workspace_subdomain
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, f"https://{host}.myclickfunnels.com/api/v2{path}",
                headers={"Authorization": f"Bearer {credential.api_key}",
                         "Accept": "application/json", "User-Agent": "NoClick/ClickFunnels"},
                params=params, json=body,
            )
        if response.is_error:
            # Keep the provider's rejection intact for the manual-connect verdict.
            raise ValueError(f"ClickFunnels API {response.status_code}: {response.text}")
        if response.status_code == 204:
            return None, response
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"ClickFunnels returned non-JSON ({response.status_code})") from exc
        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors")):
            raise ValueError(f"ClickFunnels API: {response.text}")
        return payload, response

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict[str, Any],
                                 context=None, search=None, page_token=None):
        if field_name != "team_id":
            return []
        credential = ClickFunnelsAPIKeyCredential.model_validate(credential_data)
        params = {"per_page": 100}
        if page_token:
            params["after"] = page_token
        rows, _ = await cls._request(credential, "GET", "/teams", params=params, account=True)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or "id" not in row for row in rows):
            raise ValueError("ClickFunnels returned an invalid teams list")
        return [{"value": str(row["id"]), "label": row.get("name") or str(row["id"])}
                for row in rows if not search or search.lower() in str(row.get("name", "")).lower()]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ClickFunnelsNodeConfig):
            raise ValueError("ClickFunnels configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a ClickFunnels API key")
        started = time.monotonic()
        config = self.config.config
        method, route, path_fields, wrapper, result_key = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        path = route.format(**{key: values.pop(field) for key, field in path_fields.items()})
        params = values if method == "GET" else None
        body = None
        if wrapper:
            if "custom_attributes_json" in values:
                custom = _json_object(values.pop("custom_attributes_json"), "Custom Attributes")
                if any(not isinstance(v, str) for v in custom.values()):
                    raise ValueError("Custom Attribute values must be strings")
                values["custom_attributes"] = custom
            if "line_items_json" in values:
                values["line_items_attributes"] = _line_items(
                    values.pop("line_items_json"), invoice=config.operation == "create_invoice")
            if not values:
                raise ValueError("Provide at least one field to update")
            body = {wrapper: values}
        payload, response = await self._request(
            credential, method, path, params=params, body=body,
            account=config.operation in {"list_teams", "list_workspaces"},
        )
        if result_key:
            if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                raise ValueError("ClickFunnels returned an invalid resource list")
            data = {result_key: payload, "count": len(payload),
                    "next_cursor": response.headers.get("Pagination-Next"),
                    "next_link": response.headers.get("Link")}
        elif method == "DELETE":
            data = {"deleted": True}
        else:
            if not isinstance(payload, dict):
                raise ValueError("ClickFunnels returned an invalid resource object")
            data = payload
        return {"status": "success", "action": config.operation, "data": data,
                "status_code": response.status_code,
                "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}
