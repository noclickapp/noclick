"""Native Proposify Connect reads and V3 draft workflows; no sends/signatures.

V3 IDs are UUIDs. Legacy user/template IDs are numbers.202 is acceptance only;
there is no invented event-status polling or automatic mutation retry.
"""
from datetime import datetime, timezone
import json
import re
from typing import Annotated, Any, Dict, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.core.credential_fields import clean_secret
from nodes.oauth.proposify_oauth import ProposifyCredentialsTableStore, CURRENT_ORGANIZATION
from utils.ssrf import SSRFError, guarded_async_client

FAMILY, BASE_URL = "proposify_issued_token", "https://connect.proposify.com"
SCOPES = {"read_users", "read_templates", "read_documents", "write_documents"}
MAX_BYTES, MAX_ROWS = 2 * 1024 * 1024, 500

# Keep the schema contract aligned with the strict runtime UUID validator.
V3ID = Annotated[str, Field(json_schema_extra={"format": "uuid"})]


def _text(value, maximum=500, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use bounded Proposify text without control characters")
    return value


def _secret(value):
    value = _text(value, 4096)
    if any(c.isspace() for c in value): raise ValueError("Use a raw issued value without its Bearer prefix")
    return clean_secret(value, field_name="Proposify issued token")


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value): raise ValueError("Use a V3 UUID, never a legacy numeric ID or URL")
    return str(UUID(value))


def _number(value):
    # The legacy spec uses number; integral JSON floats are accepted without
    # conflating numeric IDs with V3 UUIDs or trusting imprecise large doubles.
    if type(value) is float and value.is_integer() and 0 < value <= 2**53-1: value = int(value)
    if type(value) is not int or not 1 <= value <= 2**53-1: raise ValueError("Use a positive exact legacy numeric ID")
    return value


class ProposifyIssuedTokenCredential(BaseModel):
    model_config = ConfigDict(title="Proposify Issued OAuth Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://apidocs.proposify.com/",
        "x-credential-instructions": "Supply an already-issued Proposify Connect Bearer token and its actual granted scopes. No OAuth client registration, authorization, exchange or refresh is automated. Expiry/client/account absence is unknown, not filled from an app/global client. API enablement/paid entitlement remains unverified. Draft mutations require an expected account ID observed from a protected V3 object. User list is account users, not token-user identity."})
    credential_type: Literal["proposify_issued_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Already-Issued Proposify Access Token", json_schema_extra={"ui:widget": "password"})
    token_type: Literal["Bearer"] = Field(..., title="Actual Token Type")
    scopes: list[Literal["read_users", "read_templates", "read_documents", "write_documents"]] = Field(..., min_length=1, max_length=4, title="Actual Granted Operation Scopes", description="Record actual applicable read/write permissions, not requested/guessed scopes. At least one read permission is needed for protected connect proof.")
    client_id: str | None = Field(None, title="Actual Issuing Client ID (if known)")
    expected_account_id: int | None = Field(None, title="Expected Proposify Account ID (if known)", description="Actual numeric account.id observed on an accessible V3 object. Optional for reads; required locally for draft mutations. This is a resource/account binding, not proof of the token principal.")
    expires_at: datetime | None = Field(None, title="Actual Issuer Token Expiry (if known)", description="Timezone-aware known expiry only. Unknown expiry is not a non-expiring token. Replace expired/rejected issued tokens; this credential does not refresh.")

    @field_validator("access_token", "client_id", mode="before")
    @classmethod
    def token_values(cls, value): return None if value is None else _secret(value)

    @field_validator("expected_account_id", mode="before")
    @classmethod
    def account(cls, value): return None if value is None else _number(value)

    @field_validator("scopes", mode="before")
    @classmethod
    def granted_scopes(cls, value):
        if not isinstance(value, list) or any(not isinstance(v, str) or v not in SCOPES for v in value) or len(set(value)) != len(value) or not set(value) & {"read_users", "read_templates", "read_documents"}: raise ValueError("Supply distinct actual read/write scopes with at least one supported read scope")
        return sorted(value)

    @field_validator("expires_at", mode="before")
    @classmethod
    def known_expiry(cls, value):
        if value is None: return None
        if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None: return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value): raise ValueError("Use actual timezone-aware issuer expiry")
        return value


