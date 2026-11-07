"""Hivelocity v2 device metadata. Protected catalog access is not client identity."""
import json
import re
from typing import Annotated, Any, Dict, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

from repositories.credentials import credential_access_predicate
from repositories.organization import OrgRepo, PRIMARY_ORG_SQL


def _authority_guard():
    # $2 is the currently resolved principal; $4 is the actual runner. A
    # fallback principal must STILL own the workflow and its positive grant.
    primary_org = PRIMARY_ORG_SQL.replace("$1", "$4::uuid")
    return f"""
        {credential_access_predicate()}
        AND (NOT $5::boolean OR $3::uuid IS NOT DISTINCT FROM ({primary_org}))
        AND ($2::uuid = $4::uuid OR (
            $6::uuid IS NOT NULL AND EXISTS (
                SELECT 1 FROM workflows w
                JOIN workflow_authorized_credentials a ON a.workflow_id = w.id
                WHERE w.id = $6::uuid AND w.owner_id = $2::uuid
                  AND a.credential_id = c.id
            )
        ))
    """


class HivelocityCredentialsRepo:
    def __init__(self, pool):
        self.pool = pool

    async def load(self, credential_id, principal_id, organization_id, *,
                   caller_id, current_organization, workflow_id):
        async with self.pool.acquire() as conn:
            if current_organization:
                organization_id = await OrgRepo(self.pool).get_primary_org_id(conn, caller_id)
            row = await conn.fetchrow(f"""
                SELECT c.credential, c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at
                FROM credentials c
                WHERE c.id = $1::uuid AND {_authority_guard()}
            """, credential_id, principal_id, organization_id, caller_id,
                current_organization, workflow_id)
        return row, organization_id


from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID


CURRENT_ORGANIZATION = object()


@dataclass(frozen=True)
class CredentialAuthority:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: str | None
    current_organization: bool
    workflow_id: str | None
    owner_id: str
    credential_type: str
    token_version: int


