"""LearnWorlds public API v2 operations. One request per operation; lists expose one page."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class LearnWorldsAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="LearnWorlds Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.learnworlds.com/support/solutions/articles/12000080177-how-to-request-your-api-keys-and-access-tokens",
            "x-credential-instructions": "In your LearnWorlds school, open Settings > Developers > API. Copy the API URL and Client ID, then copy an Access Token. API access requires a Learning Center or High Volume plan. Use the original school.learnworlds.com URL. Paste only the token, without Bearer. Replace it here when it expires or is revoked."})
    credential_type: Literal["learnworlds_access_token"] = Field("learnworlds_access_token", json_schema_extra={"ui:hidden": True})
    school_url: str = Field(..., title="School API URL", description="Original HTTPS school.learnworlds.com URL; /admin/api or /admin/api/v2 may be included.")
    client_id: str = Field(..., min_length=1, max_length=512, title="Client ID")
    access_token: str = Field(..., min_length=1, max_length=4096, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("school_url", mode="before")
    @classmethod
    def school(cls, value):
        raw = str(value or "").strip()
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
        if parts.path.rstrip("/") not in {"", "/admin/api", "/admin/api/v2"} or parts.query or parts.fragment:
            raise ValueError("Paste the school API URL from Settings > Developers > API")
        return normalize_provider_https_origin(parts._replace(path="").geturl(), "learnworlds.com", field_name="School API URL")

    @field_validator("client_id", "access_token", mode="before")
    @classmethod
    def header_value(cls, value, info):
        value = clean_secret(value, field_name=info.field_name, key=True)
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API value without spaces or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_value(cls, value, info):
        if info.field_name in {"user_id", "course_id", "payment_id"} and value is not None:
            if not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#%") or any(ord(c) < 32 for c in value):
                raise ValueError("Use one resource ID or user email, without a URL or path")
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, description="One page only. Use next_page from the previous response; LearnWorlds repeats its last page for out-of-range page numbers.")


class LearnWorldsListUsersConfig(_Page):
    """List users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    items_per_page: int = Field(50, ge=1, le=200)
    status: Literal["paying", "non_paying", "suspended", "never_logged_in"] | None = None
    role: Literal["user", "admin", "instructor", "reporter", "license_reporter"] | None = None
    tags: str | None = Field(None, description="Comma-separated tags.")
    registration_after: float | None = Field(None, ge=0, allow_inf_nan=False)
    registration_before: float | None = Field(None, ge=0, allow_inf_nan=False)


class LearnWorldsGetUserConfig(_Input):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")


class LearnWorldsCreateUserConfig(_Input):
    """Create user."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    username: str = Field(..., min_length=1)
    fields: dict[str, str] | None = Field(None, description="Profile fields, including school custom fields prefixed cf_.")
    subscribed_for_marketing_emails: bool | None = Field(None, description="Set only with the learner's consent.")
    tags: list[str] | None = None
    send_registration_email: bool = Field(False, description="Send the registration email only when explicitly enabled.")


class LearnWorldsUpdateUserConfig(_Input):
    """Update user."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")
    email: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    username: str | None = Field(None, min_length=1)
    fields: dict[str, str] | None = Field(None, description="Profile fields, including school custom fields prefixed cf_.")
    subscribed_for_marketing_emails: bool | None = Field(None, description="Set only with the learner's consent.")


