"""Oracle Responsys v1.3 account and campaign inventory plus metadata management.

Closed native routes exclude recipients, consent, delivery, launches and programs.
Issued token/endpoint pairs use staging credential resolution and persistence.
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, WrapValidator, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client, normalize_provider_https_origin

PREFIX = "/rest/api/v1.3"
FAMILIES = ("responsys_auth_token", "responsys_password")
LOGIN_ORIGINS = ("https://login2.responsys.net", "https://login5.responsys.net",
                 "https://login.rsys8.net", "https://login.rsys9.net")
_REFERENCE = re.compile(r"\{\{.*\}\}|\$\(", re.S)
_PRIVATE = ContextVar("responsys_private_request", default=False)
MAX_BYTES, MAX_ROWS = 4 * 1024 * 1024, 1000


class ResponsysError(ValueError):
    def __init__(self, message, *, http_status=None, uncertain=False):
        super().__init__(message)
        self.http_status = http_status
        self.uncertain = uncertain


class _Privacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Responsys transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_PRIVACY = _Privacy()


def _ref(value):
    return isinstance(value, str) and bool(_REFERENCE.search(value))


def _secret(value):
    if not isinstance(value, str):
        raise ValueError("Responsys credentials must be literal text.")
    text = clean_secret(value, field_name="Responsys credential")
    if not text or _ref(text) or len(text) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in text):
        raise ValueError("Paste a literal credential without spaces or control characters.")
    return text


def _password(value):
    if not isinstance(value, str):
        raise ValueError("Responsys passwords must be literal text.")
    text = clean_secret(value, field_name="Responsys password")
    if not text or _ref(text) or len(text) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in text):
        raise ValueError("Paste a literal Responsys password without control characters.")
    return text


def _endpoint(value, *, login=False):
    if not isinstance(value, str) or _ref(value):
        raise ValueError("Supply the literal HTTPS origin issued by Oracle.")
    candidate = value.strip().rstrip("/")
    if login and candidate in LOGIN_ORIGINS:
        return candidate
    parsed = urlsplit(candidate if "://" in candidate else "https://" + candidate)
    host = parsed.hostname or ""
    domains = ("responsys.net", "rsys8.net", "rsys9.net", "responsys.ocs.oraclecloud.com")
    domain = next((d for d in domains if host.lower().endswith("." + d)), None)
    if not domain:
        raise ValueError("The endpoint must be an Oracle Responsys HTTPS origin.")
    try:
        origin = normalize_provider_https_origin(candidate, domain, field_name="Responsys endpoint")
    except ValueError:
        raise ValueError("Use an issued Responsys origin without a path, port, query or user information.") from None
    label = urlsplit(origin).hostname[:-(len(domain) + 1)]
    if login and (domain != "responsys.ocs.oraclecloud.com" or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,57}-api", label)):
        raise ValueError("Use login2, login5, login.rsys8, login.rsys9 or your exact global-routing REST login origin.")
    if not login and not (re.fullmatch(r"[a-z0-9][a-z0-9-]{0,57}-api", label)
                          or re.fullmatch(r"api-[a-z0-9][a-z0-9-]{0,57}", label)):
        raise ValueError("Paste the account REST endPoint returned by Oracle, not a login, SOAP or AFTM host.")
    return origin


def _name(value, handler):
    if _ref(value):
        return value
    value = handler(value)
    if not value or len(value) > 100 or not re.fullmatch(r"[A-Za-z0-9 !\-=@_\[\]{}]+", value):
        raise ValueError("Resource names require 1–100 supported characters, without URL path syntax.")
    return value


Name = Annotated[str, WrapValidator(_name)]
Number = Annotated[int, WrapValidator(lambda v, h: v if _ref(v) else h(v))]


class _Credential(BaseModel):
    account_endpoint: str = Field(..., title="Issued Account Endpoint", description="The exact REST endPoint returned with this authToken; login and AFTM hosts are not account REST origins.")
    auth_token_expires_at: float | None = Field(None, json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(extra="allow")
    _origin = field_validator("account_endpoint", mode="before")(_endpoint)


class ResponsysAuthTokenCredential(_Credential):
    credential_type: Literal["responsys_auth_token"] = Field("responsys_auth_token", json_schema_extra={"ui:hidden": True})
    auth_token: str = Field(..., title="Auth Token", description="Raw issued Responsys authToken, without Bearer prefix. Tokens expire after two hours.", json_schema_extra={"ui:widget": "password"})
    _token = field_validator("auth_token", mode="before")(_secret)
    model_config = ConfigDict(extra="allow", title="Responsys Auth Token", json_schema_extra={
        "x-credential-url": "https://docs.oracle.com/en/cloud/saas/marketing/responsys-develop/API/GetStarted/Authentication/authenticating.htm",
        "x-credential-instructions": "Supply an existing issued token and its exact account endpoint. This is not an IDCS OAuth token or a login cookie. Expired tokens require a newly issued pair."
    })


class ResponsysPasswordCredential(_Credential):
    credential_type: Literal["responsys_password"] = Field("responsys_password", json_schema_extra={"ui:hidden": True})
    login_origin: str = Field(..., title="Login Origin", description="The exact Oracle login2/login5/login.rsys8/login.rsys9 or account global-routing REST origin.")
    user_name: str = Field(..., title="API Username", min_length=1, max_length=200)
    password: str = Field(..., title="Password", json_schema_extra={"ui:widget": "password"})
    auth_token: str | None = Field(None, json_schema_extra={"ui:hidden": True})
    _password_validator = field_validator("password", mode="before")(_password)
    @field_validator("auth_token", mode="before")
    @classmethod
    def token(cls, value):
        return None if value is None else _secret(value)
    @field_validator("login_origin", mode="before")
    @classmethod
    def origin(cls, value):
        return _endpoint(value, login=True)
    @field_validator("user_name", mode="before")
    @classmethod
    def username(cls, value):
        if not isinstance(value, str) or _ref(value) or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Supply a literal Responsys API username.")
        return value.strip()
    model_config = ConfigDict(extra="allow", title="Responsys API Password", json_schema_extra={
        "x-credential-url": "https://docs.oracle.com/en/cloud/saas/marketing/responsys-develop/API/GetStarted/Authentication/authenticating.htm",
        "x-credential-instructions": "Supply your provisioned API username and password, Oracle login origin and previously issued account endpoint. The issued token renews automatically."
    })


Credential = Union[ResponsysAuthTokenCredential, ResponsysPasswordCredential]
CREDENTIAL = TypeAdapter(Credential)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")
    @model_validator(mode="before")
    @classmethod
    def trim(cls, data):
        return {k: v.strip() if isinstance(v, str) and k != "operation" else v for k, v in data.items()} if isinstance(data, dict) else data


class _Page(_Base):
    limit: Number = Field(200, ge=1, le=200)
    offset: Number = Field(0, ge=0, le=1000000)


class _Folder(_Base):
    folder_name: Name = Field(..., title="Folder Name", json_schema_extra={"x-resource-type": "responsys_folder_name"})


class _FolderPage(_Folder, _Page):
    pass


class _List(_Base):
    list_name: Name = Field(..., json_schema_extra={"x-resource-type": "responsys_profile_list_name"})


class _Campaign(_Base):
    campaign_name: Name = Field(..., json_schema_extra={"x-resource-type": "responsys_campaign_name"})


class _CampaignPage(_Page):
    campaign_type: Literal["email", "push", "sms", "mms", "pushiocampaign"] = Field("email", description="Metadata only; never launches or sends.")


class _Table(_Folder):
    table_name: Name = Field(..., json_schema_extra={"x-resource-type": "responsys_supplemental_table_name"})


class _TableFields(_Table):
    field_type: Literal["all", "pk"] = Field("all", description="ft=all or ft=pk.")


class _Fields(_Base):
    fields_json: str = Field(..., max_length=20000, title="Field Definitions", description='JSON array of fieldName/fieldType objects. Definitions only; no recipient values.', json_schema_extra={"ui:widget": "textarea"})


class _CreateList(_Folder, _List, _Fields):
    description: str | None = Field(None, max_length=1000)
    brand_name: Name | None = Field(None, description="Existing brand context for a multi-brand account.")


class _CreateTable(_Table, _Fields):
    primary_keys: list[str] = Field(..., min_length=1, max_length=10, json_schema_extra={"ui:widget": "list"})


class _UpdateTable(_Table):
    destination_folder_name: Name = Field(..., description="Existing destination folder.")
    destination_table_name: Name = Field(..., description="The documented replacement tableName; no field or member change.")


class _Field(BaseModel):
    fieldName: str = Field(..., pattern=r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
    fieldType: Literal["CHAR", "STR25", "STR100", "STR500", "STR4000", "NUMBER", "INTEGER", "TIMESTAMP"]
    model_config = ConfigDict(extra="forbid")


class _TableField(_Field):
    dataExtractionKey: bool = False


def _definitions(value, *, table=False):
    try:
        data = json.loads(value)
        model = TypeAdapter(list[_TableField] if table else list[_Field])
        result = model.validate_python(data)
    except (ValueError, TypeError):
        raise ResponsysError("Provide a JSON array of supported field definitions, without records or extra keys.") from None
    if not 1 <= len(result) <= (40 if table else 5) or len({f.fieldName for f in result}) != len(result):
        raise ResponsysError("Provide distinct field definitions within the bounded field count.")
    return [f.model_dump() for f in result]

class ResponsysGetAccountSettingsConfig(_Base):
    operation: Literal["get_account_settings"] = Field("get_account_settings", json_schema_extra={"const": "get_account_settings", "ui:hidden": True, "x-display-name": "Get Account Settings", "x-category": "Account", "x-is-trigger": False})

class ResponsysGetAccountEndpointConfig(_Base):
    operation: Literal["get_account_endpoint"] = Field("get_account_endpoint", json_schema_extra={"const": "get_account_endpoint", "ui:hidden": True, "x-display-name": "Get Account Endpoint", "x-category": "Account", "x-is-trigger": False})

class ResponsysRefreshAuthTokenConfig(_Base):
    operation: Literal["refresh_auth_token"] = Field("refresh_auth_token", json_schema_extra={"const": "refresh_auth_token", "ui:hidden": True, "x-display-name": "Refresh Auth Token", "x-category": "Account", "x-is-trigger": False})

class ResponsysListFoldersConfig(_Page):
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"const": "list_folders", "ui:hidden": True, "x-display-name": "List Folders", "x-category": "Folders", "x-is-trigger": False})

class ResponsysGetFolderContentConfig(_FolderPage):
    operation: Literal["get_folder_content"] = Field("get_folder_content", json_schema_extra={"const": "get_folder_content", "ui:hidden": True, "x-display-name": "Get Folder Content", "x-category": "Folders", "x-is-trigger": False})

class ResponsysCreateFolderConfig(_Folder):
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"const": "create_folder", "ui:hidden": True, "x-display-name": "Create Folder", "x-category": "Folders", "x-is-trigger": False})

class ResponsysListProfileListsConfig(_Base):
    operation: Literal["list_profile_lists"] = Field("list_profile_lists", json_schema_extra={"const": "list_profile_lists", "ui:hidden": True, "x-display-name": "List Profile Lists", "x-category": "Profile Lists", "x-is-trigger": False})

class ResponsysGetProfileListFieldsConfig(_List):
    operation: Literal["get_profile_list_fields"] = Field("get_profile_list_fields", json_schema_extra={"const": "get_profile_list_fields", "ui:hidden": True, "x-display-name": "Get Profile List Fields", "x-category": "Profile Lists", "x-is-trigger": False})

class ResponsysCreateProfileListConfig(_CreateList):
    operation: Literal["create_profile_list"] = Field("create_profile_list", json_schema_extra={"const": "create_profile_list", "ui:hidden": True, "x-display-name": "Create Empty Profile List", "x-category": "Profile Lists", "x-is-trigger": False})

class ResponsysListSupplementalTablesConfig(_Page):
    operation: Literal["list_supplemental_tables"] = Field("list_supplemental_tables", json_schema_extra={"const": "list_supplemental_tables", "ui:hidden": True, "x-display-name": "List Supplemental Tables", "x-category": "Tables", "x-is-trigger": False})

class ResponsysGetSupplementalTableFieldsConfig(_TableFields):
    operation: Literal["get_supplemental_table_fields"] = Field("get_supplemental_table_fields", json_schema_extra={"const": "get_supplemental_table_fields", "ui:hidden": True, "x-display-name": "Get Supplemental Table Fields", "x-category": "Tables", "x-is-trigger": False})

class ResponsysCreateSupplementalTableConfig(_CreateTable):
    operation: Literal["create_supplemental_table"] = Field("create_supplemental_table", json_schema_extra={"const": "create_supplemental_table", "ui:hidden": True, "x-display-name": "Create Empty Supplemental Table", "x-category": "Tables", "x-is-trigger": False})

class ResponsysUpdateSupplementalTableConfig(_UpdateTable):
    operation: Literal["update_supplemental_table"] = Field("update_supplemental_table", json_schema_extra={"const": "update_supplemental_table", "ui:hidden": True, "x-display-name": "Rename or Move Supplemental Table", "x-category": "Tables", "x-is-trigger": False})

class ResponsysDeleteSupplementalTableConfig(_Table):
    operation: Literal["delete_supplemental_table"] = Field("delete_supplemental_table", json_schema_extra={"const": "delete_supplemental_table", "ui:hidden": True, "x-display-name": "Delete Supplemental Table", "x-category": "Tables", "x-is-trigger": False})

class ResponsysListCampaignsConfig(_CampaignPage):
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"const": "list_campaigns", "ui:hidden": True, "x-display-name": "List Campaign Metadata", "x-category": "Campaigns", "x-is-trigger": False})

class ResponsysGetCampaignConfig(_Campaign):
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"const": "get_campaign", "ui:hidden": True, "x-display-name": "Get Email Campaign Metadata", "x-category": "Campaigns", "x-is-trigger": False})

class ResponsysGetCampaignOrganizationsConfig(_Campaign):
    operation: Literal["get_campaign_organizations"] = Field("get_campaign_organizations", json_schema_extra={"const": "get_campaign_organizations", "ui:hidden": True, "x-display-name": "Get Campaign Organizations", "x-category": "Campaigns", "x-is-trigger": False})

class ResponsysListOrganizationsConfig(_Base):
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"const": "list_organizations", "ui:hidden": True, "x-display-name": "List Organizations", "x-category": "Organizations", "x-is-trigger": False})

Config = Annotated[Union[ResponsysGetAccountSettingsConfig, ResponsysGetAccountEndpointConfig, ResponsysRefreshAuthTokenConfig, ResponsysListFoldersConfig, ResponsysGetFolderContentConfig, ResponsysCreateFolderConfig, ResponsysListProfileListsConfig, ResponsysGetProfileListFieldsConfig, ResponsysCreateProfileListConfig, ResponsysListSupplementalTablesConfig, ResponsysGetSupplementalTableFieldsConfig, ResponsysCreateSupplementalTableConfig, ResponsysUpdateSupplementalTableConfig, ResponsysDeleteSupplementalTableConfig, ResponsysListCampaignsConfig, ResponsysGetCampaignConfig, ResponsysGetCampaignOrganizationsConfig, ResponsysListOrganizationsConfig], Field(discriminator="operation")]


class ResponsysNodeConfig(NodeConfig[Config, Credential]):
    pass


def _raw_guard(data):
    if not isinstance(data, dict):
        raise ValueError("Responsys node configuration must be an object.")
    creds = data.get("credentials")
    chosen, mapping = data.get("credential_id"), data.get("credentialIds") or {}
    if chosen is not None and (not isinstance(chosen, str) or not chosen):
        raise ValueError("The selected credential ID must be literal text.")
    if not isinstance(mapping, dict) or any(k not in FAMILIES or not isinstance(v, str) or not v for k, v in mapping.items()):
        raise ValueError("Select only a native Responsys credential.")
    if len(set(mapping.values())) > 1 or (chosen and mapping and chosen not in mapping.values()):
        raise ValueError("Select one unambiguous Responsys credential.")
    if isinstance(creds, dict):
        family = creds.get("credential_type")
        stored = bool(chosen or mapping) or any(creds.get(k) is not None for k in ("id", "token_version", "updated_at"))
        if (stored or family is not None) and family not in FAMILIES:
            raise ValueError("Stored Responsys credentials require an explicit native family.")
        if mapping and family not in mapping:
            raise ValueError("The selected Responsys attachment family does not match.")
        if any(creds.get(k) is not None for k in ("id", "token_version", "updated_at")) and not (chosen or mapping):
            raise ValueError("Stored Responsys credentials require a selected row ID.")
        for k in ("auth_token", "password", "user_name", "login_origin", "account_endpoint"):
            if k in creds and creds[k] is not None and not isinstance(creds[k], str):
                raise ValueError("Responsys credential values must be literal text.")
    cfg = data.get("config", data)
    if isinstance(cfg, dict):
        for k in ("folder_name", "list_name", "table_name", "campaign_name", "destination_folder_name", "destination_table_name"):
            if cfg.get(k) is not None and not isinstance(cfg[k], str):
                raise ValueError("Responsys resource names must be text before configuration shaping.")
        if any(isinstance(cfg.get(k), bool) for k in ("offset", "limit")):
            raise ValueError("Responsys pagination cannot be boolean.")


def _chosen(data):
    _raw_guard(data)
    return data.get("credential_id") or next(iter((data.get("credentialIds") or {}).values()), None)


def _unresolved(value):
    if isinstance(value, str):
        return _ref(value)
    if isinstance(value, (dict, list)):
        return any(_unresolved(v) for v in (value.values() if isinstance(value, dict) else value))
    return False


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,30}", str(value)):
        raise ResponsysError("Responsys returned an invalid metadata ID.")
    return str(value)


def _fields(rows):
    if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(r, dict) for r in rows):
        raise ResponsysError("Responsys returned invalid field metadata.")
    result = []
    for row in rows:
        if not isinstance(row.get("fieldName"), str) or not isinstance(row.get("fieldType"), str):
            raise ResponsysError("Responsys returned invalid field metadata.")
        result.append({k: row[k] for k in ("fieldName", "fieldType")})
    return result


class ResponsysNode(WorkflowNode):
    integration_type = "automation-responsys"
    credential_provider_labels = {"responsys": "Oracle Responsys"}
    connection_evidence = ConnectionEvidence(
        operation="get_account_settings", identity_operation="get_account_settings",
        noun="account", label_keys=("name",), identity_keys=("name",), proves="account")
    scope_registry = ScopeRegistry("Oracle Responsys", {
        op: ScopeRequirement(credential_types=FAMILIES, note="Existing Responsys API user, account entitlement and Web Services role access.")
        for op in ["get_account_settings","get_account_endpoint","refresh_auth_token","list_folders","get_folder_content","create_folder","list_profile_lists","get_profile_list_fields","create_profile_list","list_supplemental_tables","get_supplemental_table_fields","create_supplemental_table","update_supplemental_table","delete_supplemental_table","list_campaigns","get_campaign","get_campaign_organizations","list_organizations"]
    })

    @classmethod
    def get_config_model(cls):
        return ResponsysNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _raw_guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    def _context(self):
        return (self.user_id, self.organization_id, self.workflow_id, _chosen(self.node_data),
                json.dumps(self.node_data.get("config", {}), sort_keys=True, default=str),
                json.dumps(self.node_data.get("credentials", {}), sort_keys=True, default=str),
                self.config.config.model_dump(mode="json"))

    async def run(self, inputs):
        cid = _chosen(self.node_data)
        if cid:
            self.node_data["credential_id"] = cid
        self._admitted = self._context()
        return await super().run(inputs)

    def _check_context(self):
        if getattr(self, "_admitted", self._context()) != self._context() or getattr(self, "_executing", self._context()) != self._context():
            raise ResponsysError("Responsys caller, selected credential or configured arguments changed; run the configured operation again.")

    @staticmethod
    def _material(credential):
        return (credential.credential_type, credential.account_endpoint,
                getattr(credential, "login_origin", None), getattr(credential, "user_name", None),
                getattr(credential, "password", None), credential.auth_token, credential.auth_token_expires_at)

    async def _current(self, *, conn=None):
        # Execution credentials have already passed staging's shared resolver,
        # including workflow-owner fallback. Do not add a second access policy.
        self._check_context()
        credential = getattr(self, "_unsaved", None) or self.config.credentials
        if credential is None:
            raise ResponsysError("Connect a Responsys credential.")
        return credential, ("resolved", self._material(credential)), None, self.user_id

    async def _guard(self, *, conn=None):
        credential, binding, row, actor = await self._current(conn=conn)
        if binding != self._binding:
            raise ResponsysError("Responsys current credential, endpoint pair or access policy changed during this operation.")
        return credential, row, actor

    async def _request(self, method, path, *, origin=None, token=None, params=None, body=None, form=None, auth=False, conn=None):
        credential, _, _ = await self._guard(conn=conn)
        origin = origin or credential.account_endpoint
        if auth:
            if path != PREFIX + "/auth/token" or origin not in (credential.account_endpoint, getattr(credential, "login_origin", None)):
                raise ResponsysError("Responsys authentication endpoint does not match the selected credential.")
        elif not path.startswith(PREFIX + "/") or origin != credential.account_endpoint:
            raise ResponsysError("Responsys metadata route is outside the selected account.")
        for name in {"httpx", "httpcore", "httpcore.http11", "httpcore.http2", "httpcore.connection", "httpcore.connection_pool", *logging.Logger.manager.loggerDict}:
            if name in ("httpx", "httpcore") or name.startswith(("httpx.", "httpcore.")):
                logging.getLogger(name).addFilter(_PRIVACY)
        private = _PRIVATE.set(True)
        write = method != "GET"
        try:
            async with guarded_async_client(timeout=25, follow_redirects=False, trust_env=False) as client:
                await self._guard(conn=conn)
                async with client.stream(method, origin + path, params=params, json=body, data=form,
                        headers={"Accept": "application/json", **({"Authorization": token} if token else {})}) as response:
                    status, buffer = response.status_code, bytearray()
                    async for part in response.aiter_bytes():
                        buffer.extend(part)
                        if len(buffer) > MAX_BYTES:
                            raise ResponsysError("Responsys response exceeded the bounded size." + (" Outcome is unknown; verify before repeating." if write else ""), uncertain=write)
        except httpx.HTTPError:
            raise ResponsysError("Responsys transport failed." + (" Outcome is unknown; verify before repeating." if write else ""), uncertain=write) from None
        finally:
            _PRIVATE.reset(private)
        try:
            await self._guard(conn=conn)
        except ResponsysError:
            raise ResponsysError("Responsys authorization changed before accepting the response." + (" Outcome is unknown; verify before repeating." if write else ""), uncertain=write) from None
        try:
            data = json.loads(buffer)
        except (ValueError, UnicodeError):
            uncertain = write and (200 <= status < 400 or status >= 500)
            raise ResponsysError("Responsys returned an unexpected response." + (" Outcome is unknown; verify before repeating." if uncertain else ""), http_status=status, uncertain=uncertain) from None
        if not auth:
            secrets = [v for v in (credential.auth_token, getattr(credential, "password", None)) if v]
            def reflected(value):
                if isinstance(value, str):
                    return any(s in value for s in secrets)
                if isinstance(value, dict):
                    return any(reflected(k) or reflected(v) for k, v in value.items())
                return any(reflected(v) for v in value) if isinstance(value, list) else False
            if reflected(data):
                raise ResponsysError("Responsys returned authentication material; the response was withheld." + (" Outcome is unknown; verify before repeating." if write else ""), uncertain=write)
        error = data.get("errorCode") if isinstance(data, dict) else None
        if not 200 <= status < 300 or error:
            uncertain = write and (300 <= status < 400 or status >= 500)
            message = {"INSUFFICIENT_ACCESS": "Responsys permission denied; check Web Services role permissions and organizational access.",
                       "API_DISABLED_FOR_USER": "Responsys API entitlement does not allow this operation.",
                       "INVALID_TOKEN": "Responsys rejected the issued token; reconnect with a new token/endpoint pair.",
                       "TOKEN_EXPIRED": "Responsys token expired; reconnect with a new issued pair."}.get(error)
            if not message:
                message = {401: "Responsys rejected this request; check the issued pair, API entitlement and role access.",
                           403: "Responsys permissions denied this operation.",
                           404: "Responsys resource was not found in this account.",
                           429: "Responsys request limit reached; retry later."}.get(status, "Responsys request failed.")
            raise ResponsysError(message + (" Outcome is unknown; verify before repeating." if uncertain else ""), http_status=status, uncertain=uncertain)
        if isinstance(data, dict) and (data.get("success") is False or data.get("status") is False):
            raise ResponsysError("Responsys rejected the metadata operation.", http_status=status)
        return data

    async def _successor(self, *, refresh):
        from utils.credential_loader import load_credential
        from utils.credentials import update_credential_data_detailed

        current, _, _ = await self._guard()
        cid = _chosen(self.node_data)
        snapshot = None
        if cid:
            # Use staging's canonical loader for the versioned refresh write.
            snapshot = await load_credential(None, self.user_id, cid, raise_on_error=True)
            if snapshot is None:
                raise ResponsysError("The saved Responsys credential is unavailable for refresh; reconnect it.")
            loaded = CREDENTIAL.validate_python(snapshot)
            if self._material(loaded) != self._material(current):
                raise ResponsysError("The saved Responsys pair changed; run the operation again.")
        if refresh:
            if not current.auth_token:
                raise ResponsysError("An existing valid authToken is required for token refresh.")
            origin, form, token = current.account_endpoint, {"auth_type": "token"}, current.auth_token
        else:
            if not isinstance(current, ResponsysPasswordCredential):
                raise ResponsysError("Expired supplied tokens need a newly issued pair.")
            origin, form, token = current.login_origin, {"user_name": current.user_name, "password": current.password, "auth_type": "password"}, None
        response = await self._request("POST", PREFIX + "/auth/token", origin=origin, token=token, form=form, auth=True)
        try:
            if not isinstance(response, dict) or isinstance(response.get("issuedAt"), bool) or not isinstance(response.get("issuedAt"), (int, str)):
                raise ValueError()
            successor = _secret(response.get("authToken"))
            endpoint = _endpoint(response.get("endPoint"))
            if endpoint != current.account_endpoint or (refresh and successor == current.auth_token):
                raise ValueError()
            updated = CREDENTIAL.validate_python({**current.model_dump(), "auth_token": successor,
                "auth_token_expires_at": time.time() + 7140, "issued_at": response["issuedAt"]})
        except (ValueError, TypeError):
            raise ResponsysError("Responsys returned an invalid or mismatched successor pair; reconnect. No successor was persisted.", uncertain=True) from None
        await self._guard()
        if cid:
            version = snapshot.get("token_version")
            if not isinstance(version, int) or isinstance(version, bool):
                raise ResponsysError("The saved token version is unavailable; successor persistence was refused.", uncertain=True)
            count, _ = await update_credential_data_detailed(
                credential_id=cid, user_id=self.user_id,
                new_data=updated.model_dump(exclude={"id", "token_version", "updated_at"}),
                expected_token_version=version,
                expected_credential_type=current.credential_type,
            )
            if count != 1:
                raise ResponsysError("Responsys successor persistence lost its current-row guard; reconnect before retrying.", uncertain=True)
        self._unsaved = updated
        self._binding = ("resolved", self._material(updated))
        return updated

    async def _verify_pair(self):
        credential, _, _ = await self._guard()
        body = await self._request("GET", PREFIX + "/settings/account/endpoint", token=credential.auth_token)
        if not isinstance(body, dict) or body.get("apiType") != "rest":
            raise ResponsysError("Responsys did not return the documented REST account endpoint.")
        try:
            endpoint = _endpoint(body.get("endPoint"))
        except ValueError:
            raise ResponsysError("Responsys returned an invalid account endpoint.") from None
        if endpoint != credential.account_endpoint:
            raise ResponsysError("The token is bound to a different issued account endpoint.")
        return body

    async def _get(self, path, params=None):
        credential, _, _ = await self._guard()
        return await self._request("GET", PREFIX + path, token=credential.auth_token, params=params)

    async def _write(self, method, path, body=None):
        credential, _, _ = await self._guard()
        return await self._request(method, PREFIX + path, token=credential.auth_token, body=body)

    def _page(self, body, key, path):
        if key == "campaigns" and isinstance(body, dict) and "campaigns" not in body and "items" in body:
            key = "items"
        if not isinstance(body, dict) or not isinstance(body.get(key), list) or len(body[key]) > self.config.config.limit:
            raise ResponsysError("Responsys returned an invalid bounded metadata page.")
        links = body.get("links", [])
        if not isinstance(links, list):
            raise ResponsysError("Responsys returned invalid pagination.")
        next_offset = None
        for link in links:
            if not isinstance(link, dict):
                raise ResponsysError("Responsys returned invalid pagination.")
            if link.get("rel") != "next":
                continue
            href = link.get("href")
            if not isinstance(href, str) or len(href) > 4096 or link.get("method", "GET") != "GET":
                raise ResponsysError("Responsys returned an invalid next-page reference.")
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc or parsed.path != PREFIX + path or parsed.fragment:
                raise ResponsysError("Responsys next-page reference is outside the exact native route.")
            query = parse_qs(parsed.query, strict_parsing=True)
            if set(query) - {"offset", "limit", "type"} or len(query.get("offset", [])) != 1 or not query["offset"][0].isdigit():
                raise ResponsysError("Responsys returned an invalid next offset.")
            offset = int(query["offset"][0])
            if offset <= self.config.config.offset or offset > 1000000 or next_offset is not None:
                raise ResponsysError("Responsys next offset is repeated or outside the bound.")
            next_offset = offset
        return body[key], next_offset

    @staticmethod
    def _rows(body):
        # Both the reference's items envelope and developer-guide array are documented.
        rows = body.get("items") if isinstance(body, dict) else body
        if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(r, dict) for r in rows):
            raise ResponsysError("Responsys returned an invalid metadata collection.")
        return rows

    async def _folder(self, name):
        for offset in range(0, 2000, 200):
            body = await self._get("/folders", {"limit": 200, "offset": offset})
            rows = body.get("folders") if isinstance(body, dict) else None
            if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(r, dict) for r in rows):
                raise ResponsysError("Responsys returned an invalid folder inventory.")
            matching = [r for r in rows if r.get("name") == name]
            if len(matching) > 1:
                raise ResponsysError("Responsys folder name is ambiguous.")
            if matching:
                return _id(matching[0].get("id"))
            if len(rows) < 200:
                raise ResponsysError("The configured folder was not found in the bounded account inventory.")
        raise ResponsysError("Folder inventory exceeded the bound; no metadata write was attempted.")

    async def execute(self, inputs):
        self._check_context()
        config = self.config.config
        if _unresolved(config.model_dump()):
            raise ResponsysError("Resolve Responsys resource references before execution.")
        self._executing = self._context()
        credential, self._binding, _, _ = await self._current()
        self.scope_registry.enforce_credential_type(config.operation, credential.credential_type)
        expiry = credential.auth_token_expires_at
        if not credential.auth_token or (expiry is not None and expiry <= time.time()):
            credential = await self._successor(refresh=False)
        elif config.operation == "refresh_auth_token" or (expiry is not None and expiry - time.time() < 300):
            credential = await self._successor(refresh=True)
        await self._verify_pair()
        op = config.operation
        if op == "refresh_auth_token":
            data = {"refreshed": True, "persisted": bool(_chosen(self.node_data))}
        elif op == "get_account_endpoint":
            data = {"api_type": "rest", "endpoint_matches": True}
        elif op == "get_account_settings":
            body = await self._get("/settings/account")
            if not isinstance(body, dict) or not isinstance(body.get("name"), str) or not body["name"]:
                raise ResponsysError("Responsys did not return the documented account name.")
            try:
                matches = _endpoint(body.get("endpoint")) == credential.account_endpoint
            except ValueError:
                matches = False
            if not matches:
                raise ResponsysError("Responsys account settings do not match the issued endpoint.")
            data = {"name": body["name"]}
        elif op in ("list_folders", "get_folder_content", "list_campaigns"):
            if op == "list_folders":
                path, key = "/folders", "folders"
            elif op == "get_folder_content":
                folder_id = await self._folder(config.folder_name)
                path, key = "/folders/" + quote(config.folder_name, safe="") + "/content", "riObjects"
            else:
                path, key = "/campaigns", "campaigns"
            params = {"offset": config.offset, "limit": config.limit}
            if op == "list_campaigns":
                params["type"] = config.campaign_type
            body = await self._get(path, params)
            rows, next_offset = self._page(body, key, path)
            safe = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ResponsysError("Responsys returned invalid inventory metadata.")
                if op == "get_folder_content" and _id(row.get("folderId")) != folder_id:
                    raise ResponsysError("Responsys returned a foreign folder object.")
                fields = ("id", "name", "status", "subType", "objectType", "type", "folderName", "folderId", "campaignStatus", "purpose", "listName")
                safe.append({k: _id(row[k]) if k in ("id", "folderId") else row[k] for k in fields if k in row and isinstance(row[k], (str, int, bool))})
            data = {"items": safe, "offset": config.offset, "next_offset": next_offset, "has_more": next_offset is not None}
        elif op == "create_folder":
            body = await self._write("POST", "/folders", {"folderName": config.folder_name})
            if not isinstance(body, dict) or body.get("success") is not True:
                raise ResponsysError("Responsys did not acknowledge folder creation; read back before repeating.", uncertain=True)
            try:
                data = {"folder_id": _id(body.get("folderId")), "folder_name": config.folder_name, "accepted": True, "readback_required": True}
            except ResponsysError:
                raise ResponsysError("Responsys folder acknowledgement lacked a valid ID; read back before repeating.", uncertain=True) from None
        elif op in ("list_profile_lists", "list_supplemental_tables"):
            path = "/lists" if op == "list_profile_lists" else "/suppData"
            params = {"limit": config.limit, "offset": config.offset} if op == "list_supplemental_tables" else None
            rows = self._rows(await self._get(path, params))
            if op == "list_supplemental_tables" and len(rows) > config.limit:
                raise ResponsysError("Responsys supplemental-table page exceeded the requested limit.")
            data = {"items": [{k: r[k] for k in ("name", "folderName") if isinstance(r.get(k), str)} | {"fields": _fields(r.get("fields", []))} for r in rows],
                    "continuation_known": False}
        elif op == "get_profile_list_fields":
            body = await self._get("/lists/" + quote(config.list_name, safe="") + "/fields")
            if not isinstance(body, dict):
                raise ResponsysError("Responsys returned invalid profile-list field metadata.")
            data = {"list_name": config.list_name, "fields": _fields(body.get("fields"))}
        elif op == "create_profile_list":
            await self._folder(config.folder_name)
            body = {"listName": config.list_name, "listFolderName": config.folder_name, "fields": _definitions(config.fields_json)}
            if config.description:
                body["description"] = config.description
            if config.brand_name:
                body["brandName"] = config.brand_name
            ack = await self._write("POST", "/lists", body)
            if not isinstance(ack, dict) or not isinstance(ack.get("listName"), str) or ack["listName"].strip() != config.list_name:
                raise ResponsysError("Responsys list acknowledgement was invalid; read back before repeating.", uncertain=True)
            data = {"list_name": config.list_name, "accepted": True, "readback_required": True}
        elif op in ("get_supplemental_table_fields", "create_supplemental_table", "update_supplemental_table", "delete_supplemental_table"):
            folder, table = quote(config.folder_name, safe=""), quote(config.table_name, safe="")
            fields_path = "/folder/" + folder + "/suppData/" + table
            if op == "create_supplemental_table":
                await self._folder(config.folder_name)
                fields = _definitions(config.fields_json, table=True)
                if len(set(config.primary_keys)) != len(config.primary_keys) or not set(config.primary_keys) <= {f["fieldName"] for f in fields}:
                    raise ResponsysError("Primary keys must be distinct field names from this table definition.")
                ack = await self._write("POST", "/folders/" + folder + "/suppData",
                    {"table": {"objectName": config.table_name}, "fields": fields, "primaryKeys": config.primary_keys})
                if ack is not True:
                    raise ResponsysError("Responsys did not return the documented table creation acknowledgement; read back before repeating.", uncertain=True)
                data = {"table_name": config.table_name, "folder_name": config.folder_name, "accepted": True, "readback_required": True}
            else:
                body = await self._get(fields_path, {"ft": config.field_type if op == "get_supplemental_table_fields" else "all"})
                metadata = body.get("suppData") if isinstance(body, dict) else None
                if not isinstance(metadata, dict) or metadata.get("objectName") != config.table_name or metadata.get("folderName") != config.folder_name:
                    raise ResponsysError("Responsys supplemental table parent metadata does not match.")
                if op == "get_supplemental_table_fields":
                    data = {"table_name": config.table_name, "folder_name": config.folder_name, "fields": _fields(body.get("fields"))}
                elif op == "update_supplemental_table":
                    await self._folder(config.destination_folder_name)
                    ack = await self._write("PUT", "/folders/" + folder + "/suppData/" + table,
                        {"folderName": config.destination_folder_name, "tableName": config.destination_table_name})
                    if not isinstance(ack, dict) or ack.get("status") is not True:
                        raise ResponsysError("Responsys did not acknowledge the table change; read back before repeating.", uncertain=True)
                    data = {"table_name": config.destination_table_name, "folder_name": config.destination_folder_name, "accepted": True, "readback_required": True}
                else:
                    # Oracle's delete example incorrectly labels the ack petName; do not claim an echoed table identity.
                    ack = await self._write("DELETE", "/folders/" + folder + "/suppData/" + table + "/table")
                    if not isinstance(ack, dict):
                        raise ResponsysError("Responsys deletion acknowledgement was unexpected; verify absence before repeating.", uncertain=True)
                    data = {"table_name": config.table_name, "folder_name": config.folder_name, "accepted": True, "deletion_verified": False}
        elif op == "get_campaign":
            body = await self._get("/campaigns/" + quote(config.campaign_name, safe=""))
            if not isinstance(body, dict) or body.get("name") != config.campaign_name:
                raise ResponsysError("Responsys campaign metadata does not match.")
            data = {k: body[k] for k in ("id", "name", "folderName", "type", "purpose", "listName", "campaignStatus") if isinstance(body.get(k), (str, int))}
        elif op in ("list_organizations", "get_campaign_organizations"):
            path = "/attributes/organizations" if op == "list_organizations" else "/attributes/campaigns/" + quote(config.campaign_name, safe="")
            body = await self._get(path)
            try:
                roots = body["attributes"]["organizations"]["attributeValues"]
            except (KeyError, TypeError):
                raise ResponsysError("Responsys returned invalid organizational metadata.") from None
            count = [0]
            def project(rows, depth=0):
                if not isinstance(rows, list) or depth > 20:
                    raise ResponsysError("Responsys organization hierarchy exceeded the bound.")
                result = []
                for row in rows:
                    count[0] += 1
                    if count[0] > MAX_ROWS or not isinstance(row, dict) or not isinstance(row.get("name"), str):
                        raise ResponsysError("Responsys returned invalid organizational metadata.")
                    item = {"id": _id(row.get("id")), "name": row["name"]}
                    if isinstance(row.get("lineage"), str):
                        item["lineage"] = row["lineage"]
                    if "children" in row:
                        item["children"] = project(row["children"], depth + 1)
                    result.append(item)
                return result
            data = {"organizations": project(roots)}
        else:
            raise ResponsysError("Unsupported native Responsys operation.")
        await self._guard()
        return {"status": "success", "data": data}
