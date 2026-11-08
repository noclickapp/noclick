"""Fireberry CRM record operations using the published tokenid API contract."""
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class FireberryAPIToken(BaseModel):
    model_config = ConfigDict(
        title="Fireberry API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.fireberry.com/reference/get-all-accounts",
            "x-credential-instructions": "Paste your Fireberry API token. NoClick sends it in the tokenid header to api.fireberry.com. Your token's user must have permission for the records you automate.",
        },
    )
    credential_type: Literal["fireberry_api_token"] = Field(
        "fireberry_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API token",
        min_length=1,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    pagesize: int = Field(
        50, ge=1, le=50, description="Records per page; Fireberry allows at most 50."
    )
    pagenumber: int = Field(
        1, ge=1, le=10, description="Page to read; Fireberry allows pages 1 through 10."
    )


class _Record(_Input):
    record_id: str = Field(
        ...,
        title="Record ID",
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        description="The Fireberry record's GUID.",
    )


class ListAccounts(_Page):
    operation: Literal["list_accounts"] = Field(
        "list_accounts", title="Get all Accounts", json_schema_extra={"ui:hidden": True}
    )


class GetAccount(_Record):
    operation: Literal["get_account"] = Field(
        "get_account", title="Get an Account", json_schema_extra={"ui:hidden": True}
    )


class CreateAccount(_Input):
    operation: Literal["create_account"] = Field(
        "create_account",
        title="Create an Account",
        json_schema_extra={"ui:hidden": True},
    )
    accountname: str = Field(
        ..., description="Name of the account (Primary).", min_length=1
    )
    accountnumber: str | None = Field(
        None,
        description="Used for identification, unique values are recommended.",
        max_length=4000,
    )
    firstname: str | None = Field(None, description="First name", max_length=4000)
    lastname: str | None = Field(None, description="Last name", max_length=4000)
    emailaddress1: str | None = Field(
        None,
        description="Primary email address, must be in email format.",
        max_length=4000,
    )
    telephone1: str | None = Field(
        None,
        description="Primary phone number, contains exclusively numbers.",
        max_length=4000,
    )
    websiteurl: str | None = Field(
        None, description="Website of the account in URL format.", max_length=4000
    )
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )
    statuscode: int | None = Field(
        None, description="Status of the account (Picklist)."
    )
    statecode: int | None = Field(
        None,
        description="Sets the state of the account as active or inactive (Picklist).",
    )
    revenue: float | None = Field(None, description="Account revenue")


class UpdateAccount(_Record):
    operation: Literal["update_account"] = Field(
        "update_account",
        title="Update an Account",
        json_schema_extra={"ui:hidden": True},
    )
    accountname: str = Field(
        ..., description="Name of the account (Primary).", min_length=1
    )
    accountnumber: str | None = Field(
        None,
        description="Used for identification, unique values are recommended.",
        max_length=4000,
    )
    firstname: str | None = Field(None, description="First name", max_length=4000)
    lastname: str | None = Field(None, description="Last name", max_length=4000)
    emailaddress1: str | None = Field(
        None,
        description="Primary email address, must be in email format.",
        max_length=4000,
    )
    telephone1: str | None = Field(
        None,
        description="Primary phone number, contains exclusively numbers.",
        max_length=4000,
    )
    websiteurl: str | None = Field(
        None, description="Website of the account in URL format.", max_length=4000
    )
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )
    statuscode: int | None = Field(
        None, description="Status of the account (Picklist)."
    )
    statecode: int | None = Field(
        None,
        description="Sets the state of the account as active or inactive (Picklist).",
    )
    revenue: float | None = Field(None, description="Account revenue")


class DeleteAccount(_Record):
    operation: Literal["delete_account"] = Field(
        "delete_account",
        title="Delete an Account",
        json_schema_extra={"ui:hidden": True},
    )


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field(
        "list_contacts", title="Get all Contacts", json_schema_extra={"ui:hidden": True}
    )


class GetContact(_Record):
    operation: Literal["get_contact"] = Field(
        "get_contact", title="Get a Contact", json_schema_extra={"ui:hidden": True}
    )


class CreateContact(_Input):
    operation: Literal["create_contact"] = Field(
        "create_contact",
        title="Create a Contact",
        json_schema_extra={"ui:hidden": True},
    )
    firstname: str = Field(..., description="First name of the contact.", min_length=1)
    lastname: str | None = Field(None, description="Last name", max_length=4000)
    accountid: str | None = Field(
        None, description="The related account's GUID.", max_length=4000
    )
    companyname: str | None = Field(None, description="Company name", max_length=4000)
    emailaddress1: str | None = Field(
        None,
        description="Primary email address, must be in email format.",
        max_length=4000,
    )
    mobilephone1: str | None = Field(
        None, description="Primary mobile phone number.", max_length=4000
    )
    telephone1: str | None = Field(
        None,
        description="Primary phone number, contains exclusively numbers.",
        max_length=4000,
    )
    jobtitle: str | None = Field(None, description="Job title", max_length=4000)
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )


