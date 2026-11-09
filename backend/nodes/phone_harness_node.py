"""Phone Harness account, session and ADB API (published contract 2026-09-14).

Each operation performs one request. Session admission and cleanup can be
asynchronous; callers inspect state or recover the original create receipt.
Viewer URLs, ADB unlock codes and newly created keys are sensitive output.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.phone-harness.com"
NODE_TYPE = "automation-phone-harness"


class PhoneHarnessAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Phone Harness API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://phone-harness.com/api-reference/account/create-api-key",
            "x-credential-instructions": "Create your first account API key in the Phone Harness dashboard, then paste it here. This account-wide key can start billed sessions and manage other keys. Paste only the key, without the Bearer prefix.",
        })
    credential_type: Literal["phone_harness_api_key"] = Field("phone_harness_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _SessionOperation(_Operation):
    sid: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", title="Session ID",
        description="The id returned when the session was created.")


class CreateSessionConfig(_Operation):
    """Allocate an Android phone asynchronously. HTTP 202 means admitted, not ready. Poll the returned id. The deadline includes provisioning. Use one stable Idempotency-Key per logical Start. Pass your account's profile_id (from GET /me) to use your own phone, which is saved when the session ends and comes back the same way next time; omit it for a temporary phone that keeps nothing. Raw capabilities and runtime resource overrides are not supported. Omit provider to use the service default."""
    operation: Literal["create_session"] = Field("create_session", json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{16,128}$",
        description="Use one stable key per logical Start; reuse exactly the same key and body after a timeout. Never generate a fresh key just to retry.")
    timeout_seconds: int | None = Field(None, ge=1, description="Lifetime from admission including provisioning; the service default is 300 seconds.")
    platform: Literal["android", "ios"] | None = Field(None, description="Set together with kind, or omit both for a temporary Android emulator.")
    kind: Literal["emulator", "device"] | None = None
    profile_id: str | None = Field(None, min_length=1, description="Your profile id from Get account. Omit for a temporary phone.")

    @model_validator(mode="after")
    def paired_platform(self):
        if (self.platform is None) != (self.kind is None):
            raise ValueError("Set platform and kind together")
        return self


class ListSessionsConfig(_Operation):
    """Return this account's sessions known to the live runtime, including provisioning, error, or closing entries. Completed sessions belong in history."""
    operation: Literal["list_sessions"] = Field("list_sessions", json_schema_extra={"ui:hidden": True})


class GetSessionConfig(_SessionOperation):
    """Inspect state, deadline, geometry and advertised operations. A valid read-only watch grant may read only its own session. Ready does not mean a browser frame has been displayed."""
    operation: Literal["get_session"] = Field("get_session", json_schema_extra={"ui:hidden": True})


class EndSessionConfig(_SessionOperation):
    """Request closure of an owned session. New API operations stop and billable use ends at recorded closure. Capacity stays occupied until cleanup is confirmed. Repeating after the session is removed may return 404; use the create receipt to confirm cleanup."""
    operation: Literal["end_session"] = Field("end_session", json_schema_extra={"ui:hidden": True})


class RecoverCreateRequestConfig(_Operation):
    """Look up a durable, account-scoped create receipt, including after cleanup. A missing receipt does not justify retrying with a new key; reuse the same key and body for the same logical Start."""
    operation: Literal["recover_create_request"] = Field("recover_create_request", json_schema_extra={"ui:hidden": True})
    request_key: str = Field(..., pattern=r"^[A-Za-z0-9_-]{16,128}$", description="The original create idempotency key.")


class GetOwnerViewerConfig(_SessionOperation):
    """Mint an opaque, expiring interactive viewer URL for a ready, owned session. Treat it as a secret and never log it. Current embedding is restricted to the configured Phone Harness dashboard origin; arbitrary third-party embedding is not a supported integration. Reconnection does not extend the phone deadline. Watch grants cannot call this endpoint."""
    operation: Literal["get_owner_viewer"] = Field("get_owner_viewer", json_schema_extra={"ui:hidden": True})


class GetViewerConfig(_SessionOperation):
    """Mint an opaque, expiring view-only viewer URL for a ready session: the same live video as the owner viewer, without input. This is what a watch link opens. The session owner may call it with a bearer credential; a watch link's holder passes its view grant as the token query parameter. Treat the URL as a secret and never log it. Embedding is restricted to the Phone Harness dashboard origin. Reconnection does not extend the phone deadline."""
    operation: Literal["get_viewer"] = Field("get_viewer", json_schema_extra={"ui:hidden": True})


