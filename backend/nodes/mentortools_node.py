"""Mentortools Public API 1.10.1: explicit single-request operations.

The provider publishes no webhook registration or time-ordered list contract.
Pagination uses the provider's explicit limit and offset, without hidden reads.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.mentortools.com/public_api"
DOCS = "https://app.mentortools.com/public_api/docs"


class MentortoolsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mentortools API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "In Mentortools, open Settings → Integrations & Automations and create an API key with permission for your selected actions. Paste the key here without Bearer. NoClick sends it to app.mentortools.com as a bearer token. Connecting reads your courses; Get Account reads the key, portal and owner identity."})
    credential_type: Literal["mentortools_api_key"] = Field("mentortools_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Page(_Input):
    limit: int = Field(15, ge=1, le=100, description="Maximum rows in this page. Use offset to request another page.")
    offset: int = Field(0, ge=0)


class _Course(_Input):
    course_id: int = Field(..., description="Course ID returned by List Courses.")


class _Module(_Input):
    module_id: int = Field(..., description="Module ID returned by List Modules.")


class _Lesson(_Input):
    lesson_id: int = Field(..., description="Lesson ID returned by List Lessons.")


class _CourseFields(_Input):
    title: str = Field(..., min_length=1)
    description: str | None = None
    payload: str | None = Field(None, description="Text or HTML course content.")
    image_id: str | None = None
    url: str | None = Field(None, description="Sales page URL.")
    is_active: StrictBool = False
    is_secret: StrictBool = False
    is_archived: StrictBool = False
    is_displayed_in_app: StrictBool = False
    is_offline_downloadable: StrictBool = False
    order: int | None = None
    launch_date_enabled: StrictBool | None = None
    launch_date: int | None = Field(None, description="Course launch timestamp, as accepted by Mentortools.")


class _Patch(_Input):
    @model_validator(mode="after")
    def change(self):
        path_id = {"update_course": "course_id", "update_module": "module_id", "update_lesson": "lesson_id"}[self.operation]
        if not self.model_dump(exclude={"operation", path_id}, exclude_none=True):
            raise ValueError("Provide at least one field to update")
        return self


class _CoursePatch(_Patch):
    title: str | None = Field(None, min_length=1)
    description: str | None = None
    payload: str | None = None
    image_id: str | None = None
    url: str | None = None
    is_active: StrictBool | None = None
    is_secret: StrictBool | None = None
    is_archived: StrictBool | None = None
    is_displayed_in_app: StrictBool | None = None
    is_offline_downloadable: StrictBool | None = None
    order: int | None = None
    launch_date_enabled: StrictBool | None = None
    launch_date: int | None = None



class _ModuleFields(_Input):
    title: str = Field(..., min_length=1)
    public_description: str | None = None
    short_description: str | None = None
    image_id: str | None = None
    mandatory: StrictBool = False
    is_published: StrictBool = False
    is_active: StrictBool = False
    available_at: int | None = Field(None, ge=0, le=36500, description="Delay in days after course access is granted; not a timestamp.")
    order: int | None = None


class _ModulePatch(_Patch):
    title: str | None = Field(None, min_length=1)
    public_description: str | None = None
    short_description: str | None = None
    image_id: str | None = None
    mandatory: StrictBool | None = None
    is_published: StrictBool | None = None
    is_active: StrictBool | None = None
    available_at: int | None = Field(None, ge=0, le=36500, description="Delay in days after course access is granted.")
    order: int | None = None


class _LessonFields(_Input):
    title: str = Field(..., min_length=1)
    lesson_type: Literal["lesson", "quiz"] = "lesson"
    payload: str | None = None
    image_id: str | None = None
    submodule_id: int | None = None
    thread_id: int | None = None
    is_active: StrictBool = False
    is_published: StrictBool = False
    mandatory: StrictBool = False
    available_at: int | None = Field(None, ge=0, le=36500, description="Delay in days after the parent module becomes available; not a timestamp.")
    order: int | None = None


class _LessonPatch(_Patch):
    title: str | None = Field(None, min_length=1)
    payload: str | None = None
    image_id: str | None = None
    module_id: int | None = Field(None, description="Set to move the lesson to another module.")
    submodule_id: int | None = None
    thread_id: int | None = None
    is_active: StrictBool | None = None
    is_published: StrictBool | None = None
    mandatory: StrictBool | None = None
    available_at: int | None = Field(None, ge=0, le=36500, description="Delay in days after the parent module becomes available.")
    order: int | None = None


class Buyer(_Input):
    email: str = Field(..., min_length=3, description="Buyer email address.")
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None


class Transaction(_Input):
    amount: float = Field(..., description="Decimal transaction amount, e.g. 10.00.")
    id: str = Field(..., min_length=1, description="Stable external transaction ID for retry deduplication. For a refund, use a new ID distinct from the payment transaction.")


class RecordPayment(_Input):
    """Record a payment and unlock courses for a buyer; use stable IDs for retries."""
    operation: Literal["record_payment"] = "record_payment"
    marketplace_buyer: Buyer
    course_ids: list[int] = Field(..., min_length=1)
    id: str = Field(..., min_length=1, title="External Order ID", description="Reuse this ID for retries; the provider adds the portal prefix if absent.")
    transaction: Transaction | None = None
    send_email: StrictBool = Field(False, description="Send the provider's buyer notification email.")
    billing_type: Literal["single_payment", "subscription", "installment", "free", "fake", "gift", "single_payment_imported", "subscription_imported", "installment_imported", "free_imported", "fake_imported", "gift_imported"] = "single_payment"
    access_until: int | None = Field(None, description="Access end Unix timestamp in milliseconds; required for subscriptions.")
    occurred_at: int | None = Field(None, description="Order Unix timestamp in milliseconds.")

    @model_validator(mode="after")
    def subscription_end(self):
        if self.billing_type in {"subscription", "subscription_imported"} and self.access_until is None:
            raise ValueError("Subscriptions require access_until in Unix milliseconds")
        return self


class RecordRefund(_Input):
    """Record an order refund; supply a distinct refund transaction ID for retry deduplication."""
    operation: Literal["record_refund"] = "record_refund"
    id: str = Field(..., min_length=1, title="Original External Order ID", description="Original order ID or external_order_id returned by Record Payment.")
    transaction: Transaction | None = None


class GetAccount(_Input):
    """Read key, portal and owner identity."""
    operation: Literal["get_account"] = "get_account"


class ListCourses(_Page):
    """List one page of courses."""
    operation: Literal["list_courses"] = "list_courses"
    archived: StrictBool = False


class CountCourses(_Input):
    """Count courses."""
    operation: Literal["count_courses"] = "count_courses"
    archived: StrictBool = False


class GetCourse(_Course):
    """Read a course."""
    operation: Literal["get_course"] = "get_course"


class GetCourseInfo(_Course):
    """Read a course including modules and content blocks."""
    operation: Literal["get_course_info"] = "get_course_info"


class CreateCourse(_CourseFields):
    """Create a course with explicit visibility flags."""
    operation: Literal["create_course"] = "create_course"


class UpdateCourse(_Course, _CoursePatch):
    """Update only supplied course fields."""
    operation: Literal["update_course"] = "update_course"


class DeleteCourse(_Course):
    """Delete a course."""
    operation: Literal["delete_course"] = "delete_course"


class ListModules(_Course, _Page):
    """List one page of course modules."""
    operation: Literal["list_modules"] = "list_modules"


class GetModule(_Module):
    """Read a course module."""
    operation: Literal["get_module"] = "get_module"


class CreateModule(_Course, _ModuleFields):
    """Create a module in a course."""
    operation: Literal["create_module"] = "create_module"


class UpdateModule(_Module, _ModulePatch):
    """Update only supplied module fields."""
    operation: Literal["update_module"] = "update_module"


class DeleteModule(_Module):
    """Delete a module."""
    operation: Literal["delete_module"] = "delete_module"


class ListLessons(_Module, _Page):
    """List one page of lessons in a module."""
    operation: Literal["list_lessons"] = "list_lessons"


class GetLesson(_Lesson):
    """Read a lesson."""
    operation: Literal["get_lesson"] = "get_lesson"


class CreateLesson(_Module, _LessonFields):
    """Create a lesson in a module."""
    operation: Literal["create_lesson"] = "create_lesson"


class UpdateLesson(_Lesson, _LessonPatch):
    """Update lesson fields or move it to another module."""
    operation: Literal["update_lesson"] = "update_lesson"


class DeleteLesson(_Lesson):
    """Delete a lesson."""
    operation: Literal["delete_lesson"] = "delete_lesson"


class ListFiles(_Page):
    """List one page of media files in a folder."""
    operation: Literal["list_files"] = "list_files"
    parent_folder_id: int | None = Field(None, description="Parent folder ID; omit for the root folder.")
    filename: str | None = None
    file_type: Literal["image", "video", "audio", "document", "archive"] | None = None


class GetFile(_Input):
    """Read media file metadata."""
    operation: Literal["get_file"] = "get_file"
    id_: int = Field(..., title="Resource ID", description="Integer media database ID, not the opaque file_id hash.")


class ListFolders(_Page):
    """List one page of media folders."""
    operation: Literal["list_folders"] = "list_folders"
    parent_folder_id: int | None = Field(None, description="Parent folder ID; omit for the root folder.")


class CreateFolder(_Input):
    """Create a media folder."""
    operation: Literal["create_folder"] = "create_folder"
    parent_folder_id: int | None = Field(None, description="Parent folder ID; omit for the root folder.")
    name: str = Field(..., min_length=1)


class GetFolder(_Input):
    """Read a media folder."""
    operation: Literal["get_folder"] = "get_folder"
    id_: int = Field(..., title="Resource ID", description="Integer media database ID, not the opaque file_id hash.")


Operation = Annotated[Union[GetAccount, ListCourses, CountCourses, GetCourse, GetCourseInfo, CreateCourse, UpdateCourse, DeleteCourse, ListModules, GetModule, CreateModule, UpdateModule, DeleteModule, ListLessons, GetLesson, CreateLesson, UpdateLesson, DeleteLesson, ListFiles, GetFile, ListFolders, CreateFolder, GetFolder, RecordPayment, RecordRefund], Field(discriminator="operation")]


class MentortoolsConfig(NodeConfig[Operation, MentortoolsAPIKeyCredential]):
    pass


ROUTES = {
    'get_account': ('GET', '/general/v1/whoami'),
    'list_courses': ('GET', '/courses/v1/'),
    'count_courses': ('GET', '/courses/v1/count'),
    'get_course': ('GET', '/courses/v1/{course_id}'),
    'get_course_info': ('GET', '/courses/v1/{course_id}/info'),
    'create_course': ('POST', '/courses/v1/'),
    'update_course': ('PATCH', '/courses/v1/{course_id}'),
    'delete_course': ('DELETE', '/courses/v1/{course_id}'),
    'list_modules': ('GET', '/courses/v1/{course_id}/modules'),
    'get_module': ('GET', '/courses/v1/modules/{module_id}'),
    'create_module': ('POST', '/courses/v1/{course_id}/modules'),
    'update_module': ('PATCH', '/courses/v1/modules/{module_id}'),
    'delete_module': ('DELETE', '/courses/v1/modules/{module_id}'),
    'list_lessons': ('GET', '/courses/v1/modules/{module_id}/lessons'),
    'get_lesson': ('GET', '/courses/v1/lessons/{lesson_id}'),
    'create_lesson': ('POST', '/courses/v1/modules/{module_id}/lessons'),
    'update_lesson': ('PATCH', '/courses/v1/lessons/{lesson_id}'),
    'delete_lesson': ('DELETE', '/courses/v1/lessons/{lesson_id}'),
    'list_files': ('GET', '/mediastorage/v1/files'),
    'get_file': ('GET', '/mediastorage/v1/files/{id_}'),
    'list_folders': ('GET', '/mediastorage/v1/folders'),
    'create_folder': ('POST', '/mediastorage/v1/folders'),
    'get_folder': ('GET', '/mediastorage/v1/folders/{id_}'),
    'record_payment': ('POST', '/orders/v1/ipn/payment'),
    'record_refund': ('POST', '/orders/v1/ipn/refund'),
}


class MentortoolsNode(WorkflowNode):
    integration_type = "automation-mentortools"
    connection_evidence = ConnectionEvidence(operation="list_courses", noun="courses", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return MentortoolsConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Mentortools API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        # Only placeholders in this fixed route consume IDs: moving a lesson
        # must retain module_id in the PATCH body.
        for field in tuple(values):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", str(values.pop(field)))
        kwargs = {}
        if method == "GET":
            kwargs["params"] = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif method in {"POST", "PATCH"}:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Mentortools could not be reached") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Mentortools response exceeded the JSON limit")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Mentortools returned invalid JSON (HTTP " + str(response.status_code) + ")") from None
        if not isinstance(body, dict) or type(body.get("done")) is not bool:
            raise ValueError("Mentortools returned an invalid response envelope")
        if not response.is_success or body["done"] is False:
            message = body.get("error")
            if not isinstance(message, str) or not message:
                message = "Mentortools returned HTTP " + str(response.status_code)
            return {"status": "error", "http_status": response.status_code,
                    "error": message[:2000].replace(key, "[redacted]")}
        if body.get("error") is not None or "result" not in body:
            raise ValueError("Mentortools success response has no confirmed result")
        result = body["result"]
        if op.operation.startswith("list_") and (not isinstance(result, list) or any(not isinstance(row, dict) for row in result)):
            raise ValueError("Mentortools returned an invalid result list")
        if op.operation == "get_account":
            if not isinstance(result, dict) or not all(isinstance(result.get(k), dict) for k in ("api_key", "portal", "owner")):
                raise ValueError("Mentortools returned an invalid account identity")
            # The identity contract includes key metadata. Keep the account proof
            # free of key material, including any unexpected extra provider fields.
            result = {"portal": {k: result["portal"][k] for k in ("id", "domain") if k in result["portal"]},
                      "owner": {k: result["owner"][k] for k in ("id", "email") if k in result["owner"]}}
        return {"status": "success", "operation": op.operation, "data": result}
