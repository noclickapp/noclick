"""46elks SMS, MMS, voice and account operations, pinned to its published Swagger 2 contract.

Requests use Basic authentication and form encoding. Incoming SMS/MMS callbacks
are unsigned form POSTs as documented at https://46elks.com/docs/receive-sms
and https://46elks.com/docs/receive-mms. Each trigger replaces one callback on
an explicitly selected number; teardown clears it only while it still belongs
to this workflow. Sending and number allocation can incur provider charges.
"""
from __future__ import annotations
import base64
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import (
    ExternalWebhookTriggerMixin,
    WebhookTriggerConfigBase,
)
from utils.ssrf import guarded_async_client

BASE = "https://api.46elks.com/a1"
FAMILY = "46elks_basic_auth"


class Elks46Credential(BaseModel):
    model_config = ConfigDict(
        title="46elks API Account",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.46elks.com/",
            "x-credential-instructions": "Copy the API username and API password from your 46elks dashboard. These are API credentials, separate from your dashboard login. NoClick uses HTTP Basic authentication to api.46elks.com.",
        },
    )
    credential_type: Literal["46elks_basic_auth"] = Field(
        "46elks_basic_auth", json_schema_extra={"ui:hidden": True}
    )
    api_username: str = Field(
        ...,
        min_length=1,
        title="API username",
        json_schema_extra={"ui:widget": "password"},
    )
    api_password: str = Field(
        ...,
        min_length=1,
        title="API password",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_username", "api_password", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API credential")
        if ":" in value or any(c.isspace() for c in value):
            raise ValueError(
                "Paste only the API credential, without a Basic header or whitespace"
            )
        return value