class HivelocityCredentialsStore:
    def __init__(self, pool, user_id, credential_id, *, credential_type,
                 validate, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.credential_type = credential_type
        self.validate = validate
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.current = None

    def _repo(self):
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        return HivelocityCredentialsRepo(self.pool)

    def _validated(self, data):
        try:
            shaped = self.validate(data)
        except Exception:
            # Model and provider-validation input details can contain tokens.
            raise ValueError("Hivelocity credential grant shape or binding is invalid.") from None
        if not isinstance(shaped, dict) or shaped.get("credential_type") != self.credential_type:
            raise ValueError("Hivelocity credential validator returned an invalid grant.")
        return shaped

    async def _load_principal(self, credential_id, principal_id, pool, org_id):
        from utils.encryption import get_encryption
        current_org = self.organization_id is CURRENT_ORGANIZATION
        row, org = await self._repo().load(
            credential_id, principal_id, org_id, caller_id=self.user_id,
            current_organization=current_org, workflow_id=self.workflow_id,
        )
        if row is None:
            return None
        # Admit raw row identity/live/version BEFORE touching the encrypted blob.
        version = row["token_version"]
        if (row["revoked_at"] is not None or row["credential_type"] != self.credential_type
                or type(version) is not int or version < 1):
            raise ValueError("Hivelocity credential is unavailable or its saved authority changed.")
        try:
            owner = str(UUID(str(row["owner_id"])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Hivelocity credential saved owner is invalid.") from exc
        try:
            data = get_encryption().decrypt_credential(row["credential"])
        except Exception:
            raise ValueError("Hivelocity saved credential could not be decrypted.") from None
        if not isinstance(data, dict):
            raise ValueError("Hivelocity saved credential has an invalid shape.")
        data["credential_type"] = row["credential_type"]
        data = self._validated(data)
        self.current = CredentialAuthority(
            self.credential_id, self.user_id, str(principal_id), org, current_org,
            self.workflow_id, owner, row["credential_type"], version,
        )
        data = deepcopy(data)
        data["token_version"] = version
        if row["updated_at"] is not None:
            data["updated_at"] = row["updated_at"].isoformat()
        return data

    async def load(self):
        # Staging exposes the access predicate and workflow fallback gates, but
        # not a custom raw-row loader. Keep this key's row checks local.
        from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
        self.current = None
        self._repo()
        org = None if self.organization_id is CURRENT_ORGANIZATION else self.organization_id
        data = await self._load_principal(self.credential_id, self.user_id, self.pool, org)
        if data is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if (owner and str(owner) != self.user_id
                    and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id)):
                data = await self._load_principal(self.credential_id, owner, self.pool, org)
        if data is None or self.current is None:
            raise ValueError("Hivelocity credential not found or current access denied.")
        return data


BASE, MAX_BYTES, MAX_ROWS, MAX_ID = "https://core.hivelocity.net/api/v2", 2 * 1024 * 1024, 500, 9007199254740991
FIELDS = ("deviceId", "status", "spsStatus", "deviceType", "deviceTypeGroup", "createdDate", "isProvisioning", "isReload", "selfProvisioning", "provisioningProgress", "monitorsTotal", "monitorsUp")
FIELD_MASK = ",".join(FIELDS)
PROVISIONING_STAGES = {"pending", "pxe", "network_setup", "disk_setup", "installation", "configuration", "post_network", "finalizing", "end"}
DEVICE_STATES = {"BUILDING", "IPMI_READY", "PROVISIONABLE", "RESERVED", "WAIT_FOR_PXE", "PROVISION_STARTED", "PROVISION_WAIT_FOR_ADDONS", "PROVISION_FINISHED", "WAIT_TO_COMPLETE_ORDER", "WAIT_TO_ASSIGN_SERVICE", "WAIT_FOR_HARDWARE_SCAN", "IN_USE", "RELOADING", "DEVICE_READY_TO_TEST", "DEVICE_READY_TO_WIPE", "DEVICE_READY_TO_UPGRADE_FIRMWARE", "FAILED", "CLEANUP_MOVE_TO_FAILED", "IN_REVIEW", "READY_FOR_MIGRATION"}


def _text(value, limit=300, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use bounded text without control characters")
    if re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("URLs are outside metadata output")
    return value


def _integer(value):
    if type(value) is not int or not 0 <= value <= MAX_ID: raise ValueError("Unsupported nonnegative safe integer")
    return value


def _id(value):
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,15}", value): value = int(value)
    return _integer(value)


def _object(value):
    if not isinstance(value, dict): raise ValueError("Unsupported published Device-dump object")
    return value


class HivelocityAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hivelocity API Key", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developers.hivelocity.net/reference/introduction", "x-credential-instructions": "Supply an existing X-API-KEY and independently known accessible device ID. Fixed core.hivelocity.net/api/v2. Catalog plus detail establish protected resource reachability, never client/account/principal ownership. No key issue/OAuth/refresh. Entitlement and permissions unknown."})
    credential_type: Literal["hivelocity_api_key"] = Field("hivelocity_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, title="Existing API Key", json_schema_extra={"ui:widget": "password"})
    reference_device_id: int = Field(..., ge=0, le=MAX_ID, title="Independently Known Accessible Device ID", description="Native safe integer bound, not a documented provider maximum.")
    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply the raw issued key without a Bearer prefix")
        return clean_secret(value, field_name="Hivelocity API key")
    @field_validator("reference_device_id", mode="before")
    @classmethod
    def reference(cls, value): return _id(value)


def _credential(raw):
    if isinstance(raw, HivelocityAPIKeyCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "hivelocity_api_key": raise ValueError("Select the actual Hivelocity issued API-key family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) - {"credential_type", "api_key", "reference_device_id"}: raise ValueError("Unsupported key family/grant; no host override or refresh")
    try: return HivelocityAPIKeyCredential.model_validate(raw)
    except Exception: raise ValueError("Hivelocity issued key/reference binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store):
        super().__init__(data); self.store, self.anchor = store, self.identity(store.current)
    @staticmethod
    def identity(row): return tuple(getattr(row, name) for name in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))
    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("Hivelocity current key/reference or saved authority changed") from None
    def __repr__(self): return "<Hivelocity current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Device Metadata", "x-is-trigger": False})


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Custom Device Names", description="Opt in to the documented name scalar. Hostname, IP, apps, config, credentials, billing and URLs remain omitted.")


class HivelocityDevicesConfig(_Config):
    operation: Literal["list_devices"] = _op("list_devices", "Read Protected Device Catalog Metadata")
class HivelocityDeviceConfig(_Config):
    operation: Literal["get_device"] = _op("get_device", "Get Selected Device Metadata")
    device_id: int = Field(..., ge=0, le=MAX_ID, title="Device in Current Protected Catalog", json_schema_extra={"x-resource-type": "device_id", "x-dynamic-options": {"field_name": "device_id", "allow_custom": True}})
    @field_validator("device_id", mode="before")
    @classmethod
    def device(cls, value): return _id(value)

HivelocityOperation = Annotated[Union[HivelocityDevicesConfig, HivelocityDeviceConfig], Field(discriminator="operation")]
class HivelocityNodeConfig(NodeConfig[HivelocityOperation, HivelocityAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _device(raw, names=False):
    row = _object(raw); out = {"deviceId": _integer(row.get("deviceId")), "resource_type": "device"}
    for field in FIELDS[1:]:
        # Only name is required in the full OAS. Never fabricate missing optional metadata.
        if field not in row: continue
        value = row[field]
        if field in {"isProvisioning", "isReload", "selfProvisioning"}:
            if type(value) is not bool: raise ValueError("Unsupported provisioning flag")
        elif field in {"monitorsTotal", "monitorsUp"}: value = _integer(value)
        else:
            value = _text(value, 100 if field == "createdDate" else 300)
            if field == "status" and value not in {"active", "inactive"}: raise ValueError("Unsupported documented status")
            if field == "spsStatus" and value not in DEVICE_STATES: raise ValueError("Unsupported documented device state")
            if field == "provisioningProgress" and value not in PROVISIONING_STAGES: raise ValueError("Unsupported provisioning stage")
        out[field] = value
    if "monitorsUp" in out and "monitorsTotal" in out and out["monitorsUp"] > out["monitorsTotal"]: raise ValueError("Inconsistent monitor counts")
    if names: out["name"] = _text(row.get("name"), empty=True)
    return out


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, action): self.raw, self.key, self.action, self.attempted, self.status = raw, _credential(raw), action, False, None
    def error(self, message): return {"status": "error", "action": self.action, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, device_id=None, names=False):
        if type(names) is not bool: raise ValueError("Explicit boolean names opt-in required")
        path = BASE + "/device/" + (str(_id(device_id)) if device_id is not None else "")
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", path, headers={"X-API-KEY": key.api_key, "Accept": "application/json", "X-Fields": FIELD_MASK + (",name" if names else "")}) as response:
                    self.status = response.status_code; data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES: raise ValueError("Hivelocity response exceeds native bound")
                        data.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200:
                message = "Hivelocity HTTP403 documents missing permission; protected access could not be verified" if self.status == 403 else "Hivelocity protected read could not be verified; check access/entitlement"
                raise _ProviderError(self.error(message + ". Private provider text omitted; no retry occurred"))
            return json.loads(data)
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("Hivelocity transport outcome is unknown; no retry occurred")) from None
    async def catalog(self, names=False):
        rows = await self.request(names=names)
        if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise ValueError("Unsupported bounded bare Device-dump array")
        data = [_device(row, names) for row in rows]; catalog = {row["deviceId"]: row for row in data}
        if len(catalog) != len(data): raise ValueError("Duplicate device IDs")
        if self.key.reference_device_id not in catalog: raise ValueError("Known protected reference not established; empty lists are not identity")
        return catalog
    async def detail(self, device_id, names=False):
        data = _device(await self.request(device_id, names), names)
        if data["deviceId"] != device_id: raise ValueError("Selected device ID differs from direct object")
        return data


class HivelocityNode(WorkflowNode):
    integration_type = "automation-hivelocity"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_devices", noun="Hivelocity protected device catalog", proves="reachability")
    edit_examples = ["Read Hivelocity device provisioning status and monitor counts", "Get metadata only for a device in my current catalog", "Opt in to custom device names"]
    @classmethod
    def get_config_model(cls): return HivelocityNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._current_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def _current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        _credential(credential_data)
        if not credential_id: return credential_data
        if organization_id is None and not workflow_id: organization_id = CURRENT_ORGANIZATION
        store = HivelocityCredentialsStore(pool, user_id, credential_id, credential_type="hivelocity_api_key", validate=_stored, organization_id=organization_id, workflow_id=workflow_id)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("Hivelocity saved credential unavailable under current authority") from None
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Hivelocity key/reference family unsupported"}
        if validation_context is None: return {"valid": True, "provider_verified": False}
        await validation_context.revalidate(); result = await validation_context.run_operation("list_devices"); await validation_context.revalidate()
        if result.get("status") == "success" and result.get("protected_reachability_verified") is True: return {"valid": True, "provider_verified": True}
        return {"valid": None, "error": result.get("error", "Protected device catalog could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config.operation)
        try:
            catalog = await session.catalog(config.include_names)
            await session.detail(session.key.reference_device_id)
            if config.operation == "list_devices": out = {"data": list(catalog.values()), "returned_count": len(catalog), "total_count": None, "has_more": None, "next_page": None, "pagination_complete": None, "continuation_supported": False}
            elif config.operation == "get_device":
                if config.device_id not in catalog: raise ValueError("Selected device not established in current protected catalog")
                out = {"data": await session.detail(config.device_id, config.include_names)}
            else: raise ValueError("Unsupported native operation")
            response_status = session.status; current = await session.catalog()
            if config.operation == "list_devices" and set(current) != set(catalog): raise ValueError("Catalog membership changed before output")
            await session.detail(session.key.reference_device_id)
            if config.operation == "get_device":
                if config.device_id not in current: raise ValueError("Selected device left current catalog")
                await session.detail(config.device_id)
            encoded = json.dumps(out, ensure_ascii=False, allow_nan=False)
            if session.key.api_key in encoded: raise ValueError("Output contains secret material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": response_status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "tenant_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError): return session.error("Current key/catalog/resource ancestry or bounded published response could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data); context = context or {}
        if field_name != "device_id" or page_token is not None: raise ValueError("Only native device discovery; no documented cursor")
        names = context.get("include_names", False)
        if type(names) is not bool: raise ValueError("Explicit boolean names opt-in required")
        if search is not None: _text(search, 100)
        result = await cls._dispatch(credential_data, HivelocityDevicesConfig(include_names=names))
        if result.get("status") != "success": raise ValueError(result["error"])
        return {"options": [{"value": row["deviceId"], "label": row.get("name") or str(row["deviceId"]), "metadata": {"resource_type": "device"}} for row in result["data"] if not search or search.casefold() in (row.get("name") or str(row["deviceId"])).casefold()], "has_more": None, "next_page_token": None, "pagination_complete": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        initial = _credential(self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials)
        credential = await self._current_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
