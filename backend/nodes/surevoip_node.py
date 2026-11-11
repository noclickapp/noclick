"""SureVoIP operations pinned to its published OpenAPI 9dcb0dc8 contract."""
from typing import Annotated, Literal, Optional, Union
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.surevoip.co.uk"


class SureVoIPCredential(BaseModel):
    model_config = ConfigDict(title="Surevoip Account", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.surevoip.co.uk/support/wiki/api_documentation",
            "x-credential-instructions": "Enter your SureVoIP API username and password for HTTP Basic authentication. Use the credentials supplied by SureVoIP for API access. NoClick sends them only to api.surevoip.co.uk and reads your customer account location to check the connection."})
    credential_type: Literal["surevoip_basic"] = Field("surevoip_basic", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=256, title="API Username", description="Your SureVoIP API username.")
    password: str = Field(..., min_length=1, max_length=4096, title="API Password", repr=False,
        description="Your SureVoIP API password.", json_schema_extra={"ui:widget": "password"})

    @field_validator("username", "password")
    @classmethod
    def no_controls(cls, value, info):
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or (info.field_name == "username" and ":" in value):
            raise ValueError("Use API credentials without control characters or a colon in the username")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AnnouncementAudio(_Input):
    model_config = ConfigDict(extra="forbid")
    announcement_id: str = Field(..., min_length=1, max_length=256)


class CallOptions(_Input):
    model_config = ConfigDict(extra="forbid")
    a_leg_only: Optional[Literal[0, 1]] = None
    a_leg_caller_id: Optional[str] = Field(None, pattern=r"^[0-9]+$", max_length=32)
    connect_key: Optional[int] = Field(None, ge=0, le=9)
    cancel_key: Optional[int] = Field(None, ge=0, le=9)
    play_audio: Optional[list[AnnouncementAudio]] = Field(None, max_length=100)


class CreateCall(_Input):
    """Ring the from party first, then connect them to the to party."""
    operation: Literal["create_call"] = Field("create_call", json_schema_extra={
        "ui:hidden": True, "x-display-name": "Create Phone Call", "x-category": "Calls", "x-is-trigger": False})
    from_number: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="From Number", description="First party to ring (a leg), for example 442035159999.")
    to_number: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="To Number", description="Second party to ring (b leg), for example 442035159995.")
    caller_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, title="Caller ID", description="Caller ID shown to the second party.")
    announcement_at: Optional[str] = Field(None, pattern=r"^[0-9]+$", description="Seconds after answer to play the announcement.")
    announcement_id: Optional[str] = Field(None, min_length=1, max_length=256)
    hangup_at: Optional[str] = Field(None, pattern=r"^[0-9]+$", description="Seconds after answer to hang up.")
    hangup_announcement_id: Optional[str] = Field(None, min_length=1, max_length=256)
    options: Optional[CallOptions] = None

    @model_validator(mode="after")
    def announcement_dependencies(self):
        if (self.announcement_at is None) != (self.announcement_id is None):
            raise ValueError("Supply announcement_at and announcement_id together")
        if self.hangup_announcement_id is not None and self.hangup_at is None:
            raise ValueError("hangup_at is required for a hangup announcement")
        return self


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    label: str
    category: str
    status: int = 200


OPERATIONS = {
    "create_call": Operation("POST", "/calls", "Create Phone Call", "Calls", 202),
    "list_sms": Operation("GET", "/sms", "List SMS", "Messages"),
    "list_customers": Operation("GET", "/customers", "Find Customer Account", "Customers", 302),
    "get_customer": Operation("GET", "/customers/{account}", "Get Customer", "Customers"),
    "list_contacts": Operation("GET", "/contacts", "List Contacts", "Customers"),
    "list_billing": Operation("GET", "/billing", "List Billing Details", "Billing"),
    "list_charges": Operation("GET", "/charges", "List Charges", "Billing"),
    "list_topups": Operation("GET", "/topups", "List Credit Topups", "Billing"),
    "list_sip_accounts": Operation("GET", "/sip", "List SIP Accounts", "Accounts"),
    "list_numbers": Operation("GET", "/numbers", "List Available Number Allocations", "Numbers"),
    "list_areacodes": Operation("GET", "/areacodes", "List Area Codes", "Numbers"),
    "list_customer_announcements": Operation("GET", "/customers/{account}/announcements", "List Customer Announcements", "Announcements"),
    "get_announcement": Operation("GET", "/customers/{account}/announcements/{announcement_id}", "Get Announcement", "Announcements"),
    "list_announcements": Operation("GET", "/announcements", "List Global Announcements", "Announcements"),
    "list_hosted_domains": Operation("GET", "/hosted", "List Hosted VoIP Domains", "Accounts"),
    "list_mobile_accounts": Operation("GET", "/mobile", "List Mobile Accounts", "Accounts"),
    "list_partners": Operation("GET", "/partners", "List Partner Accounts", "Accounts"),
    "list_ported_numbers": Operation("GET", "/porting", "List Ported Numbers", "Numbers"),
    "get_service_status": Operation("GET", "/service-status", "Get Service Status", "Support"),
}


def _config(name, op):
    fields = {}
    if "{account}" in op.path:
        fields["account"] = (int, Field(..., ge=1, title="Customer Account ID"))
    if "{announcement_id}" in op.path:
        fields["announcement_id"] = (str, Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$", title="Announcement ID"))
    return create_model("SureVoIP" + "".join(s.title() for s in name.split("_")), __base__=_Input,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True,
            "x-display-name": op.label, "x-category": op.category, "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: CreateCall if name == "create_call" else _config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
SureVoIPConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class SureVoIPFullConfig(NodeConfig[SureVoIPConfig, SureVoIPCredential]):
    pass


class SureVoIPNode(WorkflowNode):
    integration_type = "automation-surevoip"
    credential_provider_labels = {"surevoip": "SureVoIP Account"}
    connection_evidence = ConnectionEvidence(noun="SureVoIP customer account",
        identity_operation="list_customers", identity_keys=("location",))

    @classmethod
    def get_config_model(cls):
        return SureVoIPFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your SureVoIP account")
        config = self.config.config
        op = OPERATIONS[config.operation]
        path = op.path
        for key in ("account", "announcement_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(getattr(config, key)), safe=""))
        body = None
        if isinstance(config, CreateCall):
            body = config.model_dump(exclude_none=True, exclude={"operation", "from_number", "to_number"})
            body.update({"from": config.from_number, "to": config.to_number})
        # Never follow the account discovery redirect or retry a call creation.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(op.method, BASE_URL + path,
                headers={"Accept": "application/json"}, auth=httpx.BasicAuth(credential.username, credential.password),
                **({"json": body} if body is not None else {}))
        if response.status_code != op.status:
            message = response.text[:2000].replace(credential.password, "[redacted]")
            raise ValueError(f"SureVoIP HTTP {response.status_code}: {message}")
        if len(response.content) > 10_000_000:
            raise ValueError("SureVoIP response exceeds 10 MB")
        data = response.json() if response.content else None
        return {"data": data, "http_status": response.status_code}