class UpdateContact(_Record):
    operation: Literal["update_contact"] = Field(
        "update_contact",
        title="Update a Contact",
        json_schema_extra={"ui:hidden": True},
    )
    firstname: str = Field(..., description="First name of the contact.", min_length=1)
    lastname: str | None = Field(None, description="Last name", max_length=4000)
    accountid: str | None = Field(
        None, description="The related account's GUID.", max_length=4000
    )
    companyname: str | None = Field(None, description="Company name", max_length=4000)
    emailaddress1: str | None = Field(
        None,
        description="Primary email address, must be in email format.",
        max_length=4000,
    )
    mobilephone1: str | None = Field(
        None, description="Primary mobile phone number.", max_length=4000
    )
    telephone1: str | None = Field(
        None,
        description="Primary phone number, contains exclusively numbers.",
        max_length=4000,
    )
    jobtitle: str | None = Field(None, description="Job title", max_length=4000)
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )


class DeleteContact(_Record):
    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        title="Delete a Contact",
        json_schema_extra={"ui:hidden": True},
    )


class ListOpportunitys(_Page):
    operation: Literal["list_opportunities"] = Field(
        "list_opportunities",
        title="Get all Opportunities",
        json_schema_extra={"ui:hidden": True},
    )


class GetOpportunity(_Record):
    operation: Literal["get_opportunity"] = Field(
        "get_opportunity",
        title="Get an Opportunity",
        json_schema_extra={"ui:hidden": True},
    )


class CreateOpportunity(_Input):
    operation: Literal["create_opportunity"] = Field(
        "create_opportunity",
        title="Create an Opportunity",
        json_schema_extra={"ui:hidden": True},
    )
    accountid: str = Field(..., description="The related account's GUID.", min_length=1)
    name: str = Field(
        ..., description="Name of the opportunity (Primary).", min_length=1
    )
    contacttid: str | None = Field(
        None, description="The related contact's GUID.", max_length=4000
    )
    closeprobability: float | None = Field(
        None, description="Probability the opportunity will close successfully."
    )
    estimatedvalue: float | None = Field(
        None, description="Estimated total value of the deal."
    )
    estimatedclosedate: str | None = Field(
        None,
        description="Estimated date and time the deal will be closed by.",
        max_length=4000,
    )
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )
    statuscode: int | None = Field(None, description="Status (Picklist)")


class UpdateOpportunity(_Record):
    operation: Literal["update_opportunity"] = Field(
        "update_opportunity",
        title="Update an Opportunity",
        json_schema_extra={"ui:hidden": True},
    )
    accountid: str = Field(..., description="The related account's GUID.", min_length=1)
    name: str = Field(
        ..., description="Name of the opportunity (Primary).", min_length=1
    )
    contacttid: str | None = Field(
        None, description="The related contact's GUID.", max_length=4000
    )
    closeprobability: float | None = Field(
        None, description="Probability the opportunity will close successfully."
    )
    estimatedvalue: float | None = Field(
        None, description="Estimated total value of the deal."
    )
    estimatedclosedate: str | None = Field(
        None,
        description="Estimated date and time the deal will be closed by.",
        max_length=4000,
    )
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )
    statuscode: int | None = Field(None, description="Status (Picklist)")


class DeleteOpportunity(_Record):
    operation: Literal["delete_opportunity"] = Field(
        "delete_opportunity",
        title="Delete an Opportunity",
        json_schema_extra={"ui:hidden": True},
    )


class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field(
        "list_tasks", title="Get all Tasks", json_schema_extra={"ui:hidden": True}
    )


class GetTask(_Record):
    operation: Literal["get_task"] = Field(
        "get_task", title="Get a Task", json_schema_extra={"ui:hidden": True}
    )


class CreateTask(_Input):
    operation: Literal["create_task"] = Field(
        "create_task", title="Create a Task", json_schema_extra={"ui:hidden": True}
    )
    subject: str = Field(
        ..., description="Subject of the task (Primary).", min_length=1
    )
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    objectid: str | None = Field(
        None,
        description="The related record's GUID. Can belong to any editable system object type.",
        max_length=4000,
    )
    objecttypecode: int | None = Field(
        None,
        description="Object number of the object the related record belongs to. If you set the objectid field, you MUST set this field as well.",
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )
    prioritycode: int | None = Field(None, description="Priority (Picklist)")
    reminderdate: str | None = Field(
        None,
        description="Date and time the owner will be reminded of the task.",
        max_length=4000,
    )
    scheduledend: str | None = Field(
        None,
        description="Date and time the task is scheduled to be completed by.",
        max_length=4000,
    )
    statuscode: int | None = Field(None, description="Status (Picklist)")
    tasktypecode: int | None = Field(None, description="Type (Picklist)")

    @model_validator(mode="after")
    def related_record(self):
        if self.objectid is not None and self.objecttypecode is None:
            raise ValueError("Object type code is required with a related record ID")
        return self


