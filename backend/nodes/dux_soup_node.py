"""Dux-Soup Public API: signed outreach requests and documented webhook deliveries.

Contract: https://www.postman.com/collections/51439365-615513e8-60f7-4c8e-8ac9-0b40aea9dc83
Queued activity responses acknowledge scheduling, not successful LinkedIn delivery.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import WebhookTriggerConfigBase, ExternalWebhookTriggerMixin

DOCS = "https://www.postman.com/collections/51439365-615513e8-60f7-4c8e-8ac9-0b40aea9dc83"
BASE = "https://app.dux-soup.com/xapi/remote/control"
CREDENTIAL_TYPE = "dux_soup_api_key"


class DuxSoupCredential(BaseModel):
    model_config = ConfigDict(title="Dux-Soup API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://support.dux-soup.com/article/836-how-to-get-your-stacked-api-key",
            "x-credential-instructions": "Copy your User ID and Authentication Key from Settings → Connect. Enable Remote Control there to execute queued LinkedIn activities. NoClick signs requests with your key; no OAuth app is needed."})
    credential_type: Literal["dux_soup_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    userid: str = Field(..., title="User ID", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="The Dux-Soup account User ID shown in Settings → Connect.")
    api_key: str = Field(..., title="Authentication Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="Authentication Key")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Profile(_Input):
    profile: str = Field(..., title="LinkedIn Profile URL", min_length=1, max_length=2048,
        description="LinkedIn profile URL. InMail also accepts Sales Navigator lead URLs.")

    @field_validator("profile")
    @classmethod
    def profile_url(cls, value):
        if not re.fullmatch(r"https://(?:www\.)?linkedin\.com/(?:in|sales|talent)/[^\s?#]+(?:\?[^\s#]*)?", value):
            raise ValueError("Paste a LinkedIn profile URL")
        return value


class _Message(_Profile):
    messagetext: str = Field(..., title="Message Text", min_length=1, max_length=20000, json_schema_extra={"ui:widget": "textarea"})


class _Connect(_Profile):
    messagetext: str = Field("", title="Connection Note", max_length=300)


class _InMail(_Message):
    messagesubject: str = Field(..., title="Subject", min_length=1, max_length=200)


class _Tags(_Input):
    tags: list[str] = Field(..., title="Tags", min_length=1, max_length=100)

    @field_validator("tags")
    @classmethod
    def nonempty_tags(cls, value):
        if any(not tag.strip() or len(tag) > 1000 for tag in value):
            raise ValueError("Each tag must be nonempty and at most 1000 characters")
        return value


class _TagProfile(_Profile, _Tags):
    pass


def campaign_picker():
    return {"x-dynamic-options": {"field_name": "campaignid", "searchable": True, "allow_custom": True}}


def _path_id(value):
    if value in {".", ".."}:
        raise ValueError("Use a resource ID, not a dot path segment")
    return value


class _Campaign(_Input):
    campaignid: str = Field(..., title="Campaign", min_length=1, max_length=256, json_schema_extra=campaign_picker())
    _identifier = field_validator("campaignid")(_path_id)


class _Prospect(_Input):
    profileid: str = Field(..., title="Internal Profile ID", min_length=1, max_length=256, description="Dux-Soup internal ID, for example id.123456789.")
    _identifier = field_validator("profileid")(_path_id)


class _EnrollProfile(_Input):
    id: str = Field(..., title="Internal Profile ID", min_length=1, max_length=256)
    Profile: str = Field(..., title="LinkedIn Profile URL", min_length=1, max_length=2048)
    Degree: int = Field(..., title="Connection Degree", ge=1, le=3)
    _url = field_validator("Profile")(_Profile.profile_url.__func__)


class _Enroll(_Campaign):
    profile: _EnrollProfile = Field(..., title="Prospect")


class _Unenroll(_Campaign):
    profileid: str = Field(..., title="LinkedIn Profile URL", min_length=1, max_length=2048)
    _url = field_validator("profileid")(_Profile.profile_url.__func__)


class _AddTags(_Prospect, _Tags):
    pass


class _RecentActions(_Input):
    days: int = Field(30, title="Days Back", ge=1, le=365)
    limit: int = Field(100, title="Limit", ge=1, le=1000,
        description="Returns this many recent activities at most; this endpoint provides no pagination cursor.")


# Each entry is one published request. Shared RPC routes keep fixed command names.
# name: (label, input model, HTTP method, route, queued command)
OPERATIONS = {
    "visit_profile": ("Visit Profile", _Profile, "POST", "/queue", "visit"),
    "connect_profile": ("Send Connection Request", _Connect, "POST", "/queue", "connect"),
    "message_profile": ("Send LinkedIn Message", _Message, "POST", "/queue", "message"),
    "inmail_profile": ("Send InMail", _InMail, "POST", "/queue", "inmail"),
    "tag_profile": ("Queue Profile Tags", _TagProfile, "POST", "/queue", "tag"),
    "untag_profile": ("Queue Remove Profile Tags", _TagProfile, "POST", "/queue", "untag"),
    "follow_profile": ("Follow Profile", _Profile, "POST", "/queue", "follow"),
    "disconnect_profile": ("Disconnect Profile", _Profile, "POST", "/queue", "disconnect"),
    "list_campaigns": ("List Campaigns", _Input, "GET", "/campaigns", None),
    "get_campaign": ("Get Campaign", _Campaign, "GET", "/campaigns/{campaignid}", None),
    "enroll_profile": ("Enroll Profile in Campaign", _Enroll, "POST", "/campaign/{campaignid}/enroll", None),
    "unenroll_profile": ("Unenroll Profile from Campaign", _Unenroll, "POST", "/campaign/{campaignid}/unenroll", None),
    "get_recent_actions": ("Get Recent Activities", _RecentActions, "GET", "/actions/recent", None),
    "get_conversation": ("Get Conversation", _Prospect, "GET", "/conversations/{profileid}", None),
    "add_prospect_tags": ("Add Prospect Tags Directly", _AddTags, "PUT", "/prospects/{profileid}/tags", None),
    "get_queued_items": ("Get Queued Items", _Input, "GET", "/queue/items", None),
    "get_queue_size": ("Get Queue Size", _Input, "GET", "/queue/size", None),
    "clear_queue": ("Clear Activity Queue", _Input, "POST", "/reset", None),
    "get_user_profile": ("Get Account Profile", _Input, "GET", "/profile", None),
    "list_contacts": ("List Recorded Contacts", _Input, "GET", "/contacts", None),
}


def _operation(name, spec):
    label, base, method, _, command = spec
    return create_model("DuxSoup" + "".join(word.title() for word in name.split("_")) + "Config",
        __base__=base, __module__=__name__, operation=(Literal[name], Field(name, title=label,
            description="Queues a LinkedIn activity; messageid confirms scheduling only." if command else label,
            json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
                "x-operation-kind": "read" if method == "GET" else "write"})))


CONFIG_MODELS = {name: _operation(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


TRIGGERS = {"on_profile_visit": "visit", "on_action_completed": "action", "on_linkedin_message": "message"}


class _Webhook(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically in Dux-Soup Settings. Deliveries use the provider's documented unauthenticated webhook setup.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class DuxSoupOnProfileVisitConfig(_Webhook):
    operation: Literal["on_profile_visit"] = Field("on_profile_visit", title="On Profile Visit", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Profile Visit", "x-category": "Triggers"})


class DuxSoupOnActionCompletedConfig(_Webhook):
    operation: Literal["on_action_completed"] = Field("on_action_completed", title="On Completed LinkedIn Action", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Completed LinkedIn Action", "x-category": "Triggers"})


class DuxSoupOnLinkedInMessageConfig(_Webhook):
    operation: Literal["on_linkedin_message"] = Field("on_linkedin_message", title="On LinkedIn Message", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On LinkedIn Message", "x-category": "Triggers"})


DuxSoupOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) + (DuxSoupOnProfileVisitConfig, DuxSoupOnActionCompletedConfig, DuxSoupOnLinkedInMessageConfig)], Field(discriminator="operation")]


class DuxSoupNodeConfig(NodeConfig[DuxSoupOperation, DuxSoupCredential]):
    pass


async def request(credential, method, route, *, params=None, body=None):
    url = BASE + "/" + quote(credential.userid, safe="") + route
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    content = None
    if method == "GET":
        url = str(httpx.URL(url, params=params)) if params else url
        message = url.encode()
    else:
        payload = {"targeturl": url, "timestamp": int(time.time() * 1000), "userid": credential.userid, **(body or {})}
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        message = content
    headers["X-Dux-Signature"] = base64.b64encode(hmac.new(credential.api_key.encode(), message, hashlib.sha1).digest()).decode()
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.request(method, url, headers=headers, content=content)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise httpx.HTTPStatusError(
            f"Dux-Soup HTTP {response.status_code}: {response.text[:2000]}",
            request=exc.request, response=exc.response) from None
    data = response.json()
    if not isinstance(data, (dict, list)):
        raise ValueError("Dux-Soup returned an unexpected response")
    if isinstance(data, dict) and data.get("success") is False:
        raise ValueError(str(data.get("error") or data.get("message") or "Dux-Soup rejected this request"))
    return data


class DuxSoupNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_signing_secret_not_issued = True
    integration_type = "automation-dux-soup"
    connection_evidence = ConnectionEvidence(identity_operation="get_user_profile", noun="account", identity_keys=("firstName", "lastName", "email"))

    @classmethod
    def get_config_model(cls):
        return DuxSoupNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "campaignid":
            return {"options": []}
        data = await request(DuxSoupCredential.model_validate(credential_data), "GET", "/campaigns")
        rows = data["campaigns"]
        return {"options": [{"value": row["id"], "label": row["name"]} for row in rows
            if not search or search.lower() in row["name"].lower()]}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGERS.get((config or {}).get("operation"))
        if event is None:
            raise ValueError("Choose a Dux-Soup webhook trigger")
        if not webhook_url.startswith("https://"):
            raise ValueError("Dux-Soup requires an HTTPS webhook URL")
        cred = DuxSoupCredential.model_validate(credential)
        settings = await request(cred, "GET", "/settings")
        hooks = settings["webhooks"]
        if not isinstance(hooks, list) or any(not isinstance(h, dict) or not isinstance(h.get("url"), str) for h in hooks):
            raise ValueError("Dux-Soup returned invalid webhook settings")
        others = [h for h in hooks if h["url"] != webhook_url]
        if len(others) >= 5:
            raise ValueError("Dux-Soup already has five webhook targets; remove one before activating this trigger")
        await request(cred, "POST", "/settings", body={"settings": {
            "webhookprofileflag": True, "webhooks": [*others, {"url": webhook_url, "events": [event]}]}})
        # The settings API identifies a target by URL, not a server-generated ID.
        return {"external_webhook_id": webhook_url}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        target = (config or {}).get("external_webhook_id")
        if not target:
            return
        if not credential:
            raise ValueError("Dux-Soup credentials are required to remove this webhook target")
        cred = DuxSoupCredential.model_validate(credential)
        settings = await request(cred, "GET", "/settings")
        hooks = settings["webhooks"]
        if not isinstance(hooks, list) or any(not isinstance(h, dict) or not isinstance(h.get("url"), str) for h in hooks):
            raise ValueError("Dux-Soup returned invalid webhook settings")
        remaining = [h for h in hooks if h["url"] != target]
        if remaining != hooks:
            await request(cred, "POST", "/settings", body={"settings": {"webhooks": remaining}})

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Official delivery setup explicitly shows Authentication: None:
        # https://support.dux-soup.com/article/572-send-dux-soup-leads-to-your-crm-with-n8n
        # (the screenshot under "The STACKED data is located in the body section").
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        expected = TRIGGERS.get((config or {}).get("operation"))
        if not expected or not isinstance(payload, dict) or payload.get("type") != expected:
            return False
        stages = {"visit": {"create", "update"}, "action": {"completed", "create"}, "message": {"received", "sent"}}
        return payload.get("event") in stages[expected] and isinstance(payload.get("data"), dict)

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"operation": config.get("operation"), "delivery": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if isinstance(output, dict) and output.get("status") == "no_event":
            return None
        if not isinstance(output, dict) or "delivery" not in output:
            return super().resolve_agent_event(output)
        payload = output["delivery"]
        data = payload["data"]
        kind, stage, userid = payload["type"], payload["event"], payload["userid"]
        # Names differ between initial visits, enriched visits and message direction.
        # Optional fields are read only when present in the provider's payload.
        def present(*keys):
            return next((data[key] for key in keys if key in data and data[key]), "")
        if kind == "visit":
            name = " ".join(filter(None, [present("FirstName", "First Name"), present("LastName", "Last Name")]))
            profileid = data["id"]
            text = f"Profile visit {stage}: {name or profileid} at {present('Company') or 'unknown company'}; {data['Profile']}; profile ID {profileid}."
        elif kind == "message":
            prefix = "from" if stage == "received" else "to"
            profileid = data[prefix + "Id"]
            name = " ".join(filter(None, [data[prefix + "FirstName"], data[prefix + "LastName"]]))
            text = f"LinkedIn message {stage}: {name} ({data[prefix]}, profile ID {profileid}); conversation {data['url']}; {data['type']} at {data['timestamp']}:\n{data['text']}"
        elif kind == "action":
            profileid = data["profileid"]
            params = data["params"] if "params" in data else {}
            campaign = params["campaignid"] if "campaignid" in params else ""
            content = params["messagetext"] if "messagetext" in params else ""
            text = f"LinkedIn action {data['name']} completed for {data['targeturl']} (profile ID {profileid}, campaign {campaign}); success={data['successflag']}. {content}"
        else:
            return None
        return {"text": f"Dux-Soup account {userid} at {payload['time']}: {text}",
            "conversation_key": f"dux-soup:{userid}:{profileid}"}

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Dux-Soup with your User ID and Authentication Key")
        name = config.operation
        if name in TRIGGERS:
            return {"status": "no_event", "operation": name}
        _, _, method, route, command = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            marker = "{" + field + "}"
            if marker in route:
                route = route.replace(marker, quote(str(values.pop(field)), safe=""))
        body = {"command": command, "params": values} if command else values
        result = await request(credential, method, route,
            params=values if method == "GET" else None, body=body if method != "GET" else None)
        if name == "get_user_profile" and (not isinstance(result, dict) or result.get("userid") != credential.userid):
            raise ValueError("Dux-Soup returned an unexpected account identity")
        return {"items": result} if isinstance(result, list) else result
