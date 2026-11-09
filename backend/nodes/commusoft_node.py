"""Commusoft private-application v2 operations, pinned to the published API contract.

Account-specific property reads establish connection evidence. Each operation sends
one request to the selected documented regional root, without automatic write retries.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

ROOTS = {"uk": "https://app.commusoft.co.uk/api/v2", "us": "https://app.commusoft.us/api/v2"}
AUTH_DOC = "https://developer.commusoft.com/authentication-1985209m0"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CommusoftAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Commusoft API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOC,
            "x-credential-instructions": "An administrator can create an API key in Commusoft Settings → Private applications. Paste the key and choose the business region. Your subscription must support private applications."})
    credential_type: Literal["commusoft_api_key"] = Field("commusoft_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        description="Paste the private application's API key without the Bearer prefix.",
        json_schema_extra={"ui:widget": "password"}, repr=False)
    region: Literal["uk", "us"] = Field("uk", title="Region", description="UK, or US for a US/Canada business.")

    @field_validator("api_key")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value.isascii() or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class ContactBody(_Input):
    firstName: str = Field(..., title="First Name", min_length=1)
    lastName: str = Field(..., title="Last Name", min_length=1)
    email: str | None = Field(None, title="Email")
    telephone: str | None = Field(None, title="Telephone")
    mobile: str | None = Field(None, title="Mobile")


class CustomerBody(_Input):
    contact: ContactBody
    addressLine1: str = Field(..., title="Address Line 1", min_length=1)
    postcode: str = Field(..., title="Postcode", min_length=1)
    addressLine2: str | None = None
    addressLine3: str | None = None
    town: str | None = None
    provinceID: int | None = None
    customerType: int | None = None
    accountingSystemReference: str | None = None
    vacant: Literal["Yes", "No"] | None = None
    advertisingID: int | None = None
    buildingTypeID: int | None = None
    priceBookID: int | None = None
    creditorsDayID: int | None = None
    hasAfterSalesCareBeenTurnedOn: bool | None = None


class CustomerUpdateBody(_Input):
    contact: ContactBody | None = None
    addressLine1: str | None = None
    addressLine2: str | None = None
    addressLine3: str | None = None
    town: str | None = None
    provinceID: int | None = None
    postcode: str | None = None
    accountingSystemReference: str | None = None
    vacant: Literal["Yes", "No"] | None = None
    advertisingID: int | None = None
    buildingTypeID: int | None = None
    priceBookID: int | None = None
    creditorsDayID: int | None = None
    hasAfterSalesCareBeenTurnedOn: bool | None = None


class PropertyContactBody(_Input):
    firstName: str = Field(..., title="First Name", min_length=1)
    lastName: str = Field(..., title="Last Name", min_length=1)
    email: str | None = None
    position: str | None = None


class OpportunityBody(_Input):
    opportunityTemplateID: int = Field(..., title="Opportunity Template ID", ge=1)
    salesPersonID: int | None = None
    pipelineID: int | None = None
    customerContactID: int | None = None
    siteContactID: int | None = None
    notes: str | None = None
    customerReference: str | None = None
    businessUnitID: int | None = None
    userGroupID: int | None = None
    reportingLineID: int | None = None
    tags: list[str] | None = None


class OpportunityStageBody(_Input):
    stageID: int = Field(..., title="Stage ID")


class JobBody(_Input):
    settingsJobDescriptionID: str = Field(..., title="Job Description Template ID", min_length=1)
    customerContactID: str | None = None
    siteContactID: str | None = None
    notes: str | None = None
    customerReference: str | None = None
    quotedAmount: str | None = None
    priority: str | None = None
    businessUnitID: int | None = None
    userGroupID: int | None = None


class JobUpdateBody(_Input):
    notes: str | None = None
    customerContactID: str | None = None
    siteContactID: str | None = None
    customerReference: str | None = None
    quotedAmount: str | None = None
    priority: str | None = None
    businessUnitID: int | None = None
    userGroupID: int | None = None


class JobStageBody(_Input):
    stageID: int = Field(..., title="Stage ID")
    pipelineID: int = Field(..., title="Pipeline ID")


class JobCompleteBody(_Input):
    completeDateTime: datetime = Field(..., title="Completion Time", description="ISO 8601 completion timestamp.")


class AppointmentBody(_Input):
    parentType: Literal["normal", "job", "estimate", "opportunity"]
    parentID: int
    date: str = Field(..., title="Date", description="Appointment date in YYYY-MM-DD format.")
    hasTime: bool
    assigneeUserID: int
    description: str
    timeSlot: str | None = None
    startTime: datetime | None = None
    endTime: datetime | None = None
    notes: str | None = None
    isRecurringEvent: Literal[False] = Field(False, description="Create a single appointment; recurring events are not supported by this operation.")


class ListPropertiesConfig(_Input):
    """List properties using GET /properties."""
    operation: Literal["list_properties"] = Field("list_properties", json_schema_extra={"ui:hidden": True})
    createdOnDateTime: str | None = Field(None, title='createdOnDateTime')
    lastUpdatedOnDateTime: str | None = Field(None, title='lastUpdatedOnDateTime')
    customerTypeID: int | None = Field(None, title='customerTypeID')
    type: Literal['customer', 'workaddress'] | None = Field(None, title='type')
    status: Literal['active', 'dormant'] | None = Field(None, title='status')
    UPRN: str | None = Field(None, title='UPRN')
    limit: int | None = Field(None, title='limit', ge=1)
    after: int | None = Field(None, title='after', ge=1)
    before: int | None = Field(None, title='before', ge=1)
    sort: Literal['createdOnDateTime', 'lastUpdatedOnDateTime', 'customerTypeID', 'type', 'lastName', 'companyName'] | None = Field(None, title='sort')
    includeCount: bool | None = Field(None, title='includeCount')


class GetPropertyConfig(_Input):
    """Get property using GET /properties/{propertyID}."""
    operation: Literal["get_property"] = Field("get_property", json_schema_extra={"ui:hidden": True})
    propertyID: str = Field(..., title='propertyID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class CreateCustomerConfig(_Input):
    """Create customer using POST /customers."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    payload: CustomerBody = Field(..., title="Create Customer Data")


