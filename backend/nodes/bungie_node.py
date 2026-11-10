"""Bungie account reads and Destiny 2 actions from the published 2.21.9 contract.

A manually supplied API key and short-lived bearer token enable account proof and
writes. The activity poll uses the contract's newest-first activity history.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.bungie import BUNGIE_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.bungie.net/Platform"


def _decimal_id(value):
    # IDs exceed JavaScript's safe integer range: the editor must keep text.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Use a decimal Bungie ID")
    text = str(value)
    if not text.isascii() or not text.isdecimal() or len(text) > 19 or int(text) > 9223372036854775807:
        raise ValueError("Use a decimal Bungie ID within the signed 64-bit range")
    return text


BungieId = Annotated[str, BeforeValidator(_decimal_id), Field(pattern=r"^[0-9]{1,19}$")]



class BungieTokenCredential(BaseModel):
    model_config = ConfigDict(title="Bungie API Key and Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.bungie.net/en/Application",
            "x-credential-instructions": "Paste your application's API key and an existing Bungie access token from that same application. The token needs ReadBasicUserProfile for connection, ReadDestinyInventoryAndVault for private inventory, and MoveEquipDestinyItems for item and loadout actions. Tokens expire; replace the access token when it expires. NoClick does not refresh this manually supplied token.",
        })
    credential_type: Literal["bungie_token"] = Field("bungie_token", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})
    access_token: str = Field(..., title="Access token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "access_token", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name, key=True)
        if any(ch.isspace() for ch in value):
            raise ValueError("Paste the credential value without a header or spaces")
        return value


class BungieInput(BaseModel):
    model_config = ConfigDict(extra="ignore")



class BungieGetCurrentUserConfig(BungieInput):
    """Returns a list of accounts associated with signed in user. This is useful for OAuth implementations that do not give you access to the token response."""
    operation: Literal['get_current_user'] = Field('get_current_user', json_schema_extra={"ui:hidden": True})


class BungieGetManifestConfig(BungieInput):
    """Returns the current version of the manifest as a json object."""
    operation: Literal['get_manifest'] = Field('get_manifest', json_schema_extra={"ui:hidden": True})


class BungieSearchPlayerConfig(BungieInput):
    """Returns a list of Destiny memberships given a global Bungie Display Name. This method will hide overridden memberships due to cross save."""
    operation: Literal['search_player'] = Field('search_player', json_schema_extra={"ui:hidden": True})
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')
    displayName: str = Field(...)
    displayNameCode: int = Field(...)


class BungieGetMembershipsConfig(BungieInput):
    """Returns a list of accounts associated with the supplied membership ID and membership type. This will include all linked accounts (even when hidden) if supplied credentials permit it."""
    operation: Literal['get_memberships'] = Field('get_memberships', json_schema_extra={"ui:hidden": True})
    membershipId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')


class BungieGetProfileConfig(BungieInput):
    """Returns Destiny Profile information for the supplied membership."""
    operation: Literal['get_profile'] = Field('get_profile', json_schema_extra={"ui:hidden": True})
    components: list[int] = Field([100], min_length=1, max_length=100, description='Destiny component numbers, e.g. 100 (profile), 200 (characters), 300 (item instances). At least one required.')
    destinyMembershipId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')


class BungieGetCharacterConfig(BungieInput):
    """Returns character information for the supplied character."""
    operation: Literal['get_character'] = Field('get_character', json_schema_extra={"ui:hidden": True})
    characterId: BungieId = Field(...)
    components: list[int] = Field([200], min_length=1, max_length=100, description='Destiny component numbers, e.g. 100 (profile), 200 (characters), 300 (item instances). At least one required.')
    destinyMembershipId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')


class BungieGetItemConfig(BungieInput):
    """Retrieve the details of an instanced Destiny Item. An instanced Destiny item is one with an ItemInstanceId. Non-instanced items, such as materials, have no useful instance-specific details and thus are not queryable here."""
    operation: Literal['get_item'] = Field('get_item', json_schema_extra={"ui:hidden": True})
    components: list[int] = Field([300], min_length=1, max_length=100, description='Destiny component numbers, e.g. 100 (profile), 200 (characters), 300 (item instances). At least one required.')
    destinyMembershipId: BungieId = Field(...)
    itemInstanceId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')


class BungieGetVendorsConfig(BungieInput):
    """Get currently available vendors from the list of vendors that can possibly have rotating inventory. Note that this does not include things like preview vendors and vendors-as-kiosks, neither of whom have rotating/dynamic inventories. Use their definitions as-is for those."""
    operation: Literal['get_vendors'] = Field('get_vendors', json_schema_extra={"ui:hidden": True})
    characterId: BungieId = Field(...)
    components: list[int] = Field([400, 402], min_length=1, max_length=100, description='Destiny component numbers, e.g. 100 (profile), 200 (characters), 300 (item instances). At least one required.')
    destinyMembershipId: BungieId = Field(...)
    filter: int | None = Field(None, description='The filter of what vendors and items to return, if any.')
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')


class BungieGetMilestonesConfig(BungieInput):
    """Gets public information about currently available Milestones."""
    operation: Literal['get_milestones'] = Field('get_milestones', json_schema_extra={"ui:hidden": True})


class BungieGetActivityHistoryConfig(BungieInput):
    """Gets activity history stats for indicated character."""
    operation: Literal['get_activity_history'] = Field('get_activity_history', json_schema_extra={"ui:hidden": True})
    characterId: BungieId = Field(...)
    count: int = Field(25, ge=1, le=250)
    destinyMembershipId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254, description='The types of membership the Accounts system supports. This is the external facing enum used in place of the internal-only Bungie.SharedDefinitions.MembershipType.')
    mode: int = Field(0, description="For historical reasons, this list will have both D1 and D2-relevant Activity Modes in it. Please don't take this to mean that some D1-only feature is coming back!")
    page: int = Field(0, ge=0)


class BungieGetPostGameReportConfig(BungieInput):
    """Gets the available post game carnage report for the activity ID."""
    operation: Literal['get_post_game_report'] = Field('get_post_game_report', json_schema_extra={"ui:hidden": True})
    activityId: BungieId = Field(...)


class BungieTransferItemConfig(BungieInput):
    """Transfer an item to/from your vault. You must have a valid Destiny account. You must also pass BOTH a reference AND an instance ID if it's an instanced item. itshappening.gif"""
    operation: Literal['transfer_item'] = Field('transfer_item', json_schema_extra={"ui:hidden": True})
    itemReferenceHash: int = Field(..., ge=0, le=4294967295)
    stackSize: int = Field(..., ge=1)
    transferToVault: bool = Field(...)
    itemId: BungieId = Field(..., description='The instance ID of the item for this action request.')
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungiePullFromPostmasterConfig(BungieInput):
    """Extract an item from the Postmaster, with whatever implications that may entail. You must have a valid Destiny account. You must also pass BOTH a reference AND an instance ID if it's an instanced item."""
    operation: Literal['pull_from_postmaster'] = Field('pull_from_postmaster', json_schema_extra={"ui:hidden": True})
    itemReferenceHash: int = Field(..., ge=0, le=4294967295)
    stackSize: int = Field(..., ge=1)
    itemId: BungieId = Field(..., description='The instance ID of the item for this action request.')
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungieEquipItemConfig(BungieInput):
    """Equip an item. You must have a valid Destiny Account, and either be in a social space, in orbit, or offline."""
    operation: Literal['equip_item'] = Field('equip_item', json_schema_extra={"ui:hidden": True})
    itemId: BungieId = Field(..., description='The instance ID of the item for this action request.')
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungieEquipItemsConfig(BungieInput):
    """Equip a list of items by itemInstanceIds. You must have a valid Destiny Account, and either be in a social space, in orbit, or offline. Any items not found on your character will be ignored."""
    operation: Literal['equip_items'] = Field('equip_items', json_schema_extra={"ui:hidden": True})
    itemIds: list[BungieId] = Field(..., min_length=1, max_length=100, description="Item instance IDs as quoted decimal strings, to preserve every digit.")
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungieSetItemLockStateConfig(BungieInput):
    """Set the Lock State for an instanced item. You must have a valid Destiny Account."""
    operation: Literal['set_item_lock_state'] = Field('set_item_lock_state', json_schema_extra={"ui:hidden": True})
    state: bool = Field(...)
    itemId: BungieId = Field(..., description='The instance ID of the item for this action request.')
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungieEquipLoadoutConfig(BungieInput):
    """Equip a loadout. You must have a valid Destiny Account, and either be in a social space, in orbit, or offline."""
    operation: Literal['equip_loadout'] = Field('equip_loadout', json_schema_extra={"ui:hidden": True})
    loadoutIndex: int = Field(..., ge=0, le=9, description='The index of the loadout for this action request.')
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungieSnapshotLoadoutConfig(BungieInput):
    """Snapshot a loadout with the currently equipped items."""
    operation: Literal['snapshot_loadout'] = Field('snapshot_loadout', json_schema_extra={"ui:hidden": True})
    colorHash: int = Field(..., ge=0, le=4294967295)
    iconHash: int = Field(..., ge=0, le=4294967295)
    nameHash: int = Field(..., ge=0, le=4294967295)
    loadoutIndex: int = Field(..., ge=0, le=9, description='The index of the loadout for this action request.')
    characterId: BungieId = Field(...)
    membershipType: int = Field(..., ge=-1, le=254)


