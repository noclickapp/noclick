"""Loopy Loyalty stamp-card automation against the published v1 contract.

A manually supplied API key, signing secret and username produce a fresh HS256
JWT for each request; credentials and authorization headers never enter output.
"""
from __future__ import annotations

import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.loopyloyalty.com/v1"
TYPE = "loopy_loyalty_api_key"


def picker(field, parent=None):
    spec = {"field_name": field, "allow_custom": True, "placeholder": "Choose a record", "custom_placeholder": "Paste Loopy Loyalty ID"}
    if parent:
        spec["depends_on"] = parent
    return {"x-dynamic-options": spec}


class LoopyLoyaltyCredential(BaseModel):
    model_config = ConfigDict(title="Loopy Loyalty API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.loopyloyalty.com/settings",
        "x-credential-instructions": "Copy your API key, API secret and account username from Loopy Loyalty Settings. NoClick signs a short-lived JWT for each request. Use an account with permission to manage the campaigns you automate.",
    })
    credential_type: Literal["loopy_loyalty_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, title="API secret", json_schema_extra={"ui:widget": "password"})
    username: str = Field(..., min_length=1, title="Username")

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        return clean_secret(value, field_name=info.field_name)

    @field_validator("username")
    @classmethod
    def user(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter the Loopy Loyalty account username")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListCampaigns(Input):
    """List the connected account's campaigns."""
    operation: Literal["list_campaigns"] = "list_campaigns"


class Campaign(Input):
    campaign_id: str = Field(..., min_length=1, json_schema_extra=picker("campaign_id"))


class GetCampaign(Campaign):
    """Get a campaign by its ID."""
    operation: Literal["get_campaign"] = "get_campaign"


class GetCampaignByName(Input):
    """Get a campaign by its exact name."""
    operation: Literal["get_campaign_by_name"] = "get_campaign_by_name"
    name: str = Field(..., min_length=1)


class Page(Campaign):
    start: int = Field(0, ge=0, description="Zero-based row offset; this operation returns one page.")
    length: int = Field(50, ge=1, le=1000, description="Rows requested per page.")
    search: Optional[str] = None


class ListCards(Page):
    """List one page of cards in a campaign."""
    operation: Literal["list_cards"] = "list_cards"


class ListEvents(Page):
    """List one page of campaign transaction events."""
    operation: Literal["list_events"] = "list_events"


class Card(Input):
    card_id: str = Field(..., min_length=1, description="Card ID returned by list cards or enrol customer.")


class GetCard(Card):
    """Get a card, optionally including events and rewards."""
    operation: Literal["get_card"] = "get_card"
    include_events: bool = False
    include_rewards: bool = False


class UniqueCard(Campaign):
    unique_id_type: Literal["email", "phone", "text"]
    unique_id_value: str = Field(..., min_length=1)


class GetCardByUniqueId(UniqueCard):
    """Find a card using the campaign's unique customer identifier."""
    operation: Literal["get_card_by_unique_id"] = "get_card_by_unique_id"


class EnrolCustomer(Campaign):
    """Enrol a customer using the campaign's configured data field names."""
    operation: Literal["enrol_customer"] = "enrol_customer"
    customer_data: dict[str, str] = Field(..., description="Keys are the field names from Edit design data in Loopy Loyalty.")
    data_consent_opt_in: bool = Field(..., description="The customer's actual consent choice.")
    time_zone_offset: Optional[int] = Field(None, description="Timezone offset used by campaign expiry settings.")


class Scan(Input):
    scan_latitude: Optional[float] = Field(None, ge=-90, le=90)
    scan_longitude: Optional[float] = Field(None, ge=-180, le=180)


class AddStamps(Card, Scan):
    """Add stamps to a card; a negative number deducts stamps."""
    operation: Literal["add_stamps"] = "add_stamps"
    stamps: int


class RedeemReward(Card, Scan):
    """Redeem rewards by card ID, using a one-based reward type."""
    operation: Literal["redeem_reward"] = "redeem_reward"
    reward_type: int = Field(..., ge=1)
    rewards_to_redeem: int = Field(1, ge=1)


class AddStampsByUniqueId(UniqueCard, Scan):
    """Add or deduct stamps using the customer's unique identifier."""
    operation: Literal["add_stamps_by_unique_id"] = "add_stamps_by_unique_id"
    stamps: int


class RedeemRewardByUniqueId(UniqueCard, Scan):
    """Redeem rewards using the customer's unique identifier."""
    operation: Literal["redeem_reward_by_unique_id"] = "redeem_reward_by_unique_id"
    reward_type: int = Field(..., ge=1)
    rewards_to_redeem: int = Field(1, ge=1)


class SendCardMessage(Card):
    """Send a message to one card; delivery depends on the mobile wallet."""
    operation: Literal["send_card_message"] = "send_card_message"
    message: str = Field(..., min_length=1)


class ResyncCard(Card):
    """Request a card resync with the mobile wallet."""
    operation: Literal["resync_card"] = "resync_card"


class ListLocations(Input):
    """List the connected account's locations."""
    operation: Literal["list_locations"] = "list_locations"


class GetLocation(Input):
    """Get a location by ID."""
    operation: Literal["get_location"] = "get_location"
    location_id: str = Field(..., min_length=1, json_schema_extra=picker("location_id"))


LoopyLoyaltyConfig = Annotated[Union[ListCampaigns, GetCampaign, GetCampaignByName, ListCards, ListEvents,
    GetCard, GetCardByUniqueId, EnrolCustomer, AddStamps, RedeemReward, AddStampsByUniqueId,
    RedeemRewardByUniqueId, SendCardMessage, ResyncCard, ListLocations, GetLocation], Field(discriminator="operation")]


class LoopyLoyaltyFullConfig(NodeConfig[LoopyLoyaltyConfig, LoopyLoyaltyCredential]):
    pass


def segment(value):
    # Encode each user-controlled path component, including slashes, independently.
    if str(value) in {".", ".."}:
        raise ValueError("Use a Loopy Loyalty record identifier, not a dot segment")
    return quote(str(value), safe="")


def request_for(op):
    """Each native operation maps to exactly one published API operation."""
    action = op.operation
    method, params, body = "GET", {}, None
    if action == "list_campaigns":
        path = "/campaigns"
    elif action == "get_campaign":
        path = "/campaign/id/" + segment(op.campaign_id)
    elif action == "get_campaign_by_name":
        path = "/campaign/name/" + segment(op.name)
    elif action in {"list_cards", "list_events"}:
        method = "POST"
        path = ("/card/cid/" if action == "list_cards" else "/events/analytics/transactions/") + segment(op.campaign_id)
        body = {"cid": op.campaign_id, "dt": {"start": str(op.start), "length": str(op.length)}}
        if op.search is not None:
            body["dt"]["search"] = op.search
    elif action == "get_card":
        path = "/card/" + segment(op.card_id)
        params = {"includeEvents": str(op.include_events).lower(), "includeRewards": str(op.include_rewards).lower()}
    elif isinstance(op, UniqueCard):
        path = "/uniquecard/campaignid/" + "/".join(segment(v) for v in (op.campaign_id, op.unique_id_type, op.unique_id_value))
        if action != "get_card_by_unique_id":
            method = "POST"
            body = {"campaignId": op.campaign_id, "uniqueIdType": op.unique_id_type, "uniqueIdValue": op.unique_id_value}
    elif action == "enrol_customer":
        method, path = "POST", "/enrol/" + segment(op.campaign_id)
        body = {"campaignId": op.campaign_id, "customerData": op.customer_data, "dataConsentOptIn": op.data_consent_opt_in}
        if op.time_zone_offset is not None:
            body["timeZoneOffset"] = str(op.time_zone_offset)
    elif action in {"add_stamps", "redeem_reward", "resync_card"}:
        method, path = "POST", "/card/cid/" + segment(op.card_id)
        body = {"cid": op.card_id}
        if action == "resync_card":
            method, path = "PUT", path + "/resync"
    elif action == "send_card_message":
        method, path, body = "POST", "/card/push", {"cardID": op.card_id, "message": op.message}
    elif action == "list_locations":
        path = "/locations"
    elif action == "get_location":
        path = "/location/" + segment(op.location_id)
    else:
        raise ValueError("Unknown Loopy Loyalty operation")
    if isinstance(op, Scan):
        if hasattr(op, "stamps"):
            path += "/addStamps/" + str(op.stamps)
            body["stamps"] = str(op.stamps)
        else:
            path += "/redeemReward/" + str(op.reward_type) + "/" + str(op.rewards_to_redeem)
            body.update(rewardType=str(op.reward_type), rewardsToRedeem=str(op.rewards_to_redeem))
        for field, wire in (("scan_latitude", "scanLatitude"), ("scan_longitude", "scanLongitude")):
            if getattr(op, field) is not None:
                body[wire] = getattr(op, field)
    return method, path, params, body


class LoopyLoyaltyNode(WorkflowNode):
    integration_type = "automation-loopy-loyalty"
    connection_evidence = ConnectionEvidence(field="campaign_id", noun="Loopy Loyalty campaigns")

    @classmethod
    def get_config_model(cls):
        return LoopyLoyaltyFullConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in {"campaign_id", "location_id"}:
            return {"options": [], "next_page_token": None}
        from nodes.core.run_op import run_node_operation
        result = await run_node_operation(node_type=cls.integration_type,
            operation="list_campaigns" if field_name == "campaign_id" else "list_locations",
            arguments={}, credential_data=credential_data, user_id="")
        if result.get("status") != "success":
            raise ValueError(result.get("error", "Loopy Loyalty choices are unavailable"))
        options = []
        for row in result["data"].get("rows", []):
            value = row.get("value", {})
            if isinstance(value, dict) and value.get("id"):
                label = value.get("name") or value["id"]
                if not search or search.casefold() in label.casefold():
                    options.append({"value": value["id"], "label": label})
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Loopy Loyalty API key")
        op = self.config.config
        method, path, params, body = request_for(op)
        issued = int(time.time())
        token = jwt.encode({"uid": credential.api_key, "pid": credential.api_key,
            "username": credential.username, "iat": issued, "exp": issued + 60}, credential.api_secret, algorithm="HS256")
        # Fixed HTTPS origin, no redirects, and no automatic write retries.
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": token, "Accept": "application/json"})
        except httpx.HTTPError:
            return {"status": "error", "error": "Loopy Loyalty request did not complete; inspect writes before retrying"}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "Loopy Loyalty returned a non-JSON response"}
        if not isinstance(data, dict):
            return {"status": "error", "http_status": response.status_code, "error": "Loopy Loyalty returned an unexpected response"}
        if not 200 <= response.status_code < 300 or data.get("error") or data.get("success") is False:
            detail = data.get("message") or data.get("error") or "Loopy Loyalty did not confirm the request"
            detail = str(detail)
            for secret in (credential.api_key, credential.api_secret, token):
                detail = detail.replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": detail}
        output = {"status": "success", "operation": op.operation, "data": data}
        if isinstance(op, Page):
            rows = data.get("data", [])
            total = data.get("recordsFiltered", data.get("recordsTotal"))
            next_start = op.start + len(rows) if isinstance(rows, list) else op.start
            output["next_start"] = next_start if total is not None and next_start < int(total) and next_start > op.start else None
        return output