class GetAccountConfig(_Operation):
    """Read account identity, credits and account capacity. can_rent describes the rental-access gate only; balance and shared capacity are checked separately when creating a session."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class ResetProfileConfig(_Operation):
    """Forget the saved profile phone: its apps, logins and data. The next session started with your profile_id begins with a fresh phone. Refused while a session holds the phone."""
    operation: Literal["reset_profile"] = Field("reset_profile", json_schema_extra={"ui:hidden": True})


class ResetDeviceConfig(_Operation):
    """Erase one of your iPhones and set it up again: its apps, accounts and data are deleted, and it stays assigned to your account. Takes a few minutes; meanwhile its state in GET /me → available is resetting and a start on it answers 409 device_resetting. It ends available, or reset_failed if the reset did not finish: reset it again (the same call). Refused while a session holds the phone."""
    operation: Literal["reset_device"] = Field("reset_device", json_schema_extra={"ui:hidden": True})
    device_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="Device id from Get account available, for example iph-622c376ba7. Erases apps, accounts and data.")


class ListApiKeysConfig(_Operation):
    """List active keys for your account. Full bearer keys are never returned here."""
    operation: Literal["list_api_keys"] = Field("list_api_keys", json_schema_extra={"ui:hidden": True})


class CreateApiKeyConfig(_Operation):
    """Create another account-wide key. The raw secret is shown only once. For your first key, use the authenticated dashboard. A key can manage other keys on the same account."""
    operation: Literal["create_api_key"] = Field("create_api_key", json_schema_extra={"ui:hidden": True})
    label: str | None = Field(None, description="A descriptive name for the new account-wide key; its raw value is returned only once.")


class RevokeApiKeyConfig(_Operation):
    """Revoke a key belonging to this account using its key_hash from the key list, not the raw key. Revoking a key does not end sessions. The response is idempotent and does not prove the identifier existed."""
    operation: Literal["revoke_api_key"] = Field("revoke_api_key", json_schema_extra={"ui:hidden": True})
    key_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$", description="Identifier from List API keys, never the raw key. Does not end sessions.")


class ListHistoryPageConfig(_Operation):
    """Paginated finished-session records ordered by ended time, then session ID, descending. Cursors are opaque and account-bound. History end time is not cleanup confirmation; use the create receipt for that."""
    operation: Literal["list_history_page"] = Field("list_history_page", json_schema_extra={"ui:hidden": True})
    limit: int = Field(40, ge=1, le=100)
    cursor: str | None = Field(None, description="The previous next_cursor, passed unchanged.")


class GetRecentHistoryConfig(_Operation):
    """Return up to 100 finished sessions, ordered by creation time descending. This endpoint has no pagination parameters. Prefer GET /history/page for a complete history."""
    operation: Literal["get_recent_history"] = Field("get_recent_history", json_schema_extra={"ui:hidden": True})


class EnableAdbConfig(_SessionOperation):
    """Return the ADB endpoint and unlock code for one ready session owned by your account. Ready phones already have ADB enabled and carry the same values in the session's adb block, so this is only needed to re-enable after DELETE; it is idempotent. Takes no body. Watch tokens cannot enable access. See the [connection guide](/guides/connect-adb)."""
    operation: Literal["enable_adb"] = Field("enable_adb", json_schema_extra={"ui:hidden": True})


class GetAdbConfig(_SessionOperation):
    """Return the ADB endpoint and unlock code for enabled ADB access, or enabled: false. Requires a ready, unexpired session owned by your account. Watch tokens cannot read this endpoint."""
    operation: Literal["get_adb"] = Field("get_adb", json_schema_extra={"ui:hidden": True})


class RevokeAdbConfig(_SessionOperation):
    """Revoke ADB access for your session. This does not end the phone or stop its billing; use DELETE /sessions/{sid} to end the session. Revocation can be requested while a live session is closing or its deadline has passed, provided its allocation is still available. An already-removed session returns 404. Watch tokens cannot revoke access."""
    operation: Literal["revoke_adb"] = Field("revoke_adb", json_schema_extra={"ui:hidden": True})


class ResetAdbConfig(_SessionOperation):
    """Mint a new unlock code for this session and close every existing ADB connection. Use it when the code has been shared too widely. The endpoint's host and port stay the same. Takes no body. Watch tokens cannot reset."""
    operation: Literal["reset_adb"] = Field("reset_adb", json_schema_extra={"ui:hidden": True})