class UpdateCustomerConfig(_Input):
    """Update customer using PATCH /customers/{propertyID}."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    propertyID: str = Field(..., title='propertyID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: CustomerUpdateBody = Field(..., title="Update Customer Data")


class ListContactsConfig(_Input):
    """List contacts using GET /propertyContacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    propertyID: int = Field(..., title='propertyID')
    createdOnDateTime_gte: str | None = Field(None, title='createdOnDateTime[gte]')
    lastUpdatedOnDateTime_lt: str | None = Field(None, title='lastUpdatedOnDateTime[lt]')
    limit: int | None = Field(None, title='limit', ge=1)
    after: int | None = Field(None, title='after', ge=1)
    before: int | None = Field(None, title='before', ge=1)
    includeCount: bool | None = Field(None, title='includeCount')
    type: str | None = Field(None, title='type')


class CreateContactConfig(_Input):
    """Create contact using POST /properties/{propertyID}/contacts."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    propertyID: str = Field(..., title='propertyID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: PropertyContactBody = Field(..., title="Create Contact Data")


class UpdateContactConfig(_Input):
    """Update contact using PATCH /contacts/{contactID}."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contactID: str = Field(..., title='contactID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: PropertyContactBody = Field(..., title="Update Contact Data")


class ListAssetsConfig(_Input):
    """List assets using GET /assets."""
    operation: Literal["list_assets"] = Field("list_assets", json_schema_extra={"ui:hidden": True})
    createdOnDateTime: datetime | None = Field(None, title='createdOnDateTime')
    lastUpdatedOnDateTime: datetime | None = Field(None, title='lastUpdatedOnDateTime')
    propertyID: int | None = Field(None, title='propertyID')
    assetGroupID: int | None = Field(None, title='assetGroupID')
    assetTypeID: int | None = Field(None, title='assetTypeID')
    limit: int | None = Field(None, title='limit', ge=1)
    after: int | None = Field(None, title='after', ge=1)
    before: int | None = Field(None, title='before', ge=1)
    sort: str | None = Field(None, title='sort')
    includeCount: bool | None = Field(None, title='includeCount')


