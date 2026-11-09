"""Podium V4 communication and payments operations.

Responses retain the provider's data and metadata, including cursors. Each
execution makes one API call and never automatically retries a mutation.
Contract: the public Podium API - V4 Postman collection, saved examples included.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from datetime import datetime
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.podium_operations import OPERATIONS
from nodes.scopes.podium import PODIUM_SCOPES


class PodiumOAuthCredential(BaseModel):
    credential_type: Literal["podium_oauth"] = Field(
        "podium_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        min_length=1,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: str | None = Field(
        None,
        title="Refresh Token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: str | None = Field(None, title="Token Expiry")
    model_config = ConfigDict(
        title="Podium Account",
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "podium",
            "x-oauth-scopes": sorted(PODIUM_SCOPES.declared_scopes()),
            "x-credential-url": "https://developer.podium.com/",
        },
    )


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def validate_mutation(self):
        if (
            self.operation == "update_conversation"
            and self.assignedUserUid is None
            and self.closed is None
        ):
            raise ValueError("Supply an assigned user or closed state")
        if self.operation == "create_review_invite" and not (
            self.email or self.phoneNumber
        ):
            raise ValueError("Supply an email or phone number")
        return self


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(..., min_length=1, title="Email or Phone Number")
    type: Literal["email", "phone"] = Field(..., title="Channel Type")


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(..., ge=1, le=99999900, title="Amount in Cents")
    description: str = Field("Total", max_length=50, title="Description")


def _f(t, default=..., **kw):
    return (t, Field(default, **kw))


_UID = _f(UUID, title="Resource UID")
_LOC = _f(UUID, title="Location UID")
_TEXT = _f(str, min_length=1)
# Keep only request fields actually published by the collection. The API has
# additional fields; exposing them needs its own provider contract evidence.
BODY_FIELDS = {
    "create_appointment": {
        "contactName": _TEXT,
        "contactPhoneNumber": _TEXT,
        "datetime": _f(datetime, title="Appointment Time"),
        "locationUid": _LOC,
        "assignedUserUid": _f(UUID | None, None, title="Assigned User UID"),
        "durationMin": _f(int | None, None, ge=1, title="Duration in Minutes"),
        "note": _f(str | None, None, max_length=500),
        "status": _f(
            Literal["unconfirmed", "confirmed", "cancelled", "completed", "no_show"]
            | None,
            None,
        ),
        "type": _f(Literal["in_person", "virtual"] | None, None),
    },
    "update_conversation": {
        "assignedUserUid": _f(UUID | None, None, title="Assigned User UID"),
        "closed": _f(bool | None, None, title="Closed"),
    },
    "create_conversation_note": {
        "body": _f(str, min_length=1, title="Note"),
        "senderName": _TEXT,
    },
    "send_message": {
        "body": _f(str, min_length=1, title="Message"),
        "channel": _f(Channel),
        "locationUid": _LOC,
        "contactName": _f(str | None, None),
        "senderName": _f(str | None, None),
        "subject": _f(str | None, None),
    },
    "create_invoice": {
        "channelIdentifier": _TEXT,
        "customerName": _TEXT,
        "lineItems": _f(
            list[LineItem], min_length=1, max_length=10, title="Line Items"
        ),
        "locationUid": _LOC,
        "invoiceNumber": _TEXT,
        "accountUid": _f(UUID | None, None),
        "readerUid": _f(UUID | None, None),
    },
    "cancel_invoice": {"locationUid": _LOC, "note": _f(str | None, None)},
    "create_review_invite": {
        "locationUid": _LOC,
        "email": _f(str | None, None),
        "phoneNumber": _f(str | None, None),
    },
}
QUERY_FIELDS = {
    "limit": _f(int, 10, ge=1, le=100, title="Page Size"),
    "cursor": _f(
        str | None,
        None,
        title="Cursor",
        description="Opaque nextCursor from the previous page. Cursor requests preserve the original filters.",
    ),
    "locationUid": _f(UUID | None, None, title="Location UID"),
    "search": _f(str | None, None),
    "searchFields": _f(str | None, None, title="Search Field"),
    "senderUid": _f(UUID | None, None, title="Sender UID"),
    **{
        k: _f(datetime | None, None, title=k)
        for k in (
            "createdAt[gt]",
            "createdAt[gte]",
            "createdAt[lt]",
            "createdAt[lte]",
            "datePaid",
            "dateRefunded",
            "dateCreated",
        )
    },
}
EFFECTS = {
    "create_appointment": "Creates a customer appointment in Podium.",
    "send_message": "Sends a message to the recipient. Podium may also update the contact name.",
    "create_invoice": "Creates an invoice and can send a payment link or prompt a card reader.",
    "cancel_invoice": "Cancels the invoice so the seller cannot collect payments for it.",
    "create_review_invite": "Creates a new review invitation link. Generate a separate link for each contact.",
}


def _config(name, op):
    fields = {
        "operation": _f(
            Literal[name],
            name,
            title=op["title"],
            json_schema_extra={"ui:hidden": True},
        )
    }
    if "{uid}" in op["path"]:
        fields["uid"] = _UID
    for key in op["query"]:
        fields[key] = (
            _LOC
            if name == "get_invoice" and key == "locationUid"
            else QUERY_FIELDS[key]
        )
    fields.update(BODY_FIELDS.get(name, {}))
    return create_model(
        "Podium" + "".join(s.title() for s in name.split("_")) + "Config",
        __base__=_Config,
        __doc__=EFFECTS.get(name, op["title"]),
        **fields,
    )


CONFIGS = {name: _config(name, op) for name, op in OPERATIONS.items()}
Operation = Annotated[Union[tuple(CONFIGS.values())], Field(discriminator="operation")]


class PodiumNodeConfig(NodeConfig[Operation, PodiumOAuthCredential]):
    pass


class PodiumNode(WorkflowNode):
    integration_type = "automation-podium"
    scope_registry = PODIUM_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_locations", noun="locations"
    )

    @classmethod
    def get_config_model(cls):
        return PodiumNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.podium_oauth import refresh_access_token, is_token_expired

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            is_expired=is_token_expired,
            provider="podium",
        )

    async def execute(self, inputs):
        if not isinstance(self.config, PodiumNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Podium account")
        credential = self.config.credentials
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.podium_oauth import refresh_access_token, is_token_expired

            data = credential.model_dump()
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=data,
                refresh=refresh_access_token,
                is_expired=is_token_expired,
                provider="podium",
                caller_path="execute",
            )
            credential.access_token = data["access_token"]
            credential.refresh_token = data.get("refresh_token")
            credential.expires_at = data.get("expires_at")
        config = self.config.config
        name = config.operation
        op = OPERATIONS[name]
        self.scope_registry.require(name)
        values = config.model_dump(mode="json", exclude_none=True)
        path = op["path"].replace("{uid}", quote(values.get("uid", ""), safe=""))
        query = {k: values[k] for k in op["query"] if k in values}
        # Podium cursors encapsulate the initial filters. Do not accidentally
        # change those filters while traversing subsequent pages.
        if query.get("cursor"):
            query = {"cursor": query["cursor"]}
        body = {k: values[k] for k in op["body"] if k in values}
        headers = {
            "Authorization": "Bearer " + credential.access_token,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                op["method"],
                "https://api.podium.com" + path,
                headers=headers,
                params=query,
                **({"json": body} if op["body"] else {}),
            )
        # Preserve provider rejection text for the credential-connect seam. No
        # mutation is retried after a timeout, rejection, or ambiguous reply.
        if not 200 <= response.status_code < 300:
            return {
                "status": "error",
                "operation": name,
                "http_status": response.status_code,
                "error": response.text,
            }
        payload = response.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError("Podium returned an unexpected response envelope")
        return {"status": "success", "operation": name, **payload}
