"""Native Fountain Private Hire metadata and applicant record operations.

Creation always supplies an opening and four explicit false communication consents.
Current saved authority is checked before transport and before releasing output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Awaitable, Callable, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_serializer, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes import fountain_api as api


class FountainPrivateHireCredential(BaseModel):
    credential_type: Literal["fountain_private_hire"] = Field("fountain_private_hire", json_schema_extra={"ui:hidden": True})
    tenant: Literal["main", "us-2"] = Field("main", description="Main api.fountain.com/v2 or documented us-2.fountain.com/api/v2. Other tenants and Fountain One are not inferred.")
    api_key: str = Field(..., min_length=8, max_length=8192, repr=False, title="Private Hire API Key",
                         description="Existing private Hire key with read access. A trusted-party create-only key is not a full Private Hire connection.", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={"x-credential-url": "https://developer.fountain.com/reference/hire-api-overview"})

    @field_validator("api_key")
    @classmethod
    def header_safe(cls, value):
        if not value.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError("Private Hire API key is not header-safe.")
        return value

    @model_serializer(mode="wrap")
    def with_tag(self, handler):
        return {**handler(self), "credential_type": "fountain_private_hire"}


def credential_shape(data):
    if not isinstance(data, dict) or data.get("credential_type", "fountain_private_hire") != "fountain_private_hire":
        raise ValueError("Fountain requires a Private Hire credential.")
    try:
        return FountainPrivateHireCredential.model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Fountain Private Hire credential is invalid.") from None


def _picker(field, *, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True,
               "placeholder": "Select a Fountain resource", "custom_placeholder": "Or enter its UUID"}
    if parent:
        options["depends_on"] = [parent]
    return {"x-dynamic-options": options, "x-resource-type": field}


ResourceID = Annotated[str, Field(min_length=36, max_length=36), AfterValidator(api.resource_id)]


class _Config(BaseModel):
    # Persisted Canvas label/goal/disabled/_settings are normal runtime metadata.
    model_config = ConfigDict(extra="ignore")


class _Opening(_Config):
    opening_id: ResourceID = Field(..., description="Explicit Hire opening (funnel) UUID.", json_schema_extra=_picker("opening_id"))


class _Applicant(_Opening):
    applicant_id: ResourceID = Field(..., json_schema_extra=_picker("applicant_id", parent="opening_id"))


class ListOpenings(_Config):
    operation: Literal["list_openings"] = "list_openings"
    page: int = Field(1, ge=1, le=100000)
    per_page: int = Field(25, ge=1, le=100, description="NoClick bound, not a claim about the provider's maximum.")
    active: bool | None = None
    query: str | None = Field(None, max_length=256)


class GetOpening(_Opening):
    operation: Literal["get_opening"] = "get_opening"


class ListStages(_Opening):
    operation: Literal["list_stages"] = "list_stages"


class GetStage(_Opening):
    operation: Literal["get_stage"] = "get_stage"
    stage_id: ResourceID = Field(..., json_schema_extra=_picker("stage_id", parent="opening_id"))


class ListApplicants(_Opening):
    operation: Literal["list_applicants"] = "list_applicants"
    stage_id: ResourceID | None = Field(None, json_schema_extra=_picker("stage_id", parent="opening_id"))
    page: int | None = Field(None, ge=1, le=100000)
    cursor: str | None = Field(None, max_length=4096)
    per_page: int = Field(25, ge=1, le=100)
    exclude_temporary: bool = True

    @model_validator(mode="after")
    def valid_page(self):
        if self.page is not None and self.cursor is not None:
            raise ValueError("Use a page or a cursor, not both.")
        if self.cursor is not None:
            api.cursor_value(self.cursor)
        return self


class GetApplicant(_Applicant):
    operation: Literal["get_applicant"] = "get_applicant"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicantCreate(_Body):
    name: str = Field(..., min_length=1, max_length=512)
    email: str = Field(..., min_length=3, max_length=320)
    phone_number: str = Field(..., min_length=1, max_length=64)
    check_if_applicant_is_duplicate: bool = True
    application_locale: str | None = Field(None, min_length=2, max_length=32)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Applicant email is invalid.")
        return value


class ApplicantPatch(_Body):
    name: str | None = Field(None, max_length=512)
    email: str | None = Field(None, max_length=320)
    phone_number: str | None = Field(None, max_length=64)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value not in (None, "") and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Applicant email is invalid.")
        return value

    @model_validator(mode="after")
    def not_empty(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one applicant metadata change.")
        return self


class CreateApplicant(_Opening):
    operation: Literal["create_applicant"] = "create_applicant"
    body: ApplicantCreate


class UpdateApplicant(_Applicant):
    operation: Literal["update_applicant"] = "update_applicant"
    body: ApplicantPatch


class DeleteApplicant(_Applicant):
    operation: Literal["delete_applicant"] = "delete_applicant"


FountainConfig = Annotated[Union[ListOpenings, GetOpening, ListStages, GetStage, ListApplicants,
                                 GetApplicant, CreateApplicant, UpdateApplicant, DeleteApplicant], Field(discriminator="operation")]


class FountainNodeConfig(NodeConfig[FountainConfig, FountainPrivateHireCredential]):
    pass


@dataclass
class _Lease:
    data: dict
    load: Callable[[], Awaitable[dict | None]]

    async def recheck(self):
        current = await self.load()
        if current is None or credential_shape(current) != self.data:
            raise ValueError("Fountain saved credential authority changed; output withheld.")


async def _saved_lease(data, *, pool, user_id, credential_id, workflow_id=None, organization_id=None):
    if not user_id or not credential_id:
        raise ValueError("Fountain saved lookup requires the authenticated user and credential ID.")
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()

    async def load():
        if workflow_id:
            from utils.credentials import resolve_credential_with_owner_fallback
            return await resolve_credential_with_owner_fallback(
                credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id)
        from utils.credential_loader import load_credential
        return await load_credential(pool, user_id, credential_id, raise_on_error=True)

    current = await load()
    if current is None:
        raise ValueError("Fountain credential not found or current access denied.")
    shaped = credential_shape(data)
    if shaped != credential_shape(current):
        raise ValueError("Fountain supplied credential differs from its current saved grant.")
    return _Lease(shaped, load)


class FountainNode(WorkflowNode):
    integration_type = "automation-fountain"
    credential_provider_labels = {"fountain": "Fountain Account"}
    supports_op_tools = True
    connection_evidence = ConnectionEvidence(operation="list_openings", noun="Hire openings", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FountainNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if raw is not None:
            raw_dict = raw.model_dump() if isinstance(raw, BaseModel) else raw
            credential_shape(raw_dict)
        try:
            return TypeAdapter(FountainNodeConfig).validate_python(runtime_config_view(config_data, FountainNodeConfig))
        except Exception:
            raise ValueError("Fountain configuration is invalid; check the selected operation and required IDs.") from None

    @classmethod
    async def validate_credential_access(cls, credential_data):
        data = credential_shape(credential_data)
        api.page(await api.request(data, "GET", "/funnels", params={"page": 1, "per_page": 1}),
                 "funnels", "opening", limit=1)
        return {"valid": True, "reachable": True, "proves": "reachability"}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        lease = await _saved_lease(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        return {**lease.data, "_fountain_lease": lease}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        context = context or {}
        lease = credential_data.get("_fountain_lease") if isinstance(credential_data, dict) else None
        if not isinstance(lease, _Lease):
            raise ValueError("Fountain picker requires current saved credential admission.")
        if field_name not in {"opening_id", "stage_id", "applicant_id"}:
            raise ValueError("Unsupported Fountain picker field.")
        data = lease.data
        async def get(path, params=None):
            return await api.request(data, "GET", path, params=params, recheck=lease.recheck)
        if field_name == "opening_id":
            if page_token is not None and not re.fullmatch(r"[0-9]{1,6}", str(page_token)):
                raise ValueError("Fountain opening picker page is invalid.")
            page_number = 1 if page_token is None else int(page_token)
            if page_number < 1 or page_number > 100000:
                raise ValueError("Fountain opening picker page is invalid.")
            params = {"page": page_number, "per_page": 100}
            if search:
                if len(search) > 256:
                    raise ValueError("Fountain opening search is too long.")
                params["query"] = search
            result = api.page(await get("/funnels", params), "funnels", "opening")
            next_token = None if result["next_page"] is None else str(result["next_page"])
        else:
            opening = api.resource_id(context.get("opening_id"))
            api.project(await get(f"/funnels/{opening}"), "opening", expected_id=opening)
            if field_name == "stage_id":
                if page_token is not None:
                    raise ValueError("Fountain stage lists do not have a documented paging contract.")
                result = api.page(await get(f"/funnels/{opening}/stages"), "stages", "stage", limit=1000)
                next_token = None
            else:
                params = {"funnel_id": opening, "per_page": 100, "include_subaccounts": "false", "exclude_temporary": "true"}
                if page_token:
                    params["cursor"] = api.cursor_value(page_token)
                result = api.page(await get("/applicants", params), "applicants", "applicant", opening_id=opening)
                # The applicant picker uses the documented opaque cursor. Page-only
                # continuation is exposed by the action, not silently truncated here.
                next_token = result["next_cursor"]
                if next_token is None and result["next_page"] is not None:
                    raise ValueError("Fountain applicant picker requires its documented next cursor.")
        options = [{"value": row["id"], "label": row.get("title") or row.get("name") or row["id"]} for row in result["data"]]
        if search and field_name != "opening_id":
            options = [row for row in options if search.lower() in row["label"].lower()]
        await lease.recheck()
        return {"options": options, "next_page_token": next_token}

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, FountainNodeConfig) or config.credentials is None:
            raise ValueError("Fountain Private Hire credentials are required.")
        data = credential_shape(config.credentials.model_dump(mode="json"))
        raw = self.node_data or {}
        credential_id = raw.get("credential_id") or raw.get("_credential_id")
        lease = None
        if credential_id:
            lease = await _saved_lease(raw.get("credentials") or data, pool=raw.get("_approval_pool"),
                        user_id=self.user_id, credential_id=credential_id, workflow_id=self.workflow_id,
                        organization_id=self.organization_id)
            data = lease.data
        async def call(method, path, *, params=None, body=None):
            return await api.request(data, method, path, params=params, body=body,
                                     recheck=None if lease is None else lease.recheck)
        op = config.config
        if isinstance(op, ListOpenings):
            params = {"page": op.page, "per_page": op.per_page}
            if op.active is not None:
                params["active"] = str(op.active).lower()
            if op.query:
                params["query"] = op.query
            return api.page(await call("GET", "/funnels", params=params), "funnels", "opening", limit=op.per_page)
        opening = op.opening_id
        opening_record = api.project(await call("GET", f"/funnels/{opening}"), "opening", expected_id=opening)
        if isinstance(op, GetOpening):
            return {"data": opening_record}
        if isinstance(op, (ListStages, GetStage)) or (isinstance(op, ListApplicants) and op.stage_id):
            stages = api.page(await call("GET", f"/funnels/{opening}/stages"), "stages", "stage", limit=1000)
            if isinstance(op, ListStages):
                return stages
            if op.stage_id not in {row["id"] for row in stages["data"]}:
                raise ValueError("Fountain stage does not belong to the selected opening.")
            if isinstance(op, GetStage):
                return {"data": api.project(await call("GET", f"/stages/{op.stage_id}"), "stage", expected_id=op.stage_id)}
        if isinstance(op, ListApplicants):
            params = {"funnel_id": opening, "per_page": op.per_page,
                      "include_subaccounts": "false", "exclude_temporary": str(op.exclude_temporary).lower()}
            if op.stage_id:
                params["stage_id"] = op.stage_id
            if op.cursor:
                params["cursor"] = op.cursor
            elif op.page is not None:
                params["page"] = op.page
            result = api.page(await call("GET", "/applicants", params=params), "applicants", "applicant", limit=op.per_page, opening_id=opening)
            if op.stage_id and any(row.get("stage", {}).get("id") != op.stage_id for row in result["data"]):
                raise ValueError("Fountain returned applicants from a different stage.")
            return result
        if isinstance(op, CreateApplicant):
            body = op.body.model_dump(exclude_unset=True, mode="json")
            body.update(funnel_id=opening, **{field: False for field in api.CONSENT_FIELDS})
            # Explicitly preserve duplicate checking even when the UI omits its default.
            body["check_if_applicant_is_duplicate"] = op.body.check_if_applicant_is_duplicate
            result = api.project(await call("POST", "/applicants", body=body), "applicant", opening_id=opening)
            return {"data": result, "applied": None, "readback_required": True,
                    "communication_consents_sent": {field: False for field in api.CONSENT_FIELDS}}
        applicant = op.applicant_id
        result = api.project(await call("GET", f"/applicants/{applicant}"), "applicant", expected_id=applicant, opening_id=opening)
        if isinstance(op, GetApplicant):
            return {"data": result}
        if isinstance(op, UpdateApplicant):
            result = api.project(await call("PUT", f"/applicants/{applicant}", body=op.body.model_dump(exclude_unset=True)),
                                 "applicant", expected_id=applicant, opening_id=opening)
            return {"data": result, "applied": None, "readback_required": True}
        if isinstance(op, DeleteApplicant):
            await call("DELETE", f"/applicants/{applicant}")
            return {"id": applicant, "opening_id": opening, "deletion_verified": None, "readback_required": True}
        raise ValueError("Unsupported Fountain operation.")
