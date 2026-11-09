"""Jackrabbit Customer API v1 operations for class administration.

Routes, query spelling and JSON fields follow the published v1 OpenAPI contract.
Organization tokens are pasted by a person; corporate tokens can select an org.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.jackrabbitclass.com"
CREDENTIAL_TYPE = "jackrabbit_class_api_token"
Identifier = Annotated[int, Field(ge=1, le=2147483647)]


class JackrabbitClassAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Jackrabbit Class API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.jackrabbitclass.com/",
            "x-credential-instructions": "Paste the Customer API token provided by Jackrabbit, without the Bearer prefix. Organization tokens already select their organization. For a corporate token, enter the organization ID to send as X-Org-Id. NoClick checks the organization name using Options/me.",
        },
    )
    credential_type: Literal["jackrabbit_class_api_token"] = Field(
        CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, title="Customer API token",
                           json_schema_extra={"ui:widget": "password"})
    organization_id: Identifier | None = Field(None, title="Organization ID",
        description="Only for corporate tokens. Leave empty for an organization token.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Customer API token")
        value = clean_secret(value, field_name="Customer API token", key=True)
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EnrollmentDays(_Input):
    """Per-day classes require at least one selected day; omit for standard classes."""
    mon: StrictBool = False
    tue: StrictBool = False
    wed: StrictBool = False
    thu: StrictBool = False
    fri: StrictBool = False
    sat: StrictBool = False
    sun: StrictBool = False

    @model_validator(mode="after")
    def selected(self):
        if not any(self.model_dump().values()):
            raise ValueError("Select at least one enrollment day")
        return self


class GetOrganizationConfig(_Input):
    """Get Organization Details."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})

class ListLocationsConfig(_Input):
    """Get Location Options."""
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})

class GetEnrollmentOptionsConfig(_Input):
    """Get options required to create or update an enrollment."""
    operation: Literal["get_enrollment_options"] = Field("get_enrollment_options", json_schema_extra={"ui:hidden": True})

