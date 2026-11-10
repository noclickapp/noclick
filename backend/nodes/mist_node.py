"""Juniper Mist API 2610.1.0: https://www.juniper.net/documentation/us/en/software/mist/api/.

Fixed routes; one page per list call, preserving provider response structures.
"""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import (
    ExternalWebhookTriggerMixin,
    WebhookTriggerConfigBase,
)
from utils.ssrf import guarded_async_client

DOCS = "https://www.juniper.net/documentation/us/en/software/mist/api/"
API_HOSTS = (
    "https://api.mist.com",
    "https://api.gc1.mist.com",
    "https://api.ac2.mist.com",
    "https://api.gc2.mist.com",
    "https://api.gc4.mist.com",
    "https://api.eu.mist.com",
    "https://api.gc3.mist.com",
    "https://api.ac6.mist.com",
    "https://api.gc6.mist.com",
    "https://api.ac5.mist.com",
    "https://api.gc5.mist.com",
    "https://api.gc7.mist.com",
)


class MistAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Mist API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "Paste an admin or organization API token with access to the sites you want to automate. Choose your Mist API region. NoClick sends Authorization: Token to that region only. Mist automatically removes tokens unused for 90 days.",
        },
    )
    credential_type: Literal["mist_api_token"] = Field(
        "mist_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    api_base_url: Literal[*API_HOSTS] = Field(
        "https://api.mist.com", title="API Region"
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste an API token")
        value = clean_secret(value, field_name="API Token", key=True)
        if (
            "{{" in value
            or "}}" in value
            or not value.isascii()
            or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)
        ):
            raise ValueError(
                "Paste the API token without the Token prefix or whitespace"
            )
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_timezone(cls, value, info):
        if info.field_name == "timezone" and value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(
                    "Use an IANA timezone such as America/Los_Angeles"
                ) from None
        return value


def text(title, *, required=False, maximum=1000):
    return (
        str if required else str | None,
        Field(... if required else None, title=title, min_length=1, max_length=maximum),
    )


def identifier(title):
    return (
        UUID,
        Field(..., title=title, description="Mist UUID from a previous list or event"),
    )


PAGE = {
    "limit": (int, Field(100, ge=1, le=1000, title="Page Size")),
    "page": (
        int,
        Field(
            1, ge=1, title="Page", description="Starts at 1; increase for the next page"
        ),
    ),
}
TIME = {
    "start": (int | None, Field(None, ge=0, title="Start Epoch Seconds")),
    "end": (int | None, Field(None, ge=0, title="End Epoch Seconds")),
    "duration": text("Duration", maximum=30),
}
SEARCH = {
    "limit": PAGE["limit"],
    **TIME,
    "sort": text("Sort Field", maximum=100),
    "search_after": text("Search Cursor", maximum=4096),
}
SITE = {"site_id": identifier("Site ID")}
ORG = {"org_id": identifier("Organization ID")}
DEVICE = {**SITE, "device_id": identifier("Device ID")}
WLAN = {**SITE, "wlan_id": identifier("WLAN ID")}
ALARM = {**SITE, "alarm_id": identifier("Alarm ID")}
SITE_BODY = {
    "name": text("Site Name", required=True),
    "address": text("Address"),
    "timezone": text("Timezone", maximum=100),
    "notes": text("Notes", maximum=10000),
}


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    contract_id: str
    fields: dict[str, Any]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