def _credential(raw):
    if isinstance(raw, ProposifyIssuedTokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != FAMILY or raw.get("token_type") != "Bearer": raise ValueError("Select the authoritative Proposify issued Bearer family")
    if any(raw.get(k) is not None for k in ("api_key", "refresh_token", "client_secret", "scope", "base_url", "host", "headers", "instance_url")): raise ValueError("Use only this already-issued Proposify token contract")
    try: return ProposifyIssuedTokenCredential.model_validate(raw)
    except Exception: raise ValueError("Proposify token, account or actual grant shape is unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store):
        super().__init__(data)
        self.store, self.anchor = store, self.identity(store.current)
    @staticmethod
    def identity(row): return tuple(getattr(row, k) for k in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))
    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("Proposify current saved grant or authority changed") from None
    def __repr__(self): return "<Proposify current credential>"


def _op(value, title, category): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})
def _pick(name): return Field(..., title=name.replace("_", " ").title(), json_schema_extra={"x-resource-type": name, "x-dynamic-options": {"field_name": name, "allow_custom": True}})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class ProposifyProbeConfig(_Config):
    operation: Literal["check_connection"] = _op("check_connection", "Check Protected API Reachability", "Connection")


class ProposifyUsersConfig(_Config):
    operation: Literal["list_users"] = _op("list_users", "List Account User Metadata", "Users")
    include_personal_details: bool = Field(False, strict=True, title="Include User Names and Email", description="Default returns only numeric user ID and title. Listing account users never identifies the token's principal.")


class ProposifyLegacyTemplatesConfig(_Config):
    operation: Literal["list_legacy_templates"] = _op("list_legacy_templates", "List Legacy Numeric Template Metadata", "Templates")


class ProposifyV3TemplatesConfig(_Config):
    operation: Literal["list_v3_templates"] = _op("list_v3_templates", "List V3 UUID Template Metadata", "Templates")


class ProposifyV3DocumentsConfig(_Config):
    operation: Literal["list_v3_documents"] = _op("list_v3_documents", "List V3 Document Metadata", "Documents")


class _DocumentID(_Config):
    document_id: V3ID = _pick("document_id")
    @field_validator("document_id", mode="before")
    @classmethod
    def document(cls, value): return _uuid(value)


class _Name(_Config):
    name: str = Field(..., min_length=1, max_length=255, title="Document Name")
    @field_validator("name", mode="before")
    @classmethod
    def bounded_name(cls, value): return _text(value, 255)


class ProposifyGetV3DocumentConfig(_DocumentID):
    operation: Literal["get_v3_document"] = _op("get_v3_document", "Get Selected V3 Document Metadata", "Documents")


class ProposifyCreateDraftConfig(_Name):
    operation: Literal["create_draft_document_from_template"] = _op("create_draft_document_from_template", "Create V3 Draft from Selected Template", "Draft Documents")
    template_id: V3ID = _pick("template_id")
    new_document_id: V3ID | None = Field(None, title="Optional New V3 Document UUID", description="Optional documented id. It is not an idempotency guarantee; reconcile an ambiguous request before retrying.")
    @field_validator("template_id", "new_document_id", mode="before")
    @classmethod
    def uuids(cls, value): return None if value is None else _uuid(value)


class ProposifyRenameDraftConfig(_DocumentID, _Name):
    operation: Literal["rename_draft_document"] = _op("rename_draft_document", "Rename Editable V3 Draft", "Draft Documents")


class ProposifySoftDeleteDraftConfig(_DocumentID):
    operation: Literal["soft_delete_draft_document"] = _op("soft_delete_draft_document", "Soft Delete Editable V3 Draft", "Draft Documents")


ProposifyOperation = Annotated[Union[ProposifyProbeConfig, ProposifyUsersConfig, ProposifyLegacyTemplatesConfig, ProposifyV3TemplatesConfig, ProposifyV3DocumentsConfig, ProposifyGetV3DocumentConfig, ProposifyCreateDraftConfig, ProposifyRenameDraftConfig, ProposifySoftDeleteDraftConfig], Field(discriminator="operation")]