class LearnWorldsUpdateUserTagsConfig(_Input):
    """Update user tags."""
    operation: Literal["update_user_tags"] = Field("update_user_tags", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")
    tags: list[str] = Field(..., min_length=1)
    action: Literal["attach", "detach"] = Field(...)


class LearnWorldsListCoursesConfig(_Page):
    """List courses."""
    operation: Literal["list_courses"] = Field("list_courses", json_schema_extra={"ui:hidden": True})
    categories: str | None = Field(None, description="Comma-separated course categories.")


class LearnWorldsGetCourseConfig(_Input):
    """Get course."""
    operation: Literal["get_course"] = Field("get_course", json_schema_extra={"ui:hidden": True})
    course_id: str = Field(..., min_length=1, description="Course ID.")


class LearnWorldsCreateCourseConfig(_Input):
    """Create course."""
    operation: Literal["create_course"] = Field("create_course", json_schema_extra={"ui:hidden": True})
    titleId: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str | None = None
    price: float | None = Field(None, ge=0, allow_inf_nan=False)
    access: Literal["paid", "free", "coming_soon", "private", "draft"] = Field(...)
    dripFeed: Literal["days", "date", "none"] | None = None
    categories: list[str] | None = None
    label: str | None = None


class LearnWorldsUpdateCourseConfig(_Input):
    """Update course."""
    operation: Literal["update_course"] = Field("update_course", json_schema_extra={"ui:hidden": True})
    course_id: str = Field(..., min_length=1, description="Course ID.")
    title: str | None = Field(None, min_length=1)
    description: str | None = None
    price: float | None = Field(None, ge=0, allow_inf_nan=False)
    access: Literal["paid", "free", "coming_soon", "private", "draft", "enrollment_closed"] | None = None
    dripFeed: Literal["days", "date", "none"] | None = None
    categories: list[str] | None = None
    label: str | None = None


class LearnWorldsEnrollUserConfig(_Input):
    """Enroll user."""
    operation: Literal["enroll_user"] = Field("enroll_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")
    productId: str = Field(..., min_length=1)
    productType: Literal["course", "bundle", "subscription"] = Field(...)
    price: float = Field(..., ge=0, allow_inf_nan=False)
    justification: str | None = None
    duration_type: Literal["months", "weeks", "days"] | None = None
    duration: int | None = Field(None, ge=1)
    send_enrollment_email: bool = Field(False, description="Send an enrollment email only when explicitly enabled.")


class LearnWorldsUnenrollUserConfig(_Input):
    """Unenroll user."""
    operation: Literal["unenroll_user"] = Field("unenroll_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")
    productId: str = Field(..., min_length=1)
    productType: Literal["course", "bundle", "subscription"] = Field(...)


class LearnWorldsListUserCoursesConfig(_Page):
    """List user courses."""
    operation: Literal["list_user_courses"] = Field("list_user_courses", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")


class LearnWorldsListCourseUsersConfig(_Page):
    """List course users."""
    operation: Literal["list_course_users"] = Field("list_course_users", json_schema_extra={"ui:hidden": True})
    course_id: str = Field(..., min_length=1, description="Course ID.")
    items_per_page: int = Field(50, ge=1, le=200)


class LearnWorldsGetUserProductsConfig(_Input):
    """Get user products."""
    operation: Literal["get_user_products"] = Field("get_user_products", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")


class LearnWorldsGetCourseContentsConfig(_Input):
    """Get course contents."""
    operation: Literal["get_course_contents"] = Field("get_course_contents", json_schema_extra={"ui:hidden": True})
    course_id: str = Field(..., min_length=1, description="Course ID.")


class LearnWorldsGetCourseAnalyticsConfig(_Input):
    """Get course analytics."""
    operation: Literal["get_course_analytics"] = Field("get_course_analytics", json_schema_extra={"ui:hidden": True})
    course_id: str = Field(..., min_length=1, description="Course ID.")


class LearnWorldsGetUserCourseProgressConfig(_Input):
    """Get user course progress."""
    operation: Literal["get_user_course_progress"] = Field("get_user_course_progress", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, description="LearnWorlds user ID or email.")
    course_id: str = Field(..., min_length=1, description="Course ID.")


class LearnWorldsListLeadsConfig(_Page):
    """List leads."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})


class LearnWorldsListPaymentsConfig(_Page):
    """List payments."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    items_per_page: int = Field(50, ge=1, le=200)
    user_id: str | None = None
    product_type: Literal["course", "bundle", "subscription"] | None = None
    product_id: str | None = None
    created_after: float | None = Field(None, ge=0, allow_inf_nan=False)
    created_before: float | None = Field(None, ge=0, allow_inf_nan=False)


class LearnWorldsGetPaymentConfig(_Input):
    """Get payment."""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    payment_id: str = Field(..., min_length=1)


LearnWorldsConfig = Annotated[Union[
    LearnWorldsListUsersConfig,
    LearnWorldsGetUserConfig,
    LearnWorldsCreateUserConfig,
    LearnWorldsUpdateUserConfig,
    LearnWorldsUpdateUserTagsConfig,
    LearnWorldsListCoursesConfig,
    LearnWorldsGetCourseConfig,
    LearnWorldsCreateCourseConfig,
    LearnWorldsUpdateCourseConfig,
    LearnWorldsEnrollUserConfig,
    LearnWorldsUnenrollUserConfig,
    LearnWorldsListUserCoursesConfig,
    LearnWorldsListCourseUsersConfig,
    LearnWorldsGetUserProductsConfig,
    LearnWorldsGetCourseContentsConfig,
    LearnWorldsGetCourseAnalyticsConfig,
    LearnWorldsGetUserCourseProgressConfig,
    LearnWorldsListLeadsConfig,
    LearnWorldsListPaymentsConfig,
    LearnWorldsGetPaymentConfig
], Field(discriminator="operation")]


class LearnWorldsFullConfig(NodeConfig[LearnWorldsConfig, LearnWorldsAccessTokenCredential]):
    pass


OPERATIONS = {'list_users': {'method': 'GET',
                'path': '/v2/users',
                'path_fields': [],
                'query_fields': ['page',
                                 'items_per_page',
                                 'status',
                                 'role',
                                 'tags',
                                 'registration_after',
                                 'registration_before'],
                'body_fields': []},
 'get_user': {'method': 'GET',
              'path': '/v2/users/{user_id}',
              'path_fields': ['user_id'],
              'query_fields': [],
              'body_fields': []},
 'create_user': {'method': 'POST',
                 'path': '/v2/users',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': ['email',
                                 'username',
                                 'fields',
                                 'subscribed_for_marketing_emails',
                                 'tags',
                                 'send_registration_email']},
 'update_user': {'method': 'PUT',
                 'path': '/v2/users/{user_id}',
                 'path_fields': ['user_id'],
                 'query_fields': [],
                 'body_fields': ['email', 'username', 'fields', 'subscribed_for_marketing_emails']},
 'update_user_tags': {'method': 'PUT',
                      'path': '/v2/users/{user_id}/tags',
                      'path_fields': ['user_id'],
                      'query_fields': [],
                      'body_fields': ['tags', 'action']},
 'list_courses': {'method': 'GET',
                  'path': '/v2/courses',
                  'path_fields': [],
                  'query_fields': ['page', 'categories'],
                  'body_fields': []},
 'get_course': {'method': 'GET',
                'path': '/v2/courses/{course_id}',
                'path_fields': ['course_id'],
                'query_fields': [],
                'body_fields': []},
 'create_course': {'method': 'POST',
                   'path': '/v2/courses',
                   'path_fields': [],
                   'query_fields': [],
                   'body_fields': ['titleId',
                                   'title',
                                   'description',
                                   'price',
                                   'access',
                                   'dripFeed',
                                   'categories',
                                   'label']},
 'update_course': {'method': 'PUT',
                   'path': '/v2/courses/{course_id}',
                   'path_fields': ['course_id'],
                   'query_fields': [],
                   'body_fields': ['title',
                                   'description',
                                   'price',
                                   'access',
                                   'dripFeed',
                                   'categories',
                                   'label']},
 'enroll_user': {'method': 'POST',
                 'path': '/v2/users/{user_id}/enrollment',
                 'path_fields': ['user_id'],
                 'query_fields': [],
                 'body_fields': ['productId',
                                 'productType',
                                 'price',
                                 'justification',
                                 'duration_type',
                                 'duration',
                                 'send_enrollment_email']},
 'unenroll_user': {'method': 'DELETE',
                   'path': '/v2/users/{user_id}/enrollment',
                   'path_fields': ['user_id'],
                   'query_fields': [],
                   'body_fields': ['productId', 'productType']},
 'list_user_courses': {'method': 'GET',
                       'path': '/v2/users/{user_id}/courses',
                       'path_fields': ['user_id'],
                       'query_fields': ['page'],
                       'body_fields': []},
 'list_course_users': {'method': 'GET',
                       'path': '/v2/courses/{course_id}/users',
                       'path_fields': ['course_id'],
                       'query_fields': ['page', 'items_per_page'],
                       'body_fields': []},
 'get_user_products': {'method': 'GET',
                       'path': '/v2/users/{user_id}/products',
                       'path_fields': ['user_id'],
                       'query_fields': [],
                       'body_fields': []},
 'get_course_contents': {'method': 'GET',
                         'path': '/v2/courses/{course_id}/contents',
                         'path_fields': ['course_id'],
                         'query_fields': [],
                         'body_fields': []},
 'get_course_analytics': {'method': 'GET',
                          'path': '/v2/courses/{course_id}/analytics',
                          'path_fields': ['course_id'],
                          'query_fields': [],
                          'body_fields': []},
 'get_user_course_progress': {'method': 'GET',
                              'path': '/v2/users/{user_id}/courses/{course_id}/progress',
                              'path_fields': ['user_id', 'course_id'],
                              'query_fields': [],
                              'body_fields': []},
 'list_leads': {'method': 'GET',
                'path': '/v2/leads',
                'path_fields': [],
                'query_fields': ['page'],
                'body_fields': []},
 'list_payments': {'method': 'GET',
                   'path': '/v2/payments',
                   'path_fields': [],
                   'query_fields': ['page',
                                    'items_per_page',
                                    'user_id',
                                    'product_type',
                                    'product_id',
                                    'created_after',
                                    'created_before'],
                   'body_fields': []},
 'get_payment': {'method': 'GET',
                 'path': '/v2/payments/{payment_id}',
                 'path_fields': ['payment_id'],
                 'query_fields': [],
                 'body_fields': []}}


class LearnWorldsNode(WorkflowNode):
    integration_type = "automation-learnworlds"
    connection_evidence = ConnectionEvidence(
        noun="courses", operation="list_courses", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return LearnWorldsFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a LearnWorlds access token")
        credential = self.config.credentials
        op = self.config.config
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        path = spec["path"].format(**{
            name: quote(values[name], safe="") for name in spec["path_fields"]})
        params = {name: values[name] for name in spec["query_fields"] if name in values}
        body = {name: values[name] for name in spec["body_fields"] if name in values}
        if op.operation in {"update_user", "update_course"} and not body:
            raise ValueError("Provide at least one field to update")
        if op.operation == "enroll_user" and op.productType == "subscription" and (
            op.duration is None or op.duration_type is None
        ):
            raise ValueError("Subscription enrollments require duration and duration type")
        origin = normalize_provider_https_origin(credential.school_url, "learnworlds.com", field_name="School API URL")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                spec["method"], origin + "/admin/api" + path,
                headers={"Authorization": "Bearer " + credential.access_token,
                         "Lw-Client": credential.client_id, "Accept": "application/json"},
                params=params, **({"json": body} if spec["body_fields"] else {}))
        if response.status_code >= 400:
            message = response.text[:4000].replace(credential.access_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        if not 200 <= response.status_code < 300:
            raise ValueError("LearnWorlds did not confirm the request; redirects are refused")
        output = {"status": "success", "operation": op.operation, "http_status": response.status_code}
        if response.status_code == 204:
            return {**output, "data": None}
        if len(response.content) > 8_000_000:
            raise ValueError("LearnWorlds response exceeded the size limit")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("LearnWorlds returned an unexpected JSON response")
        if isinstance(data, dict) and (data.get("success") is False or data.get("errors") or data.get("error")):
            import json
            message = json.dumps(data, ensure_ascii=False)[:4000].replace(credential.access_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        if op.operation.startswith("list_"):
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("LearnWorlds returned an unexpected list envelope")
            meta = data.get("meta")
            if not isinstance(meta, dict):
                raise ValueError("LearnWorlds pagination metadata is missing")
            page, pages = meta.get("page"), meta.get("totalPages")
            if not isinstance(page, int) or isinstance(page, bool) or not isinstance(pages, int) or isinstance(pages, bool) or page < 1 or pages < 0:
                raise ValueError("LearnWorlds pagination metadata is invalid")
            output.update(data=data["data"], meta=meta, next_page=page + 1 if page < pages else None)
        else:
            output["data"] = data
        return output
