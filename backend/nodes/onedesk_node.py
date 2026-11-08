"""OneDesk public API v1: fixed operations authenticated with OD-Public-API-Key.

Contract: https://onedesk.com/public-api/onedesk-public-api.json
Each operation makes one request; list operations return one bounded offset page.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.onedesk.com"
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
RESOURCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9@._-]{0,255}$"


def _date_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use an ISO 8601 date and time") from None
    if parsed.tzinfo is None:
        raise ValueError("Include a timezone in the date and time")
    return value


UUIDText = Annotated[str, Field(pattern=UUID_PATTERN, json_schema_extra={"format": "uuid"})]
ISODateTime = Annotated[str, Field(json_schema_extra={"format": "date-time"}), AfterValidator(_date_time)]


class OnedeskAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OneDesk API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.onedesk.com/public-api/",
        "x-credential-instructions": "Paste your OneDesk public API key. NoClick sends it in the OD-Public-API-Key header to app.onedesk.com and reads your organization profile to verify the connection.",
    })
    credential_type: Literal["onedesk_api_key"] = Field("onedesk_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PropertyFilter(_Input):
    property: str = Field(..., min_length=1, max_length=200, description="Property name supported by this resource's documented filter table.")
    operation: Literal["EQ", "NE", "GT", "LT", "GE", "LE", "CONTAINS", "NOT_CONTAINS"]
    value: Union[str, StrictBool, int, float, list[Union[str, int, float]]]


class _List(_Input):
    limit: int = Field(10, ge=1, le=50, description="Details page size, maximum 50. Request the next page with offset + the number of returned records.")
    offset: int = Field(0, ge=0, le=2147483647)
    isAsc: StrictBool = Field(False, title="Ascending creation order")
    properties: Optional[list[PropertyFilter]] = Field(None, max_length=50, description="Optional AND-combined property filters; unsupported filters are reported as errors.")


class _Update(_Input):
    external_id: str = Field(..., pattern=UUID_PATTERN, title="External ID", description="OneDesk external UUID, not the numeric display ID.")

    @model_validator(mode="after")
    def changes_required(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "external_id"}):
            raise ValueError("Supply at least one field to update")
        return self


class OnedeskGetOrganizationConfig(_Input):
    """Get organization profile and policy."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})


class OnedeskGetItemConfig(_Input):
    """Get item details by external id."""
    operation: Literal["get_item"] = Field("get_item", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=UUID_PATTERN, title="External ID")


class OnedeskCreateItemConfig(_Input):
    """Create work item."""
    operation: Literal["create_item"] = Field("create_item", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000, description='name of the item', title='Name', examples=['new name'])
    type: Optional[str] = Field(None, min_length=1, max_length=1000, description='name of the item type', title='Type', examples=['ticket'])
    description: Optional[str] = Field(None, min_length=1, max_length=20000, description='description of the item', title='Description', examples=['my description'])
    projectExternalId: Optional[str] = Field(None, min_length=1, max_length=1000, pattern=UUID_PATTERN, description='project external id', title='Project external id', examples=['0fcd5fgh-0000-0000-0000-c75df7969bad'])
    priority: Optional[Literal[0, 20, 40, 60, 80, 100]] = Field(None, description='priority of the work item ([0,20,40,60,80,100] correspond to [0,1,2,3,4,5] stars respectively)', title='Priority', examples=[0])
    requesterExternalIds: Optional[list[UUIDText]] = Field(None, max_length=100, title='Requester external ids')
    requesterEmails: Optional[list[EmailStr]] = Field(None, max_length=100, title='Requester emails')
    followerExternalIds: Optional[list[UUIDText]] = Field(None, max_length=100, title='Follower external ids')
    plannedHour: Optional[float] = Field(None, ge=0, allow_inf_nan=False, description='planned number of hours', title='Planned hour', examples=[8])
    plannedStart: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Planned start', examples=['2019-10-18T11:09:09+00:00'])
    plannedFinish: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Planned finish', examples=['2019-10-19T11:09:09+00:00'])
    customFields: Optional[dict[str, Union[str, list[str]]]] = Field(None, title='Custom fields')