class BungieOnNewActivityConfig(PollTriggerConfigBase):
    """Watch a newest-first window of completed activities for one character.

    Poll frequently enough that fewer than 250 activities complete between polls.
    The first poll records a baseline; changing the character resets that baseline.
    """
    operation: Literal["on_new_activity"] = Field("on_new_activity", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Completed Activity",
        "x-category": "Triggers"})
    membershipType: int = Field(..., ge=0, le=254)
    destinyMembershipId: BungieId = Field(...)
    characterId: BungieId = Field(...)
    mode: int = Field(0, ge=0, description="Destiny activity mode; 0 includes all modes.")



BungieConfig = Annotated[Union[BungieGetCurrentUserConfig, BungieGetManifestConfig, BungieSearchPlayerConfig, BungieGetMembershipsConfig, BungieGetProfileConfig, BungieGetCharacterConfig, BungieGetItemConfig, BungieGetVendorsConfig, BungieGetMilestonesConfig, BungieGetActivityHistoryConfig, BungieGetPostGameReportConfig, BungieTransferItemConfig, BungiePullFromPostmasterConfig, BungieEquipItemConfig, BungieEquipItemsConfig, BungieSetItemLockStateConfig, BungieEquipLoadoutConfig, BungieSnapshotLoadoutConfig, BungieOnNewActivityConfig], Field(discriminator="operation")]