PhoneHarnessOperation = Annotated[Union[
    CreateSessionConfig,
    ListSessionsConfig,
    GetSessionConfig,
    EndSessionConfig,
    RecoverCreateRequestConfig,
    GetOwnerViewerConfig,
    GetViewerConfig,
    GetAccountConfig,
    ResetProfileConfig,
    ResetDeviceConfig,
    ListApiKeysConfig,
    CreateApiKeyConfig,
    RevokeApiKeyConfig,
    ListHistoryPageConfig,
    GetRecentHistoryConfig,
    EnableAdbConfig,
    GetAdbConfig,
    RevokeAdbConfig,
    ResetAdbConfig
], Field(discriminator="operation")]


class PhoneHarnessConfig(NodeConfig[PhoneHarnessOperation, PhoneHarnessAPIKeyCredential]):
    pass


# Exact single-endpoint mappings from the published OpenAPI contract.
ROUTES = {
    "create_session": ("POST", "/sessions"),
    "list_sessions": ("GET", "/sessions"),
    "get_session": ("GET", "/sessions/{sid}"),
    "end_session": ("DELETE", "/sessions/{sid}"),
    "recover_create_request": ("GET", "/sessions/requests/{request_key}"),
    "get_owner_viewer": ("GET", "/sessions/{sid}/owner-viewer"),
    "get_viewer": ("GET", "/sessions/{sid}/viewer"),
    "get_account": ("GET", "/me"),
    "reset_profile": ("POST", "/me/profile/reset"),
    "reset_device": ("POST", "/me/devices/{id}/reset"),
    "list_api_keys": ("GET", "/me/keys"),
    "create_api_key": ("POST", "/me/keys"),
    "revoke_api_key": ("POST", "/me/keys/revoke"),
    "list_history_page": ("GET", "/history/page"),
    "get_recent_history": ("GET", "/history"),
    "enable_adb": ("POST", "/sessions/{sid}/adb"),
    "get_adb": ("GET", "/sessions/{sid}/adb"),
    "revoke_adb": ("DELETE", "/sessions/{sid}/adb"),
    "reset_adb": ("POST", "/sessions/{sid}/adb/reset"),
}


class PhoneHarnessNode(WorkflowNode):
    integration_type = "automation-phone-harness"
    connection_evidence = ConnectionEvidence(noun="Phone Harness account", identity_operation="get_account",
        identity_keys=("name", "email", "uid"))

    @classmethod
    def get_config_model(cls):
        return PhoneHarnessConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Phone Harness API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        if hasattr(config, "sid"):
            path = path.replace("{sid}", quote(config.sid, safe=""))
        if hasattr(config, "device_id"):
            path = path.replace("{id}", quote(config.device_id, safe=""))
        if hasattr(config, "request_key"):
            path = path.replace("{request_key}", quote(config.request_key, safe=""))
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"}
        kwargs = {}
        if config.operation == "create_session":
            if config.idempotency_key:
                headers["Idempotency-Key"] = config.idempotency_key
            kwargs["json"] = config.model_dump(include={"platform", "kind", "profile_id", "timeout_seconds"}, exclude_none=True)
        elif config.operation == "create_api_key":
            kwargs["json"] = config.model_dump(include={"label"}, exclude_none=True)
        elif config.operation == "revoke_api_key":
            kwargs["json"] = {"key_hash": config.key_hash}
        elif config.operation == "list_history_page":
            kwargs["params"] = config.model_dump(include={"limit", "cursor"}, exclude_none=True)
        # Never retry writes here: an admission may have succeeded before timeout.
        # Never follow redirects or forward the account key to returned viewer URLs.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error", "Phone Harness request failed")
            except (ValueError, AttributeError):
                error = "Phone Harness request failed"
            error = str(error).replace(self.config.credentials.api_key, "[redacted]")
            return {"status": "error", "error": error, "http_status": response.status_code}
        if response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise ValueError("Expected a JSON response from Phone Harness")
        data = response.json()
        if not isinstance(data, (dict, list)) or (isinstance(data, dict) and "error" in data and "id" not in data):
            raise ValueError("Phone Harness returned an unexpected response")
        if config.operation == "get_account" and (
            not isinstance(data, dict) or not isinstance(data.get("uid"), str) or not data["uid"]
        ):
            raise ValueError("Phone Harness did not return an account identity")
        # Preserve all documented fields, including pending cleanup and provisioning
        # state. A successful HTTP response does not mean a phone is ready/released.
        return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": data}