class OnedeskUpdateItemConfig(_Update):
    """Update item by external id."""
    operation: Literal["update_item"] = Field("update_item", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, min_length=1, max_length=1000, description='name of item', title='Name', examples=['new name'])
    description: Optional[str] = Field(None, min_length=1, max_length=20000, description='description of the item', title='Description', examples=['new description'])
    type: Optional[str] = Field(None, min_length=1, max_length=1000, description='item type', title='Type', examples=['Task'])
    projectExternalId: Optional[str] = Field(None, min_length=1, max_length=1000, pattern=UUID_PATTERN, description='project external id of item', title='Project external id', examples=['a08bd539-0000-0000-0000-cc4991ed51f7'])
    priority: Optional[Literal[0, 20, 40, 60, 80, 100]] = Field(None, description='priority of the work item ([0,20,40,60,80,100] correspond to [0,1,2,3,4,5] stars respectively)', title='Priority', examples=[80])
    percentComplete: Optional[int] = Field(None, ge=0, le=100, description='progress of item', title='Percent complete', examples=[50])
    lifecycleStatusName: Optional[str] = Field(None, min_length=1, max_length=1000, description='name of lifecycle status', title='Lifecycle status name', examples=['complete'])
    archived: Optional[StrictBool] = Field(None, description='archive or unarchive the item', title='Archived', examples=[False])
    customFields: Optional[dict[str, Union[str, list[str]]]] = Field(None, title='Custom fields')


class OnedeskListItemsConfig(_List):
    """Filter items and get item details."""
    operation: Literal["list_items"] = Field("list_items", json_schema_extra={"ui:hidden": True})
    itemType: list[str] = Field(..., min_length=1, max_length=100, description='type of items to be filtered', title='Item type', examples=[['task']])


class OnedeskGetCustomerConfig(_Input):
    """Get customer by external id."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=UUID_PATTERN, title="External ID")


class OnedeskCreateCustomerConfig(_Input):
    """Create customer."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=1, max_length=1000, description='email of the customer', title='Email', examples=['customer01@example.com'])
    firstName: Optional[str] = Field(None, min_length=1, max_length=1000, description='first name of customer', title='First name', examples=['first name'])
    lastName: Optional[str] = Field(None, min_length=1, max_length=1000, description='last name of customer', title='Last name', examples=['last name'])
    type: Optional[str] = Field(None, min_length=1, max_length=1000, description='customer type', title='Type', examples=['interested customer'])
    customerOrganization: Optional[str] = Field(None, min_length=1, max_length=1000, pattern=UUID_PATTERN, description='id of customer organization this customer belongs to', title='Customer organization', examples=['1234596f4-0000-0000-0000-cb0e42b1db19'])


class OnedeskUpdateCustomerConfig(_Update):
    """Update customer by external id."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    firstName: Optional[str] = Field(None, min_length=1, max_length=1000, description='updated customer first name', title='First name', examples=['John'])
    lastName: Optional[str] = Field(None, min_length=1, max_length=1000, description='updated customer last name', title='Last name', examples=['Doe'])
    email: Optional[EmailStr] = Field(None, min_length=1, max_length=1000, description='updated customer email', title='Email', examples=['customer01@example.com'])
    phoneNumber: Optional[str] = Field(None, min_length=1, max_length=1000, description='updated customer work phone number', title='Phone number', examples=['+11234567890'])
    type: Optional[str] = Field(None, min_length=1, max_length=1000, description='updated customer type', title='Type', examples=['interested-customer'])
    priority: Optional[Literal[0, 20, 40, 60, 80, 100]] = Field(None, description='updated customer priority', title='Priority', examples=[80])
    deactivate: Optional[StrictBool] = Field(None, description='when set to true, deactivate this customer', title='Deactivate', examples=[False])
    customerOrganizationExternalId: Optional[str] = Field(None, min_length=1, max_length=1000, pattern=UUID_PATTERN, description='new customer organization for customer (external id)', title='Customer organization external id', examples=['e69a790c-0000-0000-a3f9-f73df4385760'])
    customFields: Optional[dict[str, Union[str, list[str]]]] = Field(None, title='Custom fields')


class OnedeskListCustomersConfig(_List):
    """Filter customers and get customer details."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})