class BungieFullConfig(NodeConfig[BungieConfig, BungieTokenCredential]):
    pass


# Each entry maps to exactly one provider operation; no arbitrary paths.
OPERATIONS = {'get_current_user': ('GET', '/User/GetMembershipsForCurrentUser/', [], []),
 'get_manifest': ('GET', '/Destiny2/Manifest/', [], []),
 'search_player': ('POST',
                   '/Destiny2/SearchDestinyPlayerByBungieName/{membershipType}/',
                   [],
                   ['displayName', 'displayNameCode']),
 'get_memberships': ('GET', '/User/GetMembershipsById/{membershipId}/{membershipType}/', [], []),
 'get_profile': ('GET',
                 '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/',
                 ['components'],
                 []),
 'get_character': ('GET',
                   '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/Character/{characterId}/',
                   ['components'],
                   []),
 'get_item': ('GET',
              '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/Item/{itemInstanceId}/',
              ['components'],
              []),
 'get_vendors': ('GET',
                 '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/Character/{characterId}/Vendors/',
                 ['components', 'filter'],
                 []),
 'get_milestones': ('GET', '/Destiny2/Milestones/', [], []),
 'get_activity_history': ('GET',
                          '/Destiny2/{membershipType}/Account/{destinyMembershipId}/Character/{characterId}/Stats/Activities/',
                          ['count', 'mode', 'page'],
                          []),
 'get_post_game_report': ('GET', '/Destiny2/Stats/PostGameCarnageReport/{activityId}/', [], []),
 'transfer_item': ('POST',
                   '/Destiny2/Actions/Items/TransferItem/',
                   [],
                   ['itemReferenceHash',
                    'stackSize',
                    'transferToVault',
                    'itemId',
                    'characterId',
                    'membershipType']),
 'pull_from_postmaster': ('POST',
                          '/Destiny2/Actions/Items/PullFromPostmaster/',
                          [],
                          ['itemReferenceHash',
                           'stackSize',
                           'itemId',
                           'characterId',
                           'membershipType']),
 'equip_item': ('POST',
                '/Destiny2/Actions/Items/EquipItem/',
                [],
                ['itemId', 'characterId', 'membershipType']),
 'equip_items': ('POST',
                 '/Destiny2/Actions/Items/EquipItems/',
                 [],
                 ['itemIds', 'characterId', 'membershipType']),
 'set_item_lock_state': ('POST',
                         '/Destiny2/Actions/Items/SetLockState/',
                         [],
                         ['state', 'itemId', 'characterId', 'membershipType']),
 'equip_loadout': ('POST',
                   '/Destiny2/Actions/Loadouts/EquipLoadout/',
                   [],
                   ['loadoutIndex', 'characterId', 'membershipType']),
 'snapshot_loadout': ('POST',
                      '/Destiny2/Actions/Loadouts/SnapshotLoadout/',
                      [],
                      ['colorHash',
                       'iconHash',
                       'nameHash',
                       'loadoutIndex',
                       'characterId',
                       'membershipType'])}


class BungieNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-bungie"
    scope_registry = BUNGIE_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="Bungie account memberships", operation="get_current_user",
        label_keys=("displayName", "membershipId"), identity_operation="get_current_user",
        identity_keys=("displayName", "uniqueName", "membershipId"),
    )

    @classmethod
    def get_config_model(cls):
        return BungieFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Bungie API credentials")
        headers = {"X-API-Key": credential.api_key,
                   "Authorization": "Bearer " + credential.access_token,
                   "Accept": "application/json"}
        async with guarded_async_client() as client:
            response = await client.request(method, BASE_URL + path, headers=headers,
                params=params, json=body, timeout=30, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Bungie returned an invalid response envelope")
        # Bungie returns HTTP 200 for API failures; ErrorCode 1 means success.
        if data.get("ErrorCode") != 1:
            message = data.get("Message") or data.get("ErrorStatus") or "Bungie did not confirm the request"
            # Never include credentials even if a provider reflects request text.
            message = str(message).replace(credential.api_key, "[redacted]").replace(credential.access_token, "[redacted]")
            raise ValueError(message)
        if "Response" not in data:
            raise ValueError("Bungie response is missing Response")
        return data["Response"]

    async def execute(self, inputs):
        config = self.config.config
        self.scope_registry.require(config.operation)
        polling = isinstance(config, BungieOnNewActivityConfig)
        name = "get_activity_history" if polling else config.operation
        method, path, query_fields, body_fields = OPERATIONS[name]
        values = config.model_dump(exclude_none=True)
        if polling:
            values.update(count=250, page=0)
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: ",".join(map(str, values[key])) if isinstance(values[key], list) else values[key]
                  for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields} if body_fields else None
        if body is not None:
            for field in ("itemId", "characterId"):
                if field in body:
                    body[field] = int(body[field])
            if "itemIds" in body:
                body["itemIds"] = [int(value) for value in body["itemIds"]]
        data = await self._request(method, path, params=params, body=body)
        if polling:
            if not isinstance(data, dict):
                raise ValueError("Bungie activity history must be an object")
            activities = data.get("activities", [])
            if not isinstance(activities, list):
                raise ValueError("Bungie activities must be a list")
            for activity in activities:
                if not isinstance(activity, dict) or not isinstance(activity.get("activityDetails"), dict) or not activity["activityDetails"].get("instanceId"):
                    raise ValueError("Bungie activity lacks its documented instance ID")
            fresh = await self._filter_unseen(activities, lambda activity: str(activity["activityDetails"]["instanceId"]))
            return {"activities": fresh, "new_activity_count": len(fresh),
                    "membershipType": config.membershipType, "destinyMembershipId": config.destinyMembershipId,
                    "characterId": config.characterId}
        return {"data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        activities = output.get("activities", [])
        if not activities:
            return None
        return {"text": "New Destiny 2 completed activities for character " + str(output.get("characterId"))
                + " on membership " + str(output.get("destinyMembershipId")) + ": "
                + ", ".join(str(activity["activityDetails"]["instanceId"]) + " at " + str(activity.get("period", "unknown time"))
                            for activity in activities), "data": output}