class UpdateTask(_Record):
    operation: Literal["update_task"] = Field(
        "update_task", title="Update a Task", json_schema_extra={"ui:hidden": True}
    )
    subject: str = Field(
        ..., description="Subject of the task (Primary).", min_length=1
    )
    description: str | None = Field(
        None, description="Description of up to 4,000 characters.", max_length=4000
    )
    objectid: str | None = Field(
        None,
        description="The related record's GUID. Can belong to any editable system object type.",
        max_length=4000,
    )
    objecttypecode: int | None = Field(
        None,
        description="Object number of the object the related record belongs to. If you set the objectid field, you MUST set this field as well.",
    )
    ownerid: str | None = Field(
        None,
        description="The GUID of the system user who created the record, can also be set manually. Will be used for permissions.",
        max_length=4000,
    )
    prioritycode: int | None = Field(None, description="Priority (Picklist)")
    reminderdate: str | None = Field(
        None,
        description="Date and time the owner will be reminded of the task.",
        max_length=4000,
    )
    scheduledend: str | None = Field(
        None,
        description="Date and time the task is scheduled to be completed by.",
        max_length=4000,
    )
    statuscode: int | None = Field(None, description="Status (Picklist)")
    tasktypecode: int | None = Field(None, description="Type (Picklist)")

    @model_validator(mode="after")
    def related_record(self):
        if self.objectid is not None and self.objecttypecode is None:
            raise ValueError("Object type code is required with a related record ID")
        return self


class DeleteTask(_Record):
    operation: Literal["delete_task"] = Field(
        "delete_task", title="Delete a Task", json_schema_extra={"ui:hidden": True}
    )


FireberryConfig = Annotated[
    Union[
        ListAccounts,
        GetAccount,
        CreateAccount,
        UpdateAccount,
        DeleteAccount,
        ListContacts,
        GetContact,
        CreateContact,
        UpdateContact,
        DeleteContact,
        ListOpportunitys,
        GetOpportunity,
        CreateOpportunity,
        UpdateOpportunity,
        DeleteOpportunity,
        ListTasks,
        GetTask,
        CreateTask,
        UpdateTask,
        DeleteTask,
    ],
    Field(discriminator="operation"),
]


class FireberryFullConfig(NodeConfig[FireberryConfig, FireberryAPIToken]):
    pass


ROUTES = {
    "list_accounts": ("GET", "/api/record/account"),
    "get_account": ("GET", "/api/record/account/{id}"),
    "create_account": ("POST", "/api/record/account"),
    "update_account": ("PUT", "/api/record/account/{id}"),
    "delete_account": ("DELETE", "/api/record/account/{id}"),
    "list_contacts": ("GET", "/api/record/contact"),
    "get_contact": ("GET", "/api/record/contact/{id}"),
    "create_contact": ("POST", "/api/record/contact"),
    "update_contact": ("PUT", "/api/record/contact/{id}"),
    "delete_contact": ("DELETE", "/api/record/contact/{id}"),
    "list_opportunities": ("GET", "/api/record/opportunity"),
    "get_opportunity": ("GET", "/api/record/opportunity/{id}"),
    "create_opportunity": ("POST", "/api/record/opportunity"),
    "update_opportunity": ("PUT", "/api/record/opportunity/{id}"),
    "delete_opportunity": ("DELETE", "/api/record/opportunity/{id}"),
    "list_tasks": ("GET", "/api/record/task"),
    "get_task": ("GET", "/api/record/task/{id}"),
    "create_task": ("POST", "/api/record/task"),
    "update_task": ("PUT", "/api/record/task/{id}"),
    "delete_task": ("DELETE", "/api/record/task/{id}"),
}


class FireberryNode(WorkflowNode):
    integration_type = "automation-fireberry"
    connection_evidence = ConnectionEvidence(
        operation="list_accounts",
        noun="accounts",
        label_keys=("accountname", "accountid"),
    )

    @classmethod
    def get_config_model(cls):
        return FireberryFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Fireberry API token")
        method, path = ROUTES[config.operation]
        if "{id}" in path:
            path = path.replace("{id}", quote(config.record_id, safe=""))
        values = config.model_dump(
            exclude_none=True, exclude={"operation", "record_id"}
        )
        listing = config.operation.startswith("list_")
        kwargs = (
            {"params": {k: str(v) for k, v in values.items()}}
            if listing
            else {"json": values}
            if method in {"POST", "PUT"}
            else {}
        )
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                "https://api.fireberry.com" + path,
                headers={"tokenid": credential.api_token, "Accept": "application/json"},
                **kwargs,
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            raise ValueError(
                str(
                    body.get("message")
                    or body.get("Message")
                    or "Fireberry did not confirm success"
                )
                if isinstance(body, dict)
                else "Unexpected Fireberry response"
            )
        data = body.get("data")
        if listing:
            if not isinstance(data, dict) or not isinstance(data.get("Records"), list):
                raise ValueError("Expected Fireberry data.Records")
            return {
                "status": "success",
                "items": data["Records"],
                "data": data,
                "page_number": config.pagenumber,
                "page_size": config.pagesize,
            }
        return {"status": "success", "data": data, "message": body.get("message", "")}