OPERATIONS = {
    "get_account": Operation(
        "Get Current Account", "Account", "GET", "/self", "getSelf", {}
    ),
    "list_sites": Operation(
        "List Organization Sites",
        "Sites",
        "GET",
        "/orgs/{org_id}/sites",
        "listOrgSites",
        {**ORG, **PAGE},
        ("limit", "page"),
    ),
    "create_site": Operation(
        "Create Site",
        "Sites",
        "POST",
        "/orgs/{org_id}/sites",
        "createOrgSite",
        {**ORG, **SITE_BODY},
        body=tuple(SITE_BODY),
    ),
    "get_site": Operation(
        "Get Site", "Sites", "GET", "/sites/{site_id}", "getSiteInfo", SITE
    ),
    "update_site": Operation(
        "Update Site",
        "Sites",
        "PUT",
        "/sites/{site_id}",
        "updateSiteInfo",
        {**SITE, **SITE_BODY},
        body=tuple(SITE_BODY),
    ),
    "list_inventory": Operation(
        "List Organization Inventory",
        "Devices",
        "GET",
        "/orgs/{org_id}/inventory",
        "getOrgInventory",
        {
            **ORG,
            **PAGE,
            "serial": text("Serial Numbers"),
            "model": text("Models"),
            "modified_after": (
                int | None,
                Field(None, ge=0, title="Modified After Epoch Seconds"),
            ),
        },
        ("limit", "page", "serial", "model", "modified_after"),
    ),
    "list_devices": Operation(
        "List Site Devices",
        "Devices",
        "GET",
        "/sites/{site_id}/devices",
        "listSiteDevices",
        {
            **SITE,
            **PAGE,
            "type": (
                Literal["ap", "switch", "gateway", "router", "all"],
                Field("all", title="Device Type"),
            ),
            "name": text("Device Name"),
        },
        ("limit", "page", "type", "name"),
    ),
    "get_device": Operation(
        "Get Device",
        "Devices",
        "GET",
        "/sites/{site_id}/devices/{device_id}",
        "getSiteDevice",
        DEVICE,
    ),
    "list_device_stats": Operation(
        "List Device Statistics",
        "Devices",
        "GET",
        "/sites/{site_id}/stats/devices",
        "listSiteDevicesStats",
        {
            **SITE,
            **PAGE,
            "type": (
                Literal["ap", "switch", "gateway", "router", "all"],
                Field("all", title="Device Type"),
            ),
            "status": (
                Literal["all", "connected", "disconnected"],
                Field("all", title="Connection Status"),
            ),
        },
        ("limit", "page", "type", "status"),
    ),
    "restart_device": Operation(
        "Restart Device",
        "Devices",
        "POST",
        "/sites/{site_id}/devices/{device_id}/restart",
        "restartSiteDevice",
        {
            **DEVICE,
            "member": (
                int | None,
                Field(None, ge=0, le=9, title="Virtual Chassis Member"),
            ),
            "node": (
                Literal["node0", "node1"] | None,
                Field(None, title="SRX or SSR Node"),
            ),
        },
        body=("member", "node"),
    ),
    "list_clients": Operation(
        "List Wireless Client Statistics",
        "Clients",
        "GET",
        "/sites/{site_id}/stats/clients",
        "listSiteWirelessClientsStats",
        {**SITE, "limit": PAGE["limit"], **TIME},
        ("limit", "start", "end", "duration"),
    ),
    "list_wlans": Operation(
        "List WLANs",
        "WLANs",
        "GET",
        "/sites/{site_id}/wlans",
        "listSiteWlans",
        {**SITE, **PAGE},
        ("limit", "page"),
    ),
    "get_wlan": Operation(
        "Get WLAN",
        "WLANs",
        "GET",
        "/sites/{site_id}/wlans/{wlan_id}",
        "getSiteWlan",
        WLAN,
    ),
    "create_wlan": Operation(
        "Create PSK WLAN",
        "WLANs",
        "POST",
        "/sites/{site_id}/wlans",
        "createSiteWlan",
        {
            **SITE,
            "ssid": text("SSID", required=True, maximum=32),
            "psk": (
                str,
                Field(
                    ...,
                    title="Wi-Fi Password",
                    min_length=8,
                    max_length=64,
                    repr=False,
                    json_schema_extra={"ui:widget": "password"},
                ),
            ),
            "enabled": (
                bool,
                Field(
                    False,
                    title="Enable WLAN",
                    description="Enable when ready to broadcast this SSID",
                ),
            ),
        },
        body=("ssid", "psk", "enabled"),
    ),
    "update_wlan": Operation(
        "Update WLAN Name or Status",
        "WLANs",
        "PUT",
        "/sites/{site_id}/wlans/{wlan_id}",
        "updateSiteWlan",
        {
            **WLAN,
            "ssid": text("SSID", required=True, maximum=32),
            "enabled": (bool | None, Field(None, title="Enable WLAN")),
        },
        body=("ssid", "enabled"),
    ),
    "delete_wlan": Operation(
        "Delete WLAN",
        "WLANs",
        "DELETE",
        "/sites/{site_id}/wlans/{wlan_id}",
        "deleteSiteWlan",
        WLAN,
    ),
    "search_device_events": Operation(
        "Search Device Events",
        "Events",
        "GET",
        "/sites/{site_id}/devices/events/search",
        "searchSiteDeviceEvents",
        {**SITE, **SEARCH, "mac": text("Device MAC"), "text": text("Event Text")},
        (*SEARCH, "mac", "text"),
    ),
    "search_alarms": Operation(
        "Search Alarms",
        "Alarms",
        "GET",
        "/sites/{site_id}/alarms/search",
        "searchSiteAlarms",
        {
            **SITE,
            **SEARCH,
            "type": text("Alarm Types"),
            "acked": (bool | None, Field(None, title="Acknowledged")),
        },
        (*SEARCH, "type", "acked"),
    ),
    "acknowledge_alarm": Operation(
        "Acknowledge Alarm",
        "Alarms",
        "POST",
        "/sites/{site_id}/alarms/{alarm_id}/ack",
        "ackSiteAlarm",
        {**ALARM, "note": text("Note")},
        body=("note",),
    ),
    "unacknowledge_alarm": Operation(
        "Unacknowledge Alarm",
        "Alarms",
        "POST",
        "/sites/{site_id}/alarms/{alarm_id}/unack",
        "unackSiteAlarm",
        {**ALARM, "note": text("Note")},
        body=("note",),
    ),
}
CONFIG_MODELS = {}
for name, spec in OPERATIONS.items():
    CONFIG_MODELS[name] = create_model(
        "Mist" + "".join(w.title() for w in name.split("_")) + "Config",
        __base__=_Input,
        operation=(
            Literal[name],
            Field(
                name,
                title=spec.label,
                json_schema_extra={
                    "ui:hidden": True,
                    "x-display-name": spec.label,
                    "x-category": spec.category,
                    "x-api-operation": spec.contract_id,
                },
            ),
        ),
        **spec.fields,
    )