class GetAssetConfig(_Input):
    """Get asset using GET /assets/{assetID}."""
    operation: Literal["get_asset"] = Field("get_asset", json_schema_extra={"ui:hidden": True})
    assetID: str = Field(..., title='assetID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ListOpportunitiesConfig(_Input):
    """List opportunities using GET /opportunities."""
    operation: Literal["list_opportunities"] = Field("list_opportunities", json_schema_extra={"ui:hidden": True})
    createdByType: str | None = Field(None, title='createdByType')
    createdByID: int | None = Field(None, title='createdByID')
    createdOnDateTime_gte: datetime | None = Field(None, title='createdOnDateTime[gte]')
    lastUpdatedOnDateTime_lte: datetime | None = Field(None, title='lastUpdatedOnDateTime[lte]')
    propertyID: int | None = Field(None, title='propertyID')
    opportunityTemplateID: int | None = Field(None, title='opportunityTemplateID')
    salesPersonID: int | None = Field(None, title='salesPersonID')
    userGroupID: int | None = Field(None, title='userGroupID')
    businessUnitID: int | None = Field(None, title='businessUnitID')
    reportingLineID: int | None = Field(None, title='reportingLineID')
    pipelineID: int | None = Field(None, title='pipelineID')
    stageID: int | None = Field(None, title='stageID')
    includeCount: bool | None = Field(None, title='includeCount')
    limit: int | None = Field(None, title='limit', ge=1)
    after: int | None = Field(None, title='after', ge=1)
    before: int | None = Field(None, title='before', ge=1)
    sort: str | None = Field(None, title='sort')


class GetOpportunityConfig(_Input):
    """Get opportunity using GET /opportunities/{opportunityID}."""
    operation: Literal["get_opportunity"] = Field("get_opportunity", json_schema_extra={"ui:hidden": True})
    opportunityID: str = Field(..., title='opportunityID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    includeContacts: bool | None = Field(None, title='includeContacts')
    includeProposal: bool | None = Field(None, title='includeProposal')


class CreateOpportunityConfig(_Input):
    """Create opportunity using POST /properties/{propertyID}/opportunities."""
    operation: Literal["create_opportunity"] = Field("create_opportunity", json_schema_extra={"ui:hidden": True})
    propertyID: str = Field(..., title='propertyID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: OpportunityBody = Field(..., title="Create Opportunity Data")


class ChangeOpportunityStageConfig(_Input):
    """Change opportunity stage using POST /opportunities/{opportunityID}/changeStage."""
    operation: Literal["change_opportunity_stage"] = Field("change_opportunity_stage", json_schema_extra={"ui:hidden": True})
    opportunityID: str = Field(..., title='opportunityID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: OpportunityStageBody = Field(..., title="Change Opportunity Stage Data")


class ListJobsConfig(_Input):
    """List jobs using GET /jobs."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    createdByType: str | None = Field(None, title='createdByType')
    createdByID: int | None = Field(None, title='createdByID')
    createdOnDateTime_gte: str | None = Field(None, title='createdOnDateTime[gte]')
    lastUpdatedOnDateTime: str | None = Field(None, title='lastUpdatedOnDateTime')
    customerID: int | None = Field(None, title='customerID')
    propertyID: int | None = Field(None, title='propertyID')
    settingsJobDescriptionID: int | None = Field(None, title='settingsJobDescriptionID')
    status: Literal['ongoing', 'completed', 'on_hold', 'pending'] | None = Field(None, title='status')
    pipelineID: int | None = Field(None, title='pipelineID')
    stageID: str | None = Field(None, title='stageID')
    businessUnitID: int | None = Field(None, title='businessUnitID')
    userGroupID: int | None = Field(None, title='userGroupID')
    teamID: int | None = Field(None, title='teamID')
    jobReportedDateTime: str | None = Field(None, title='jobReportedDateTime')
    usersCurrentlyAssignedToJob: str | None = Field(None, title='usersCurrentlyAssignedToJob')
    tags: str | None = Field(None, title='tags')
    priority: str | None = Field(None, title='priority')
    completedOnDateTime_lte: str | None = Field(None, title='completedOnDateTime[lte]')
    closedOnDateTime_lte: str | None = Field(None, title='closedOnDateTime[lte]')
    closedOutcome: Literal['Invoiced', 'FreeOfCharge', 'Aborted'] | None = Field(None, title='closedOutcome')
    isJobOnHold: Literal['true', 'false'] | None = Field(None, title='isJobOnHold')
    limit: int | None = Field(None, title='limit', ge=1)
    after: int | None = Field(None, title='after', ge=1)
    before: int | None = Field(None, title='before', ge=1)
    sort: str | None = Field(None, title='sort')
    includeCount: bool | None = Field(None, title='includeCount')


class GetJobConfig(_Input):
    """Get job using GET /jobs/{jobID}."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., title='jobID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class CreateJobConfig(_Input):
    """Create job using POST /properties/{propertyID}/jobs."""
    operation: Literal["create_job"] = Field("create_job", json_schema_extra={"ui:hidden": True})
    propertyID: int = Field(..., title='propertyID', ge=1)
    payload: JobBody = Field(..., title="Create Job Data")


class UpdateJobConfig(_Input):
    """Update job using PATCH /jobs/{jobID}."""
    operation: Literal["update_job"] = Field("update_job", json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., title='jobID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: JobUpdateBody = Field(..., title="Update Job Data")


class ChangeJobStageConfig(_Input):
    """Change job stage using POST /jobs/{jobID}/changeStage."""
    operation: Literal["change_job_stage"] = Field("change_job_stage", json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., title='jobID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: JobStageBody = Field(..., title="Change Job Stage Data")


class CompleteJobConfig(_Input):
    """Complete job using POST /jobs/{jobID}/complete."""
    operation: Literal["complete_job"] = Field("complete_job", json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., title='jobID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    payload: JobCompleteBody = Field(..., title="Complete Job Data")


class ListAppointmentsConfig(_Input):
    """List appointments using GET /appointments."""
    operation: Literal["list_appointments"] = Field("list_appointments", json_schema_extra={"ui:hidden": True})
    createdOnDateTime: str | None = Field(None, title='createdOnDateTime')
    lastUpdatedOnDateTime: str | None = Field(None, title='lastUpdatedOnDateTime')
    parentType: Literal['normal', 'job', 'estimate', 'opportunity'] | None = Field(None, title='parentType')
    engineerID: str | None = Field(None, title='engineerID')
    fromDate: str | None = Field(None, title='fromDate')
    toDate: str | None = Field(None, title='toDate')
    status: Literal['accepted', 'rejected', 'travel', 'arrived', 'aborted', 'no_access', 'left', 'cancelled', 'just_booked', 'completed'] | None = Field(None, title='status')
    lockStatus: Literal['no_lock', 'lock_to_engineer', 'lock_to_date_time', 'lock_to_engineer_and_date_time', 'lock_to_service_window'] | None = Field(None, title='lockStatus')
    limit: int | None = Field(None, title='limit', ge=1)
    after: int | None = Field(None, title='after', ge=1)
    before: int | None = Field(None, title='before', ge=1)
    sort: Literal['createdOnDateTime', 'lastUpdatedOnDateTime'] | None = Field(None, title='sort')
    includeCount: bool | None = Field(None, title='includeCount')


class GetAppointmentConfig(_Input):
    """Get appointment using GET /appointments/{appointmentID}."""
    operation: Literal["get_appointment"] = Field("get_appointment", json_schema_extra={"ui:hidden": True})
    appointmentID: str = Field(..., title='appointmentID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class CreateAppointmentConfig(_Input):
    """Create appointment using POST /appointments."""
    operation: Literal["create_appointment"] = Field("create_appointment", json_schema_extra={"ui:hidden": True})
    payload: AppointmentBody = Field(..., title="Create Appointment Data")


class DeleteAppointmentConfig(_Input):
    """Delete appointment using DELETE /appointments/{appointmentID}."""
    operation: Literal["delete_appointment"] = Field("delete_appointment", json_schema_extra={"ui:hidden": True})
    appointmentID: str = Field(..., title='appointmentID', min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ListUsersConfig(_Input):
    """List users using GET /users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    createdByType: str | None = Field(None, title='createdByType')
    createdByID: str | None = Field(None, title='createdByID')
    createdOnDateTime: str | None = Field(None, title='createdOnDateTime')
    lastUpdatedOnDateTime: str | None = Field(None, title='lastUpdatedOnDateTime')
    limit: str | None = Field(None, title='limit')
    after: str | None = Field(None, title='after')
    before: str | None = Field(None, title='before')
    deleted: Literal['Yes', 'No'] | None = Field(None, title='deleted')
    includeCount: bool | None = Field(None, title='includeCount')


CommusoftConfig = Annotated[Union[
    ListPropertiesConfig,
    GetPropertyConfig,
    CreateCustomerConfig,
    UpdateCustomerConfig,
    ListContactsConfig,
    CreateContactConfig,
    UpdateContactConfig,
    ListAssetsConfig,
    GetAssetConfig,
    ListOpportunitiesConfig,
    GetOpportunityConfig,
    CreateOpportunityConfig,
    ChangeOpportunityStageConfig,
    ListJobsConfig,
    GetJobConfig,
    CreateJobConfig,
    UpdateJobConfig,
    ChangeJobStageConfig,
    CompleteJobConfig,
    ListAppointmentsConfig,
    GetAppointmentConfig,
    CreateAppointmentConfig,
    DeleteAppointmentConfig,
    ListUsersConfig
], Field(discriminator="operation")]


class CommusoftFullConfig(NodeConfig[CommusoftConfig, CommusoftAPIKeyCredential]):
    pass


ROUTES = {'list_properties': ('GET',
                     '/properties',
                     {'createdOnDateTime': 'createdOnDateTime',
                      'lastUpdatedOnDateTime': 'lastUpdatedOnDateTime',
                      'customerTypeID': 'customerTypeID',
                      'type': 'type',
                      'status': 'status',
                      'UPRN': 'UPRN',
                      'limit': 'limit',
                      'after': 'after',
                      'before': 'before',
                      'sort': 'sort',
                      'includeCount': 'includeCount'}),
 'get_property': ('GET', '/properties/{propertyID}', {}),
 'create_customer': ('POST', '/customers', {}),
 'update_customer': ('PATCH', '/customers/{propertyID}', {}),
 'list_contacts': ('GET',
                   '/propertyContacts',
                   {'propertyID': 'propertyID',
                    'createdOnDateTime_gte': 'createdOnDateTime[gte]',
                    'lastUpdatedOnDateTime_lt': 'lastUpdatedOnDateTime[lt]',
                    'limit': 'limit',
                    'after': 'after',
                    'before': 'before',
                    'includeCount': 'includeCount',
                    'type': 'type'}),
 'create_contact': ('POST', '/properties/{propertyID}/contacts', {}),
 'update_contact': ('PATCH', '/contacts/{contactID}', {}),
 'list_assets': ('GET',
                 '/assets',
                 {'createdOnDateTime': 'createdOnDateTime',
                  'lastUpdatedOnDateTime': 'lastUpdatedOnDateTime',
                  'propertyID': 'propertyID',
                  'assetGroupID': 'assetGroupID',
                  'assetTypeID': 'assetTypeID',
                  'limit': 'limit',
                  'after': 'after',
                  'before': 'before',
                  'sort': 'sort',
                  'includeCount': 'includeCount'}),
 'get_asset': ('GET', '/assets/{assetID}', {}),
 'list_opportunities': ('GET',
                        '/opportunities',
                        {'createdByType': 'createdByType',
                         'createdByID': 'createdByID',
                         'createdOnDateTime_gte': 'createdOnDateTime[gte]',
                         'lastUpdatedOnDateTime_lte': 'lastUpdatedOnDateTime[lte]',
                         'propertyID': 'propertyID',
                         'opportunityTemplateID': 'opportunityTemplateID',
                         'salesPersonID': 'salesPersonID',
                         'userGroupID': 'userGroupID',
                         'businessUnitID': 'businessUnitID',
                         'reportingLineID': 'reportingLineID',
                         'pipelineID': 'pipelineID',
                         'stageID': 'stageID',
                         'includeCount': 'includeCount',
                         'limit': 'limit',
                         'after': 'after',
                         'before': 'before',
                         'sort': 'sort'}),
 'get_opportunity': ('GET',
                     '/opportunities/{opportunityID}',
                     {'includeContacts': 'includeContacts', 'includeProposal': 'includeProposal'}),
 'create_opportunity': ('POST', '/properties/{propertyID}/opportunities', {}),
 'change_opportunity_stage': ('POST', '/opportunities/{opportunityID}/changeStage', {}),
 'list_jobs': ('GET',
               '/jobs',
               {'createdByType': 'createdByType',
                'createdByID': 'createdByID',
                'createdOnDateTime_gte': 'createdOnDateTime[gte]',
                'lastUpdatedOnDateTime': 'lastUpdatedOnDateTime',
                'customerID': 'customerID',
                'propertyID': 'propertyID',
                'settingsJobDescriptionID': 'settingsJobDescriptionID',
                'status': 'status',
                'pipelineID': 'pipelineID',
                'stageID': 'stageID',
                'businessUnitID': 'businessUnitID',
                'userGroupID': 'userGroupID',
                'teamID': 'teamID',
                'jobReportedDateTime': 'jobReportedDateTime',
                'usersCurrentlyAssignedToJob': 'usersCurrentlyAssignedToJob',
                'tags': 'tags',
                'priority': 'priority',
                'completedOnDateTime_lte': 'completedOnDateTime[lte]',
                'closedOnDateTime_lte': 'closedOnDateTime[lte]',
                'closedOutcome': 'closedOutcome',
                'isJobOnHold': 'isJobOnHold',
                'limit': 'limit',
                'after': 'after',
                'before': 'before',
                'sort': 'sort',
                'includeCount': 'includeCount'}),
 'get_job': ('GET', '/jobs/{jobID}', {}),
 'create_job': ('POST', '/properties/{propertyID}/jobs', {}),
 'update_job': ('PATCH', '/jobs/{jobID}', {}),
 'change_job_stage': ('POST', '/jobs/{jobID}/changeStage', {}),
 'complete_job': ('POST', '/jobs/{jobID}/complete', {}),
 'list_appointments': ('GET',
                       '/appointments',
                       {'createdOnDateTime': 'createdOnDateTime',
                        'lastUpdatedOnDateTime': 'lastUpdatedOnDateTime',
                        'parentType': 'parentType',
                        'engineerID': 'engineerID',
                        'fromDate': 'fromDate',
                        'toDate': 'toDate',
                        'status': 'status',
                        'lockStatus': 'lockStatus',
                        'limit': 'limit',
                        'after': 'after',
                        'before': 'before',
                        'sort': 'sort',
                        'includeCount': 'includeCount'}),
 'get_appointment': ('GET', '/appointments/{appointmentID}', {}),
 'create_appointment': ('POST', '/appointments', {}),
 'delete_appointment': ('DELETE', '/appointments/{appointmentID}', {}),
 'list_users': ('GET',
                '/users',
                {'createdByType': 'createdByType',
                 'createdByID': 'createdByID',
                 'createdOnDateTime': 'createdOnDateTime',
                 'lastUpdatedOnDateTime': 'lastUpdatedOnDateTime',
                 'limit': 'limit',
                 'after': 'after',
                 'before': 'before',
                 'deleted': 'deleted',
                 'includeCount': 'includeCount'})}


class CommusoftNode(WorkflowNode):
    integration_type = "automation-commusoft"
    connection_evidence = ConnectionEvidence(operation="list_properties", noun="properties",
        label_keys=("companyName", "addressLine1", "postcode", "id"))

    @classmethod
    def get_config_model(cls):
        return CommusoftFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Commusoft API key")
        credential = self.config.credentials
        config = self.config.config
        method, route, query_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for name in re.findall(r"{(\w+)}", route):
            route = route.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {wire: values[field] for field, wire in query_fields.items() if field in values}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if config.operation in {"list_jobs", "create_job", "update_job", "get_job"}:
            headers["X-API-VERSION"] = "2.0"
        kwargs = {}
        if "payload" in values:
            body = values["payload"]
            if not body:
                raise ValueError("Provide at least one field to update")
            kwargs["json"] = body
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, ROOTS[credential.region] + route,
                headers=headers, params=params, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for the connection-evidence seam.
            message = response.text.replace(credential.api_key, "[redacted]")[:2000]
            output = {"status": "error", "http_status": response.status_code,
                "message": message or f"Commusoft returned HTTP {response.status_code}"}
        else:
            data = response.json() if response.content else None
            if isinstance(data, dict) and data.get("error"):
                output = {"status": "error", "message": str(data["error"]).replace(credential.api_key, "[redacted]")[:2000]}
            else:
                output = {"status": "success", "operation": config.operation, "data": data}
        await self.emit(output)
        return output
