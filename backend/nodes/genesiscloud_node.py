"""Genesis Cloud Compute API: two existing-instance metadata GETs.

Exact current instance envelopes; resource reachability, never account identity.
Network, credentials, settings and capability projections are deliberately absent.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, WrapValidator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.genesiscloud.com/compute/v1"
FAMILY = "genesiscloud_api_token"
OPERATIONS = ("list_instances", "get_instance")
STATES = frozenset(("creating", "pending_payment", "active", "stopping", "stopped", "starting", "resetting", "error", "deleting"))
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_private_transport = contextvars.ContextVar("genesiscloud_private_transport", default=False)


class GenesisCloudError(ValueError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(f"{message} (HTTP {status_code})" if status_code is not None else message)
        self.status_code = status_code


def _reference(value):
    return isinstance(value, str) and "{{" in value and "}}" in value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(UUID_PATTERN, value):
        raise ValueError("Enter an exact lowercase Genesis Cloud instance UUID, not a URL.")
    if str(UUID(value)) != value:
        raise ValueError("Enter a canonical Genesis Cloud instance UUID.")
    return value


def _pending(value, handler):
    return value if _reference(value) else handler(value)


InstanceID = Annotated[str, Field(pattern=UUID_PATTERN, min_length=36, max_length=36), WrapValidator(_pending)]
Page = Annotated[int, Field(ge=1, le=1000000), WrapValidator(_pending)]
PageSize = Annotated[int, Field(ge=1, le=100), WrapValidator(_pending)]


class GenesisCloudAPITokenCredential(BaseModel):
    credential_type: Literal["genesiscloud_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., description="Your Genesis Cloud API token, without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Genesis Cloud API Token", extra="ignore", json_schema_extra={
        "x-credential-type": "api_key", "x-credential-url": "https://developers.genesiscloud.com/compute-api/",
        "x-credential-instructions": "In the Genesis Cloud dashboard, open Keys and Tokens. Generate or copy an API token and paste it here without the Bearer prefix. Connecting checks access to your existing instances.",
    })

    @field_validator("api_token", mode="before")
    @classmethod
    def _valid_token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a text Genesis Cloud API token.")
        value = clean_secret(value, field_name="API token")
        if not value or len(value) > 8192 or _reference(value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter a valid API token without whitespace, Bearer prefix or references.")
        return value

class _Common(BaseModel):
    include_names: bool = Field(False, description="Include human-readable instance names. Names can disclose business resources.")
    model_config = ConfigDict(extra="ignore")


class ListInstancesConfig(_Common):
    """Read one documented existing-instance page, excluding network and credential details."""
    operation: Literal["list_instances"] = "list_instances"
    page: Page = Field(1, description="Positive provider page. The native cap of 1,000,000 is a local bound, not a documented provider maximum.")
    per_page: PageSize = Field(50, description="One provider page, 1–100 rows; documented default is 50. No automatic paging.")


class GetInstanceConfig(_Common):
    """Read one protected existing instance by its exact selected UUID."""
    operation: Literal["get_instance"] = "get_instance"
    instance_id: InstanceID = Field(..., description="Exact existing instance UUID. Enter an explicit ID or resolved workflow reference; catalog/detail access proves reachability only.", json_schema_extra={"x-resource-type": "genesiscloud_instance_id"})


GenesisCloudOperation = Annotated[Union[ListInstancesConfig, GetInstanceConfig], Field(discriminator="operation")]


class GenesisCloudNodeConfig(NodeConfig[GenesisCloudOperation, GenesisCloudAPITokenCredential]):
    model_config = ConfigDict(title="Genesis Cloud Node Configuration")


def _raw_guard(data):
    if not isinstance(data, dict):
        raise ValueError("Genesis Cloud configuration must be an object.")
    ids = data.get("credentialIds")
    ids = {} if ids is None else ids
    if not isinstance(ids, dict) or any(k not in (FAMILY, "credential_type") for k in ids) or ids.get("credential_type") not in (None, FAMILY) or data.get("credential_type") not in (None, FAMILY):
        raise ValueError("Select the native Genesis Cloud token credential family.")
    chosen, mapped = data.get("credential_id"), ids.get(FAMILY)
    for value in (chosen, mapped):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Select a saved Genesis Cloud credential UUID.")
            try:
                if str(UUID(value)) != value:
                    raise ValueError("Noncanonical UUID")
            except (ValueError, TypeError):
                raise ValueError("Select a canonical saved Genesis Cloud credential UUID.") from None
    if chosen and mapped and chosen != mapped:
        raise ValueError("Genesis Cloud credential selections disagree.")
    creds = data.get("credentials")
    if creds is not None:
        if not isinstance(creds, dict) or creds.get("credential_type") not in (None, FAMILY):
            raise ValueError("Foreign credential data cannot authenticate Genesis Cloud.")
        if (chosen or mapped or creds.get("token_version") is not None or creds.get("updated_at") is not None) and creds.get("credential_type") != FAMILY:
            raise ValueError("Stored Genesis Cloud credentials require their native family tag.")
        try:
            GenesisCloudAPITokenCredential.model_validate(creds)
        except Exception:
            raise ValueError("Check the Genesis Cloud API-token field.") from None
    inner = data.get("config")
    inner = {} if inner is None else inner
    if not isinstance(inner, dict):
        raise ValueError("Genesis Cloud operation configuration must be an object.")
    if inner.get("operation") == "get_instance" and inner.get("instance_id") not in (None, "") and not _reference(inner["instance_id"]):
        _id(inner["instance_id"])
    if inner.get("operation") == "list_instances":
        for key in ("page", "per_page"):
            value = inner.get(key)
            if value not in (None, "") and not _reference(value) and type(value) is not int:
                raise ValueError("Genesis Cloud paging values must be integers.")
    if "include_names" in inner and inner["include_names"] not in (None, "") and type(inner["include_names"]) is not bool:
        raise ValueError("Include names must be a checkbox value.")


class _TransportFilter(logging.Filter):
    def filter(self, record):
        return not _private_transport.get()


@contextmanager
def _quiet_transport():
    token = _private_transport.set(True)
    filters = []
    try:
        for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logger = logging.getLogger(name)
            f = _TransportFilter()
            logger.addFilter(f)
            filters.append((logger, f))
        yield
    finally:
        for logger, f in filters:
            logger.removeFilter(f)
        _private_transport.reset(token)


class GenesisCloudNode(WorkflowNode):
    integration_type = "automation-genesiscloud"
    connection_evidence = ConnectionEvidence(operation="list_instances", noun="instances", label_keys=("id",), proves="reachability")
    scope_registry = ScopeRegistry("genesiscloud", {op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPERATIONS})

    @classmethod
    def get_config_model(cls):
        return GenesisCloudNodeConfig

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

    def _selected_id(self):
        _raw_guard(self.node_data)
        return self.node_data.get("credential_id") or (self.node_data.get("credentialIds") or {}).get(FAMILY)

    def _snapshot(self):
        return hashlib.sha256(json.dumps({"actor": self.user_id, "org": self.organization_id, "workflow": self.workflow_id,
            "raw": {k: self.node_data.get(k) for k in ("credentials", "credential_id", "credentialIds", "config")},
            "typed": self.config.model_dump(mode="json")}, sort_keys=True, default=str).encode()).hexdigest()

    def _unchanged(self):
        if self._snapshot() != self._frame:
            raise GenesisCloudError("Genesis Cloud actor, credential or resource selection changed. Retry with the current selection.")

    async def run(self, inputs):
        cid = self._selected_id()
        self.node_data = dict(self.node_data)
        if cid:
            self.node_data["credential_id"] = cid
        self._frame = self._snapshot()
        return await super().run(inputs)

    async def _fresh(self):
        self._unchanged()
        attached = self.config.credentials
        if attached is None:
            raise GenesisCloudError("Select a Genesis Cloud API token.")
        # Staging resolves saved credentials before constructing the node.
        credential = attached
        raw = self.node_data.get("credentials")
        if isinstance(raw, dict) and GenesisCloudAPITokenCredential.model_validate(raw) != attached:
            raise GenesisCloudError("Genesis Cloud credential shaping changed; parse the current selection.")
        binding = (self._selected_id(), credential.api_token)
        if self._binding is None:
            self._binding = binding
        elif self._binding != binding:
            raise GenesisCloudError("Genesis Cloud credential access or version changed during this read.")
        self._unchanged()
        return credential

    async def _request(self, route, params=None):
        if route == "/instances":
            allowed = {"page", "per_page"}
        elif re.fullmatch(r"/instances/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", route):
            _id(route.rsplit("/", 1)[1])
            allowed = set()
        else:
            raise GenesisCloudError("Unsupported Genesis Cloud metadata route.")
        params = dict(params or {})
        if not set(params) <= allowed:
            raise GenesisCloudError("Unsupported Genesis Cloud request parameters.")
        for key, maximum in (("page", 1000000), ("per_page", 100)):
            if key in params and (type(params[key]) is not int or not 1 <= params[key] <= maximum):
                raise GenesisCloudError("Genesis Cloud paging exceeded its native bound.")
        credential = await self._fresh()
        path = "/compute/v1" + route

        async def before_send(request):
            current = await self._fresh()
            if request.url.scheme != "https" or request.url.host != "api.genesiscloud.com" or request.url.port not in (None, 443) or request.url.path != path or sorted(request.url.params.multi_items()) != sorted((k, str(v)) for k, v in params.items()):
                raise GenesisCloudError("Genesis Cloud request origin, instance or paging changed.")
            request.headers["Authorization"] = "Bearer " + current.api_token

        try:
            with _quiet_transport():
                async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [before_send]}) as client:
                    async with client.stream("GET", BASE_URL + route, params=params, headers={"Accept": "application/json", "Authorization": "Bearer " + credential.api_token}) as response:
                        status = response.status_code
                        if status != 200:
                            raise GenesisCloudError({400: "Genesis Cloud rejected the metadata parameters.", 401: "Genesis Cloud rejected the API token.", 403: "Genesis Cloud permission or resource access is missing.", 404: "Genesis Cloud resource was not found.", 422: "Genesis Cloud rejected the metadata filters.", 429: "Genesis Cloud rate limit reached; retry later."}.get(status, "Genesis Cloud did not return a completed metadata read."), status)
                        if "json" not in response.headers.get("content-type", "").lower():
                            raise GenesisCloudError("Genesis Cloud returned unsupported response media.")
                        body = bytearray()
                        async for part in response.aiter_bytes():
                            body.extend(part)
                            if len(body) > 4 * 1024 * 1024:
                                raise GenesisCloudError("Genesis Cloud response exceeded the metadata size bound.")
                        try:
                            data = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                        except (ValueError, RecursionError):
                            raise GenesisCloudError("Genesis Cloud returned invalid JSON metadata.") from None
            await self._fresh()
            pending, visited = [data], 0
            while pending:
                value = pending.pop(); visited += 1
                if visited > 100000:
                    raise GenesisCloudError("Genesis Cloud JSON exceeded the metadata complexity bound.")
                if isinstance(value, str) and credential.api_token in value:
                    raise GenesisCloudError("Genesis Cloud reflected credential material; response withheld.")
                if isinstance(value, dict):
                    pending.extend(value.keys()); pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            if not isinstance(data, dict):
                raise GenesisCloudError("Genesis Cloud returned an unsupported metadata envelope.")
            return data
        except httpx.HTTPError:
            raise GenesisCloudError("Genesis Cloud metadata transport failed; no response is confirmed.") from None

    @staticmethod
    def _integer(value, *, minimum=0):
        if type(value) is not int or not minimum <= value <= 2**63 - 1:
            raise GenesisCloudError("Genesis Cloud returned an invalid integer count or disk size.")
        return value

    @staticmethod
    def _text(data, key, result, *, timestamp=False, identifier=False):
        value = data.get(key)
        if value is None:
            return
        maximum = 64 if timestamp else 256 if identifier else 500
        if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value) or "://" in value:
            raise GenesisCloudError("Genesis Cloud returned invalid text metadata.")
        if identifier and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", value):
            raise GenesisCloudError("Genesis Cloud returned an unsupported type or region identifier.")
        if timestamp:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
                raise GenesisCloudError("Genesis Cloud returned invalid ISO timestamp metadata.")
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise GenesisCloudError("Genesis Cloud returned invalid ISO timestamp metadata.") from None
        result[key] = value

    def _instance(self, data):
        if not isinstance(data, dict):
            raise GenesisCloudError("Genesis Cloud returned an unsupported instance envelope.")
        try:
            instance_id = _id(data.get("id"))
        except ValueError:
            raise GenesisCloudError("Genesis Cloud returned an invalid instance UUID.") from None
        result = {"id": instance_id}
        for key in ("type", "region"):
            self._text(data, key, result, identifier=True)
        if data.get("status") is not None:
            if not isinstance(data["status"], str) or data["status"] not in STATES:
                raise GenesisCloudError("Genesis Cloud returned an undocumented instance state.")
            result["status"] = data["status"]
        if data.get("disk_size") is not None:
            result["disk_size"] = self._integer(data["disk_size"], minimum=80)
        if data.get("image") is not None:
            image = data["image"]
            if not isinstance(image, dict):
                raise GenesisCloudError("Genesis Cloud returned an unsupported image metadata shape.")
            if image.get("id") is not None:
                try:
                    result["image_id"] = _id(image["id"])
                except ValueError:
                    raise GenesisCloudError("Genesis Cloud returned an invalid image UUID.") from None
        for key in ("created_at", "updated_at"):
            self._text(data, key, result, timestamp=True)
        if self.config.config.include_names:
            self._text(data, "name", result)
        return result

    def _page(self, data, config):
        if not isinstance(data, dict) or not isinstance(data.get("instances"), list):
            raise GenesisCloudError("Genesis Cloud instance pages require the documented instances wrapper.")
        rows = data["instances"]
        if len(rows) > config.per_page:
            raise GenesisCloudError("Genesis Cloud instance page exceeded the requested row bound.")
        page = self._integer(data.get("page"), minimum=1)
        per_page = self._integer(data.get("per_page"), minimum=1)
        total = self._integer(data.get("total_count"))
        if page != config.page or per_page != config.per_page or total < len(rows):
            raise GenesisCloudError("Genesis Cloud returned inconsistent page metadata.")
        instances = [self._instance(row) for row in rows]
        if len({row["id"] for row in instances}) != len(instances):
            raise GenesisCloudError("Genesis Cloud returned duplicate instance UUIDs.")
        return {"instances": instances, "returned_count": len(instances), "page": page, "per_page": per_page,
            "total_count": total, "has_more_pages": page * per_page < total,
            "completion": "unknown", "reachability": "existing_instance_catalog"}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        _raw_guard(self.node_data)
        self._frame = getattr(self, "_frame", self._snapshot())
        self._binding = None
        config = self.config.config
        if any(_reference(value) for value in config.model_dump().values()):
            raise GenesisCloudError("Resolve Genesis Cloud instance and paging references before execution.")
        await self._fresh()
        if config.operation == "list_instances":
            data = await self._request("/instances", {"page": config.page, "per_page": config.per_page})
            result = self._page(data, config)
        elif config.operation == "get_instance":
            instance_id = _id(config.instance_id)
            data = await self._request("/instances/" + instance_id)
            if not isinstance(data, dict) or not isinstance(data.get("instance"), dict):
                raise GenesisCloudError("Genesis Cloud detail requires the documented instance wrapper.")
            instance = self._instance(data["instance"])
            if instance["id"] != instance_id:
                raise GenesisCloudError("Genesis Cloud returned another selected instance.")
            result = {"instance": instance, "reachability": "selected_existing_instance"}
        else:
            raise GenesisCloudError("Unsupported Genesis Cloud operation.")
        await self._fresh()
        self._unchanged()
        return {"success": True, "data": result}
