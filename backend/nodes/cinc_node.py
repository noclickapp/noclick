"""CINC v2 lead, agent and label automation.

Contract: https://public.cincapi.com/v2/docs/swagger/swagger.json (v1).
Prose response envelopes: https://public.cincapi.com/v2/docs/.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.cinc_operations import OPERATIONS
from nodes.scopes.cinc import CINC_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://public.cincapi.com/v2"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class CINCOAuthCredential(BaseModel):
    model_config = ConfigDict(title="CINC Account", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "cinc",
            "x-oauth-scopes": CINC_SCOPES.declared_scopes(),
            "x-credential-url": "https://public.cincapi.com/v2/docs/#cinc-developer-sign-up",
            "x-credential-instructions": "Connect your CINC account. CINC requires a registered integration and broker permissions for site reads and writes. Self-hosted installations must register an OAuth application with CINC and configure CINC_CLIENT_ID, CINC_CLIENT_SECRET and CINC_REDIRECT_URI."})
    credential_type: Literal["cinc_oauth"] = Field("cinc_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Expires At")
    scope: str | None = None
    _secrets = field_validator("access_token", "refresh_token", mode="before")(lambda v: clean_secret(v) if v is not None else v)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PhoneNumbers(_Closed):
    cell_phone: str | None = Field(None)
    office_phone: str | None = Field(None)
    home_phone: str | None = Field(None)
    work_phone: str | None = Field(None)


class AddressInfo(_Closed):
    street: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None)
    postal_or_zip: str | None = Field(None)
    county: str | None = Field(None)
    unit: str | None = Field(None)


class ContactInfo(_Closed):
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    phone_numbers: PhoneNumbers | None = Field(None)
    email: str | None = Field(None)
    is_validated_email: bool | None = Field(None, strict=True)
    mailing_address: AddressInfo | None = Field(None)


class BuyerInfo(_Closed):
    median_price: float | None = Field(None)
    average_price: float | None = Field(None)
    favorite_city: str | None = Field(None)
    timeline: str | None = Field(None)


class SellerProperty(_Closed):
    id: str | None = Field(None)
    address: AddressInfo | None = Field(None)
    created_date: str | None = Field(None, json_schema_extra={"format": "date-time"})
    total_beds: int | None = Field(None)
    total_baths: int | None = Field(None)
    asking_price: float | None = Field(None)
    updated_date: str | None = Field(None, json_schema_extra={"format": "date-time"})


class SellerInfo(_Closed):
    timeline: str | None = Field(None)
    properties: list[SellerProperty] | None = Field(None)


class SecondaryInfo(_Closed):
    relation: str | None = Field(None)
    contact: ContactInfo | None = Field(None)


class LeadInfo(_Closed):
    status: str | None = Field(None)
    contact: ContactInfo | None = Field(None)
    updated_date: str | None = Field(None, json_schema_extra={"format": "date-time"})
    url: str | None = Field(None)
    is_partial: bool | None = Field(None, strict=True)
    is_buyer: bool | None = Field(None, strict=True)
    buyer: BuyerInfo | None = Field(None)
    is_seller: bool | None = Field(None, strict=True)
    seller: SellerInfo | None = Field(None)
    source: str | None = Field(None)
    secondary: SecondaryInfo | None = Field(None)


class LeadNote(_Closed):
    id: str | None = Field(None)
    content: str | None = Field(None)
    category: str | None = Field(None)
    created_by: str | None = Field(None)
    created_date: str | None = Field(None, json_schema_extra={"format": "date-time"})
    updated_date: str | None = Field(None, json_schema_extra={"format": "date-time"})
    is_pinned: bool | None = Field(None, strict=True)
    notified_agents: list[str] | None = Field(None)


class LeadRequest(_Closed):
    registered_date: str | None = Field(None, json_schema_extra={"format": "date-time"})
    info: LeadInfo | None = Field(None)
    notes: list[LeadNote] | None = Field(None)


class LeadLabelRequest(_Closed):
    name: str | None = Field(None)
    color: str | None = Field(None)


class Identifier(_Closed):
    id: str | None = Field(None)


class LabelIds(_Closed):
    labels: list[Identifier] | None = Field(None)


BODY_MODELS = {"LeadRequest": LeadRequest, "LeadLabelRequest": LeadLabelRequest, "LabelIds": LabelIds}


def _make_config(name, op):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={
        "ui:hidden": True, "x-display-name": op["label"], "x-is-trigger": False,
        "x-operation-kind": "read" if op["method"] == "GET" else "write"}))}
    for field in re.findall(r"{(\w+)}", op["path"]):
        fields[field] = (str, Field(..., min_length=1, max_length=256,
            pattern=r"^[A-Za-z0-9_-]+$", title=field.replace("_", " ").title()))
    if name in {"list_leads", "list_agents"}:
        fields.update(offset=(int, Field(0, ge=0)), limit=(int, Field(100, ge=1, le=500)),
            next=(str | None, Field(None, title="Next Page Token", description="Opaque next value from CINC's paging object. Use instead of offset.")))
    if op["body"]:
        fields["body"] = (BODY_MODELS[op["body"]], Field(..., title="Details", json_schema_extra=JSON_EDITOR,
            description=("Lead upsert matches contact details and can update an existing lead." if name == "upsert_lead" else "CINC label fields for this action.")))
    return create_model("CINC" + "".join(s.title() for s in name.split("_")) + "Config",
        __base__=_Closed, __module__=__name__, **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({cls.__name__: cls for cls in CONFIG_MODELS.values()})
CINCConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class CINCFullConfig(NodeConfig[CINCConfig, CINCOAuthCredential]):
    pass


def _payload(body):
    if isinstance(body, dict):
        if body.get("error") or body.get("errors") or body.get("success") is False:
            raise ValueError("CINC returned an error response")
        if "body" in body:
            body = body["body"]
            if not isinstance(body, dict):
                raise ValueError("CINC returned an invalid response envelope")
            if body.get("error") or body.get("errors") or body.get("success") is False:
                raise ValueError("CINC returned an error response")
    return body


class CINCNode(WorkflowNode):
    integration_type = "automation-cinc"
    scope_registry = CINC_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_agents", noun="CINC agents",
        label_keys=("username", "id"), identity_operation="get_me", identity_keys=("username",))

    @classmethod
    def get_config_model(cls):
        return CINCFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.cinc_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="cinc")

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a CINC account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.cinc_oauth import refresh_access_token
        credential = self.config.credentials.model_dump()
        await ensure_fresh_oauth_token(credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=refresh_access_token, provider="cinc", caller_path="execute")
        config = self.config.config
        op = OPERATIONS[config.operation]
        path = op["path"]
        for name in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + name + "}", quote(getattr(config, name), safe=""))
        params = {}
        if config.operation in {"list_leads", "list_agents"}:
            params = {"limit": config.limit}
            params.update({"next": config.next} if config.next is not None else {"offset": config.offset})
        kwargs = {"json": config.body.model_dump(exclude_none=True)} if op["body"] else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(op["method"], BASE + path, params=params,
                headers={"Authorization": "Bearer " + credential["access_token"], "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise ValueError("CINC did not confirm the request")
        data = _payload(response.json()) if response.content else None
        key = op["result"]
        if config.operation.startswith("list_"):
            rows = data.get(key) if isinstance(data, dict) else data
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("CINC returned an invalid list")
            paging = data.get("paging") if isinstance(data, dict) else None
            if paging is not None and not isinstance(paging, dict):
                raise ValueError("CINC returned invalid pagination")
            return {"status": "success", "data": rows, "paging": paging,
                "next_page_token": paging.get("next") if paging else None,
                "pagination_available": paging is not None}
        if key and isinstance(data, dict) and key in data:
            data = data[key]
        if op["method"] == "GET" and not isinstance(data, dict):
            raise ValueError("CINC returned an invalid record")
        return {"status": "success", "data": data, "http_status": response.status_code}
