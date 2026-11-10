"""Thinkific Admin API v1: students, enrollments, courses, bundles and commerce.

Contract: https://developers.thinkific.com/openapi/thinkific-admin-api-v1.yaml
Token auth: https://support.thinkific.dev/hc/en-us/articles/38357676036887
Each operation performs one documented API request; lists return one page and
preserve meta.pagination for subsequent sync runs. External orders are stored by
Thinkific but do not appear in its orders report/dashboard. Signed triggers use
the Webhooks API v2 and documented event examples:
https://developers.thinkific.com/openapi/thinkific-webhooks-v2.yaml
https://support.thinkific.dev/hc/en-us/articles/4422658311703-Webhooks-Documentation
https://support.thinkific.dev/hc/en-us/articles/4422685850775-Using-Webhooks
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import time
import hashlib
import hmac
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

THINKIFIC_WEBHOOK_BASE = "https://platform.thinkific.com/api/v2"

THINKIFIC_API_BASE = "https://api.thinkific.com/api/public/v1"


class ThinkificAPITokenCredential(BaseModel):
    credential_type: Literal["thinkific_api_token"] = Field(
        "thinkific_api_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="API Access Token",
        min_length=1,
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Thinkific API Access Token",
        json_schema_extra={
            "x-credential-url": "https://support.thinkific.com/hc/en-us/articles/360052415534-How-to-Create-API-Access-Tokens",
            "x-credential-instructions": "In Thinkific, open Settings → Code & analytics → API Access Tokens. Create a token and paste it here. Your plan must include API access. Rotate the token before it expires.",
        },
    )


class ThinkificTransaction(BaseModel):
    amount: int = Field(
        ...,
        ge=0,
        description="Amount in the currency's smallest unit (for example, cents).",
    )
    currency: str = Field(
        ..., min_length=3, max_length=3, description="Currency code, for example USD."
    )
    reference: str | None = Field(
        None, description="Reference from your external payment provider."
    )
    action: Literal["purchase"] = "purchase"


class ThinkificProfileField(BaseModel):
    custom_profile_field_definition_id: int = Field(..., gt=0)
    value: str


class ThinkificListStudentsConfig(BaseModel):
    """List Users: GET /users."""

    operation: Literal["list_students"] = Field(
        "list_students",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Students",
            "x-category": "Students",
        },
    )
    page: int = Field(1, ge=1, description="The page within the collection to fetch")
    limit: int = Field(25, ge=1, description="The number of items to be returned")
    email: str | None = Field(None, description="Search Users by email.")
    role: str | None = Field(None, description="Search Users by role.")


class ThinkificGetStudentConfig(BaseModel):
    """List Users by ID: GET /users/{id}."""

    operation: Literal["get_student"] = Field(
        "get_student",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Student",
            "x-category": "Students",
        },
    )
    student_id: int = Field(..., gt=0, title="Student Id")


class ThinkificCreateStudentConfig(BaseModel):
    """Create user: POST /users."""

    operation: Literal["create_student"] = Field(
        "create_student",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create Student",
            "x-category": "Students",
        },
    )
    first_name: str = Field(..., description="User's first name ")
    last_name: str = Field(..., description="User's last name")
    email: str = Field(..., description="User's email")
    bio: str | None = Field(None, description="User's bio")
    company: str | None = Field(None, description="User's Company Name")
    headline: str | None = Field(None, description="User's headline")
    custom_profile_fields: list[ThinkificProfileField] | None = Field(
        None, description="Custom profile fields for the User."
    )
    send_welcome_email: bool | None = Field(
        None,
        description="Option to send the Site Welcome email to the User. Leave it false when your system delivers the Express Sign In Link itself through `POST /users/{id}/express_sign_in_link`.",
    )
    external_id: str | None = Field(
        None,
        description="Optional identifier of the user in an external system. Typically used in conjunction with Thinkific's single sign-on. For further information on this, please read [this](https://help.thinkific.com/support/solutions/articles/221622-sso-automatically-sign-in-from-your-own-website)",
    )
    provider: Literal["SSO", "OPENID_CONNECT"] | None = Field(
        None,
        description="When using Thinkific single sign-on and providing an external_id, specify the provider type to distinguish which single sign-on type the user should be associated with.",
    )


class ThinkificUpdateStudentConfig(BaseModel):
    """Update user by ID: PUT /users/{id}."""

    operation: Literal["update_student"] = Field(
        "update_student",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update Student",
            "x-category": "Students",
        },
    )
    student_id: int = Field(..., gt=0, title="Student Id")
    first_name: str | None = Field(None, description="User's first name ")
    last_name: str | None = Field(None, description="User's last name")
    email: str | None = Field(
        None,
        description="User's email. This can only be updated by private integrations.",
    )
    bio: str | None = Field(None, description="User's bio")
    company: str | None = Field(None, description="User's Company Name")
    headline: str | None = Field(None, description="User's headline")
    custom_profile_fields: list[ThinkificProfileField] | None = Field(
        None, description="Custom profile fields for the User."
    )


class ThinkificListCoursesConfig(BaseModel):
    """Get Courses: GET /courses."""

    operation: Literal["list_courses"] = Field(
        "list_courses",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Courses",
            "x-category": "Courses",
        },
    )
    page: int = Field(1, ge=1, description="The page within the collection to fetch.")
    limit: int = Field(25, ge=1, description="The number of items to be returned")


class ThinkificGetCourseConfig(BaseModel):
    """Get courses by ID: GET /courses/{id}."""

    operation: Literal["get_course"] = Field(
        "get_course",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Course",
            "x-category": "Courses",
        },
    )
    course_id: int = Field(..., gt=0, title="Course Id")


class ThinkificListEnrollmentsConfig(BaseModel):
    """Get Enrollments: GET /enrollments."""

    operation: Literal["list_enrollments"] = Field(
        "list_enrollments",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Enrollments",
            "x-category": "Enrollments",
        },
    )
    page: int = Field(1, ge=1, description="The page within the collection to fetch.")
    limit: int = Field(25, ge=1, description="The number of items to be returned.")
    user_id: int | None = Field(None, description="Search Enrollments by User ID.")
    course_id: int | None = Field(None, description="Search Enrollments by Course ID.")
    email: str | None = Field(None, description="Search Enrollments by User email.")
    free_trial: bool | None = Field(
        None, description="Filter for only Free Trial Enrollments when set to true."
    )
    full: bool | None = Field(
        None, description="Filter for only full Enrollments when set to true."
    )
    completed: bool | None = Field(
        None, description="Filter for only completed Enrollments when set to true."
    )
    expired: bool | None = Field(
        None, description="Filter for only expired Enrollments when set to true."
    )
    created_after: str | None = Field(
        None,
        description="Filter for only Enrollments created after the date specified.",
    )
    updated_after: str | None = Field(
        None,
        description="Filter for only Enrollments updated after the date specified.",
    )


class ThinkificGetEnrollmentConfig(BaseModel):
    """Get enrollments by ID: GET /enrollments/{id}."""

    operation: Literal["get_enrollment"] = Field(
        "get_enrollment",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Enrollment",
            "x-category": "Enrollments",
        },
    )
    enrollment_id: int = Field(..., gt=0, title="Enrollment Id")


class ThinkificCreateEnrollmentConfig(BaseModel):
    """Create enrollment: POST /enrollments."""

    operation: Literal["create_enrollment"] = Field(
        "create_enrollment",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create Enrollment",
            "x-category": "Enrollments",
        },
    )
    course_id: int = Field(..., description="The ID of the Course as an integer.")
    user_id: int = Field(
        ..., description="The ID of the User owning the Enrollment as an integer."
    )
    activated_at: str | None = Field(
        None,
        description="The date/time at which the Enrollment is activated. If not provided, the Enrollment is a free trial.",
    )
    expiry_date: str | None = Field(
        None,
        description="The date/time at which the Enrollment expired. If not provided, the Enrollment does not expire.",
    )


class ThinkificUpdateEnrollmentConfig(BaseModel):
    """Update enrollment: PUT /enrollments/{id}."""

    operation: Literal["update_enrollment"] = Field(
        "update_enrollment",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update Enrollment",
            "x-category": "Enrollments",
        },
    )
    enrollment_id: int = Field(..., gt=0, title="Enrollment Id")
    activated_at: str | None = Field(
        None,
        description="The date/time at which the Enrollment is activated. If not provided, the Enrollment is a free trial.",
    )
    expiry_date: str | None = Field(
        None,
        description="The date/time at which the Enrollment expired. If not provided, the Enrollment does not expire.",
    )


class ThinkificGetBundleConfig(BaseModel):
    """List a bundle: GET /bundles/{id}."""

    operation: Literal["get_bundle"] = Field(
        "get_bundle",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Bundle",
            "x-category": "Bundles",
        },
    )
    bundle_id: int = Field(..., gt=0, title="Bundle Id")


class ThinkificListBundleCoursesConfig(BaseModel):
    """List Courses by bundle ID: GET /bundles/{id}/courses."""

    operation: Literal["list_bundle_courses"] = Field(
        "list_bundle_courses",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Bundle Courses",
            "x-category": "Bundles",
        },
    )
    bundle_id: int = Field(..., gt=0, title="Bundle Id")
    page: int = Field(1, ge=1, description="The page within the collection to fetch")
    limit: int = Field(25, ge=1, description="The number of items to be returned")


class ThinkificListBundleEnrollmentsConfig(BaseModel):
    """List a enrollments in a bundle: GET /bundles/{id}/enrollments."""

    operation: Literal["list_bundle_enrollments"] = Field(
        "list_bundle_enrollments",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Bundle Enrollments",
            "x-category": "Bundles",
        },
    )
    bundle_id: int = Field(..., gt=0, title="Bundle Id")
    page: int = Field(1, ge=1, description="The page within the collection to fetch")
    limit: int = Field(25, ge=1, description="The number of items to be returned")
    user_id: int | None = Field(
        None, description="Search Bundle Enrollments by User ID."
    )
    email: str | None = Field(
        None, description="Search Bundle Enrollments by User email"
    )
    created_after: str | None = Field(
        None,
        description="Filter for only Enrollments created after the date specified.",
    )
    updated_after: str | None = Field(
        None,
        description="Filter for only Enrollments updated after the date specified.",
    )


class ThinkificEnrollInBundleConfig(BaseModel):
    """Create an Enrollment in a Bundle of Courses: POST /bundles/{id}/enrollments."""

    operation: Literal["enroll_in_bundle"] = Field(
        "enroll_in_bundle",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Enroll In Bundle",
            "x-category": "Bundles",
        },
    )
    bundle_id: int = Field(..., gt=0, title="Bundle Id")
    user_id: int = Field(..., description="user id")
    activated_at: str | None = Field(
        None,
        description="The date/time at which the Enrollment is to be activated. If not provided, the Enrollment will only provide access to free preview content within the Courses. Provide full access to courses by setting this value to the current date/time.",
    )
    expiry_date: str | None = Field(
        None,
        description="The date/time at which the Enrollment should be expired. If not provided, the Enrollment does not expire.",
    )


class ThinkificListOrdersConfig(BaseModel):
    """Get Orders: GET /orders."""

    operation: Literal["list_orders"] = Field(
        "list_orders",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Orders",
            "x-category": "Orders",
        },
    )
    page: int = Field(1, ge=1, description="The page within the collection to fetch.")
    limit: int = Field(25, ge=1, description="The number of items to be returned.")


class ThinkificGetOrderConfig(BaseModel):
    """Get orders by ID: GET /orders/{id}."""

    operation: Literal["get_order"] = Field(
        "get_order",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Order",
            "x-category": "Orders",
        },
    )
    order_id: int = Field(..., gt=0, title="Order Id")


class ThinkificListProductsConfig(BaseModel):
    """List products: GET /products."""

    operation: Literal["list_products"] = Field(
        "list_products",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List Products",
            "x-category": "Products",
        },
    )
    page: int = Field(1, ge=1, description="The page within the collection to fetch")
    limit: int = Field(25, ge=1, description="The number of items to be returned")


class ThinkificGetProductConfig(BaseModel):
    """Get product by ID: GET /products/{id}."""

    operation: Literal["get_product"] = Field(
        "get_product",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Get Product",
            "x-category": "Products",
        },
    )
    product_id: int = Field(..., gt=0, title="Product Id")


class ThinkificCreateExternalOrderConfig(BaseModel):
    """Record an external order. These records do not appear in Thinkific orders reports or the dashboard."""

    operation: Literal["create_external_order"] = Field(
        "create_external_order",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create External Order",
            "x-category": "Orders",
        },
    )
    payment_provider: str = Field(..., description="An identifier to external provider")
    user_id: int = Field(..., description="The ID of the user as an integer")
    product_id: int = Field(..., description="The ID of the product as an integer")
    order_type: Literal["one-time", "subscription", "payment-plan"] = Field(
        ..., description="type of the order"
    )
    transaction: ThinkificTransaction | None = Field(
        None, description="External Order Transaction"
    )


class ThinkificRecordPurchaseConfig(BaseModel):
    """purchase transaction: POST /external_orders/{id}/transactions/purchase."""

    operation: Literal["record_purchase"] = Field(
        "record_purchase",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Record Purchase",
            "x-category": "Orders",
        },
    )
    external_order_id: int = Field(..., gt=0, title="External Order Id")
    amount: int = Field(
        ...,
        ge=0,
        description="Amount in the currency's smallest unit, for example cents.",
    )
    currency: str = Field(
        ..., min_length=3, max_length=3, description="Currency code, for example USD."
    )
    reference: str | None = Field(
        None, description="reference number provided by external payment provider"
    )
    action: Literal["purchase"] = Field(
        "purchase", description="Record an external purchase transaction."
    )


# Event names and payloads: Thinkific's Webhooks Documentation linked above.
THINKIFIC_TRIGGERS = {
    "on_student_signup": ("user.signup", "New Student"),
    "on_student_updated": ("user.updated", "Student Updated"),
    "on_enrollment_created": ("enrollment.created", "New Enrollment"),
    "on_enrollment_trial": ("enrollment.trial", "New Trial Enrollment"),
    "on_enrollment_completed": ("enrollment.completed", "Course Completed"),
    "on_enrollment_progress": ("enrollment.progress", "Course Progress Updated"),
    "on_order_created": ("order.created", "New Order"),
    "on_lesson_completed": ("lesson.completed", "Lesson Completed"),
}


class ThinkificWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(
        None, title="Webhook URL", description="Registered with Thinkific automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


THINKIFIC_TRIGGER_MODELS = tuple(
    create_model(
        "Thinkific" + "".join(part.title() for part in operation.split("_")) + "Config",
        __base__=ThinkificWebhookConfig, __module__=__name__,
        operation=(Literal[operation], Field(operation, json_schema_extra={
            "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
            "x-display-name": label,
        })),
    )
    for operation, (_, label) in THINKIFIC_TRIGGERS.items()
)
globals().update({model.__name__: model for model in THINKIFIC_TRIGGER_MODELS})


ThinkificConfig = Annotated[
    Union[
        ThinkificListStudentsConfig,
        ThinkificGetStudentConfig,
        ThinkificCreateStudentConfig,
        ThinkificUpdateStudentConfig,
        ThinkificListCoursesConfig,
        ThinkificGetCourseConfig,
        ThinkificListEnrollmentsConfig,
        ThinkificGetEnrollmentConfig,
        ThinkificCreateEnrollmentConfig,
        ThinkificUpdateEnrollmentConfig,
        ThinkificGetBundleConfig,
        ThinkificListBundleCoursesConfig,
        ThinkificListBundleEnrollmentsConfig,
        ThinkificEnrollInBundleConfig,
        ThinkificListOrdersConfig,
        ThinkificGetOrderConfig,
        ThinkificListProductsConfig,
        ThinkificGetProductConfig,
        ThinkificCreateExternalOrderConfig,
        ThinkificRecordPurchaseConfig,
        *THINKIFIC_TRIGGER_MODELS,
    ],
    Field(discriminator="operation"),
]


class ThinkificNodeConfig(NodeConfig[ThinkificConfig, ThinkificAPITokenCredential]):
    pass


# Each route is one documented API operation. Query mappings preserve bracketed wire names.
OPERATIONS = {
    "list_students": (
        "GET",
        "/users",
        None,
        {
            "page": "page",
            "limit": "limit",
            "email": "query[email]",
            "role": "query[role]",
        },
        [],
        True,
    ),
    "get_student": ("GET", "/users/{id}", "student_id", {}, [], False),
    "create_student": (
        "POST",
        "/users",
        None,
        {},
        [
            "first_name",
            "last_name",
            "email",
            "bio",
            "company",
            "headline",
            "custom_profile_fields",
            "send_welcome_email",
            "external_id",
            "provider",
        ],
        False,
    ),
    "update_student": (
        "PUT",
        "/users/{id}",
        "student_id",
        {},
        [
            "first_name",
            "last_name",
            "email",
            "bio",
            "company",
            "headline",
            "custom_profile_fields",
        ],
        False,
    ),
    "list_courses": (
        "GET",
        "/courses",
        None,
        {"page": "page", "limit": "limit"},
        [],
        True,
    ),
    "get_course": ("GET", "/courses/{id}", "course_id", {}, [], False),
    "list_enrollments": (
        "GET",
        "/enrollments",
        None,
        {
            "page": "page",
            "limit": "limit",
            "user_id": "query[user_id]",
            "course_id": "query[course_id]",
            "email": "query[email]",
            "free_trial": "query[free_trial]",
            "full": "query[full]",
            "completed": "query[completed]",
            "expired": "query[expired]",
            "created_after": "query[created_after]",
            "updated_after": "query[updated_after]",
        },
        [],
        True,
    ),
    "get_enrollment": ("GET", "/enrollments/{id}", "enrollment_id", {}, [], False),
    "create_enrollment": (
        "POST",
        "/enrollments",
        None,
        {},
        ["course_id", "user_id", "activated_at", "expiry_date"],
        False,
    ),
    "update_enrollment": (
        "PUT",
        "/enrollments/{id}",
        "enrollment_id",
        {},
        ["activated_at", "expiry_date"],
        False,
    ),
    "get_bundle": ("GET", "/bundles/{id}", "bundle_id", {}, [], False),
    "list_bundle_courses": (
        "GET",
        "/bundles/{id}/courses",
        "bundle_id",
        {"page": "page", "limit": "limit"},
        [],
        True,
    ),
    "list_bundle_enrollments": (
        "GET",
        "/bundles/{id}/enrollments",
        "bundle_id",
        {
            "page": "page",
            "limit": "limit",
            "user_id": "query[user_id]",
            "email": "query[email]",
            "created_after": "query[created_after]",
            "updated_after": "query[updated_after]",
        },
        [],
        True,
    ),
    "enroll_in_bundle": (
        "POST",
        "/bundles/{id}/enrollments",
        "bundle_id",
        {},
        ["user_id", "activated_at", "expiry_date"],
        False,
    ),
    "list_orders": (
        "GET",
        "/orders",
        None,
        {"page": "page", "limit": "limit"},
        [],
        True,
    ),
    "get_order": ("GET", "/orders/{id}", "order_id", {}, [], False),
    "list_products": (
        "GET",
        "/products",
        None,
        {"page": "page", "limit": "limit"},
        [],
        True,
    ),
    "get_product": ("GET", "/products/{id}", "product_id", {}, [], False),
    "create_external_order": (
        "POST",
        "/external_orders",
        None,
        {},
        ["payment_provider", "user_id", "product_id", "order_type", "transaction"],
        False,
    ),
    "record_purchase": (
        "POST",
        "/external_orders/{id}/transactions/purchase",
        "external_order_id",
        {},
        ["amount", "currency", "reference", "action"],
        False,
    ),
}


class ThinkificNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-thinkific"
    connection_evidence = ConnectionEvidence(operation="list_courses", noun="courses")
    edit_examples = [
        "Create a student and enroll them in a course",
        "Enroll a student in all courses in a bundle",
        "Sync Thinkific orders and learner progress to my CRM",
        "Record a purchase from my external payment provider",
    ]

    @classmethod
    def get_config_model(cls):
        return ThinkificNodeConfig

    @staticmethod
    async def _webhook_request(token, method, path, body=None):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, THINKIFIC_WEBHOOK_BASE + path, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        # A deleted subscription already satisfies cleanup.
        if method == "DELETE" and response.status_code == 404:
            return {}
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Thinkific webhook request failed (HTTP {response.status_code})")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        operation = (config or {}).get("operation")
        if operation not in THINKIFIC_TRIGGERS:
            raise ValueError("Choose a Thinkific trigger")
        token = credential.get("access_token")
        if not token:
            raise ValueError("Connect a Thinkific API access token")
        data = await cls._webhook_request(token, "POST", "/webhooks", {
            "topic": THINKIFIC_TRIGGERS[operation][0], "target_url": webhook_url,
            "generate_signing_secret": True,
        })
        endpoint_id = data.get("id")
        secret = data.get("signing_secret")
        if not endpoint_id:
            raise ValueError("Thinkific did not return a webhook ID")
        if not secret:
            # Signing secrets are rolling out. Never leave an unverifiable subscription behind.
            await cls._webhook_request(token, "DELETE", f"/webhooks/{quote(str(endpoint_id), safe='')}")
            raise ValueError("Thinkific has not enabled webhook signing secrets for this site; contact Thinkific support")
        return {"external_webhook_id": str(endpoint_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id and credential and credential.get("access_token"):
            await cls._webhook_request(
                credential["access_token"], "DELETE", f"/webhooks/{quote(str(endpoint_id), safe='')}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-thinkific-hmac-sha256"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return len(signature) == 64 and signature.isascii() and hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        expected = THINKIFIC_TRIGGERS.get((config or {}).get("operation"))
        return bool(expected and isinstance(payload, dict)
                    and f"{payload.get('resource')}.{payload.get('action')}" == expected[0]
                    and isinstance(payload.get("payload"), dict))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return super().resolve_agent_event(output)
        resource, action = output.get("resource"), output.get("action")
        topic = f"{resource}.{action}"
        if topic not in {event for event, _ in THINKIFIC_TRIGGERS.values()}:
            return super().resolve_agent_event(output)
        record = output["payload"]
        user = record if resource == "user" else record["user"]
        name = " ".join(str(user.get(key) or "") for key in ("first_name", "last_name")).strip()
        lines = [f"Thinkific {topic}: {name} ({user.get('email')})",
                 f"Site ID: {output.get('tenant_id')}; student_id: {user.get('id')}",
                 f"At: {output.get('created_at')}; event_id: {output.get('id')}"]
        if resource == "enrollment":
            course = record["course"]
            lines += [f"Course: {course.get('name')} (course_id: {course.get('id')})",
                      f"enrollment_id: {record.get('id')}; progress: {record.get('percentage_completed')}"]
        elif resource == "lesson":
            course, lesson = record["course"], record["lesson"]
            lines += [f"Course: {course.get('name')} (course_id: {course.get('id')})",
                      f"Lesson: {lesson.get('name')} (lesson_id: {lesson.get('id')})",
                      f"enrollment_id: {record['enrollment'].get('id')}"]
        elif resource == "order":
            lines += [f"Order #{record.get('order_number')} (order_id: {record.get('id')}): {record.get('status')}",
                      f"Product: {record.get('product_name')} (product_id: {record.get('product_id')})",
                      f"Amount: {record.get('amount_cents')} cents; payment type: {record.get('payment_type')}"]
        title = lines[0]
        return {"text": "\n".join(lines), "title": title,
                "conversation_key": f"{output.get('tenant_id')}:student:{user.get('id')}"}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ThinkificNodeConfig):
            raise ValueError("A valid Thinkific configuration is required")
        credentials = self.config.credentials
        if credentials is None:
            raise ValueError("Connect a Thinkific API access token")
        op = self.config.config
        if isinstance(op, ThinkificWebhookConfig):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload") or inputs
            return self.resolve_trigger_payload(payload, op.model_dump())
        method, path, id_field, query_fields, body_fields, is_list = OPERATIONS[
            op.operation
        ]
        values = op.model_dump(mode="json", exclude_none=True)
        if id_field:
            path = path.replace("{id}", quote(str(values[id_field]), safe=""))
        params = {
            wire: values[field]
            for field, wire in query_fields.items()
            if field in values and values[field] != ""
        }
        body = (
            {field: values[field] for field in body_fields if field in values}
            if body_fields
            else None
        )
        started = time.monotonic()

        def result(status, **kwargs):
            return {
                "status": status,
                "action": op.operation,
                **kwargs,
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    THINKIFIC_API_BASE + path,
                    params=params,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {credentials.access_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException:
            return result("error", error="Thinkific request timed out")
        except httpx.RequestError:
            return result("error", error="Could not reach the Thinkific API")
        code = response.status_code
        if not 200 <= code < 300:
            # Retain the provider's rejection for connection verification, with the
            # secret removed if an upstream proxy happens to echo it.
            try:
                error = response.json()
                error = (
                    error.get("error", error.get("errors"))
                    if isinstance(error, dict)
                    else None
                )
            except ValueError:
                error = None
            message = (
                str(error) if error else f"Thinkific API request failed (HTTP {code})"
            )
            return result(
                "error",
                status_code=code,
                error=message.replace(credentials.access_token, "[redacted]"),
            )
        # Thinkific documents empty 204 updates, 201/202 bundle enrollment,
        # and 200 external purchase acknowledgements without response schemas.
        empty_success = code == 204 or op.operation in {
            "enroll_in_bundle",
            "record_purchase",
        }
        if empty_success and not response.content:
            return result("success", status_code=code, data={"success": True})
        try:
            data = response.json()
        except ValueError:
            return result(
                "error", status_code=code, error="Thinkific returned invalid JSON"
            )
        if not isinstance(data, dict) or "error" in data or "errors" in data:
            return result(
                "error",
                status_code=code,
                error="Thinkific returned an unexpected response",
            )
        if is_list:
            items = data.get("items")
            if not isinstance(items, list) or any(
                not isinstance(item, dict) for item in items
            ):
                return result(
                    "error",
                    status_code=code,
                    error="Thinkific returned an invalid collection",
                )
            if op.operation == "list_courses" and any(
                "id" not in x or "name" not in x for x in items
            ):
                return result(
                    "error",
                    status_code=code,
                    error="Thinkific returned an invalid course list",
                )
        elif not empty_success and "id" not in data:
            return result(
                "error",
                status_code=code,
                error="Thinkific returned an invalid resource",
            )
        return result("success", status_code=code, data=data)
