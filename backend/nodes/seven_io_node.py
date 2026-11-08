"""Seven messaging and address-book operations using a pasted API key.

Routes are pinned to Seven's OpenAPI contract; API-key authentication is also
published at https://docs.seven.io/en/rest-api/authentication.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class SevenIoCredential(BaseModel):
    model_config = ConfigDict(title="Seven Io API Key", json_schema_extra={
        "x-credential-url": "https://dashboard.seven.io/developer",
        "x-credential-instructions": "Create an API key in the Seven dashboard Developer area. Allow access to the endpoints used by your workflow; Contacts access is needed to verify the connection.",
    })
    credential_type: Literal["seven_io_api_key"] = Field("seven_io_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        description="Paste the API key from the Developer area of your Seven dashboard.",
        json_schema_extra={"ui:widget": "password"})


class Empty(BaseModel):
    pass


class PageFields(BaseModel):
    limit: int = Field(30, ge=1, le=100, title="Limit")
    offset: int = Field(0, ge=0, title="Offset")


class Identifier(BaseModel):
    id: int = Field(..., ge=1, title="Resource ID")


class ContactFields(BaseModel):
    firstname: str | None = Field(None, title="First Name")
    lastname: str | None = Field(None, title="Last Name")
    mobile_number: str | None = Field(None, title="Mobile Number")
    home_number: str | None = Field(None, title="Home Number")
    email: str | None = Field(None, title="Email")
    address: str | None = Field(None, title="Address")
    postal_code: str | None = Field(None, title="Postal Code")
    city: str | None = Field(None, title="City")
    birthday: str | None = Field(None, title="Birthday", description="Date in YYYY-MM-DD format.")
    notes: str | None = Field(None, title="Notes")


class ContactUpdate(ContactFields, Identifier):
    pass


class GroupFields(BaseModel):
    name: str = Field(..., min_length=1, title="Group Name")


class GroupUpdate(GroupFields, Identifier):
    pass


class SMSFields(BaseModel):
    to: str = Field(..., min_length=1, title="Recipients", description="Phone numbers or contact/group names, separated by commas.")
    text: str = Field(..., min_length=1, max_length=1520, title="Message", json_schema_extra={"ui:widget": "textarea"})
    sender: str | None = Field(None, title="Sender", description="Up to 11 alphanumeric or 16 numeric characters.")
    foreign_id: str | None = Field(None, title="Foreign ID", pattern=r"^[A-Za-z0-9.\-_@]+$")
    label: str | None = Field(None, title="Label", pattern=r"^[A-Za-z0-9.\-_@]+$")
    delay: str | None = Field(None, title="Scheduled Time", description="Unix timestamp or YYYY-MM-DD HH:MM:SS.")
    flash: bool = Field(False, title="Flash SMS")
    performance_tracking: bool = Field(False, title="Track Link Performance")


class StatusFields(BaseModel):
    msg_id: str = Field(..., min_length=1, title="Message IDs", description="Comma-separated SMS IDs.")


class JournalFields(BaseModel):
    date_from: str | None = Field(None, title="Start Date")
    date_to: str | None = Field(None, title="End Date")
    to: str | None = Field(None, title="Recipient")
    limit: int = Field(100, ge=1, le=100, title="Limit")
    offset: int = Field(0, ge=0, title="Offset", description="Starting position for this page. Increase by the limit for the next page.")


class LookupFields(BaseModel):
    number: str = Field(..., min_length=1, title="Phone Number")


class AnalyticsFields(BaseModel):
    start: str | None = Field(None, title="Start Date", description="YYYY-MM-DD")
    end: str | None = Field(None, title="End Date", description="YYYY-MM-DD")
    label: str | None = Field(None, title="Label")


class GetBalance(Empty):
    operation: Literal["get_balance"] = Field("get_balance", title="Get Balance", json_schema_extra={"ui:hidden": True})


class ListContacts(PageFields):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})


class GetContact(Identifier):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(ContactUpdate):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})


class DeleteContact(Identifier):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class ListGroups(PageFields):
    operation: Literal["list_groups"] = Field("list_groups", title="List Groups", json_schema_extra={"ui:hidden": True})


class GetGroup(Identifier):
    operation: Literal["get_group"] = Field("get_group", title="Get Group", json_schema_extra={"ui:hidden": True})


class CreateGroup(GroupFields):
    operation: Literal["create_group"] = Field("create_group", title="Create Group", json_schema_extra={"ui:hidden": True})


class UpdateGroup(GroupUpdate):
    operation: Literal["update_group"] = Field("update_group", title="Update Group", json_schema_extra={"ui:hidden": True})


class DeleteGroup(Identifier):
    operation: Literal["delete_group"] = Field("delete_group", title="Delete Group", json_schema_extra={"ui:hidden": True})


class SendSms(SMSFields):
    operation: Literal["send_sms"] = Field("send_sms", title="Send Sms", json_schema_extra={"ui:hidden": True})


class GetSmsStatus(StatusFields):
    operation: Literal["get_sms_status"] = Field("get_sms_status", title="Get Sms Status", json_schema_extra={"ui:hidden": True})


class ListOutboundMessages(JournalFields):
    operation: Literal["list_outbound_messages"] = Field("list_outbound_messages", title="List Outbound Messages", json_schema_extra={"ui:hidden": True})


class ListInboundMessages(JournalFields):
    operation: Literal["list_inbound_messages"] = Field("list_inbound_messages", title="List Inbound Messages", json_schema_extra={"ui:hidden": True})


class LookupFormat(LookupFields):
    operation: Literal["lookup_format"] = Field("lookup_format", title="Lookup Format", json_schema_extra={"ui:hidden": True})


class LookupHlr(LookupFields):
    operation: Literal["lookup_hlr"] = Field("lookup_hlr", title="Lookup Hlr", json_schema_extra={"ui:hidden": True})


class GetAnalyticsByDate(AnalyticsFields):
    operation: Literal["get_analytics_by_date"] = Field("get_analytics_by_date", title="Get Analytics By Date", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetBalance, ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact, ListGroups, GetGroup, CreateGroup, UpdateGroup, DeleteGroup, SendSms, GetSmsStatus, ListOutboundMessages, ListInboundMessages, LookupFormat, LookupHlr, GetAnalyticsByDate], Field(discriminator="operation")]


class SevenIoConfig(NodeConfig[Operation, SevenIoCredential]):
    pass


ROUTES = {'get_balance': ('GET', '/balance'), 'list_contacts': ('GET', '/contacts'), 'get_contact': ('GET', '/contacts/{id}'), 'create_contact': ('POST', '/contacts'), 'update_contact': ('PATCH', '/contacts/{id}'), 'delete_contact': ('DELETE', '/contacts/{id}'), 'list_groups': ('GET', '/groups'), 'get_group': ('GET', '/groups/{id}'), 'create_group': ('POST', '/groups'), 'update_group': ('PATCH', '/groups/{id}'), 'delete_group': ('DELETE', '/groups/{id}'), 'send_sms': ('POST', '/sms'), 'get_sms_status': ('GET', '/status'), 'list_outbound_messages': ('GET', '/journal/outbound'), 'list_inbound_messages': ('GET', '/journal/inbound'), 'lookup_format': ('GET', '/lookup/format'), 'lookup_hlr': ('GET', '/lookup/hlr'), 'get_analytics_by_date': ('GET', '/analytics/date')}


class SevenIoNode(WorkflowNode):
    integration_type = "automation-seven-io"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return SevenIoConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Seven Io API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(str(values.pop("id")), safe=""))
        if "sender" in values:
            values["from"] = values.pop("sender")
        if config.operation == "delete_group":
            values["delete_contacts"] = "false"
        # Form booleans must be lowercase on the wire.
        values = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://gateway.seven.io/api" + path,
                headers={"X-Api-Key": credential.api_key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"data": values}))
        response.raise_for_status()
        if method == "DELETE" and not response.content:
            return {"status": "success", "data": {"success": True}}
        body = response.json()
        if isinstance(body, dict) and (body.get("success") is False or body.get("error")):
            return {"status": "error", "error": str(body.get("error") or "Seven rejected the request")}
        if config.operation == "send_sms" and isinstance(body, dict) and str(body.get("success")) != "100":
            return {"status": "error", "error": str(body.get("success")), "data": body}
        if config.operation == "lookup_hlr" and isinstance(body, dict) and body.get("status") is False:
            return {"status": "error", "error": str(body.get("status_message") or "Seven lookup failed"), "data": body}
        return {"status": "success", "data": body}