class ProposifyNodeConfig(NodeConfig[ProposifyOperation, ProposifyIssuedTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _rows(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or len(payload["data"]) > MAX_ROWS or any(not isinstance(row, dict) for row in payload["data"]): raise ValueError("Proposify bounded collection differs from its published envelope")
    if len({row.get("id") for row in payload["data"]}) != len(payload["data"]): raise ValueError("Duplicate Proposify object IDs")
    return payload["data"]


def _document(raw, credential):
    if not isinstance(raw, dict): raise ValueError()
    out = {"id": _uuid(raw.get("id"))}
    for name in ("name", "created_at", "updated_at"):
        if raw.get(name) is not None: out[name] = _text(raw[name], empty=True)
    if raw.get("status") is not None:
        if raw["status"] not in {"DRAFT", "LOST", "WON", "ACTIVE"}: raise ValueError()
        out["status"] = raw["status"]
    if raw.get("is_locked") is not None:
        if type(raw["is_locked"]) is not bool: raise ValueError()
        out["is_locked"] = raw["is_locked"]
    if raw.get("account") is not None:
        if not isinstance(raw["account"], dict) or type(raw["account"].get("id")) is not int: raise ValueError()
        out["account_id"] = _number(raw["account"]["id"])
    if credential.expected_account_id is not None and out.get("account_id") != credential.expected_account_id: raise ValueError("V3 object account differs from the expected resource account")
    return out


def _error(action, message, *, status=None, attempted=False, mutation=False):
    return {"status": "error", "action": action, "error": message, "executed": attempted,
        **({"http_status": status, "status_code": status} if status is not None else {}),
        **({"mutation_outcome_unknown": True} if mutation and (status is None or status in {200, 202, 204} or status >= 500) else {}),
        **({"_halt_downstream": True} if status not in {401, 403} else {})}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, action):
        self.raw, self.key, self.action = raw, _credential(raw), action
        self.attempted, self.mutation, self.status = False, False, None
    async def request(self, method, path, scope, *, body=None):
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw)
            if scope not in key.scopes or (key.expires_at is not None and key.expires_at <= datetime.now(timezone.utc)): raise ValueError("Actual Proposify scope or unexpired token is required")
            self.mutation = method != "GET"
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream(method, BASE_URL + path, json=body, headers={"Authorization": f"Bearer {key.access_token}", "Accept": "application/json", "Content-Type": "application/json"}) as response:
                    self.status = response.status_code
                    if self.status != {"GET": 200, "POST": 202, "PATCH": 200}[method]:
                        raise _ProviderError(_error(self.action, {401: "Proposify rejected this issued token; replace it", 403: "Proposify refused this scope or resource access", 422: "Proposify rejected this document contract", 429: "Proposify rate limit reached; no retry occurred"}.get(self.status, "Proposify refused this request; no retry occurred"), status=self.status, attempted=True, mutation=self.mutation))
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_BYTES: raise ValueError()
                        raw.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            # PATCH200 has no declared content schema. Bound/discard the actual
            # bytes, including empty or text responses; do not invent a body.
            if method == "PATCH": return None
            payload = json.loads(raw)
            if not isinstance(payload, dict): raise ValueError()
            return payload
        except _ProviderError: raise
        except (httpx.HTTPError, SSRFError): raise _ProviderError(_error(self.action, "Proposify transport outcome is unknown; no retry occurred", status=self.status, attempted=self.attempted, mutation=self.mutation)) from None


class ProposifyNode(WorkflowNode):
    integration_type = "automation-proposify"
    workflow_credential_refresh = True
    scope_registry = ScopeRegistry("proposify", {
        "list_users": ScopeRequirement(("read_users",)),
        "list_legacy_templates": ScopeRequirement(("read_templates",)),
        **{op: ScopeRequirement(("read_documents",)) for op in (
            "list_v3_templates", "list_v3_documents", "get_v3_document")},
        **{op: ScopeRequirement(("read_documents", "write_documents")) for op in (
            "create_draft_document_from_template", "rename_draft_document", "soft_delete_draft_document")},
    }, unmapped=("check_connection",))
    # The probe selects any held read scope at runtime. ScopeRequirement is a
    # conjunction and cannot describe these alternatives without over-requesting.
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Proposify API", proves="reachability")
    edit_examples = ["List V3 template metadata", "Create a draft from a selected UUID template", "Rename an editable draft without sending it"]
    @classmethod
    def get_config_model(cls): return ProposifyNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._load_current_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _load_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        _credential(credential_data)
        if not credential_id: return credential_data
        if organization_id is None and not workflow_id: organization_id = CURRENT_ORGANIZATION
        store = ProposifyCredentialsTableStore(pool, user_id, credential_id, credential_type=FAMILY, validate=_stored, organization_id=organization_id, workflow_id=workflow_id)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("Proposify saved issued grant is unavailable under current access") from None
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Proposify issued-token or actual grant shape is unsupported"}
        if validation_context is None: return {"valid": True, "provider_verified": False}
        await validation_context.revalidate()
        result = await validation_context.run_operation("check_connection")
        await validation_context.revalidate()
        if result.get("status") == "success" and result.get("reachability_verified") is True: return {"valid": True, "provider_verified": True}
        return {"valid": False if result.get("status_code") in {401, 403} else None, "error": result.get("error", "Proposify access could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            action = config.operation
            if action == "check_connection":
                order = ("read_documents", "read_users", "read_templates") if session.key.expected_account_id is not None else ("read_users", "read_templates", "read_documents")
                scope = next(s for s in order if s in session.key.scopes)
                path = {"read_users": "/user", "read_templates": "/template", "read_documents": "/v3/content/Document"}[scope]
                rows = _rows(await session.request("GET", path, scope))
                for row in rows:
                    _document(row, session.key) if scope == "read_documents" else _number(row.get("id"))
                out = {"data": [], "reachability_verified": True, "principal_identity_proven": False, "account_binding_verified": bool(rows) and scope == "read_documents" and session.key.expected_account_id is not None}
            elif action in {"list_users", "list_legacy_templates"}:
                users = action == "list_users"
                rows = _rows(await session.request("GET", "/user" if users else "/template", "read_users" if users else "read_templates"))
                data = []
                for row in rows:
                    item = {"id": _number(row.get("id"))}
                    names = (("title", "email", "first_name", "last_name") if config.include_personal_details else ("title",)) if users else ("name",)
                    for name in names:
                        if row.get(name) is not None: item[name] = _text(row[name], empty=True)
                    data.append(item)
                out = {"data": data, "id_namespace": "legacy_numeric", "pagination_documented": False}
            elif action in {"list_v3_documents", "list_v3_templates"}:
                kind = "Document" if action == "list_v3_documents" else "Template"
                rows = _rows(await session.request("GET", f"/v3/content/{kind}", "read_documents"))
                out = {"data": [_document(row, session.key) for row in rows], "id_namespace": "v3_uuid", "pagination_documented": False}
            elif action == "get_v3_document":
                row = _document(await session.request("GET", f"/v3/document/{config.document_id}", "read_documents"), session.key)
                if row["id"] != config.document_id: raise ValueError("Selected V3 document differs from returned parent")
                out = {"data": row, "id_namespace": "v3_uuid"}
            else:
                if session.key.expected_account_id is None or not {"read_documents", "write_documents"} <= set(session.key.scopes): raise ValueError("Draft mutations require an explicit expected account and actual read/write document scopes")
                if action == "create_draft_document_from_template":
                    templates = [_document(row, session.key) for row in _rows(await session.request("GET", "/v3/content/Template", "read_documents"))]
                    if len([row for row in templates if row["id"] == config.template_id]) != 1: raise ValueError("Selected UUID template is not available in the expected account")
                    body = {"name": config.name, "fromTemplateId": config.template_id, "content": {"status": "DRAFT"}}
                    if config.new_document_id is not None: body["id"] = config.new_document_id
                    reply = await session.request("POST", "/v3/document", "write_documents", body=body)
                    acknowledgment = {"eventId": _uuid(reply.get("eventId")), "contentId": _uuid(reply.get("contentId"))}
                    if config.new_document_id is not None and acknowledgment["contentId"] != config.new_document_id: raise ValueError()
                    out = {"data": acknowledgment, "accepted": True, "pending": True, "document_state_confirmed": False}
                else:
                    row = _document(await session.request("GET", f"/v3/document/{config.document_id}", "read_documents"), session.key)
                    if row["id"] != config.document_id or row.get("status") != "DRAFT" or row.get("is_locked") is not False: raise ValueError("Selected document is not a verified editable draft in the expected account")
                    body = {"name": config.name} if action == "rename_draft_document" else {"is_deleted": True}
                    await session.request("PATCH", f"/v3/document/{config.document_id}", "write_documents", body=body)
                    out = {"data": None, "operation_acknowledged": True, "document_state_confirmed": False, "selected_document_id": config.document_id}
                    if action == "soft_delete_draft_document": out.update(soft_delete_acknowledged=True, deletion_verified=False)
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError()
            return {"status": "success", "action": action, "executed": True, "http_status": session.status, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, StopIteration): return _error(config.operation, "Proposify current authority, selected account/draft or bounded response could not be established; no retry occurred", status=session.status, attempted=session.attempted, mutation=session.mutation)
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in {"document_id", "template_id"}: raise ValueError("Unsupported Proposify selector")
        if page_token is not None: raise ValueError("Proposify publishes no paging parameter for this V3 route")
        if search is not None: _text(search, 100, empty=True)
        model = ProposifyV3DocumentsConfig if field_name == "document_id" else ProposifyV3TemplatesConfig
        result = await cls._dispatch(credential_data, model())
        if result["status"] != "success": raise ValueError(result["error"])
        options = [{"value": row["id"], "label": row.get("name") or row["id"]} for row in result["data"]]
        if search: options = [row for row in options if search.casefold() in row["label"].casefold()]
        return {"options": options, "has_more": False, "next_page_token": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        credential = await self._load_current_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