class OnedeskGetProjectConfig(_Input):
    """Get project by external id."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=UUID_PATTERN, title="External ID")


class OnedeskCreateProjectConfig(_Input):
    """Create a project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000, description='name of the project', title='Name', examples=['sample project 01'])
    type: Optional[str] = Field(None, min_length=1, max_length=1000, description='type of the project', title='Type', examples=['project 02'])
    description: Optional[str] = Field(None, min_length=1, max_length=20000, description='description of the project', title='Description', examples=['this is a description of the project'])
    parentPortfolioExternalIds: Optional[list[UUIDText]] = Field(None, max_length=100, title='Parent portfolio external ids')
    userFollowerExternalIds: Optional[list[UUIDText]] = Field(None, max_length=100, title='User follower external ids')
    customerFollowerExternalIds: Optional[list[UUIDText]] = Field(None, max_length=100, title='Customer follower external ids')
    customerRequesterExternalId: Optional[str] = Field(None, min_length=1, max_length=1000, pattern=UUID_PATTERN, description='customer organization external id to be added as requester', title='Customer requester external id', examples=['293496f4-0000-0000-0000-cb0e42b1db99'])
    invoiceType: Optional[Literal['actual work performed', 'flat fee', 'prepaid hours', 'no invoice planned']] = Field(None, description='project invoice type\n* Note: flat fee & prepaid hours require a requester', title='Invoice type', examples=['no invoice planned'])
    plannedStart: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Planned start', examples=['2019-10-18T11:09:09+00:00'])
    dueDate: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Due date', examples=['2019-10-18T11:09:09+00:00'])


class OnedeskUpdateProjectConfig(_Update):
    """Update project by external id."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(None, min_length=1, max_length=1000, description='name of the project', title='Name', examples=['sample project 01'])
    type: Optional[str] = Field(None, min_length=1, max_length=1000, description='type of the project', title='Type', examples=['project 02'])
    description: Optional[str] = Field(None, min_length=1, max_length=20000, description='description of the project', title='Description', examples=['this is a description of the project'])
    lifecycleStatus: Optional[str] = Field(None, min_length=1, max_length=1000, description='lifecycle status', title='Lifecycle status', examples=['In progress'])
    invoiceType: Optional[Literal['actual work performed', 'flat fee', 'prepaid hours', 'no invoice planned']] = Field(None, description='project invoice type', title='Invoice type', examples=['flat fee'])
    archived: Optional[StrictBool] = Field(None, description='archive or unarchive the project', title='Archived', examples=[False])
    customFields: Optional[dict[str, Union[str, list[str]]]] = Field(None, title='Custom fields')


class OnedeskListProjectsConfig(_List):
    """Filter projects and get project details."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class OnedeskGetTimesheetConfig(_Input):
    """Get timesheet by external id."""
    operation: Literal["get_timesheet"] = Field("get_timesheet", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=UUID_PATTERN, title="External ID")