class ListFamiliesConfig(_Input):
    """Get All Families."""
    operation: Literal["list_families"] = Field("list_families", json_schema_extra={"ui:hidden": True})
    status_id: Identifier | None = Field(None, description='Optional filter by status id.\r\n\r\nValid values can be retrieved from `GET /options/family-statuses`')
    location_id: Identifier | None = Field(None, description='Optional filter by location ID.\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    family_name: str | None = Field(None, description='Optional filter by family name.')
    date_last_updated: date | None = Field(None, description='Optional filter for families updated on or after the specified date.\r\n\r\nIMPORTANT: Timezone Consideration\r\nThis filter evaluates dates against server time (Eastern Standard Time, EST/EDT).')
    phone: str | None = Field(None, description='Optional filter by family home phone number.\r\nSupports multiple phone formats:\r\n- 1234567890 (digits only)\r\n- (123)4567890 (area code in parens)\r\n- (123) 456-7890 (standard format)\r\n- 123-456-7890 (dashes only)\r\n\r\nNote: This filters by the Family.HomePhone field only, not contact phone numbers.\r\nA separate contact phone filter may be implemented for filtering by contact phones.')
    page: int = Field(1, ge=1, le=2147483647, description="1-based page number. Use next_page from the previous result.")
    page_size: int = Field(25, ge=1, le=100)

class GetFamilyConfig(_Input):
    """Get Family By ID."""
    operation: Literal["get_family"] = Field("get_family", json_schema_extra={"ui:hidden": True})
    family_id: Identifier

class CreateFamilyConfig(_Input):
    """Create a new family."""
    operation: Literal["create_family"] = Field("create_family", json_schema_extra={"ui:hidden": True})
    family_name: str = Field(..., min_length=1, description='Family name (required)')
    location_id: Identifier = Field(..., description='Location (required)\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    home_phone: str | None = Field(None, description='Home phone number (optional)')
    user_field1: str | None = Field(None, description='User-defined field 1 response')
    user_field2: str | None = Field(None, description='User-defined field 2 response')
    user_field3: str | None = Field(None, description='User-defined field 3 response')
    user_field4: str | None = Field(None, description='User-defined field 4 response')
    user_field5: str | None = Field(None, description='User-defined field 5 response')

class UpdateFamilyConfig(_Input):
    """Update family."""
    operation: Literal["update_family"] = Field("update_family", json_schema_extra={"ui:hidden": True})
    family_id: Identifier
    family_name: str | None = Field(None, description='Last name or household name of the family')
    location_id: Identifier | None = Field(None, description='Location code where the family is registered\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    status_id: Identifier | None = Field(None, description="Status of the family's registration\r\n\r\nValid values can be retrieved from `GET /options/family-statuses`")
    primary_phone: str | None = Field(None, description='Primary home phone number for the family')
    emergency_info: str | None = Field(None, description='Emergency contact information for the family')
    notes: str | None = Field(None, description='Internal notes about the family')
    source_id: Identifier | None = Field(None, description='Source or channel through which the family was acquired\r\n\r\nValid values can be retrieved from `GET /options/family-sources`')
    user_field1: str | None = Field(None, description='User-defined field 1 response')
    user_field2: str | None = Field(None, description='User-defined field 2 response')
    user_field3: str | None = Field(None, description='User-defined field 3 response')
    user_field4: str | None = Field(None, description='User-defined field 4 response')
    user_field5: str | None = Field(None, description='User-defined field 5 response')

    @model_validator(mode="after")
    def changes(self):
        fields = BODY_FIELDS[self.operation]
        if not any(getattr(self, k) is not None for k in fields):
            raise ValueError("Provide at least one field to update")
        return self

class ListStudentsConfig(_Input):
    """Get All Students."""
    operation: Literal["list_students"] = Field("list_students", json_schema_extra={"ui:hidden": True})
    family_id: Identifier | None = Field(None, description='Optional filter by family ID.')
    is_active: StrictBool | None = Field(None, description='Optional filter by active status. Pass true to return active students, false to return inactive students, or null to return all.')
    location_id: Identifier | None = Field(None, description='Optional filter by location ID.\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    last_name: str | None = Field(None, description='Optional filter by last name.')
    birth_date: date | None = Field(None, description='Optional filter by birth date. Returns students born on the specified date.')
    quit_date: date | None = Field(None, description='Optional filter by student quit date. Returns students quit on the specified date.')
    created_date: date | None = Field(None, description='Optional filter by created date. Returns students created on the specified date.')
    date_last_inactive: date | None = Field(None, description='Optional filter by date last inactive. Returns students marked inactive on the specified date.')
    date_last_updated: date | None = Field(None, description='Optional filter for students updated on or after the specified date.\r\n\r\nIMPORTANT: Timezone Consideration\r\nThis filter evaluates dates against server time (Eastern Standard Time, EST/EDT).')
    page: int = Field(1, ge=1, le=2147483647, description="1-based page number. Use next_page from the previous result.")
    page_size: int = Field(25, ge=1, le=100)

class GetStudentConfig(_Input):
    """Get Student By ID."""
    operation: Literal["get_student"] = Field("get_student", json_schema_extra={"ui:hidden": True})
    student_id: Identifier

class CreateStudentConfig(_Input):
    """Create Student."""
    operation: Literal["create_student"] = Field("create_student", json_schema_extra={"ui:hidden": True})
    family_id: Identifier = Field(..., description='Id for the family this student will be added to')
    first_name: str = Field(..., min_length=1, description="Student's first name")
    middle_initial: str | None = Field(None, description="Student's middle initial")
    last_name: str | None = Field(None, description="Student's last name\r\n\r\nNote: If left blank, the student's last name will be the family name")
    gender_id: Identifier | None = Field(None, description='Gender specification Id\r\n\r\nValid values can be retrieved from `GET /options/genders`')
    phone: str | None = Field(None, description="Student's cell phone number, if any")
    email: str | None = Field(None, description="Student's email address, if any")
    birth_date: date | None = Field(None, description='Date of birth')
    school: str | None = Field(None, description='School the student attends')
    grade_level_id: Identifier | None = Field(None, description='Id for the grade level of the student\r\n\r\nValid values can be retrieved from `GET /options/grade-levels`')
    user_field1: str | None = Field(None, description='User-defined field 1 response')
    user_field2: str | None = Field(None, description='User-defined field 2 response')
    user_field3: str | None = Field(None, description='User-defined field 3 response')
    user_field4: str | None = Field(None, description='User-defined field 4 response')
    user_field5: str | None = Field(None, description='User-defined field 5 response')

class UpdateStudentConfig(_Input):
    """Update student."""
    operation: Literal["update_student"] = Field("update_student", json_schema_extra={"ui:hidden": True})
    student_id: Identifier
    first_name: str | None = Field(None, description="Student's first name")
    middle_initial: str | None = Field(None, description="Student's middle initial")
    last_name: str | None = Field(None, description="Student's last name\r\n\r\nNote: If left blank, the student's last name will be the family name")
    is_active: StrictBool | None = Field(None, description='Student Status (active/inactive)')
    birth_date: date | None = Field(None, description='Date of birth')
    gender_id: Identifier | None = Field(None, description='Gender specification Id\r\n\r\nValid values can be retrieved from `GET /options/genders`')
    grade_level_id: Identifier | None = Field(None, description='Id for the grade level of the student\r\n\r\nValid values can be retrieved from `GET /options/grade-levels`')
    email: str | None = Field(None, description="Student's email address, if any")
    phone: str | None = Field(None, description="Student's cell phone number, if any")
    school: str | None = Field(None, description='School the student attends')
    date_quit: date | None = Field(None, description='Date the student quit')
    instructor_feedback: str | None = Field(None, description='Instructor feedback on the student')
    roll_notes: str | None = Field(None, description="Notes about the student's roll")
    user_field1: str | None = Field(None, description='User-defined field 1 response')
    user_field2: str | None = Field(None, description='User-defined field 2 response')
    user_field3: str | None = Field(None, description='User-defined field 3 response')
    user_field4: str | None = Field(None, description='User-defined field 4 response')
    user_field5: str | None = Field(None, description='User-defined field 5 response')

    @model_validator(mode="after")
    def changes(self):
        fields = BODY_FIELDS[self.operation]
        if not any(getattr(self, k) is not None for k in fields):
            raise ValueError("Provide at least one field to update")
        return self

class ListContactsConfig(_Input):
    """Get All Contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    family_id: Identifier | None = Field(None, description='Optional filter by family ID.')
    member_id: str | None = Field(None, description='Optional filter by member ID (external contact identifier).')
    email: str | None = Field(None, description='Optional filter by email address.')
    primary: StrictBool | None = Field(None, description='Optional filter by primary status.')
    billing: StrictBool | None = Field(None, description='Optional filter by billing status.')
    authorized: StrictBool | None = Field(None, description='Optional filter by authorized status (whether the contact is authorized to pick up students).')
    type_id: Identifier | None = Field(None, description='Optional filter by contact type ID.\r\n\r\nValid values can be retrieved from `GET /options/contact-types`')
    date_last_updated: date | None = Field(None, description='Optional filter for contacts updated on or after the specified date.\r\n\r\nIMPORTANT: Timezone Consideration\r\nThis filter evaluates dates against server time (Eastern Standard Time, EST/EDT).')
    phone: str | None = Field(None, description='Optional filter by phone number.\r\n\r\nSearches across HomePhone, WorkPhone, and CellPhone fields using an OR condition.\r\nIf the phone number is found in any of these three fields, the contact is included in results.\r\nPhone input is normalized into 4 standard formats for flexible matching:\r\n- Digits only (e.g., 1234567890)\r\n- Area code in parens (e.g., (123)4567890)\r\n- Standard format (e.g., (123) 456-7890)\r\n- Dashes only (e.g., 123-456-7890)')
    page: int = Field(1, ge=1, le=2147483647, description="1-based page number. Use next_page from the previous result.")
    page_size: int = Field(25, ge=1, le=100)

class GetContactConfig(_Input):
    """Get Contact By ID."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: Identifier

class CreateContactConfig(_Input):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    family_id: Identifier = Field(..., description='Family identifier this contact belongs to\r\n\r\nValid values can be retrieved from `GET /families`')
    first_name: str = Field(..., min_length=1, description="Contact's first name")
    last_name: str = Field(..., min_length=1, description="Contact's last name")
    contact_type_id: Identifier | None = Field(None, description='Contact type Id\r\n\r\nValid values can be retrieved from `GET /options/contact-types`')
    is_primary: StrictBool | None = Field(None, description='Whether this is the primary contact')
    is_billing: StrictBool | None = Field(None, description='Whether this is the billing contact')
    is_authorized: StrictBool | None = Field(None, description='Whether this contact is authorized for student pick-up')
    home_phone: str | None = Field(None, description='Home phone number')
    work_phone: str | None = Field(None, description='Work phone number')
    cell_phone: str | None = Field(None, description='Cell phone number')
    email: str | None = Field(None, description="Contact's email address")
    notes: str | None = Field(None, description='Additional notes')

class UpdateContactConfig(_Input):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: Identifier
    first_name: str | None = Field(None, description="Contact's first name")
    last_name: str | None = Field(None, description="Contact's last name")
    contact_type_id: Identifier | None = Field(None, description="Contact type Id (referring to options like 'Mother', 'Father', 'Guardian', etc\r\n\r\nValid values can be retrieved from `GET /options/contact-types`")
    is_primary: StrictBool | None = Field(None, description='Whether this is the primary contact')
    is_billing: StrictBool | None = Field(None, description='Whether this is the billing contact')
    is_authorized: StrictBool | None = Field(None, description='Whether this contact is authorized for student pick-up')
    home_phone: str | None = Field(None, description='Home phone number')
    work_phone: str | None = Field(None, description='Work phone number')
    cell_phone: str | None = Field(None, description='Cell phone number')
    email: str | None = Field(None, description="Contact's email address")
    notes: str | None = Field(None, description='Additional notes')

    @model_validator(mode="after")
    def changes(self):
        fields = BODY_FIELDS[self.operation]
        if not any(getattr(self, k) is not None for k in fields):
            raise ValueError("Provide at least one field to update")
        return self

class ListClassesConfig(_Input):
    """Get all classes."""
    operation: Literal["list_classes"] = Field("list_classes", json_schema_extra={"ui:hidden": True})
    family_id: Identifier | None = Field(None, description='Optional filter by family ID.')
    instructor_id: Identifier | None = Field(None, description='Optional filter by instructor ID.')
    student_id: Identifier | None = Field(None, description='Optional filter by student ID.')
    location_id: Identifier | None = Field(None, description='Optional filter by location ID.\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    date_last_updated: date | None = Field(None, description='Optional filter for classes updated on or after the specified date.\r\n\r\nIMPORTANT: Timezone Consideration\r\nThis filter evaluates dates against server time (Eastern Standard Time, EST/EDT).')
    page: int = Field(1, ge=1, le=2147483647, description="1-based page number. Use next_page from the previous result.")
    page_size: int = Field(25, ge=1, le=100)

class GetClassConfig(_Input):
    """Get class by ID."""
    operation: Literal["get_class"] = Field("get_class", json_schema_extra={"ui:hidden": True})
    class_id: Identifier

class UpdateClassConfig(_Input):
    """Update class."""
    operation: Literal["update_class"] = Field("update_class", json_schema_extra={"ui:hidden": True})
    class_id: Identifier
    class_name: str | None = Field(None, max_length=100, description='The name of the class (max 100 characters)')
    description: str | None = Field(None, description='Class description (max 1000 characters)')
    max_size: float | None = Field(None, description='Maximum class size')
    max_wait: int | None = Field(None, description='Maximum waitlist size')
    room_id: Identifier | None = Field(None, description='Room identifier.\r\n\r\nValid values can be retrieved from `GET /options/rooms`')
    instructor1: int | None = Field(None, description='Primary instructor/teacher ID.\r\n\r\nValid values can be retrieved from `GET /options/class-instructors`')
    start_date: date | None = Field(None, description='Class start date')
    end_date: date | None = Field(None, description='Class end date (required if BillingCycleID is BySessionDates)')

    @model_validator(mode="after")
    def changes(self):
        fields = BODY_FIELDS[self.operation]
        if not any(getattr(self, k) is not None for k in fields):
            raise ValueError("Provide at least one field to update")
        return self

class GetClassRosterConfig(_Input):
    """Get class roster."""
    operation: Literal["get_class_roster"] = Field("get_class_roster", json_schema_extra={"ui:hidden": True})
    class_id: Identifier

class ListEnrollmentsConfig(_Input):
    """Get All Enrollments."""
    operation: Literal["list_enrollments"] = Field("list_enrollments", json_schema_extra={"ui:hidden": True})
    student_id: Identifier | None = Field(None, description='Optional filter by student ID.')
    family_id: Identifier | None = Field(None, description='Optional filter by family ID.')
    class_id: Identifier | None = Field(None, description='Optional filter by class ID.')
    class_location_id: Identifier | None = Field(None, description='Optional filter by class location ID.\r\n\r\nThis is the location specifically assigned to the class.\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    student_location_id: Identifier | None = Field(None, description='Optional filter by student location ID.\r\n\r\nThis is the location specifically assigned to the student/family.\r\n\r\nValid values can be retrieved from `GET /options/locations`')
    enrolled: StrictBool | None = Field(None, description='Optional filter by enrollment status. Pass false to show all dropped enrollments, true to show only existing enrollments.')
    page: int = Field(1, ge=1, le=2147483647, description="1-based page number. Use next_page from the previous result.")
    page_size: int = Field(25, ge=1, le=100)

class GetEnrollmentConfig(_Input):
    """Get Enrollment By ID."""
    operation: Literal["get_enrollment"] = Field("get_enrollment", json_schema_extra={"ui:hidden": True})
    enrollment_id: Identifier

class EnrollStudentConfig(_Input):
    """Enroll student in a class."""
    operation: Literal["enroll_student"] = Field("enroll_student", json_schema_extra={"ui:hidden": True})
    student_id: Identifier
    class_id: Identifier = Field(..., description='The ID of the class to enroll the student in')
    enroll_type_id: Identifier = Field(..., description='The enrollment type ID (maps to enrollment type option ID in organization options)\r\nRequired field that must match a valid enrollment type option\r\n\r\nValid values can be retrieved from `GET /options/enroll-types`')
    enroll_date: date | None = Field(None, description="Optional enrollment date. When omitted, defaults to the organization's\r\nlocal enrollment date. A date after the org's local today routes the\r\nenrollment to the FutureEnroll table instead of EnrollDrop.")
    days: EnrollmentDays | None = Field(None, description='days')
    enroll_comments: str | None = Field(None, description='Optional comments about the enrollment')
    ignore_age_validation: StrictBool | None = Field(None, description='Age validation is enforced by default per class MinAge/MaxAge settings.\r\nWhen true, age validation is skipped for this enrollment.')

class DropStudentConfig(_Input):
    """Drop student from a class."""
    operation: Literal["drop_student"] = Field("drop_student", json_schema_extra={"ui:hidden": True})
    student_id: Identifier
    class_id: Identifier = Field(..., description='The ID of the class to drop the student from')
    drop_date: date = Field(..., description='The date the student is being dropped from the class\r\nCan be today or in the future for future drops')
    drop_reason_id: Identifier = Field(..., description='The reason ID for the drop (references DropReasons from enrollment options)')
    drop_notes: str | None = Field(None, description='Optional notes about the drop')
    email_primary_instructor: StrictBool | None = Field(None, description='Whether to email the primary instructor a notification of the drop')

class ListAttendanceConfig(_Input):
    """Get all attendance records."""
    operation: Literal["list_attendance"] = Field("list_attendance", json_schema_extra={"ui:hidden": True})
    student_id: Identifier | None = Field(None, description='Optional filter by student ID\r\nIf submitted, the 1 year date range restriction will be bypassed for this query.')
    class_id: Identifier | None = Field(None, description='Optional filter by class ID (the original class that was missed)\r\nIf submitted, the 1 year date range restriction will be bypassed for this query.')
    makeup_class_id: Identifier | None = Field(None, description='Optional filter by makeup class ID (the class the absence was made up in)\r\nIf submitted, the 1 year date range restriction will be bypassed for this query.')
    start_date: date | None = Field(None, description='Start date for the attendance date range (optional).\r\nIf not specified, defaults to records from the last 1 year.')
    end_date: date | None = Field(None, description='End date for the attendance date range (optional).\r\nIf not specified, we will default to 1 year from the start date.\r\nCapped to a maximum of 1 year out from start date, unless StudentId, ClassId, or MakeupClassId is submitted.')
    did_attend: StrictBool | None = Field(None, description='Optional filter by attendance status (true = attended, false = did not attend, null = all)')
    has_scheduled_makeup: StrictBool | None = Field(None, description='Optional filter for attendance records with scheduled makeup (true = has makeup, false = no makeup, null = all)')
    did_attend_makeup: StrictBool | None = Field(None, description='Optional filter for makeup attendance status. When set, only returns records with scheduled makeups.\r\n(true = makeup was attended, false = makeup was not attended, null = all)')
    date_last_updated: date | None = Field(None, description='Optional filter for attendance records updated on or after the specified date.\r\n\r\nIMPORTANT: Timezone Consideration\r\nThis filter evaluates dates against server time (Eastern Standard Time, EST/EDT).')
    page: int = Field(1, ge=1, le=2147483647, description="1-based page number. Use next_page from the previous result.")
    page_size: int = Field(25, ge=1, le=100)

# Explicit one-operation-to-one-contract-route mapping. No caller-controlled URLs.
ROUTES = {'get_organization': ('GET', '/v1/Options/me'),
 'list_locations': ('GET', '/v1/Options/locations'),
 'get_enrollment_options': ('GET', '/v1/Options/enrollment'),
 'list_families': ('GET', '/v1/Families'),
 'get_family': ('GET', '/v1/Families/{id}'),
 'create_family': ('POST', '/v1/Families'),
 'update_family': ('PATCH', '/v1/Families/{id}'),
 'list_students': ('GET', '/v1/Students'),
 'get_student': ('GET', '/v1/Students/{id}'),
 'create_student': ('POST', '/v1/Students'),
 'update_student': ('PATCH', '/v1/Students/{id}'),
 'list_contacts': ('GET', '/v1/Contacts'),
 'get_contact': ('GET', '/v1/Contacts/{id}'),
 'create_contact': ('POST', '/v1/Contacts'),
 'update_contact': ('PATCH', '/v1/Contacts/{id}'),
 'list_classes': ('GET', '/v1/Classes'),
 'get_class': ('GET', '/v1/Classes/{id}'),
 'update_class': ('PATCH', '/v1/Classes/{id}'),
 'get_class_roster': ('GET', '/v1/Classes/{classId}/roster'),
 'list_enrollments': ('GET', '/v1/Enrollments'),
 'get_enrollment': ('GET', '/v1/Enrollments/{id}'),
 'enroll_student': ('POST', '/v1/Enrollments/{studentId}'),
 'drop_student': ('POST', '/v1/Enrollments/{studentId}/drop'),
 'list_attendance': ('GET', '/v1/Attendance')}
QUERY_FIELDS = {'get_organization': {},
 'list_locations': {},
 'get_enrollment_options': {},
 'list_families': {'status_id': 'StatusId',
                   'location_id': 'LocationId',
                   'family_name': 'FamilyName',
                   'date_last_updated': 'DateLastUpdated',
                   'phone': 'Phone',
                   'page': 'Page',
                   'page_size': 'PageSize'},
 'get_family': {},
 'create_family': {},
 'update_family': {},
 'list_students': {'family_id': 'FamilyId',
                   'is_active': 'IsActive',
                   'location_id': 'LocationId',
                   'last_name': 'LastName',
                   'birth_date': 'BirthDate',
                   'quit_date': 'QuitDate',
                   'created_date': 'CreatedDate',
                   'date_last_inactive': 'DateLastInactive',
                   'date_last_updated': 'DateLastUpdated',
                   'page': 'Page',
                   'page_size': 'PageSize'},
 'get_student': {},
 'create_student': {},
 'update_student': {},
 'list_contacts': {'family_id': 'FamilyId',
                   'member_id': 'MemberId',
                   'email': 'Email',
                   'primary': 'Primary',
                   'billing': 'Billing',
                   'authorized': 'Authorized',
                   'type_id': 'TypeId',
                   'date_last_updated': 'DateLastUpdated',
                   'phone': 'Phone',
                   'page': 'Page',
                   'page_size': 'PageSize'},
 'get_contact': {},
 'create_contact': {},
 'update_contact': {},
 'list_classes': {'family_id': 'FamilyId',
                  'instructor_id': 'InstructorId',
                  'student_id': 'StudentId',
                  'location_id': 'LocationId',
                  'date_last_updated': 'DateLastUpdated',
                  'page': 'Page',
                  'page_size': 'PageSize'},
 'get_class': {},
 'update_class': {},
 'get_class_roster': {},
 'list_enrollments': {'student_id': 'StudentId',
                      'family_id': 'FamilyId',
                      'class_id': 'ClassId',
                      'class_location_id': 'ClassLocationId',
                      'student_location_id': 'StudentLocationId',
                      'enrolled': 'Enrolled',
                      'page': 'Page',
                      'page_size': 'PageSize'},
 'get_enrollment': {},
 'enroll_student': {},
 'drop_student': {},
 'list_attendance': {'student_id': 'StudentId',
                     'class_id': 'ClassId',
                     'makeup_class_id': 'MakeupClassId',
                     'start_date': 'StartDate',
                     'end_date': 'EndDate',
                     'did_attend': 'DidAttend',
                     'has_scheduled_makeup': 'HasScheduledMakeup',
                     'did_attend_makeup': 'DidAttendMakeup',
                     'date_last_updated': 'DateLastUpdated',
                     'page': 'Page',
                     'page_size': 'PageSize'}}
BODY_FIELDS = {'get_organization': {},
 'list_locations': {},
 'get_enrollment_options': {},
 'list_families': {},
 'get_family': {},
 'create_family': {'family_name': 'familyName',
                   'location_id': 'locationId',
                   'home_phone': 'homePhone',
                   'user_field1': 'userField1',
                   'user_field2': 'userField2',
                   'user_field3': 'userField3',
                   'user_field4': 'userField4',
                   'user_field5': 'userField5'},
 'update_family': {'family_name': 'familyName',
                   'location_id': 'locationId',
                   'status_id': 'statusId',
                   'primary_phone': 'primaryPhone',
                   'emergency_info': 'emergencyInfo',
                   'notes': 'notes',
                   'source_id': 'sourceId',
                   'user_field1': 'userField1',
                   'user_field2': 'userField2',
                   'user_field3': 'userField3',
                   'user_field4': 'userField4',
                   'user_field5': 'userField5'},
 'list_students': {},
 'get_student': {},
 'create_student': {'family_id': 'familyId',
                    'first_name': 'firstName',
                    'middle_initial': 'middleInitial',
                    'last_name': 'lastName',
                    'gender_id': 'genderId',
                    'phone': 'phone',
                    'email': 'email',
                    'birth_date': 'birthDate',
                    'school': 'school',
                    'grade_level_id': 'gradeLevelId',
                    'user_field1': 'userField1',
                    'user_field2': 'userField2',
                    'user_field3': 'userField3',
                    'user_field4': 'userField4',
                    'user_field5': 'userField5'},
 'update_student': {'first_name': 'firstName',
                    'middle_initial': 'middleInitial',
                    'last_name': 'lastName',
                    'is_active': 'isActive',
                    'birth_date': 'birthDate',
                    'gender_id': 'genderId',
                    'grade_level_id': 'gradeLevelId',
                    'email': 'email',
                    'phone': 'phone',
                    'school': 'school',
                    'date_quit': 'dateQuit',
                    'instructor_feedback': 'instructorFeedback',
                    'roll_notes': 'rollNotes',
                    'user_field1': 'userField1',
                    'user_field2': 'userField2',
                    'user_field3': 'userField3',
                    'user_field4': 'userField4',
                    'user_field5': 'userField5'},
 'list_contacts': {},
 'get_contact': {},
 'create_contact': {'family_id': 'familyId',
                    'first_name': 'firstName',
                    'last_name': 'lastName',
                    'contact_type_id': 'contactTypeId',
                    'is_primary': 'isPrimary',
                    'is_billing': 'isBilling',
                    'is_authorized': 'isAuthorized',
                    'home_phone': 'homePhone',
                    'work_phone': 'workPhone',
                    'cell_phone': 'cellPhone',
                    'email': 'email',
                    'notes': 'notes'},
 'update_contact': {'first_name': 'firstName',
                    'last_name': 'lastName',
                    'contact_type_id': 'contactTypeId',
                    'is_primary': 'isPrimary',
                    'is_billing': 'isBilling',
                    'is_authorized': 'isAuthorized',
                    'home_phone': 'homePhone',
                    'work_phone': 'workPhone',
                    'cell_phone': 'cellPhone',
                    'email': 'email',
                    'notes': 'notes'},
 'list_classes': {},
 'get_class': {},
 'update_class': {'class_name': 'className',
                  'description': 'description',
                  'max_size': 'maxSize',
                  'max_wait': 'maxWait',
                  'room_id': 'roomId',
                  'instructor1': 'instructor1',
                  'start_date': 'startDate',
                  'end_date': 'endDate'},
 'get_class_roster': {},
 'list_enrollments': {},
 'get_enrollment': {},
 'enroll_student': {'class_id': 'classId',
                    'enroll_type_id': 'enrollTypeId',
                    'enroll_date': 'enrollDate',
                    'days': 'days',
                    'enroll_comments': 'enrollComments',
                    'ignore_age_validation': 'ignoreAgeValidation'},
 'drop_student': {'class_id': 'classId',
                  'drop_date': 'dropDate',
                  'drop_reason_id': 'dropReasonId',
                  'drop_notes': 'dropNotes',
                  'email_primary_instructor': 'emailPrimaryInstructor'},
 'list_attendance': {}}
PATH_FIELDS = {'get_organization': {},
 'list_locations': {},
 'get_enrollment_options': {},
 'list_families': {},
 'get_family': {'id': 'family_id'},
 'create_family': {},
 'update_family': {'id': 'family_id'},
 'list_students': {},
 'get_student': {'id': 'student_id'},
 'create_student': {},
 'update_student': {'id': 'student_id'},
 'list_contacts': {},
 'get_contact': {'id': 'contact_id'},
 'create_contact': {},
 'update_contact': {'id': 'contact_id'},
 'list_classes': {},
 'get_class': {'id': 'class_id'},
 'update_class': {'id': 'class_id'},
 'get_class_roster': {'classId': 'class_id'},
 'list_enrollments': {},
 'get_enrollment': {'id': 'enrollment_id'},
 'enroll_student': {'studentId': 'student_id'},
 'drop_student': {'studentId': 'student_id'},
 'list_attendance': {}}

JackrabbitClassOperation = Annotated[Union[
    GetOrganizationConfig,
    ListLocationsConfig,
    GetEnrollmentOptionsConfig,
    ListFamiliesConfig,
    GetFamilyConfig,
    CreateFamilyConfig,
    UpdateFamilyConfig,
    ListStudentsConfig,
    GetStudentConfig,
    CreateStudentConfig,
    UpdateStudentConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactConfig,
    UpdateContactConfig,
    ListClassesConfig,
    GetClassConfig,
    UpdateClassConfig,
    GetClassRosterConfig,
    ListEnrollmentsConfig,
    GetEnrollmentConfig,
    EnrollStudentConfig,
    DropStudentConfig,
    ListAttendanceConfig
], Field(discriminator="operation")]


class JackrabbitClassNodeConfig(NodeConfig[JackrabbitClassOperation, JackrabbitClassAPITokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(str(k), token): _redact(v, token) for k, v in value.items()}
    return value


class JackrabbitClassNode(WorkflowNode):
    integration_type = "automation-jackrabbit-class"
    connection_evidence = ConnectionEvidence(
        noun="organization", operation="get_organization", identity_operation="get_organization",
        label_keys=("name", "email"))

    @classmethod
    def get_config_model(cls):
        return JackrabbitClassNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Jackrabbit Class Customer API token")
        op, credential = self.config.config, self.config.credentials
        method, path = ROUTES[op.operation]
        for wire, field in PATH_FIELDS[op.operation].items():
            path = path.replace("{" + wire + "}", str(getattr(op, field)))
        values = op.model_dump(mode="json", exclude_none=True)
        params = {wire: values[field] for field, wire in QUERY_FIELDS[op.operation].items() if field in values}
        # HTTP query booleans must be lowercase; false is a meaningful filter.
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        body = {wire: values[field] for field, wire in BODY_FIELDS[op.operation].items() if field in values}
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        if credential.organization_id is not None:
            headers["X-Org-Id"] = str(credential.organization_id)
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers,
                                                params=params, **({"json": body} if writing else {}))
        except httpx.RequestError:
            if not writing:
                raise ValueError("Jackrabbit Class could not be reached; try the read again") from None
            result = {"status": "unknown", "success": False, "action": op.operation,
                      "message": "The write outcome is unknown. Check Jackrabbit before retrying.",
                      "write_outcome": "unverified"}
            await self.emit(result)
            return result
        if not 200 <= response.status_code < 300:
            # Do not follow redirects or return request headers, which contain the token.
            message = _redact(response.text[:2000], credential.api_token)
            raise ValueError(f"Jackrabbit Class HTTP {response.status_code}: {message}")
        if not response.content:
            if method == "GET":
                raise ValueError("Jackrabbit Class returned an empty read response")
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Jackrabbit Class returned an invalid JSON response; inspect any write before retrying") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Jackrabbit Class returned an unexpected JSON response")
        if op.operation == "get_organization" and (
            not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip()
        ):
            raise ValueError("Jackrabbit Class did not return an organization name")
        result = {"status": "success", "success": True, "action": op.operation,
                  "http_status": response.status_code, "data": data}
        if writing:
            result["write_outcome"] = "acknowledged"
        if "page" in values:
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("Jackrabbit Class returned an invalid paginated response")
            try:
                total = int(data["totalCount"])
                page = int(data["page"])
                size = int(data["pageSize"])
            except (KeyError, ValueError, TypeError):
                raise ValueError("Jackrabbit Class response omitted pagination counts") from None
            result["next_page"] = page + 1 if size > 0 and page * size < total else None
            result["total_count"] = total
        result = _redact(result, credential.api_token)
        await self.emit(result)
        return result
