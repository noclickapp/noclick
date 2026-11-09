"""Drop Cowboy v1 messaging, contact lists and account-owned media catalogs.

Each action makes one documented API request. Send acknowledgements retain the
provider's queued status; final delivery arrives through the provider's webhook.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.dropcowboy.com/v1"
DOCS = "https://drop-cowboy.gitbook.io/drop-cowboy-docs"


class DropCowboyCredential(BaseModel):
    model_config = ConfigDict(title="Drop Cowboy API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.dropcowboy.com/appv1/#/api",
            "x-credential-instructions": "Copy your Team ID and secret from Drop Cowboy's API settings. Enable API access in the Trust Center. NoClick checks the connection by reading your brands."})
    credential_type: Literal["drop_cowboy_api_key"] = Field("drop_cowboy_api_key", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., min_length=1, title="Team ID", json_schema_extra={"ui:widget": "password"})
    secret: str = Field(..., min_length=1, title="API secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("account_id", "secret", mode="before")
    @classmethod
    def clean(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the value without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListBrands(Input):
    operation: Literal["list_brands"] = Field("list_brands", json_schema_extra={"ui:label": "List brands"})


class ListRecordings(Input):
    operation: Literal["list_recordings"] = Field("list_recordings", json_schema_extra={"ui:label": "List recordings"})
    api_allowed: bool | None = Field(None, description="Filter by approval for API use; leave blank for all recordings.")


class ListMedia(Input):
    operation: Literal["list_media"] = Field("list_media", json_schema_extra={"ui:label": "List media"})


class ListPools(Input):
    operation: Literal["list_number_pools"] = Field("list_number_pools", json_schema_extra={"ui:label": "List number pools"})


class ListID(Input):
    list_id: str = Field(..., min_length=1, max_length=256, description="Contact list ID returned by Create contact list.")

    @field_validator("list_id")
    @classmethod
    def path_id(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
            raise ValueError("Paste a single contact list ID")
        return value


class CreateList(Input):
    operation: Literal["create_contact_list"] = Field("create_contact_list", json_schema_extra={"ui:label": "Create contact list"})
    list_name: str = Field(..., min_length=1)


class GetList(ListID):
    operation: Literal["get_contact_list"] = Field("get_contact_list", json_schema_extra={"ui:label": "Get contact list"})


class RenameList(ListID):
    operation: Literal["rename_contact_list"] = Field("rename_contact_list", json_schema_extra={"ui:label": "Rename contact list"})
    list_name: str = Field(..., min_length=1)


class DeleteList(ListID):
    operation: Literal["delete_contact_list"] = Field("delete_contact_list", json_schema_extra={"ui:label": "Delete contact list"})


ContactField = Literal["record_id", "first_name", "last_name", "company", "email", "phone", "address1", "address2", "city", "state", "postal", "country", "custom1", "custom2", "custom3", "custom4", "custom5"]


class AppendContacts(ListID):
    operation: Literal["append_contacts"] = Field("append_contacts", json_schema_extra={"ui:label": "Append contacts to list"})
    fields: list[ContactField] = Field(..., min_length=1, description="Columns corresponding to each row in Values. Repeat phone for multiple numbers.")
    values: list[list[str]] = Field(..., min_length=1, max_length=10000, description="Up to 10,000 contact rows, each with one value per field.")
    region: str | None = Field(None, pattern=r"^[A-Z]{2}$", description="ISO country code used for local phone numbers. Provider default: US.")

    @model_validator(mode="after")
    def matching_rows(self):
        if any(len(row) != len(self.fields) for row in self.values):
            raise ValueError("Each row must have one value per field")
        return self


Phone = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{1,14}$")]


class SendSMS(Input):
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:label": "Send SMS"})
    phone_number: Phone
    caller_id: Phone = Field(..., description="Return phone number in E.164 format.")
    pool_id: str = Field(..., min_length=1, description="Private number pool registered for SMS.")
    sms_body: str = Field(..., min_length=1, max_length=160)
    opt_in: Literal[True] = Field(..., description="Confirm the recipient has opted in to receive SMS.")
    foreign_id: str | None = Field(None, max_length=256)
    callback_url: str | None = None


class SendRVM(Input):
    operation: Literal["send_ringless_voicemail"] = Field("send_ringless_voicemail", json_schema_extra={"ui:label": "Send ringless voicemail"})
    phone_number: Phone
    brand_id: str = Field(..., min_length=1)
    foreign_id: str = Field(..., min_length=1, max_length=256, description="Your reference, echoed in delivery callbacks.")
    recording_id: str | None = Field(None, description="Approved recording ID. Choose recording, voice with text, or audio URL.")
    voice_id: str | None = None
    tts_body: str | None = None
    audio_url: str | None = Field(None, description="MP3/WAV URL; requires special approval from Drop Cowboy.")
    audio_type: Literal["mp3", "wav"] | None = None
    forwarding_number: Phone | None = None
    phone_ivr_id: str | None = None
    pool_id: str | None = None
    postal_code: str | None = None
    callback_url: str | None = None

    @model_validator(mode="after")
    def audio_source(self):
        if sum(bool(v) for v in (self.recording_id, self.voice_id, self.audio_url)) != 1:
            raise ValueError("Choose one recording ID, voice ID with text, or audio URL")
        if bool(self.voice_id) != bool(self.tts_body):
            raise ValueError("Voice ID and text to speak must be supplied together")
        if bool(self.audio_url) != bool(self.audio_type):
            raise ValueError("Audio URL and audio type must be supplied together")
        return self


DropCowboyOperation = Annotated[Union[ListBrands, ListRecordings, ListMedia, ListPools,
    CreateList, GetList, RenameList, DeleteList, AppendContacts, SendSMS, SendRVM], Field(discriminator="operation")]


class DropCowboyConfig(NodeConfig[DropCowboyOperation, DropCowboyCredential]):
    pass


ROUTES = {
    "list_brands": ("GET", "/brand"),
    "list_recordings": ("GET", "/recording"),
    "list_media": ("GET", "/media"),
    "list_number_pools": ("GET", "/pool"),
    "create_contact_list": ("POST", "/list"),
    "get_contact_list": ("GET", "/list/{list_id}"),
    "rename_contact_list": ("POST", "/list/{list_id}"),
    "delete_contact_list": ("DELETE", "/list/{list_id}"),
    "append_contacts": ("POST", "/list/{list_id}/contacts"),
    "send_sms": ("POST", "/sms"),
    "send_ringless_voicemail": ("POST", "/rvm"),
}


class DropCowboyNode(WorkflowNode):
    integration_type = "automation-drop-cowboy"
    connection_evidence = ConnectionEvidence(operation="list_brands", noun="brands", label_keys=("company_name", "dba_name", "brand_id"))

    @classmethod
    def get_config_model(cls):
        return DropCowboyConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Drop Cowboy Team ID and secret")
        config = self.config.config
        action = config.operation
        method, path = ROUTES[action]
        if isinstance(config, ListID):
            path = path.format(list_id=quote(config.list_id, safe=""))
        body = config.model_dump(exclude={"operation", "list_id"}, exclude_none=True)
        params = None
        if method == "GET":
            params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in body.items()}
            body = None
        elif method == "DELETE":
            body = None
        if action in {"send_sms", "send_ringless_voicemail"}:
            body.update(team_id=credential.account_id, secret=credential.secret)
        headers = {"x-team-id": credential.account_id, "x-secret": credential.secret, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body)
            if not 200 <= response.status_code < 300:
                raise ValueError(f"Drop Cowboy HTTP {response.status_code}: {response.text[:2000]}")
            if not response.content and action in {"rename_contact_list", "delete_contact_list"}:
                data = None
            else:
                data = response.json()
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False or str(data.get("status", "")).lower() in {"error", "failed", "failure"}):
                raise ValueError(str(data))
            if method == "GET" and action.startswith("list_") and not isinstance(data, list):
                raise ValueError("Drop Cowboy returned an unexpected list response")
            if action in {"send_sms", "send_ringless_voicemail"} and (not isinstance(data, dict) or not isinstance(data.get("status"), str)):
                raise ValueError("Drop Cowboy returned an unexpected send acknowledgement")
        except (httpx.HTTPError, ValueError) as exc:
            message = str(exc)
            for secret in (credential.account_id, credential.secret):
                message = message.replace(secret, "[redacted]")
            raise ValueError(message) from None
        # Responses remain provider-shaped, nested to avoid replacing our execution status.
        output = {"status": "success", "operation": action, "data": data}
        if action in {"send_sms", "send_ringless_voicemail"}:
            output["delivery_verified"] = False
        await self.emit(output)
        return output
