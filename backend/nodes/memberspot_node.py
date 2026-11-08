"""Memberspot REST API 1.0: member access, learning progress and school catalogs.

Each operation issues one published API request. Page cursors are returned intact;
mutations are never retried automatically. API reference: https://api.memberspot.de/api
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.memberspot.de"
CREDENTIAL_TYPE = "memberspot_api_key"


class MemberspotAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Memberspot API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.memberspot.de/settings/apikeys",
            "x-credential-instructions": "In Memberspot, open Settings → API keys (/settings/apikeys), create an API key and paste it here. NoClick sends it in the X-API-KEY header to api.memberspot.de. The key can manage members and course access in its school.",
        })
    credential_type: Literal["memberspot_api_key"] = Field("memberspot_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Memberspot API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("uid", "email", "id", "courseId", "chapterId", "offerId", "grantOffer", "orderId", "lastLoadedId", "lastLoadedCourseId", mode="after", check_fields=False)
    @classmethod
    def bounded_path_values(cls, value):
        if isinstance(value, str) and (not value.strip() or value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use a nonempty value without control characters")
        return value


class CustomProperty(_Input):
    id: str = Field(..., min_length=1, max_length=512)
    value: str = Field(..., max_length=10000)


class MemberspotListUsersConfig(_Input):
    """Returns a page with users"""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    lastLoadedId: str | None = Field(None, min_length=1, max_length=512, description='Page to continue loading at (located in response in next_page property)')
    pageLength: int | None = Field(10, ge=1, le=100)
    offerId: str | None = Field(None, min_length=1, max_length=512, description='Filter users by offerId')
    courseId: str | None = Field(None, min_length=1, max_length=512, description='Filter users by courseId. Also populates progress[] of each user with the progress of this course; without this parameter progress[] is empty.')
    active: StrictBool | None = Field(None, description='If not set returns all users. When set to true return just active. When set to false return just inactive')

class MemberspotGetUserByEmailConfig(_Input):
    """Returns a user with the given email or null if not found"""
    operation: Literal["get_user_by_email"] = Field("get_user_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512, description='Email to search for')

class MemberspotGetUserByUidConfig(_Input):
    """Returns a user with the given uid or null if not found"""
    operation: Literal["get_user_by_uid"] = Field("get_user_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512, description='Uid to search for')

class MemberspotGetUserOffersConfig(_Input):
    """Returns the offers of a user incl. their expiration dates"""
    operation: Literal["get_user_offers"] = Field("get_user_offers", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The uid of the user')

class MemberspotListOffersConfig(_Input):
    """Gets all offers that are available in the school"""
    operation: Literal["list_offers"] = Field("list_offers", json_schema_extra={"ui:hidden": True})

class MemberspotListCoursesConfig(_Input):
    """Lists all courses of the school"""
    operation: Literal["list_courses"] = Field("list_courses", json_schema_extra={"ui:hidden": True})

class MemberspotListCustomPropertiesConfig(_Input):
    """Lists all custom user properties """
    operation: Literal["list_custom_properties"] = Field("list_custom_properties", json_schema_extra={"ui:hidden": True})

class MemberspotListExamsConfig(_Input):
    """Lists all exams of the school"""
    operation: Literal["list_exams"] = Field("list_exams", json_schema_extra={"ui:hidden": True})

class MemberspotListExamResultsConfig(_Input):
    """Lists exam results of users that have taken the exam provided by the examId"""
    operation: Literal["list_exam_results"] = Field("list_exam_results", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=512, description='Exam to get results for. The examId as returned by the exams API/MCP tools (e.g. "kSbFak3VHbyHJRLJM3Ufb").')
    lastLoadedId: str | None = Field(None, min_length=1, max_length=512, description='Page to continue loading at (located in response in next_page property)')
    pageLength: int | None = Field(10, ge=1, le=100)

class MemberspotListCourseProgressByEmailConfig(_Input):
    """Returns paginated list of all course progress for a user by email"""
    operation: Literal["list_course_progress_by_email"] = Field("list_course_progress_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512, description='Email to search for')
    lastLoadedCourseId: str | None = Field(None, min_length=1, max_length=512, description='Page to continue loading at (last course ID from previous response)')
    pageLength: int | None = Field(None, ge=1, le=100)

class MemberspotListCourseProgressByUidConfig(_Input):
    """Returns paginated list of all course progress for a user by uid"""
    operation: Literal["list_course_progress_by_uid"] = Field("list_course_progress_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512, description='Uid to search for')
    lastLoadedCourseId: str | None = Field(None, min_length=1, max_length=512, description='Page to continue loading at (last course ID from previous response)')
    pageLength: int | None = Field(None, ge=1, le=100)

class MemberspotGetCourseProgressByEmailConfig(_Input):
    """Returns user course progress for a specific course by email"""
    operation: Literal["get_course_progress_by_email"] = Field("get_course_progress_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512, description='Email to search for')
    courseId: str = Field(..., min_length=1, max_length=512, description='The course ID to get progress for')

class MemberspotGetCourseProgressByUidConfig(_Input):
    """Returns user course progress for a specific course by uid"""
    operation: Literal["get_course_progress_by_uid"] = Field("get_course_progress_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512, description='Uid to search for')
    courseId: str = Field(..., min_length=1, max_length=512, description='The course ID to get progress for')

class MemberspotGrantOfferByEmailConfig(_Input):
    """Grants a user access to an offer by email; creates the user if absent. Omit grantOffer to create without an offer."""
    operation: Literal["grant_offer_by_email"] = Field("grant_offer_by_email", json_schema_extra={"ui:hidden": True})
    firstname: str | None = Field(None, min_length=1, max_length=10000)
    name: str | None = Field(None, min_length=1, max_length=10000)
    email: EmailStr = Field(..., min_length=1, max_length=512)
    grantOffer: str | None = Field(None, min_length=1, max_length=512)
    orderId: str | None = Field(None, min_length=1, max_length=512)

class MemberspotGrantOfferByUidConfig(_Input):
    """Grants a user access to an offer by uid"""
    operation: Literal["grant_offer_by_uid"] = Field("grant_offer_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512)
    grantOffer: str | None = Field(None, min_length=1, max_length=512)
    orderId: str | None = Field(None, min_length=1, max_length=512)

class MemberspotSetOfferStateByEmailConfig(_Input):
    """Sets the state of an offer for a user by email; omit active to remove access, false to suspend, true to activate."""
    operation: Literal["set_offer_state_by_email"] = Field("set_offer_state_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512)
    offerId: str = Field(..., min_length=1, max_length=512)
    active: StrictBool | None = Field(None)

class MemberspotSetOfferStateByUidConfig(_Input):
    """Sets the state of an offer for a user by uid; omit active to remove access, false to suspend, true to activate."""
    operation: Literal["set_offer_state_by_uid"] = Field("set_offer_state_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512)
    offerId: str = Field(..., min_length=1, max_length=512)
    active: StrictBool | None = Field(None)

class MemberspotSetOrderStateByEmailConfig(_Input):
    """Sets the state of an offer with a orderId for a user by email; omit active to remove access, false to suspend, true to activate."""
    operation: Literal["set_order_state_by_email"] = Field("set_order_state_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512)
    orderId: str = Field(..., min_length=1, max_length=512)
    active: StrictBool | None = Field(None)

class MemberspotSetOrderStateByUidConfig(_Input):
    """Sets the state of an offer with a orderId for a user; omit active to remove access, false to suspend, true to activate."""
    operation: Literal["set_order_state_by_uid"] = Field("set_order_state_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512)
    orderId: str = Field(..., min_length=1, max_length=512)
    active: StrictBool | None = Field(None)

class MemberspotSetOfferExpirationConfig(_Input):
    """Sets the expiration date for an offer for a user; omit expiresAt to remove expiration."""
    operation: Literal["set_offer_expiration"] = Field("set_offer_expiration", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512)
    offerId: str = Field(..., min_length=1, max_length=512)
    expiresAt: str | None = Field(None, min_length=1, max_length=512, json_schema_extra={"format": "date-time"})

    @field_validator("expiresAt")
    @classmethod
    def valid_date(cls, value):
        if value is None:
            return value
        try:
            if len(value) == 10:
                date.fromisoformat(value)
            elif datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError("Use an ISO 8601 date or a timestamp with timezone") from None
        return value

class MemberspotSetCourseStartDateConfig(_Input):
    """Sets the start date of a course access for a user"""
    operation: Literal["set_course_start_date"] = Field("set_course_start_date", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512, description='The uid of the user')
    courseId: str = Field(..., min_length=1, max_length=512, description='The id of the course')
    startDate: str = Field(..., min_length=1, max_length=512, json_schema_extra={"format": "date-time"}, description='New start date of the course access in ISO 8601 format: a date (2026-01-15) or a date with time and offset (2026-01-15T00:00:00.000Z, 2026-01-15T08:00:00+01:00). A time without offset is rejected. Drip content unlocks relative to this date.')
    deleteDueMessages: StrictBool | None = Field(True, description='Whether drip messages that become due through the new start date are deleted instead of sent right away. Defaults to true.')

    @field_validator("startDate")
    @classmethod
    def valid_date(cls, value):
        if value is None:
            return value
        try:
            if len(value) == 10:
                date.fromisoformat(value)
            elif datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError("Use an ISO 8601 date or a timestamp with timezone") from None
        return value

class MemberspotSetCustomPropertiesByEmailConfig(_Input):
    """Sets values to a custom user properties by email"""
    operation: Literal["set_custom_properties_by_email"] = Field("set_custom_properties_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512, description='User email')
    properties: list[CustomProperty] = Field(..., min_length=1, max_length=100, description='User custom properties')

class MemberspotSetCustomPropertiesByUidConfig(_Input):
    """Sets values to a custom user properties by uid"""
    operation: Literal["set_custom_properties_by_uid"] = Field("set_custom_properties_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512, description='User Uid')
    properties: list[CustomProperty] = Field(..., min_length=1, max_length=100, description='User custom properties')

class MemberspotGrantChapterAccessByEmailConfig(_Input):
    """Grants a user access to a chapter by email"""
    operation: Literal["grant_chapter_access_by_email"] = Field("grant_chapter_access_by_email", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=512)
    courseId: str = Field(..., min_length=1, max_length=512)
    chapterId: str = Field(..., min_length=1, max_length=512)

class MemberspotGrantChapterAccessByUidConfig(_Input):
    """Grants a user access to a chapter by uid"""
    operation: Literal["grant_chapter_access_by_uid"] = Field("grant_chapter_access_by_uid", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., min_length=1, max_length=512)
    courseId: str = Field(..., min_length=1, max_length=512)
    chapterId: str = Field(..., min_length=1, max_length=512)

MemberspotConfig = Annotated[Union[
    MemberspotListUsersConfig,
    MemberspotGetUserByEmailConfig,
    MemberspotGetUserByUidConfig,
    MemberspotGetUserOffersConfig,
    MemberspotListOffersConfig,
    MemberspotListCoursesConfig,
    MemberspotListCustomPropertiesConfig,
    MemberspotListExamsConfig,
    MemberspotListExamResultsConfig,
    MemberspotListCourseProgressByEmailConfig,
    MemberspotListCourseProgressByUidConfig,
    MemberspotGetCourseProgressByEmailConfig,
    MemberspotGetCourseProgressByUidConfig,
    MemberspotGrantOfferByEmailConfig,
    MemberspotGrantOfferByUidConfig,
    MemberspotSetOfferStateByEmailConfig,
    MemberspotSetOfferStateByUidConfig,
    MemberspotSetOrderStateByEmailConfig,
    MemberspotSetOrderStateByUidConfig,
    MemberspotSetOfferExpirationConfig,
    MemberspotSetCourseStartDateConfig,
    MemberspotSetCustomPropertiesByEmailConfig,
    MemberspotSetCustomPropertiesByUidConfig,
    MemberspotGrantChapterAccessByEmailConfig,
    MemberspotGrantChapterAccessByUidConfig
], Field(discriminator="operation")]


class MemberspotFullConfig(NodeConfig[MemberspotConfig, MemberspotAPIKeyCredential]):
    pass


# (method, fixed route, path fields, query fields) from the published 1.0 contract.
ROUTES = {'list_users': ('GET', '/v1/users/list', (), ('lastLoadedId', 'pageLength', 'offerId', 'courseId', 'active')),
 'get_user_by_email': ('GET', '/v1/users/find-by-mail/{email}', ('email',), ()),
 'get_user_by_uid': ('GET', '/v1/users/find-by-uid/{uid}', ('uid',), ()),
 'get_user_offers': ('GET', '/v1/users/offers/{uid}', ('uid',), ()),
 'list_offers': ('GET', '/v1/offers', (), ()),
 'list_courses': ('GET', '/v1/courses', (), ()),
 'list_custom_properties': ('GET', '/v1/custom-user-properties/list', (), ()),
 'list_exams': ('GET', '/v1/exams', (), ()),
 'list_exam_results': ('GET', '/v1/exams/{id}/results', ('id',), ('lastLoadedId', 'pageLength')),
 'list_course_progress_by_email': ('GET',
                                   '/v1/users/course-progress/list/{email}',
                                   ('email',),
                                   ('lastLoadedCourseId', 'pageLength')),
 'list_course_progress_by_uid': ('GET',
                                 '/v1/users/course-progress/list-by-uid/{uid}',
                                 ('uid',),
                                 ('lastLoadedCourseId', 'pageLength')),
 'get_course_progress_by_email': ('GET',
                                  '/v1/users/course-progress/{courseId}/{email}',
                                  ('email', 'courseId'),
                                  ()),
 'get_course_progress_by_uid': ('GET',
                                '/v1/users/course-progress/{courseId}/by-uid/{uid}',
                                ('uid', 'courseId'),
                                ()),
 'grant_offer_by_email': ('POST', '/v1/users/grant-user-offer-by-mail', (), ()),
 'grant_offer_by_uid': ('POST', '/v1/users/grant-user-offer-by-uid', (), ()),
 'set_offer_state_by_email': ('POST', '/v1/users/set-offer-state', (), ()),
 'set_offer_state_by_uid': ('POST', '/v1/users/set-offer-state-by-uid', (), ()),
 'set_order_state_by_email': ('POST', '/v1/users/set-order-state', (), ()),
 'set_order_state_by_uid': ('POST', '/v1/users/set-order-state-by-uid', (), ()),
 'set_offer_expiration': ('PATCH', '/v1/users/set-offer-expires', (), ()),
 'set_course_start_date': ('PATCH', '/v1/users/set-course-start-date', (), ()),
 'set_custom_properties_by_email': ('POST', '/v1/users/set-custom-user-properties', (), ()),
 'set_custom_properties_by_uid': ('POST', '/v1/users/set-custom-user-properties-by-uid', (), ()),
 'grant_chapter_access_by_email': ('POST', '/v1/chapters/chapter-access/enable', (), ()),
 'grant_chapter_access_by_uid': ('POST', '/v1/chapters/chapter-access/enable-by-uid', (), ())}


class MemberspotNode(WorkflowNode):
    integration_type = "automation-memberspot"
    connection_evidence = ConnectionEvidence(operation="list_courses", noun="courses")

    @classmethod
    def get_config_model(cls):
        return MemberspotFullConfig

    @classmethod
    def parse_config(cls, config_data):
        return MemberspotFullConfig.model_validate(runtime_config_view(config_data, MemberspotFullConfig))

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Memberspot API key")
        op = self.config.config
        method, route, path_fields, query_fields = ROUTES[op.operation]
        fields = op.model_dump(exclude={"operation"}, exclude_none=True, mode="json")
        for key in path_fields:
            route = route.replace("{" + key + "}", quote(str(fields.pop(key)), safe=""))
        query = {key: fields.pop(key) for key in query_fields if key in fields}
        # httpx's query encoder emits the documented lowercase boolean literals.
        kwargs = {"params": query} if method == "GET" else {"json": fields}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + route,
                headers={"X-API-KEY": self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Keep the provider's rejection text, without reflecting the supplied key.
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Memberspot HTTP {response.status_code}: {message}")
        if not response.content:
            body = None
        elif "json" in response.headers.get("content-type", "").lower():
            body = response.json()
        else:
            # Only the PATCH acknowledgements have no declared response schema.
            if method != "PATCH":
                raise ValueError("Expected JSON response from Memberspot")
            body = response.text
        if op.operation in {"list_users", "list_courses", "list_exams", "list_exam_results",
                            "list_course_progress_by_email", "list_course_progress_by_uid"}:
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise ValueError("Expected a Memberspot page containing a data array")
        elif op.operation == "list_custom_properties" and not isinstance(body, list):
            raise ValueError("Expected a Memberspot custom property array")
        elif op.operation == "get_user_offers":
            if not isinstance(body, dict) or not isinstance(body.get("offers"), list):
                raise ValueError("Expected Memberspot user offers")
        output = {"status": "success", "operation": op.operation, "http_status": response.status_code}
        # Preserve pagination, false flags, nulls and all documented nested fields.
        if isinstance(body, dict):
            output["data"] = body.get("data", body)
            if "nextPage" in body:
                output["nextPage"] = body["nextPage"]
        else:
            output["data"] = body
        await self.emit(output)
        return output