class OnedeskCreateTimesheetConfig(_Input):
    """Create timesheet."""
    operation: Literal["create_timesheet"] = Field("create_timesheet", json_schema_extra={"ui:hidden": True})
    userExternalId: str = Field(..., min_length=1, max_length=1000, pattern=UUID_PATTERN, description='Timesheet assignee external id', title='User external id', examples=['616c7f21-0000-0000-0000-e1c087ebe9ea'])
    taskExternalId: str = Field(..., min_length=1, max_length=1000, pattern=UUID_PATTERN, description='Timesheet item external id', title='Task external id', examples=['616c7f21-0000-0000-0000-e1c087ebe9ea'])
    works: float = Field(..., ge=0, allow_inf_nan=False, description='Timesheet work in hours', title='Works', examples=[2.0])
    billable: Optional[StrictBool] = Field(None, description='Timesheet billable', title='Billable', examples=[True])
    note: Optional[str] = Field(None, min_length=1, max_length=20000, description='Timesheet note', title='Note', examples=['this is an example timesheet note'])
    lifecycleStatusName: Optional[str] = Field(None, min_length=1, max_length=1000, description='Timesheet item lifecycle status', title='Lifecycle status name', examples=['Open'])
    percentCompleted: int = Field(..., ge=0, le=100, description='Timesheet task percent completed', title='Percent completed', examples=[50.0])
    start: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Start', examples=['2019-10-18T11:09:09+00:00'])
    finish: ISODateTime = Field(..., min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Finish', examples=['2019-10-18T11:09:09+00:00'])
    customFields: Optional[dict[str, Union[str, list[str]]]] = Field(None, title='Custom fields')


class OnedeskUpdateTimesheetConfig(_Update):
    """Update timesheet by external id."""
    operation: Literal["update_timesheet"] = Field("update_timesheet", json_schema_extra={"ui:hidden": True})
    works: Optional[float] = Field(None, ge=0, allow_inf_nan=False, description='Timesheet work in hours', title='Works', examples=[2.0])
    billable: Optional[StrictBool] = Field(None, description='Timesheet billable', title='Billable', examples=[True])
    note: Optional[str] = Field(None, min_length=1, max_length=20000, description='Timesheet note', title='Note', examples=['this is an example timesheet note'])
    status: Optional[Literal['approved', 'not approved yet', 'declined']] = Field(None, description='Timesheet status', title='Status', examples=['not approved yet'])
    completion: Optional[int] = Field(None, ge=0, le=100, description='Timesheet task percent completed', title='Completion', examples=[50.0])
    start: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Start', examples=['2019-10-18T11:09:09+00:00'])
    finish: Optional[ISODateTime] = Field(None, min_length=1, max_length=1000, description="ISO 8601 date and time with timezone.", title='Finish', examples=['2019-10-18T11:09:09+00:00'])
    invoiceWork: Optional[float] = Field(None, ge=0, allow_inf_nan=False, description='Timesheet invoice work hours', title='Invoice work', examples=[1.0])
    serviceType: Optional[str] = Field(None, min_length=1, max_length=1000, description='Timesheet financial service type option', title='Service type', examples=['Services'])
    customFields: Optional[dict[str, Union[str, list[str]]]] = Field(None, title='Custom fields')


class OnedeskListTimesheetsConfig(_List):
    """Filter timesheets and get timesheet details."""
    operation: Literal["list_timesheets"] = Field("list_timesheets", json_schema_extra={"ui:hidden": True})


class OnedeskGetUserConfig(_Input):
    """Get user by external id."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=UUID_PATTERN, title="External ID")


class OnedeskListUsersConfig(_List):
    """Filter users and get user details."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class OnedeskGetConversationConfig(_Input):
    """Get conversations by external id."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=RESOURCE_PATTERN, title="External ID")


class OnedeskCreateConversationConfig(_Input):
    """Create conversation."""
    operation: Literal["create_conversation"] = Field("create_conversation", json_schema_extra={"ui:hidden": True})
    itemExternalId: Optional[str] = Field(None, min_length=1, max_length=1000, description='external id of linked item', title='Item external id', examples=['6634596f4-0000-0000-0000-cb0e42b1db19'])
    projectExternalId: Optional[str] = Field(None, min_length=1, max_length=1000, description='external id of linked project', title='Project external id', examples=['6634596f4-0000-0000-0000-cb0e42b1db19'])
    publicConversation: Optional[StrictBool] = Field(None, description='* true - Customer Replies\n* false - Internal Messages', title='Public conversation', examples=[True])


class OnedeskGetMessageConfig(_Input):
    """Get conversation message by id."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., pattern=RESOURCE_PATTERN, title="External ID")


class OnedeskCreateMessageConfig(_Input):
    """Create conversation message."""
    operation: Literal["create_message"] = Field("create_message", json_schema_extra={"ui:hidden": True})
    conversationExternalId: str = Field(..., min_length=1, max_length=1000, description='conversation room external id', title='Conversation external id', examples=['7e895fe5-0000-0000-0000-06aa3d02e7ef@conference.im.onedesk.com'])
    content: Optional[str] = Field(None, min_length=1, max_length=20000, description='content of conversation message', title='Content', examples=['Good morning team!'])
    attachmentExternalIds: Optional[list[UUIDText]] = Field(None, max_length=100, title='Attachment external ids')


OnedeskConfig = Annotated[Union[
    OnedeskGetOrganizationConfig,
    OnedeskGetItemConfig,
    OnedeskCreateItemConfig,
    OnedeskUpdateItemConfig,
    OnedeskListItemsConfig,
    OnedeskGetCustomerConfig,
    OnedeskCreateCustomerConfig,
    OnedeskUpdateCustomerConfig,
    OnedeskListCustomersConfig,
    OnedeskGetProjectConfig,
    OnedeskCreateProjectConfig,
    OnedeskUpdateProjectConfig,
    OnedeskListProjectsConfig,
    OnedeskGetTimesheetConfig,
    OnedeskCreateTimesheetConfig,
    OnedeskUpdateTimesheetConfig,
    OnedeskListTimesheetsConfig,
    OnedeskGetUserConfig,
    OnedeskListUsersConfig,
    OnedeskGetConversationConfig,
    OnedeskCreateConversationConfig,
    OnedeskGetMessageConfig,
    OnedeskCreateMessageConfig
], Field(discriminator="operation")]


class OnedeskFullConfig(NodeConfig[OnedeskConfig, OnedeskAPIKeyCredential]):
    pass


ROUTES = {
    "get_organization": ("GET", "/rest/public/organization/profileAndPolicy"),
    "get_item": ("GET", "/rest/public/items/externalId/{externalId}"),
    "create_item": ("POST", "/rest/public/items/"),
    "update_item": ("POST", "/rest/public/items/externalId/{externalId}"),
    "list_items": ("POST", "/rest/public/items/filter/details"),
    "get_customer": ("GET", "/rest/public/customers/externalId/{externalId}"),
    "create_customer": ("POST", "/rest/public/customers/"),
    "update_customer": ("POST", "/rest/public/customers/externalId/{externalId}"),
    "list_customers": ("POST", "/rest/public/customers/filter/details"),
    "get_project": ("GET", "/rest/public/projects/externalId/{externalId}"),
    "create_project": ("POST", "/rest/public/projects/"),
    "update_project": ("POST", "/rest/public/projects/externalId/{externalId}"),
    "list_projects": ("POST", "/rest/public/projects/filter/details"),
    "get_timesheet": ("GET", "/rest/public/timesheets/externalId/{externalId}"),
    "create_timesheet": ("POST", "/rest/public/timesheets/"),
    "update_timesheet": ("POST", "/rest/public/timesheets/externalId/{externalId}"),
    "list_timesheets": ("POST", "/rest/public/timesheets/filter/details"),
    "get_user": ("GET", "/rest/public/users/externalId/{externalId}"),
    "list_users": ("POST", "/rest/public/users/filter/details"),
    "get_conversation": ("GET", "/rest/public/conversations/externalId/{externalId}"),
    "create_conversation": ("POST", "/rest/public/conversations/"),
    "get_message": ("GET", "/rest/public/conversation-messages/externalId/{externalId}"),
    "create_message": ("POST", "/rest/public/conversation-messages/"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class OnedeskNode(WorkflowNode):
    integration_type = "automation-onedesk"
    connection_evidence = ConnectionEvidence(
        noun="organization", identity_operation="get_organization", identity_keys=("organizationName", "organizationUri"),
    )

    @classmethod
    def get_config_model(cls):
        return OnedeskFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a OneDesk API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        if hasattr(config, "external_id"):
            path = path.replace("{externalId}", quote(config.external_id, safe=""))
        payload = config.model_dump(mode="json", exclude_none=True, exclude={"operation", "external_id"})
        # Exactly one request. Never retry a write, follow redirects, or accept a supplied host.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"OD-Public-API-Key": secret, "Accept": "application/json"},
                **({"json": payload} if method == "POST" else {}))
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code, "error": f"OneDesk HTTP {response.status_code}"}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected a bounded OneDesk JSON response")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("OneDesk returned invalid JSON") from None
        body = _redact(body, secret)
        code = body.get("code") if isinstance(body, dict) else body
        if code != "SUCCESS":
            return {"status": "error", "error": code if isinstance(code, str) else "OneDesk response has no result code"}
        result = {"status": "success", "operation": config.operation, "code": code}
        if isinstance(body, dict):
            if "data" not in body:
                raise ValueError("OneDesk response has no data")
            result["data"] = body["data"]
        if config.operation.startswith("list_"):
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise ValueError("OneDesk list response has no records array")
            if len(body["data"]) > config.limit:
                raise ValueError("OneDesk exceeded the requested page size")
            for key in ("notAppliedPropertyFilters", "notAppliedCustomFieldFilters"):
                if body.get(key):
                    return {"status": "error", "error": "OneDesk did not apply all filters", key: body[key]}
            result.update({k: v for k, v in body.items() if k not in {"code", "data"}})
            # totalNum is documented as the number in this output for some resources.
            # A full page means another page MAY exist, not a known total or completion.
            result.update(offset=config.offset, limit=config.limit,
                next_offset=config.offset + len(body["data"]) if len(body["data"]) == config.limit else None)
        return result