class _Input(BaseModel):
    model_config = ConfigDict(populate_by_name=True, hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_id(cls, value, info):
        if info.field_name == "id" and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Use a single 46elks resource ID")
        return value


class Elks46GetAccountConfig(_Input):
    """Get your account data"""

    operation: Literal["get_account"] = Field(
        "get_account",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Account"},
    )


class Elks46ListSubaccountsConfig(_Input):
    """Get all subaccounts"""

    operation: Literal["list_subaccounts"] = Field(
        "list_subaccounts",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Subaccounts"},
    )


class Elks46CreateSubaccountConfig(_Input):
    """Create new subaccount."""

    operation: Literal["create_subaccount"] = Field(
        "create_subaccount",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Create Subaccount"},
    )
    name: str = Field(
        ..., description="Name of subaccount", min_length=1, max_length=10000
    )
    usagelimit: int | None = Field(
        None, description="The usage limit for the subaccount.", ge=0
    )


class Elks46GetSubaccountConfig(_Input):
    """Get the data about one subaccount."""

    operation: Literal["get_subaccount"] = Field(
        "get_subaccount",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Subaccount"},
    )
    id: str = Field(
        ..., description="Id of the subaccount", min_length=1, max_length=10000
    )


class Elks46UpdateSubaccountConfig(_Input):
    """Update subaccount."""

    operation: Literal["update_subaccount"] = Field(
        "update_subaccount",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Update Subaccount"},
    )
    id: str = Field(
        ..., description="Id of the subaccount", min_length=1, max_length=10000
    )
    name: str | None = Field(
        None, description="Name of subaccount", min_length=1, max_length=10000
    )
    usagelimit: int | None = Field(
        None, description="The usage limit for the subaccount.", ge=0
    )

    @model_validator(mode="after")
    def change_required(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class Elks46ListNumbersConfig(_Input):
    """Get all numbers allocated in the API"""

    operation: Literal["list_numbers"] = Field(
        "list_numbers",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Numbers"},
    )


class Elks46AllocateNumberConfig(_Input):
    """Allocate new number for usage in the API."""

    operation: Literal["allocate_number"] = Field(
        "allocate_number",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Allocate Number"},
    )
    country: str = Field(..., description="country", min_length=1, max_length=10000)
    capabilities: str | None = Field(
        None, description="SMS, MMS, Voice", min_length=1, max_length=10000
    )
    sms_url: str | None = Field(
        None,
        description='Url where to send incomming sms. Set to "none" to clear.',
        min_length=1,
        max_length=10000,
    )
    mms_url: str | None = Field(
        None,
        description='Url where to send incomming MMS. Set to "none" to clear.',
        min_length=1,
        max_length=10000,
    )
    voice_start: str | None = Field(
        None,
        description='Url / JSON where to send incomming calls. Set to "none" to clear.',
        min_length=1,
        max_length=10000,
    )
    sms_replies: Literal["yes", "no"] | None = Field(
        None, description="Prevent automatic response from callback server."
    )


class Elks46GetNumberConfig(_Input):
    """Get information about one number."""

    operation: Literal["get_number"] = Field(
        "get_number",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Number"},
    )
    id: str = Field(
        ...,
        description="Id of the number",
        json_schema_extra={
            "x-dynamic-options": {"field_name": "number_id", "allow_custom": True}
        },
        min_length=1,
        max_length=10000,
    )


class Elks46UpdateNumberConfig(_Input):
    """Change parameters of number"""

    operation: Literal["update_number"] = Field(
        "update_number",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Update Number"},
    )
    id: str = Field(
        ...,
        description="Number id",
        json_schema_extra={
            "x-dynamic-options": {"field_name": "number_id", "allow_custom": True}
        },
        min_length=1,
        max_length=10000,
    )
    sms_url: str | None = Field(
        None,
        description="Url where to send incomming messages. Setting this replaces the existing handler. Use none to clear it.",
        min_length=1,
        max_length=10000,
    )
    voice_start: str | None = Field(
        None,
        description="Url / JSON where to send incomming calls. Setting this replaces the existing handler. Use none to clear it.",
        min_length=1,
        max_length=10000,
    )
    mms_url: str | None = Field(
        None,
        description="Url where to send incomming MMS. Setting this replaces the existing handler. Use none to clear it.",
        min_length=1,
        max_length=10000,
    )
    sms_replies: Literal["yes", "no"] | None = Field(
        None, description="Prevent automatic response from callback server."
    )
    active: Literal["yes", "no"] | None = Field(
        None, description="Prevent automatic response from callback server."
    )

    @model_validator(mode="after")
    def change_required(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class Elks46SendSmsConfig(_Input):
    """Send SMS"""

    operation: Literal["send_sms"] = Field(
        "send_sms", json_schema_extra={"ui:hidden": True, "x-display-name": "Send Sms"}
    )
    from_number: str = Field(
        ...,
        description="Senderid like Elks (3-11 chars a-Z and 0-9 starting with a char), or a 46elks number like +46766861004 or a unlocked from number like your own number +46723175800.",
        alias="from",
        min_length=1,
        max_length=10000,
    )
    to: str = Field(
        ...,
        description="Number in e164 number like +46723175800 or in local format for AU,CA,DK,FI,IN,NO,SE and US prefix with country code like SE0723175800",
        min_length=1,
        max_length=10000,
    )
    message: str = Field(
        ..., description="Text to send to the phone.", min_length=1, max_length=10000
    )
    whendelivered: str | None = Field(
        None,
        description="Url to send the Delivery report to",
        min_length=1,
        max_length=10000,
    )
    flashsms: Literal["yes", "no"] | None = Field(
        None, description="Do not store message on the phone."
    )
    dryrun: Literal["yes", "no"] | None = Field(
        None,
        description="Do not send the message, get price estimation and verify parameters.",
    )
    dontlog: str | None = Field(
        None,
        description='Do not store data about SMS in the API platform, set to "message" to hide message content.',
        min_length=1,
        max_length=10000,
    )


class Elks46ListSmsConfig(_Input):
    """List latest 100 SMS"""

    operation: Literal["list_sms"] = Field(
        "list_sms", json_schema_extra={"ui:hidden": True, "x-display-name": "List Sms"}
    )
    start: str | None = Field(
        None,
        description="Show SMS older than this date",
        min_length=1,
        max_length=10000,
    )
    end: str | None = Field(
        None,
        description="Show SMS newer than this date",
        min_length=1,
        max_length=10000,
    )


class Elks46GetSmsConfig(_Input):
    """Get one SMS."""

    operation: Literal["get_sms"] = Field(
        "get_sms", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Sms"}
    )
    id: str = Field(..., description="Id of SMS to get", min_length=1, max_length=10000)


class Elks46DeleteSmsConfig(_Input):
    """Delete SMS"""

    operation: Literal["delete_sms"] = Field(
        "delete_sms",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Sms"},
    )
    id: str = Field(..., description="Id of SMS to get", min_length=1, max_length=10000)


class Elks46SendMmsConfig(_Input):
    """Send MMS"""

    operation: Literal["send_mms"] = Field(
        "send_mms", json_schema_extra={"ui:hidden": True, "x-display-name": "Send Mms"}
    )
    from_number: str = Field(
        ...,
        description='"noreply" or number like +46723175800.',
        alias="from",
        min_length=1,
        max_length=10000,
    )
    to: str = Field(
        ...,
        description="Number in E.164 number like +46723175800.",
        min_length=1,
        max_length=10000,
    )
    message: str = Field(
        ..., description="Text to send to the phone.", min_length=1, max_length=10000
    )
    image: str | None = Field(
        None,
        description="Url or Base64/url-encoded imagedata to send.",
        min_length=1,
        max_length=10000,
    )


class Elks46ListMmsConfig(_Input):
    """List latest 100 MMS"""

    operation: Literal["list_mms"] = Field(
        "list_mms", json_schema_extra={"ui:hidden": True, "x-display-name": "List Mms"}
    )
    start: str | None = Field(
        None,
        description="Show MMS older than this date",
        min_length=1,
        max_length=10000,
    )
    end: str | None = Field(
        None,
        description="Show MMS newer than this date",
        min_length=1,
        max_length=10000,
    )


class Elks46GetMmsConfig(_Input):
    """Get one MMS."""

    operation: Literal["get_mms"] = Field(
        "get_mms", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Mms"}
    )
    id: str = Field(..., description="Id of MMS to get", min_length=1, max_length=10000)


class Elks46DeleteMmsConfig(_Input):
    """Delete MMS"""

    operation: Literal["delete_mms"] = Field(
        "delete_mms",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Mms"},
    )
    id: str = Field(..., description="Id of MMS to get", min_length=1, max_length=10000)


class Elks46StartCallConfig(_Input):
    """Start Phonecall"""

    operation: Literal["start_call"] = Field(
        "start_call",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Start Call"},
    )
    from_number: str = Field(
        ...,
        description="Your 46elks umber like +46766861647.",
        alias="from",
        min_length=1,
        max_length=10000,
    )
    to: str = Field(
        ...,
        description="Number in e164 number like +46723175800.",
        min_length=1,
        max_length=10000,
    )
    voice_start: str = Field(
        ...,
        description="The JSON data for the call or URL to access when the call is awnserd.",
        min_length=1,
        max_length=10000,
    )
    whenhangup: str | None = Field(
        None,
        description="Url to send call data to when call ends.",
        min_length=1,
        max_length=10000,
    )
    timeout: int | None = Field(
        None, description="Secounds to wait before stopping call.", ge=0
    )


class Elks46ListCallsConfig(_Input):
    """List latest 100 Calls"""

    operation: Literal["list_calls"] = Field(
        "list_calls",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Calls"},
    )
    start: str | None = Field(
        None,
        description="Show Calls older than this date",
        min_length=1,
        max_length=10000,
    )
    end: str | None = Field(
        None,
        description="Show Calls newer than this date",
        min_length=1,
        max_length=10000,
    )


class Elks46GetCallConfig(_Input):
    """Get one Call."""

    operation: Literal["get_call"] = Field(
        "get_call", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Call"}
    )
    id: str = Field(
        ..., description="Id of call to get", min_length=1, max_length=10000
    )


class Elks46DeleteCallConfig(_Input):
    """Delete Call from history"""

    operation: Literal["delete_call"] = Field(
        "delete_call",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Call"},
    )
    id: str = Field(
        ..., description="Id of Call to delete", min_length=1, max_length=10000
    )


class Elks46ListRecordingsConfig(_Input):
    """Get list of recordings"""

    operation: Literal["list_recordings"] = Field(
        "list_recordings",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Recordings"},
    )
    start: str | None = Field(
        None,
        description="Show recordings older than this date",
        min_length=1,
        max_length=10000,
    )
    end: str | None = Field(
        None,
        description="Show recordings newer than this date",
        min_length=1,
        max_length=10000,
    )


class Elks46GetRecordingConfig(_Input):
    """Get metadata of one recording."""

    operation: Literal["get_recording"] = Field(
        "get_recording",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Recording"},
    )
    id: str = Field(
        ..., description="Id of the recording", min_length=1, max_length=10000
    )


class _IncomingMessage(WebhookTriggerConfigBase):
    number_id: str = Field(
        ...,
        title="46elks number",
        description="Choose the number whose callback this workflow will replace. SMS triggers disable automatic response-body replies; use Send SMS to reply. Use a dedicated number for each channel/trigger.",
        json_schema_extra={
            "x-dynamic-options": {"field_name": "number_id", "allow_custom": True}
        },
    )
    webhook_url: str | None = Field(
        None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:loadValue": True,
            "ui:copyable": True,
        },
    )

    @field_validator("number_id")
    @classmethod
    def number(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Use a single 46elks number ID")
        return value


class Elks46IncomingSMSConfig(_IncomingMessage):
    """Receive incoming SMS on the selected number (unsigned provider callbacks)."""

    operation: Literal["on_incoming_sms"] = Field(
        "on_incoming_sms",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-category": "Triggers",
            "x-display-name": "Incoming SMS",
        },
    )


class Elks46IncomingMMSConfig(_IncomingMessage):
    """Receive incoming MMS on the selected number (unsigned provider callbacks)."""

    operation: Literal["on_incoming_mms"] = Field(
        "on_incoming_mms",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-category": "Triggers",
            "x-display-name": "Incoming MMS",
        },
    )


OPERATIONS = {
    "get_account": {"method": "GET", "path": "/me", "query": [], "body": []},
    "list_subaccounts": {
        "method": "GET",
        "path": "/subaccounts",
        "query": [],
        "body": [],
    },
    "create_subaccount": {
        "method": "POST",
        "path": "/subaccounts",
        "query": [],
        "body": ["name", "usagelimit"],
    },
    "get_subaccount": {
        "method": "GET",
        "path": "/subaccounts/{id}",
        "query": [],
        "body": [],
    },
    "update_subaccount": {
        "method": "POST",
        "path": "/subaccounts/{id}",
        "query": [],
        "body": ["name", "usagelimit"],
    },
    "list_numbers": {"method": "GET", "path": "/numbers", "query": [], "body": []},
    "allocate_number": {
        "method": "POST",
        "path": "/numbers",
        "query": [],
        "body": [
            "country",
            "capabilities",
            "sms_url",
            "mms_url",
            "voice_start",
            "sms_replies",
        ],
    },
    "get_number": {"method": "GET", "path": "/numbers/{id}", "query": [], "body": []},
    "update_number": {
        "method": "POST",
        "path": "/numbers/{id}",
        "query": [],
        "body": ["sms_url", "voice_start", "mms_url", "sms_replies", "active"],
    },
    "send_sms": {
        "method": "POST",
        "path": "/SMS",
        "query": [],
        "body": [
            "from",
            "to",
            "message",
            "whendelivered",
            "flashsms",
            "dryrun",
            "dontlog",
        ],
    },
    "list_sms": {
        "method": "GET",
        "path": "/SMS",
        "query": ["start", "end"],
        "body": [],
    },
    "get_sms": {"method": "GET", "path": "/SMS/{id}", "query": [], "body": []},
    "delete_sms": {"method": "DELETE", "path": "/SMS/{id}", "query": [], "body": []},
    "send_mms": {
        "method": "POST",
        "path": "/MMS",
        "query": [],
        "body": ["from", "to", "message", "image"],
    },
    "list_mms": {
        "method": "GET",
        "path": "/MMS",
        "query": ["start", "end"],
        "body": [],
    },
    "get_mms": {"method": "GET", "path": "/MMS/{id}", "query": [], "body": []},
    "delete_mms": {"method": "DELETE", "path": "/MMS/{id}", "query": [], "body": []},
    "start_call": {
        "method": "POST",
        "path": "/Calls",
        "query": [],
        "body": ["from", "to", "voice_start", "whenhangup", "timeout"],
    },
    "list_calls": {
        "method": "GET",
        "path": "/Calls",
        "query": ["start", "end"],
        "body": [],
    },
    "get_call": {"method": "GET", "path": "/Calls/{id}", "query": [], "body": []},
    "delete_call": {"method": "DELETE", "path": "/Calls/{id}", "query": [], "body": []},
    "list_recordings": {
        "method": "GET",
        "path": "/recordings",
        "query": ["start", "end"],
        "body": [],
    },
    "get_recording": {
        "method": "GET",
        "path": "/recordings/{id}",
        "query": [],
        "body": [],
    },
}

Elks46Config = Annotated[
    Union[
        Elks46GetAccountConfig,
        Elks46ListSubaccountsConfig,
        Elks46CreateSubaccountConfig,
        Elks46GetSubaccountConfig,
        Elks46UpdateSubaccountConfig,
        Elks46ListNumbersConfig,
        Elks46AllocateNumberConfig,
        Elks46GetNumberConfig,
        Elks46UpdateNumberConfig,
        Elks46SendSmsConfig,
        Elks46ListSmsConfig,
        Elks46GetSmsConfig,
        Elks46DeleteSmsConfig,
        Elks46SendMmsConfig,
        Elks46ListMmsConfig,
        Elks46GetMmsConfig,
        Elks46DeleteMmsConfig,
        Elks46StartCallConfig,
        Elks46ListCallsConfig,
        Elks46GetCallConfig,
        Elks46DeleteCallConfig,
        Elks46ListRecordingsConfig,
        Elks46GetRecordingConfig,
        Elks46IncomingSMSConfig,
        Elks46IncomingMMSConfig,
    ],
    Field(discriminator="operation"),
]


class Elks46NodeConfig(NodeConfig[Elks46Config, Elks46Credential]):
    pass


class Elks46Node(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-46elks"
    connection_evidence = ConnectionEvidence(
        operation="get_account", identity_operation="get_account", noun="46elks account"
    )
    webhook_signing_secret_not_issued = True

    @classmethod
    def get_config_model(cls):
        return Elks46NodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = (
            Elks46Credential.model_validate(credential)
            if isinstance(credential, dict)
            else credential
        )
        auth = base64.b64encode(
            (credential.api_username + ":" + credential.api_password).encode()
        ).decode()
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                BASE + path,
                params=params,
                data=body,
                headers={
                    "Authorization": "Basic " + auth,
                    "Accept": "application/json",
                },
            )
        if response.is_error:
            # 46elks documents plain-text errors. Preserve the provider's rejection,
            # but never echo credentials even if a proxy includes them in an error.
            detail = response.text[:1000]
            for secret in (credential.api_username, credential.api_password, auth):
                detail = detail.replace(secret, "[redacted]")
            raise ValueError(f"46elks API {response.status_code}: {detail}")
        if response.status_code != 200 or len(response.content) > 5_000_000:
            raise ValueError("46elks did not return a bounded successful response")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("46elks returned an invalid JSON object")
        return data

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, Elks46NodeConfig) or config.credentials is None:
            raise ValueError("Connect your 46elks API credentials")
        op = config.config
        if op.operation.startswith("on_incoming_"):
            return self.no_event_output(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        path = spec["path"]
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        data = await self._request(
            config.credentials,
            spec["method"],
            path,
            params={k: values[k] for k in spec["query"] if k in values},
            body={k: values[k] for k in spec["body"] if k in values}
            if spec["method"] == "POST"
            else None,
        )
        # Subaccount responses contain the API secret. Never publish it as workflow output.
        data = {k: v for k, v in data.items() if k != "secret"}
        if isinstance(data.get("data"), list):
            data["data"] = [
                {k: v for k, v in row.items() if k != "secret"} for row in data["data"]
            ]
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    async def load_field_options(
        cls,
        field_name,
        credential_data=None,
        context=None,
        *,
        page_token=None,
        search=None,
    ):
        if field_name != "number_id":
            return []
        result = await cls._request(credential_data, "GET", "/numbers")
        rows = result.get("data")
        if not isinstance(rows, list):
            raise ValueError("46elks did not return a list of numbers")
        return [
            {"value": row["id"], "label": row.get("number") or row["id"]}
            for row in rows
            if isinstance(row, dict)
            and row.get("id")
            and (
                not search
                or search.casefold() in str(row.get("number", row["id"])).casefold()
            )
        ]

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"number_id": (config or {}).get("number_id")}

    @classmethod
    def _callback(cls, config):
        op = config.get("operation")
        if op not in {"on_incoming_sms", "on_incoming_mms"}:
            raise ValueError("Choose an incoming message trigger")
        parsed = (
            Elks46IncomingSMSConfig
            if op == "on_incoming_sms"
            else Elks46IncomingMMSConfig
        ).model_validate(config)
        return parsed.number_id, "sms_url" if op == "on_incoming_sms" else "mms_url"

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ):
        number_id, field = cls._callback(config)
        await cls._request(
            credential,
            "POST",
            "/numbers/" + quote(number_id, safe=""),
            body={
                field: webhook_url,
                **({"sms_replies": "no"} if field == "sms_url" else {}),
            },
        )
        return {"external_webhook_id": number_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        number_id, field = cls._callback(config)
        if not credential or not config.get("webhook_url"):
            raise ValueError(
                "46elks credentials and the registered webhook URL are required for teardown"
            )
        path = "/numbers/" + quote(number_id, safe="")
        current = await cls._request(credential, "GET", path)
        # A person may have repointed this number in the provider dashboard.
        # Leave their replacement alone. 'none' is the documented field-clearing value.
        if current.get(field) == config["webhook_url"]:
            await cls._request(credential, "POST", path, body={field: "none"})

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # 46elks receive-sms/receive-mms document no signature or signing secret.
        # Do not invent an HMAC scheme; the minted webhook URL must stay private.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("direction") == "incoming"

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {
            "status": "success",
            "operation": config.get("operation"),
            "data": payload,
        }

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        data = output.get("data", output)
        if (
            not isinstance(data, dict)
            or not data.get("id")
            or data.get("direction") != "incoming"
        ):
            return None
        kind = "MMS" if output.get("operation") == "on_incoming_mms" else "SMS"
        sender, recipient = data.get("from"), data.get("to")
        lines = [
            f"46elks incoming {kind} from {sender} to {recipient}",
            str(data.get("message", "")),
            f"Message ID: {data['id']}",
            f"Created (UTC): {data.get('created')}",
        ]
        # The MMS docs name image, image2, image3, image4. Iterate only fields
        # delivered by the provider, preserving messages with no images.
        images = [
            str(v)
            for k, v in data.items()
            if k in {"image", "image2", "image3", "image4"} and v
        ]
        if images:
            lines.append("Images: " + ", ".join(images))
        lines.append(
            f"To reply: send_{kind.lower()} with from={recipient} and to={sender}."
        )
        return {
            "text": "\n".join(lines),
            "conversation_key": f"{recipient}:{sender}",
            "title": f"46elks {kind} from {sender}",
        }