TRIGGERS = {"on_device_status": "device-updowns", "on_alarm": "alarms"}
for name, topic in TRIGGERS.items():
    label = "On Device Up or Down" if topic == "device-updowns" else "On Alarm"
    CONFIG_MODELS[name] = create_model(
        "Mist" + "".join(w.title() for w in name.split("_")) + "Config",
        __base__=WebhookTriggerConfigBase,
        operation=(
            Literal[name],
            Field(
                name,
                title=label,
                json_schema_extra={
                    "ui:hidden": True,
                    "x-display-name": label,
                    "x-category": "Triggers",
                    "x-is-trigger": True,
                },
            ),
        ),
        site_id=identifier("Site ID"),
        webhook_url=(
            str | None,
            Field(
                None,
                title="Webhook URL",
                description="Registered with Mist automatically",
                json_schema_extra={
                    "ui:widget": "webhook",
                    "ui:copyable": True,
                    "ui:loadValue": True,
                },
            ),
        ),
    )
MistConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")
]


class MistNodeConfig(NodeConfig[MistConfig, MistAPITokenCredential]):
    pass


async def _request(
    credential, method, path, *, params=None, body=None, allow_missing=False
):
    auth = MistAPITokenCredential.model_validate(credential)
    async with guarded_async_client(
        timeout=30, trust_env=False, follow_redirects=False
    ) as client:
        response = await client.request(
            method,
            auth.api_base_url + "/api/v1" + path,
            params=params,
            json=body,
            headers={
                "Authorization": "Token " + auth.api_token,
                "Accept": "application/json",
            },
        )
    if allow_missing and response.status_code == 404:
        return {}
    if not 200 <= response.status_code < 300:
        try:
            data = response.json()
            detail = (
                (data.get("detail") or data.get("error") or data.get("message"))
                if isinstance(data, dict)
                else None
            )
        except ValueError:
            detail = None
        safe = str(detail or "request failed").replace(auth.api_token, "[redacted]")[
            :1000
        ]
        raise ValueError(f"Mist API {response.status_code}: {safe}")
    return response.json() if response.content else {}


class MistNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-mist"
    connection_evidence = ConnectionEvidence(
        operation="get_account",
        identity_operation="get_account",
        noun="Mist account and privileges",
    )

    @classmethod
    def get_config_model(cls):
        return MistNodeConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"site_id": (config or {}).get("site_id")}

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ):
        op = config.get("operation")
        if op not in TRIGGERS:
            raise ValueError("Choose a Mist trigger")
        site_id = str(UUID(str(config.get("site_id"))))
        secret = secrets.token_hex(32)
        data = await _request(
            credential,
            "POST",
            f"/sites/{site_id}/webhooks",
            body={
                "name": f"NoClick {node_id}",
                "url": webhook_url,
                "topics": [TRIGGERS[op]],
                "type": "http-post",
                "secret": secret,
                "enabled": True,
                "verify_cert": True,
            },
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError("Mist did not return the registered webhook ID")
        return {
            "external_webhook_id": str(UUID(str(data["id"]))),
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        external_id = config.get("external_webhook_id")
        if not external_id:
            return
        if not credential:
            raise ValueError("Connect Mist to remove its webhook")
        site_id = str(UUID(str(config.get("site_id"))))
        webhook_id = str(UUID(str(external_id)))
        await _request(
            credential,
            "DELETE",
            f"/sites/{site_id}/webhooks/{webhook_id}",
            allow_missing=True,
        )

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        sent = next(
            (v for k, v in headers.items() if k.lower() == "x-mist-signature-v2"), ""
        )
        if (
            not isinstance(secret, str)
            or not secret
            or not isinstance(sent, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", sent)
        ):
            return False
        return hmac.compare_digest(
            hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), sent.lower()
        )

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if not isinstance(payload, dict) or payload.get("topic") != TRIGGERS.get(
            config.get("operation")
        ):
            return False
        events = payload.get("events")
        return (
            isinstance(events, list)
            and bool(events)
            and all(
                isinstance(e, dict) and e.get("site_id") == str(config.get("site_id"))
                for e in events
            )
        )

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return {"status": "no_event", "data": {}}
        return {
            "status": "success",
            "operation": config["operation"],
            "data": {"topic": payload["topic"], "events": payload["events"]},
        }

    @classmethod
    def resolve_agent_event(cls, output):
        data = output.get("data", {}) if isinstance(output, dict) else {}
        topic, events = data.get("topic"), data.get("events")
        if topic not in TRIGGERS.values() or not isinstance(events, list) or not events:
            return None
        lines, keys = [], []
        for event in events:
            site, org, kind, at = (
                event.get("site_id"),
                event.get("org_id"),
                event.get("type"),
                event.get("timestamp"),
            )
            if topic == "device-updowns":
                ap = event.get("ap")
                lines.append(
                    f"Mist device {event.get('ap_name') or ap}: {kind} at site {event.get('site_name') or site} (site_id={site}, org_id={org}, AP MAC={ap}, timestamp={at}). Use list_devices to find its device_id for get_device or restart_device."
                )
                keys.append(str(ap))
            else:
                aid = event.get("id")
                lines.append(
                    f"Mist alarm {kind} at site_id={site}, org_id={org}, timestamp={at}. Alarm ID={aid}; use acknowledge_alarm or unacknowledge_alarm with site_id={site}, alarm_id={aid}."
                )
                keys.append(str(aid))
        return {
            "text": "\n".join(lines),
            "conversation_key": f"mist:{topic}:" + ":".join(keys),
            "title": "Mist device status"
            if topic == "device-updowns"
            else "Mist alarm",
        }

    async def execute(self, inputs):
        if not isinstance(self.config, MistNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Mist API token")
        op = self.config.config
        name = op.operation
        if name in TRIGGERS:
            payload = self.node_data.get("config", {}).get("_triggerPayload") or inputs
            return self.resolve_trigger_payload(payload, op.model_dump(mode="json"))
        spec = OPERATIONS[name]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec.path
        for field in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        params = {k: values[k] for k in spec.query if k in values}
        body = {k: values[k] for k in spec.body if k in values} if spec.body else None
        if name == "create_wlan":
            body["auth"] = {"type": "psk", "psk": body.pop("psk")}
        data = await _request(
            self.config.credentials.model_dump(),
            spec.method,
            path,
            params=params,
            body=body,
        )
        return {"status": "success", "operation": name, "data": data}
