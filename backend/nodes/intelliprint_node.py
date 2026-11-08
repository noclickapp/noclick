"""Intelliprint v1 print jobs, backgrounds and mailing lists.

Contract: https://registry.scalar.com/@intelliprint/apis/intelliprint-api-reference?format=json
A single request per operation; writes are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.intelliprint.net/v1"


class IntelliprintAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Intelliprint API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://account.intelliprint.net/api_keys",
            "x-credential-instructions": "Create an API key in your Intelliprint account, then paste it here. NoClick sends it as a bearer token to api.intelliprint.net. Connecting reads your mailing lists. Confirmed live print jobs incur charges and send physical mail.",
        })
    credential_type: Literal["intelliprint_api_key"] = Field("intelliprint_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class Address(Input):
    line: Text = Field(..., description="Complete address line, including street, town and region.")
    name: Text | None = None
    postcode: str | None = None
    country: str = Field("GB", pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2 country code.")


class Recipient(Input):
    address: Address
    variables: dict[str, Any] | None = None


class AddressValidation(Input):
    requested: bool = False


class RemoteFile(Input):
    url: str = Field(..., pattern=r"^https://[^\s]+$", description="Public HTTPS file URL; Intelliprint fetches the file, NoClick does not download it.")


class Printing(Input):
    double_sided: Literal["no", "yes", "mixed"] | None = None
    double_sided_specific_pages: list[Annotated[int, Field(ge=0)]] | None = None
    premium_quality: bool | None = None
    black_and_white: bool | None = None
    matt_finish: bool | None = None


class Postage(Input):
    service: Literal["uk_second_class", "uk_second_class_signed_for", "uk_first_class", "uk_first_class_signed_for", "uk_special_delivery_9am", "uk_special_delivery", "international", "tracked_24", "tracked_48"] | None = None
    ideal_envelope: Literal["c4", "c5", "c4_plus", "a4_box", "postcard_a6", "postcard_a5", "postcard_a5_enveloped"] | None = None
    mail_date: int | None = Field(None, ge=0, description="Unix timestamp of the mailing date.")


class ListInput(Input):
    limit: int = Field(10, ge=1, le=1000)
    skip: int = Field(0, ge=0, description="Offset for this page. Use next_skip from the previous result.")
    sort_order: Literal["asc", "desc"] = "desc"


class ListPrints(ListInput):
    operation: Literal["list_prints"] = "list_prints"
    sort_field: Literal["created", "confirmed_at", "reference", "type", "letters", "pages", "sheets", "letters.returned.date", "cost.after_tax", "cost.amount"] = "created"
    testmode: bool | None = None
    confirmed: bool | None = None
    type: Literal["letter", "postcard"] | None = None
    reference: str | None = None
    letters_status: str | None = Field(None, description="Comma-separated mail item statuses.")
    returned_acknowledged: bool | None = None


class GetPrint(Input):
    operation: Literal["get_print"] = "get_print"
    id: ResourceID


class CreatePrint(Input):
    operation: Literal["create_print"] = "create_print"
    content: Text = Field(..., description="Text or HTML to print.")
    recipients: list[Recipient] = Field(..., min_length=1, max_length=1000)
    type: Literal["letter", "postcard"] = "letter"
    testmode: bool = Field(True, description="Test mode does not charge or send mail. Disable explicitly for live mail.")
    confirmed: bool = Field(False, description="Confirm to submit for printing. Confirmed live jobs charge your account and send physical mail.")
    reference: str | None = None
    printing: Printing | None = None
    postage: Postage | None = None
    metadata: dict[str, Any] | None = None
    confirmation_email: bool = False


class UpdatePrint(Input):
    operation: Literal["update_print"] = "update_print"
    id: ResourceID
    confirmed: bool | None = Field(None, description="Confirming a live job charges your account and submits physical mail; confirmed jobs cannot be updated.")
    testmode: bool | None = None
    reference: str | None = None
    printing: Printing | None = None
    postage: Postage | None = None
    metadata: dict[str, Any] | None = None
    confidential: bool | None = None
    confirmation_email: bool | None = None
    address_window: Literal["left", "right"] | None = None


class DeletePrint(Input):
    operation: Literal["delete_print"] = "delete_print"
    id: ResourceID = Field(..., description="Delete an unconfirmed job or request cancellation of confirmed mail items. Acknowledgement does not prove all mail was cancelled.")


class ListBackgrounds(ListInput):
    operation: Literal["list_backgrounds"] = "list_backgrounds"
    sort_field: Literal["created", "name"] = "created"
    team: ResourceID | None = None


class GetBackground(Input):
    operation: Literal["get_background"] = "get_background"
    id: ResourceID


class CreateBackground(Input):
    operation: Literal["create_background"] = "create_background"
    file: RemoteFile
    name: Text | None = None
    team: ResourceID | None = None


class UpdateBackground(Input):
    operation: Literal["update_background"] = "update_background"
    id: ResourceID
    name: Text | None = None
    team: ResourceID | None = Field(None, description="Explicit null makes this background available to everyone; omit to retain the current team.")


class DeleteBackground(Input):
    operation: Literal["delete_background"] = "delete_background"
    id: ResourceID


class ListMailingLists(ListInput):
    operation: Literal["list_mailing_lists"] = "list_mailing_lists"
    sort_field: Literal["created", "name", "recipients"] = "created"


class GetMailingList(Input):
    operation: Literal["get_mailing_list"] = "get_mailing_list"
    id: ResourceID


class CreateMailingList(Input):
    operation: Literal["create_mailing_list"] = "create_mailing_list"
    name: Text
    recipients: list[Recipient] | None = Field(None, max_length=1000)
    address_validation: AddressValidation | None = None


class UpdateMailingList(Input):
    operation: Literal["update_mailing_list"] = "update_mailing_list"
    id: ResourceID
    name: Text | None = None
    recipients: list[Recipient] | None = Field(None, max_length=1000)
    delete_old_recipients: bool | None = Field(None, description="Delete all existing recipients before adding the supplied recipients.")
    address_validation: AddressValidation | None = None


class DeleteMailingList(Input):
    operation: Literal["delete_mailing_list"] = "delete_mailing_list"
    id: ResourceID


class ListRecipients(ListInput):
    operation: Literal["list_recipients"] = "list_recipients"
    mailing_list: ResourceID
    sort_field: Literal["created", "name"] = "created"


class GetRecipient(Input):
    operation: Literal["get_recipient"] = "get_recipient"
    mailing_list: ResourceID
    id: ResourceID


class CreateRecipient(Input):
    operation: Literal["create_recipient"] = "create_recipient"
    mailing_list: ResourceID
    address: Address
    variables: dict[str, Any] | None = None


class AddressPatch(Input):
    name: Text | None = None
    line: Text | None = None
    postcode: str | None = None
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$")


class UpdateRecipient(Input):
    operation: Literal["update_recipient"] = "update_recipient"
    mailing_list: ResourceID
    id: ResourceID
    address: AddressPatch | None = None
    variables: dict[str, Any] | None = None


class DeleteRecipient(Input):
    operation: Literal["delete_recipient"] = "delete_recipient"
    mailing_list: ResourceID
    id: ResourceID


IntelliprintConfig = Annotated[Union[
    ListPrints, GetPrint, CreatePrint, UpdatePrint, DeletePrint,
    ListBackgrounds, GetBackground, CreateBackground, UpdateBackground, DeleteBackground,
    ListMailingLists, GetMailingList, CreateMailingList, UpdateMailingList, DeleteMailingList,
    ListRecipients, GetRecipient, CreateRecipient, UpdateRecipient, DeleteRecipient,
], Field(discriminator="operation")]


class IntelliprintNodeConfig(NodeConfig[IntelliprintConfig, IntelliprintAPIKeyCredential]):
    pass


# Each public operation maps to exactly one published v1 operation.
ROUTES = {
    "list_prints": ("GET", "/prints"),
    "get_print": ("GET", "/prints/{id}"),
    "create_print": ("POST", "/prints"),
    "update_print": ("POST", "/prints/{id}"),
    "delete_print": ("DELETE", "/prints/{id}"),
    "list_backgrounds": ("GET", "/backgrounds"),
    "get_background": ("GET", "/backgrounds/{id}"),
    "create_background": ("POST", "/backgrounds"),
    "update_background": ("POST", "/backgrounds/{id}"),
    "delete_background": ("DELETE", "/backgrounds/{id}"),
    "list_mailing_lists": ("GET", "/mailing_lists"),
    "get_mailing_list": ("GET", "/mailing_lists/{id}"),
    "create_mailing_list": ("POST", "/mailing_lists"),
    "update_mailing_list": ("POST", "/mailing_lists/{id}"),
    "delete_mailing_list": ("DELETE", "/mailing_lists/{id}"),
    "list_recipients": ("GET", "/mailing_lists/{mailing_list}/recipients"),
    "get_recipient": ("GET", "/mailing_lists/{mailing_list}/recipients/{id}"),
    "create_recipient": ("POST", "/mailing_lists/{mailing_list}/recipients"),
    "update_recipient": ("POST", "/mailing_lists/{mailing_list}/recipients/{id}"),
    "delete_recipient": ("DELETE", "/mailing_lists/{mailing_list}/recipients/{id}"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class IntelliprintNode(WorkflowNode):
    integration_type = "automation-intelliprint"
    connection_evidence = ConnectionEvidence(noun="mailing lists", operation="list_mailing_lists")

    @classmethod
    def get_config_model(cls):
        return IntelliprintNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Intelliprint API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        for name in ("id", "mailing_list"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(getattr(op, name), safe=""))
        body = op.model_dump(mode="json", exclude={"operation", "id", "mailing_list"}, exclude_none=True)
        # Updates send only explicitly supplied fields: omitted fields retain provider values.
        if op.operation.startswith("update_"):
            body = op.model_dump(mode="json", exclude={"operation", "id", "mailing_list"}, exclude_none=True, exclude_unset=True)
            if isinstance(op, UpdateBackground) and "team" in op.model_fields_set:
                body["team"] = op.team
        kwargs = {}
        if method == "GET":
            aliases = {"letters_status": "letters.status", "returned_acknowledged": "letters.returned.acknowledged"}
            kwargs["params"] = {aliases.get(k, k): str(v).lower() if isinstance(v, bool) else v for k, v in body.items()}
        elif method == "POST":
            if not body:
                raise ValueError("Provide at least one field to update")
            # The provider's published introduction supports JSON for every endpoint.
            # These operations use text/HTML or a remote file, so no binary upload is needed.
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("Intelliprint request did not complete" + ("; write outcome is unknown, inspect your account before retrying" if method != "GET" else "")) from None
        if response.status_code not in (200, 202):
            return {"status": "error", "http_status": response.status_code,
                    "error": _redact(response.text[:2000], key),
                    "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}
        if len(response.content) > 20_000_000 or response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise ValueError("Intelliprint returned an unexpected response" + ("; inspect the write before retrying" if method != "GET" else ""))
        data = response.json()
        if not isinstance(data, dict) or data.get("error"):
            raise ValueError("Intelliprint did not return a successful resource")
        output = {**data, "status": "success", "http_status": response.status_code}
        if isinstance(op, ListInput):
            if not isinstance(data.get("data"), list) or type(data.get("has_more")) is not bool or (data["has_more"] and not data["data"]):
                raise ValueError("Intelliprint returned an unexpected list response")
            output["next_skip"] = op.skip + len(data["data"]) if data["has_more"] else None
        if isinstance(op, DeletePrint):
            output["cancellation_complete"] = False
            output["cancellation_note"] = "Cancellation requested; inspect individual mail item statuses. A 202 response means cancellation is still processing."
        return _redact(output, key)
