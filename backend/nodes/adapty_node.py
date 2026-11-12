"""Adapty Server-side API v2 profiles and explicit access-level management.

The app-specific secret is checked against returned app_id. A supplied profile is
a read probe/resource reference, never a fabricated signed-in account principal.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math
import re
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.credential_loader import load_credential
from utils.ssrf import guarded_async_client

ROOT = "https://api.adapty.io/api/v2/server-side-api/"
Kind = Literal["profile_id", "customer_user_id"]
HIDDEN = {"ui:hidden": True}


def _header(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or value.strip() != value or re.search(r"[^\x20-\x7e]", value):
        raise ValueError("Use one nonempty printable header identifier, without surrounding whitespace.")
    return value


def _target(kind, value):
    value = _header(value)
    if kind == "profile_id":
        try:
            return str(UUID(value))
        except ValueError:
            raise ValueError("Use an actual Adapty profile UUID.") from None
    if kind != "customer_user_id":
        raise ValueError("Choose an Adapty profile ID or your customer user ID.")
    return value


def _instant(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Use a timezone-aware ISO 8601 datetime or null.") from None
    return value


class AdaptyAPIKeyCredential(BaseModel):
    credential_type: Literal["adapty_api_key"] = Field("adapty_api_key", json_schema_extra=HIDDEN)
    secret_key: str = Field(..., min_length=1, max_length=4096, title="App Secret API Key", json_schema_extra={"ui:widget": "password"},
        description="Secret key from App settings → General. SDK/public keys are not Server-side API credentials.")
    app_id: UUID = Field(..., title="Adapty App ID", description="Actual internal app UUID; every returned profile must match this app.")
    verification_profile_id: UUID = Field(..., title="Known Profile for Connection Check",
        description="An existing profile in this app used for a read-only connection check. This is a resource reference, not account identity.")
    model_config = ConfigDict(extra="ignore", json_schema_extra={"x-credential-url": "https://app.adapty.io/"})

    @field_validator("secret_key", mode="before")
    @classmethod
    def secret_value(cls, value):
        value = clean_secret(value)
        if re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Use an app secret without internal whitespace.")
        return value


# Adapty's own MCP server: agents get its tools through a person's Adapty sign-in.
AdaptyMcpCredential = mcp_credential("adapty", "https://mcp.adapty.io/mcp", app="Adapty")
AdaptyCredential = Union[AdaptyAPIKeyCredential, AdaptyMcpCredential]


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "adapty_api_key":
        raise ValueError("Use a current app-scoped Adapty secret-key connection.")
    try:
        shaped = AdaptyAPIKeyCredential.model_validate({key: data[key] for key in
            AdaptyAPIKeyCredential.model_fields if key in data}).model_dump(mode="json")
    except Exception:
        raise ValueError("Adapty app secret, app ID or verification profile is invalid.") from None
    return {**data, **shaped}


class AdaptyOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdaptyCheckConnectionConfig(AdaptyOperation):
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"x-display-name": "Check App Profile Access", "x-category": "Connection"})


class AdaptyTarget(AdaptyOperation):
    identifier_kind: Kind = Field("profile_id", title="Identify Profile By")
    profile_identifier: str = Field(..., min_length=1, max_length=512, title="Profile Identifier",
        description="An actual Adapty profile UUID or your previously identified customer user ID. The picker offers the verification profile only, not an app-wide user directory.",
        json_schema_extra={"x-dynamic-options": {"field_name": "profile_identifier", "depends_on": "identifier_kind", "searchable": True, "allow_custom": True},
            "x-resource-type": "adapty_profile_identifier"})

    @model_validator(mode="after")
    def identifier_value(self):
        self.profile_identifier = _target(self.identifier_kind, self.profile_identifier)
        return self


class AdaptyGetProfileConfig(AdaptyTarget):
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"x-display-name": "Get Profile", "x-category": "Profiles"})


class AdaptyCustomAttribute(AdaptyOperation):
    key: str = Field(..., min_length=1, max_length=30, pattern=r"^[A-Za-z0-9._-]+$")
    value: Union[str, float]

    @field_validator("value", mode="before")
    @classmethod
    def attribute_value(cls, value):
        if type(value) is str and len(value) <= 50:
            return value
        if type(value) in (int, float):
            try:
                if math.isfinite(float(value)):
                    return float(value)
            except OverflowError:
                pass
        raise ValueError("Custom attribute values must be finite numbers or strings up to 50 characters.")


class AdaptyInstallationMeta(AdaptyOperation):
    device_id: UUID = Field(..., description="Actual device identifier required by the documented ProfileRequest.")
    device: Optional[str] = Field(None, max_length=512)
    locale: Optional[str] = Field(None, max_length=64)
    os: Optional[str] = Field(None, max_length=256)
    platform: Optional[Literal["iOS", "macOS", "iPadOS", "Android", "visionOS", "web"]] = None
    timezone: Optional[str] = Field(None, max_length=128)
    app_build: Optional[str] = Field(None, max_length=64)
    app_version: Optional[str] = Field(None, max_length=64)


class AdaptyProfileFields(AdaptyTarget):
    installation_meta: AdaptyInstallationMeta
    first_name: Optional[str] = Field(None, max_length=256)
    last_name: Optional[str] = Field(None, max_length=256)
    gender: Optional[Literal["f", "m", "o"]] = None
    email: Optional[str] = Field(None, max_length=320)
    phone_number: Optional[str] = Field(None, max_length=64)
    birthday: Optional[str] = None
    ip_country: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    analytics_disabled: Optional[bool] = None
    custom_attributes: Optional[list[AdaptyCustomAttribute]] = Field(None, max_length=30)

    @field_validator("birthday")
    @classmethod
    def birthday_value(cls, value):
        if value is not None:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError("Use YYYY-MM-DD or null for birthday.") from None
        return value

    @model_validator(mode="after")
    def attributes_value(self):
        if self.custom_attributes is not None and len({attr.key for attr in self.custom_attributes}) != len(self.custom_attributes):
            raise ValueError("Each custom attribute key must be unique.")
        if "custom_attributes" in self.model_fields_set and self.custom_attributes is None:
            raise ValueError("Use an attribute array; null is not a documented custom_attributes request.")
        return self


class AdaptyCreateProfileConfig(AdaptyProfileFields):
    operation: Literal["create_profile"] = Field("create_profile", json_schema_extra={"x-display-name": "Create Profile", "x-category": "Profiles"})
    platform_header: Optional[str] = Field(None, max_length=128, title="Device Platform Header")
    _platform_value = field_validator("platform_header")(lambda value: _header(value) if value is not None else None)


class AdaptyUpdateProfileConfig(AdaptyProfileFields):
    operation: Literal["update_profile"] = Field("update_profile", json_schema_extra={"x-display-name": "Update Profile", "x-category": "Profiles"})


class AdaptyDeleteProfileConfig(AdaptyTarget):
    operation: Literal["delete_profile"] = Field("delete_profile", json_schema_extra={"x-display-name": "Delete Profile", "x-category": "Profiles"})


class AdaptyListAccessLevelsConfig(AdaptyTarget):
    operation: Literal["list_access_levels"] = Field("list_access_levels", json_schema_extra={"x-display-name": "List Profile Access Levels", "x-category": "Access Levels"})


class AdaptyAccessTarget(AdaptyTarget):
    access_level_id: str = Field(..., min_length=1, max_length=256, title="Access Level ID",
        description="An existing dashboard access-level identifier. Picker lists only levels returned for the selected profile; custom entry can select another existing level.",
        json_schema_extra={"x-dynamic-options": {"field_name": "access_level_id", "depends_on": ["identifier_kind", "profile_identifier"], "searchable": True, "allow_custom": True},
            "x-resource-type": "adapty_access_level"})
    _level_value = field_validator("access_level_id")(_header)


class AdaptyGetAccessLevelConfig(AdaptyAccessTarget):
    operation: Literal["get_access_level"] = Field("get_access_level", json_schema_extra={"x-display-name": "Get Profile Access Level", "x-category": "Access Levels"})


class AdaptyCheckAccessLevelConfig(AdaptyAccessTarget):
    operation: Literal["check_access_level"] = Field("check_access_level", json_schema_extra={"x-display-name": "Check Profile Access Level", "x-category": "Access Levels"})


class AdaptyGrantAccessLevelConfig(AdaptyAccessTarget):
    operation: Literal["grant_access_level"] = Field("grant_access_level", json_schema_extra={"x-display-name": "Grant Access Level", "x-category": "Access Management"})
    starts_at: Optional[str] = Field(None, description="Aware ISO 8601 start; null/unset starts immediately.")
    expires_at: Optional[str] = Field(None, description="Aware ISO 8601 expiry. Null/unset grants lifetime access; this changes customer entitlement.")
    _starts_value = field_validator("starts_at")(_instant)
    _expires_value = field_validator("expires_at")(_instant)


class AdaptyRevokeAccessLevelConfig(AdaptyAccessTarget):
    operation: Literal["revoke_access_level"] = Field("revoke_access_level", json_schema_extra={"x-display-name": "Revoke Access Level", "x-category": "Access Management"})
    revoke_at: Optional[str] = Field(None, description="Aware ISO 8601 time; null/unset revokes immediately. This changes customer entitlement.")
    _revoke_value = field_validator("revoke_at")(_instant)


AdaptyConfig = Annotated[Union[AdaptyCheckConnectionConfig, AdaptyGetProfileConfig, AdaptyCreateProfileConfig, AdaptyUpdateProfileConfig,
    AdaptyDeleteProfileConfig, AdaptyListAccessLevelsConfig, AdaptyGetAccessLevelConfig, AdaptyCheckAccessLevelConfig,
    AdaptyGrantAccessLevelConfig, AdaptyRevokeAccessLevelConfig], Field(discriminator="operation")]


class AdaptyNodeConfig(NodeConfig[AdaptyConfig, AdaptyCredential]):
    pass


async def _request(data, method, path, kind, identifier, *, body=None, platform=None):
    data = _credential(data)
    identifier = _target(kind, identifier)
    if (method, path) not in {("GET", "profile/"), ("POST", "profile/"), ("PATCH", "profile/"), ("DELETE", "profile/"),
            ("POST", "purchase/profile/grant/access-level/"), ("POST", "purchase/profile/revoke/access-level/")}:
        raise ValueError("Unsupported native Adapty operation.")
    headers = {"Authorization": "Api-Key " + data["secret_key"], "Accept": "application/json", "adapty-" + kind.replace("_", "-"): identifier}
    if platform is not None:
        headers["adapty-platform"] = _header(platform)
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25.0) as client:
            response = await client.request(method, ROOT + path, headers=headers, json=body)
    except Exception:
        raise RuntimeError("Adapty request could not complete; access remains unverified.") from None
    if method == "DELETE":
        if response.status_code == 204 and not response.content:
            return None, 204
        raise RuntimeError("Adapty did not return the documented empty 204 deletion acknowledgement.")
    if response.status_code != 200:
        raise RuntimeError({401: "Adapty access is unverified; check the app secret key.",
            403: "Adapty access is unverified; check this app's current API permissions.",
            404: "The selected Adapty profile is not currently visible; key validity remains unverified.",
            429: "Adapty rate limit reached; no automatic retry occurred."}.get(response.status_code,
                "Adapty rejected the request; no automatic retry occurred."))
    if not response.content or len(response.content) > 2000000:
        raise RuntimeError("Adapty returned empty or excessive profile content.")
    try:
        payload = response.json()
        raw = payload["data"]
        if not isinstance(payload, dict) or "errors" in payload or "error_code" in payload or not isinstance(raw, dict):
            raise ValueError()
        actual_app, actual_profile = str(UUID(raw["app_id"])), _target("profile_id", raw["profile_id"])
        if actual_app != data["app_id"]:
            raise ValueError()
        if raw.get("customer_user_id") is not None:
            _header(raw["customer_user_id"])
        if (actual_profile if kind == "profile_id" else raw.get("customer_user_id")) != identifier:
            raise ValueError()
        if type(raw.get("timestamp")) is not int or not isinstance(raw.get("custom_attributes"), list) or not isinstance(raw.get("access_levels"), list) or len(raw["access_levels"]) > 1000:
            raise ValueError()
        attributes = [AdaptyCustomAttribute.model_validate(attr).model_dump(mode="json") for attr in raw["custom_attributes"]]
        if len(attributes) > 30 or len({attr["key"] for attr in attributes}) != len(attributes):
            raise ValueError()
        levels = [_level(level) for level in raw["access_levels"]]
        if len({level["access_level_id"] for level in levels}) != len(levels):
            raise ValueError()
    except Exception:
        raise RuntimeError("Adapty returned an error, malformed profile or another app/profile.") from None
    return {"app_id": actual_app, "profile_id": actual_profile, "customer_user_id": raw.get("customer_user_id"),
        "timestamp": raw["timestamp"], "custom_attributes": attributes, "access_levels": levels}, 200


def _level(raw):
    if not isinstance(raw, dict):
        raise ValueError()
    level_id = _header(raw.get("access_level_id"))
    result = {"access_level_id": level_id}
    for field in ("starts_at", "expires_at", "purchased_at", "originally_purchased_at", "renewal_cancelled_at", "billing_issue_detected_at"):
        if field in raw:
            result[field] = _instant(raw[field])
    for field in ("store", "store_product_id", "store_base_plan_id", "cancellation_reason"):
        if field in raw:
            if raw[field] is not None and (not isinstance(raw[field], str) or len(raw[field]) > 4096):
                raise ValueError()
            result[field] = raw[field]
    if type(raw.get("is_in_grace_period")) is not bool or "expires_at" not in raw:
        raise ValueError()
    result["is_in_grace_period"] = raw["is_in_grace_period"]
    return result


class AdaptyNode(WorkflowNode):
    integration_type = "automation-adapty"
    credential_provider_labels = {"adapty": "Adapty Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="profiles", label_keys=("profile_id",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return AdaptyNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_id:
            return _credential(credential_data)
        if not user_id:
            raise ValueError("Sign in to use a saved Adapty connection.")
        current = await load_credential(pool, user_id, credential_id, raise_on_error=True)
        return _credential(current)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        data = _credential(credential_data)
        await _request(data, "GET", "profile/", "profile_id", data["verification_profile_id"])
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        if page_token is not None or field_name not in {"verification_profile", "profile_identifier", "access_level_id"}:
            raise ValueError("Adapty has no profile-directory pagination for this selector.")
        context = context if isinstance(context, dict) else {}
        kind = context.get("identifier_kind", "profile_id")
        if kind not in {"profile_id", "customer_user_id"}:
            raise ValueError("Choose the documented profile identifier kind.")
        if search is not None:
            if not isinstance(search, str) or len(search) > 512 or re.search(r"[\x00-\x1f\x7f]", search):
                raise ValueError("Use a bounded profile selector search.")
            search = search.strip()
        if field_name == "access_level_id":
            identifier = _target(kind, context.get("profile_identifier"))
        else:
            identifier, kind = data["verification_profile_id"], "profile_id"
        profile, _ = await _request(data, "GET", "profile/", kind, identifier)
        if field_name == "access_level_id":
            options = [{"value": level["access_level_id"], "label": level["access_level_id"]} for level in profile["access_levels"]]
        elif field_name == "profile_identifier" and context.get("identifier_kind", "profile_id") == "customer_user_id":
            options = [{"value": profile["customer_user_id"], "label": profile["customer_user_id"]}] if profile["customer_user_id"] else []
        elif field_name == "verification_profile" or context.get("identifier_kind", "profile_id") == "profile_id":
            options = [{"value": profile["profile_id"], "label": "Profile " + profile["profile_id"]}]
        else:
            raise ValueError("Choose the documented profile identifier kind.")
        if search:
            options = [option for option in options if search.casefold() in option["label"].casefold()]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        if not isinstance(self.config, AdaptyNodeConfig) or not self.config.credentials:
            raise ValueError("Adapty configuration and a connection are required.")
        c = self.config.config
        data = await self.freshen_credential(self.config.credentials.model_dump(mode="json"),
            pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"))
        op = c.operation
        if op == "check_connection":
            profile, _ = await _request(data, "GET", "profile/", "profile_id", data["verification_profile_id"])
            return {"app_id": profile["app_id"], "profile_id": profile["profile_id"],
                "items": [{"profile_id": profile["profile_id"]}], "proof": "Reachability of the known profile in this app; no account identity."}
        if op in {"get_profile", "list_access_levels", "get_access_level", "check_access_level"}:
            profile, status = await _request(data, "GET", "profile/", c.identifier_kind, c.profile_identifier)
            if op == "get_profile":
                return {"data": profile, "http_status": status}
            levels = profile["access_levels"]
            if op == "list_access_levels":
                return {"items": levels, "profile_id": profile["profile_id"], "app_id": profile["app_id"], "next_page_token": None}
            selected = next((level for level in levels if level["access_level_id"] == c.access_level_id), None)
            if op == "get_access_level":
                return {"found": selected is not None, "data": selected, "profile_id": profile["profile_id"]}
            now = datetime.now(timezone.utc)
            started = selected is not None and (not selected.get("starts_at") or datetime.fromisoformat(selected["starts_at"].replace("Z", "+00:00")) <= now)
            active = bool(started and (selected["is_in_grace_period"] or selected["expires_at"] is None or datetime.fromisoformat(selected["expires_at"].replace("Z", "+00:00")) > now))
            return {"found": selected is not None, "has_access": active, "data": selected, "evaluated_at": now.isoformat(),
                "profile_id": profile["profile_id"], "derivation": "Current response start/expiry/grace; no SDK is_active field or authorization decision."}
        # Check the secret's actual app before creating a new target. Existing
        # targets are read before mutation, so a wrong app binding cannot write.
        pre_id = data["verification_profile_id"] if op == "create_profile" else c.profile_identifier
        pre_kind = "profile_id" if op == "create_profile" else c.identifier_kind
        await _request(data, "GET", "profile/", pre_kind, pre_id)
        if op == "delete_profile":
            _, status = await _request(data, "DELETE", "profile/", c.identifier_kind, c.profile_identifier)
            return {"deletion_acknowledged": True, "http_status": status, "identifier_kind": c.identifier_kind,
                "profile_identifier": c.profile_identifier, "scope": "Provider 204 for this profile; no account-wide deletion claim."}
        if op in {"create_profile", "update_profile"}:
            body = c.model_dump(mode="json", exclude={"operation", "identifier_kind", "profile_identifier", "platform_header"}, exclude_unset=True)
            method, path = ("POST" if op == "create_profile" else "PATCH"), "profile/"
        else:
            body = c.model_dump(mode="json", include={"access_level_id", "starts_at", "expires_at", "revoke_at"}, exclude_unset=True)
            path = "purchase/profile/" + ("grant" if op == "grant_access_level" else "revoke") + "/access-level/"
            method = "POST"
        profile, status = await _request(data, method, path, c.identifier_kind, c.profile_identifier,
            body=body, platform=getattr(c, "platform_header", None))
        return {"data": profile, "operation": op, "http_status": status,
            "confirmation": "Provider profile response in the bound app; not a proof of every submitted personal field or a quiet write."}
