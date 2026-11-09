"""CleverTap account/passcode API, checked against its published Postman collection.

Each action makes one documented request. Export cursors and partial-count request
IDs are returned unchanged; callers explicitly fetch the next page/result.
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class CleverTapCredential(BaseModel):
    model_config = ConfigDict(title="CleverTap Account Passcode", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.clevertap.com/docs/authentication",
        "x-credential-instructions": "In CleverTap Settings, copy your Account ID and generate an account passcode under Passcodes. Choose the region holding your account. NoClick checks the account's subscription groups before saving.",
    })
    credential_type: Literal["clevertap_passcode"] = Field("clevertap_passcode", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., min_length=1, max_length=200, title="Account ID")
    passcode: str = Field(..., min_length=1, max_length=4096, title="Account passcode", repr=False, json_schema_extra={"ui:widget": "password"})
    region: Literal["in1", "sg1", "us1", "aps3", "mec1", "eu1"] = Field("in1", title="Account region", description="India: in1; Singapore: sg1; United States: us1; Indonesia: aps3; UAE: mec1; Europe: eu1.")

    @field_validator("account_id", "passcode", mode="before")
    @classmethod
    def clean_header(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Paste the account value without spaces or header prefixes")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Range(_Input):
    from_date: int = Field(..., title="From date", description="Inclusive YYYYMMDD in the CleverTap account timezone.")
    to_date: int = Field(..., title="To date", description="Inclusive YYYYMMDD in the CleverTap account timezone.")

    @field_validator("from_date", "to_date")
    @classmethod
    def date(cls, value):
        try:
            if len(str(value)) != 8:
                raise ValueError()
            datetime.strptime(str(value), "%Y%m%d")
        except ValueError:
            raise ValueError("Use a valid YYYYMMDD calendar date") from None
        return value

    @model_validator(mode="after")
    def order(self):
        if self.from_date > self.to_date:
            raise ValueError("From date must be on or before to date")
        return self


class _EventRange(_Range):
    event_name: str = Field(..., min_length=1, max_length=512, title="Event name")


def _op(name, label, category):
    return Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


class ListSubscriptionGroups(_Input):
    operation: Literal["list_subscription_groups"] = _op("list_subscription_groups", "List Subscription Groups", "Subscriptions")


class GetProfile(_Input):
    operation: Literal["get_profile"] = _op("get_profile", "Get Profile by Identity", "Profiles")
    identity: str = Field(..., min_length=1, max_length=1024)


class UploadProfiles(_Input):
    operation: Literal["upload_profiles"] = _op("upload_profiles", "Update User Profile", "Profiles")
    object_id: str = Field(..., min_length=1, max_length=1024, title="CleverTap object ID")
    profile_data: dict[str, Any] = Field(..., min_length=1, title="Profile properties", description="CleverTap profileData, e.g. {\"Name\": \"Jack Test\"}.")


class UploadEvent(_Input):
    operation: Literal["upload_event"] = _op("upload_event", "Upload User Event", "Events")
    identity: str = Field(..., min_length=1, max_length=1024)
    event_name: str = Field(..., min_length=1, max_length=512)
    event_data: dict[str, Any] = Field(default_factory=dict, title="Event properties")


class DeleteProfile(_Input):
    operation: Literal["delete_profile"] = _op("delete_profile", "Delete User Profile", "Profiles")
    identity: str = Field(..., min_length=1, max_length=1024, description="Permanently delete this identity's profile.")


class DemergeProfiles(_Input):
    operation: Literal["demerge_profiles"] = _op("demerge_profiles", "Demerge User Profiles", "Profiles")
    identities: list[str] = Field(..., min_length=2, max_length=100)


class Subscription(_Input):
    type: Literal["phone", "email"]
    value: str = Field(..., min_length=1, max_length=1024)
    status: Literal["Unsubscribe", "Resubscribe"]


class SetSubscriptions(_Input):
    operation: Literal["set_subscriptions"] = _op("set_subscriptions", "Subscribe or Unsubscribe Users", "Subscriptions")
    subscriptions: list[Subscription] = Field(..., min_length=1, max_length=100)


class Recipients(_Input):
    Email: list[str] | None = Field(None, min_length=1, max_length=1000)
    Identity: list[str] | None = Field(None, min_length=1, max_length=1000)
    objectId: list[str] | None = Field(None, min_length=1, max_length=1000)
    FBID: list[str] | None = Field(None, min_length=1, max_length=1000)
    GPID: list[str] | None = Field(None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def any_recipient(self):
        if not any(self.model_dump(exclude_none=True).values()):
            raise ValueError("Provide at least one recipient")
        if any(not item.strip() for values in self.model_dump(exclude_none=True).values() for item in values):
            raise ValueError("Recipient IDs must not be empty")
        return self


class _Send(_Input):
    to: Recipients = Field(..., title="Recipients")
    tag_group: str = Field(..., min_length=1, max_length=512, title="Campaign tag group")
    respect_frequency_caps: bool = Field(True, title="Respect frequency caps")
    body: str = Field(..., min_length=1, max_length=500000, title="Message body")


class SendEmail(_Send):
    operation: Literal["send_email"] = _op("send_email", "Send Email", "Campaigns")
    subject: str = Field(..., min_length=1, max_length=1024)
    sender_name: str = Field(..., min_length=1, max_length=512)


class SendSms(_Send):
    operation: Literal["send_sms"] = _op("send_sms", "Send SMS", "Campaigns")


class SendPush(_Send):
    operation: Literal["send_push"] = _op("send_push", "Send Push Notification", "Campaigns")
    title: str = Field(..., min_length=1, max_length=1024)


class SendWebPush(_Send):
    operation: Literal["send_web_push"] = _op("send_web_push", "Send Web Push Notification", "Campaigns")
    title: str = Field(..., min_length=1, max_length=1024)


class CampaignRecipients(_Input):
    Email: list[str] = Field(..., min_length=1, max_length=1000, title="Recipient emails")


class TriggerCampaign(_Input):
    operation: Literal["trigger_campaign"] = _op("trigger_campaign", "Trigger Campaign", "Campaigns")
    to: CampaignRecipients
    campaign_id: int = Field(..., gt=0)


class StopCampaign(_Input):
    operation: Literal["stop_campaign"] = _op("stop_campaign", "Stop Scheduled Campaign", "Campaigns")
    campaign_id: int = Field(..., gt=0)


class GetCampaignReport(_Input):
    operation: Literal["get_campaign_report"] = _op("get_campaign_report", "Get Campaign Report", "Campaigns")
    campaign_id: int = Field(..., gt=0)


class ListCampaigns(_Range):
    operation: Literal["list_campaigns"] = _op("list_campaigns", "List API Campaigns", "Campaigns")


class GetProfileCount(_EventRange):
    operation: Literal["get_profile_count"] = _op("get_profile_count", "Get Profile Count", "Analytics")


class GetEventCount(_EventRange):
    operation: Literal["get_event_count"] = _op("get_event_count", "Get Event Count", "Analytics")


class StartProfileExport(_EventRange):
    operation: Literal["start_profile_export"] = _op("start_profile_export", "Start Profile Export", "Profiles")


class StartEventExport(_EventRange):
    operation: Literal["start_event_export"] = _op("start_event_export", "Start Event Export", "Events")


class GetProfileExportPage(_Input):
    operation: Literal["get_profile_export_page"] = _op("get_profile_export_page", "Get Profile Export Page", "Profiles")
    cursor: str = Field(..., min_length=1, max_length=16000, description="Use cursor or next_cursor from the previous export response; repeat until no next_cursor remains.")


class GetEventExportPage(_Input):
    operation: Literal["get_event_export_page"] = _op("get_event_export_page", "Get Event Export Page", "Events")
    cursor: str = Field(..., min_length=1, max_length=16000, description="Use cursor or next_cursor from the previous export response; repeat until no next_cursor remains.")


class GetVariables(_Input):
    operation: Literal["get_variables"] = _op("get_variables", "Get User Variables", "Variables")
    identity: str = Field(..., min_length=1, max_length=1024)
    include_defaults: bool = Field(False)


class OnSubscriptionGroupChanged(PollTriggerConfigBase):
    """Poll the complete list ordered locally by updated_on; baseline existing groups."""
    operation: Literal["on_subscription_group_changed"] = Field("on_subscription_group_changed", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-display-name": "On New or Updated Subscription Group", "x-is-trigger": True,
    })


class OnNewEvent(PollTriggerConfigBase):
    """Export a rolling account-timezone window and deduplicate documented records."""
    operation: Literal["on_new_event"] = Field("on_new_event", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-display-name": "On New User Event", "x-is-trigger": True,
    })
    event_name: str = Field(..., min_length=1, max_length=512, title="Event name")
    account_timezone: str = Field("UTC", title="Account timezone", description="IANA timezone matching your CleverTap account, e.g. Asia/Kolkata.")
    lookback_days: int = Field(2, ge=1, le=31, title="Lookback days", description="Rolling inclusive event-date window; existing records form the initial baseline. Events arriving outside this window are excluded. Events with the same user ID, timestamp and event/session properties are treated as one delivery.")

    @field_validator("account_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Use an IANA timezone matching the CleverTap account") from None
        return value


Operation = Annotated[Union[
    ListSubscriptionGroups, GetProfile, UploadProfiles, UploadEvent, DeleteProfile,
    DemergeProfiles, SetSubscriptions, SendEmail, SendSms, SendPush, SendWebPush,
    TriggerCampaign, StopCampaign, GetCampaignReport, ListCampaigns, GetProfileCount,
    GetEventCount, StartProfileExport, StartEventExport, GetProfileExportPage,
    GetEventExportPage, GetVariables, OnSubscriptionGroupChanged, OnNewEvent,
], Field(discriminator="operation")]


class CleverTapNodeConfig(NodeConfig[Operation, CleverTapCredential]):
    pass


ROUTES = {
    "list_subscription_groups": ("GET", "/category-groups"),
    "on_subscription_group_changed": ("GET", "/category-groups"),
    "get_profile": ("GET", "/1/profile.json"),
    "upload_profiles": ("POST", "/1/upload"),
    "upload_event": ("POST", "/1/upload"),
    "delete_profile": ("POST", "/1/delete/profiles.json"),
    "demerge_profiles": ("POST", "/1/demerge/profiles.json"),
    "set_subscriptions": ("POST", "/1/subscribe"),
    "send_email": ("POST", "/1/send/email.json"),
    "send_sms": ("POST", "/1/send/sms.json"),
    "send_push": ("POST", "/1/send/push.json"),
    "send_web_push": ("POST", "/1/send/webpush.json"),
    "trigger_campaign": ("POST", "/1/send/externaltrigger.json"),
    "stop_campaign": ("POST", "/1/targets/stop.json"),
    "get_campaign_report": ("POST", "/1/targets/result.json"),
    "list_campaigns": ("POST", "/1/targets/list.json"),
    "get_profile_count": ("POST", "/1/counts/profiles.json"),
    "get_event_count": ("POST", "/1/counts/events.json"),
    "start_profile_export": ("POST", "/1/profiles.json"),
    "start_event_export": ("POST", "/1/events.json"),
    "get_profile_export_page": ("GET", "/1/profiles.json"),
    "get_event_export_page": ("GET", "/1/events.json"),
    "get_variables": ("POST", "/1/getVars"),
}


class CleverTapNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-clevertap"
    connection_evidence = ConnectionEvidence(noun="subscription groups", operation="list_subscription_groups")

    @classmethod
    def get_config_model(cls):
        return CleverTapNodeConfig

    @staticmethod
    def _payload(op):
        if isinstance(op, _Range):
            return {"from": op.from_date, "to": op.to_date, **({"event_name": op.event_name} if isinstance(op, _EventRange) else {})}
        if isinstance(op, UploadProfiles):
            return {"d": [{"objectId": op.object_id, "type": "profile", "profileData": op.profile_data}]}
        if isinstance(op, UploadEvent):
            return {"d": [{"identity": op.identity, "type": "event", "evtName": op.event_name, "evtData": op.event_data}]}
        if isinstance(op, DeleteProfile):
            return {"identity": op.identity}
        if isinstance(op, DemergeProfiles):
            return {"identities": op.identities}
        if isinstance(op, SetSubscriptions):
            return {"d": [s.model_dump() for s in op.subscriptions]}
        if isinstance(op, _Send):
            content = {"body": op.body}
            for field in ("title", "subject", "sender_name"):
                if hasattr(op, field):
                    content[field] = getattr(op, field)
            return {"to": op.to.model_dump(exclude_none=True), "tag_group": op.tag_group,
                    "respect_frequency_caps": op.respect_frequency_caps, "content": content}
        if isinstance(op, TriggerCampaign):
            return {"to": op.to.model_dump(exclude_none=True), "campaign_id": op.campaign_id}
        if isinstance(op, (StopCampaign, GetCampaignReport)):
            return {"id": op.campaign_id}
        if isinstance(op, GetVariables):
            return {"identity": op.identity, "includeDefaults": op.include_defaults}
        return None

    async def _request(self, op):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a CleverTap account")
        host = "api.clevertap.com" if credential.region == "eu1" else credential.region + ".api.clevertap.com"
        method, path = ROUTES[op.operation]
        params = {"identity": op.identity} if isinstance(op, GetProfile) else {"cursor": op.cursor} if isinstance(op, (GetProfileExportPage, GetEventExportPage)) else None
        headers = {"X-CleverTap-Account-Id": credential.account_id, "X-CleverTap-Passcode": credential.passcode,
                   "Content-Type": "application/json", "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://" + host + path, params=params, headers=headers, json=self._payload(op))
        # Never retry writes: timeouts can occur after a message was queued.
        if not 200 <= response.status_code < 300:
            raise ValueError(f"CleverTap HTTP {response.status_code}: " + self._safe_error(response.text, credential))
        if len(response.content) > 10_000_000:
            raise ValueError("CleverTap response exceeds 10 MB; use a smaller export batch")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("CleverTap did not return JSON") from None
        if not isinstance(data, dict) or data.get("status") not in {"success", "partial"}:
            raise ValueError("CleverTap: " + self._safe_error(json.dumps(data), credential))
        if data.get("unprocessed"):
            raise ValueError("CleverTap left records unprocessed; inspect the account before retrying")
        return data

    @staticmethod
    def _safe_error(text, credential):
        for secret in (credential.account_id, credential.passcode):
            text = text.replace(secret, "[redacted]")
        return text[:1000]

    @staticmethod
    def _groups(data):
        groups = data.get("list")
        if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get("name"), str) or type(g.get("key")) is not int or type(g.get("updated_on")) is not int or type(g.get("created_on")) is not int for g in groups):
            raise ValueError("CleverTap returned invalid subscription groups")
        return sorted(groups, key=lambda g: (g["updated_on"], g["key"]))

    @staticmethod
    def _event_key(record):
        # Profile attributes and summary counts are mutable enrichment, not event
        # identity. Prefer CleverTap's stable objectId to a changeable identity.
        identifiers = {key: value for key, value in record["profile"].items() if key in {"objectId", "identity"}}
        if "objectId" in identifiers:
            identifiers = {"objectId": identifiers["objectId"]}
        immutable = {key: value for key, value in record.items() if key in {"ts", "event_props", "session_props"}}
        immutable["profile"] = identifiers
        return hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def _poll_events(self, op):
        today = datetime.now(ZoneInfo(op.account_timezone)).date()
        start = today - timedelta(days=op.lookback_days - 1)
        opened = await self._request(StartEventExport(event_name=op.event_name,
            from_date=int(start.strftime("%Y%m%d")), to_date=int(today.strftime("%Y%m%d"))))
        cursor = opened.get("cursor")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("CleverTap did not return an event export cursor")
        records, seen_cursors, warning = [], set(), None
        for _ in range(100):
            seen_cursors.add(cursor)
            page = await self._request(GetEventExportPage(cursor=cursor))
            if page.get("status") == "success" and "records" not in page and not page.get("next_cursor"):
                break  # Documented terminal response: {"status": "success"}.
            batch = page.get("records")
            if not isinstance(batch, list) or any(not isinstance(r, dict) or type(r.get("ts")) is not int or not isinstance(r.get("profile"), dict) or not isinstance(r.get("events"), dict) for r in batch):
                raise ValueError("CleverTap returned invalid event export records")
            records.extend(batch)
            if len(records) > 10000:
                raise ValueError("Event window exceeds 10,000 records; narrow the event or lookback window")
            cursor = page.get("next_cursor")
            if not cursor:
                break
            if not isinstance(cursor, str):
                raise ValueError("CleverTap returned an invalid continuation cursor")
            if cursor in seen_cursors:
                # A provider repeating its own cursor cannot make forward progress.
                # Deliver the observed events, explicitly report incomplete coverage,
                # and retry the same rolling window next tick; never assert a full scan.
                warning = "CleverTap repeated an export cursor. These are observed events only; full window coverage could not be verified. The next poll retries the window."
                break
        else:
            raise ValueError("Event export exceeds 100 pages; narrow the event or lookback window")
        unique = list({self._event_key(record): record for record in records}.values())
        fresh = await self._filter_unseen(unique, self._event_key)
        return {"operation": op.operation, "event_name": op.event_name, "records": fresh,
                "new_event_count": len(fresh), "scan_complete": warning is None, "warning": warning}

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, OnNewEvent):
            output = await self._poll_events(op)
            await self.emit(output)
            return output
        data = await self._request(op)
        if isinstance(op, (ListSubscriptionGroups, OnSubscriptionGroupChanged)):
            groups = self._groups(data)
            if isinstance(op, OnSubscriptionGroupChanged):
                groups = await self._filter_unseen(groups, lambda g: str(g["key"]) + ":" + str(g["updated_on"]))
                output = {"operation": op.operation, "groups": groups, "changed_group_count": len(groups)}
            else:
                output = {"operation": op.operation, "status": data["status"], "groups": groups}
        else:
            output = {"operation": op.operation, **data}
        await self.emit(output)
        return output

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") == "on_new_event":
            records = output.get("records", [])
            if not records:
                return None
            lines = [f"- {output['event_name']} at {r['ts']} in CleverTap. User profile and IDs: {json.dumps(r['profile'], ensure_ascii=False)}. Complete event record: {json.dumps(r, ensure_ascii=False)}" for r in records[:10]]
            warning = "\n" + output["warning"] if output.get("warning") else ""
            return {"text": f"CleverTap: {len(records)} new user event(s).\n" + "\n".join(lines) + warning, "conversation_key": None}
        if output.get("operation") != "on_subscription_group_changed":
            return super().resolve_agent_event(output)
        groups = output.get("groups", [])
        if not groups:
            return None
        lines = [f"- {g['name']} (group key {g['key']}; updated {g['updated_on']}): {g.get('description', '')}; channels {', '.join(g.get('channels', []))}" for g in groups[:20]]
        return {"text": f"CleverTap: {len(groups)} new or updated subscription group(s) in your account.\n" + "\n".join(lines), "conversation_key": None}
