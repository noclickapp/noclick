"""KumpeApps v5 account, chore, allowance and wishlist automation.

Requests use the provider's published query parameters and a pasted auth key.
A scheduled poll detects new allowance transactions within a documented day window.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://restapi.kumpeapps.com/v5"
CREDENTIAL_TYPE = "kumpeapps_auth_key"


class KumpeAppsAuthKeyCredential(BaseModel):
    model_config = ConfigDict(title="KumpeApps Auth Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.kumpeapps.com/python/",
            "x-credential-instructions": "Paste an existing user auth key obtained through KumpeApps' documented /authentication/authkey flow. API access requires the developer's approval. Use the user auth key, not an app key; NoClick sends it as X-Auth only to restapi.kumpeapps.com."
        })
    credential_type: Literal["kumpeapps_auth_key"] = Field("kumpeapps_auth_key", json_schema_extra={"ui:hidden": True})
    auth_key: str = Field(..., title="Auth key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("auth_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="Auth key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the auth key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCurrentUserConfig(_Operation):
    """Gets user info."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})
    enableBool: bool | None = Field(None, title="Enable Bool", description="Use bool values instead of Int 0/1")


class ListUsersConfig(_Operation):
    """returns list of users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    isChild: bool | None = Field(None, title="Is Child", description="Filter Search by isChild flag")
    isActive: bool | None = Field(None, title="Is Active", description="Filter Search by isActive flag")
    isAdmin: bool | None = Field(None, title="Is Admin", description="Filter Search by isAdmin flag")
    enableAllowance: bool | None = Field(None, title="Enable Allowance", description="Filter Search by enableAllowance flag")
    enableChores: bool | None = Field(None, title="Enable Chores", description="Filter Search by enableChores flag")
    userID: int | None = Field(None, title="User ID", description="userID of user to search")
    username: str | None = Field(None, title="Username", description="Username of user to search", max_length=10000)
    email: str | None = Field(None, title="Email", description="Email address of user to search", max_length=10000)


class UpdateUserConfig(_Operation):
    """updates user."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    userID: int = Field(..., title="User ID", description="userID of the user you wish to update")
    username: str = Field(..., title="Username", description="username of user to create", max_length=10000)
    email: str = Field(..., title="Email", description="email address of user to create", max_length=10000)
    firstName: str = Field(..., title="First Name", description="First Name of user to create", max_length=10000)
    lastName: str = Field(..., title="Last Name", description="Last Name of user to create", max_length=10000)
    emoji: str | None = Field(None, title="Emoji", description="emoji character for user", max_length=10000)
    tmdbKey: str | None = Field(None, title="TMDb Key", description="User's TMdB Session Key", max_length=10000)
    enableWishList: bool | None = Field(None, title="Enable Wish List", description="set status of Wish List module enabled")
    enableChores: bool | None = Field(None, title="Enable Chores", description="set status of chores module enabled")
    enableAllowance: bool | None = Field(None, title="Enable Allowance", description="set status of allowance module enabled")
    enableAdmin: bool | None = Field(None, title="Enable Admin", description="set status of isAdmin")
    enableTmdb: bool | None = Field(None, title="Enable Tmdb", description="set status of enableTmdb (movie and tv search)")
    enableObjectDetection: bool | None = Field(None, title="Enable Object Detection", description="set status of enableObjectDetection")


class CreateChildUserConfig(_Operation):
    """adds new child user."""
    operation: Literal["create_child_user"] = Field("create_child_user", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., title="Username", description="username of user to create", max_length=10000)
    password: str = Field(..., title="Password", description="password of user to create", max_length=10000, repr=False, json_schema_extra={"ui:widget": "password"})
    email: str = Field(..., title="Email", description="email address of user to create", max_length=10000)
    firstName: str = Field(..., title="First Name", description="First Name of user to create", max_length=10000)
    lastName: str = Field(..., title="Last Name", description="Last Name of user to create", max_length=10000)


class ListChoresConfig(_Operation):
    """returns list of chores for given user."""
    operation: Literal["list_chores"] = Field("list_chores", json_schema_extra={"ui:hidden": True})
    kidUsername: str | None = Field(None, title="Kid Username", description="Username of kid you wish to search", max_length=10000)
    day: Literal['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Weekly'] | None = Field(None, title="Day", description="Day of week for chores (Weekly for weekly chores)")
    status: str | None = Field(None, title="Status", description="Status of Chore to search", max_length=10000)
    blockDash: bool | None = Field(None, title="Block Dash", description="Filter results by blockDash parameter")
    optional: bool | None = Field(None, title="Optional", description="Filter results by optional parameter")
    canSteal: bool | None = Field(None, title="Can Steal", description="Filter results by canSteal parameter")
    includeCalendar: bool | None = Field(None, title="Include Calendar", description="include calendar notations (default is false)")


class CreateChoreConfig(_Operation):
    """adds chore for given user."""
    operation: Literal["create_chore"] = Field("create_chore", json_schema_extra={"ui:hidden": True})
    kidUsername: str = Field(..., title="Kid Username", description="username of kid to assign the chore to.", max_length=10000)
    day: Literal['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Weekly', 'Today'] | None = Field(None, title="Day", description="day of week (Monday, Tuesday....) for the chore. For weekly chores put Weekly or leave blank")
    nfcTag: str | None = Field(None, title="NFC Tag", description="text field of nfc tag required to check off chore", max_length=10000)
    status: str | None = Field(None, title="Status", description="status of chore (default is todo)", max_length=10000)
    choreName: str = Field(..., title="Chore Name", description="name of chore", max_length=10000)
    choreDescription: str | None = Field(None, title="Chore Description", description="optional chore description", max_length=10000)
    choreNumber: int | None = Field(None, title="Chore Number", description="number priority of chore (default is 5)")
    blockDash: bool | None = Field(None, title="Block Dash", description="block dash option on this chore")
    oneTime: bool | None = Field(None, title="One Time", description="mark as one time chore (does not repeat each week)")
    extraAllowance: int | None = Field(None, title="Extra Allowance", description="ammount of allowance added at end of week for completing this chore")
    optional: bool | None = Field(None, title="Optional", description="mark as optional chore")
    reassignable: bool | None = Field(None, title="Reassignable", description="mark as reassignable (default is true)")
    canSteal: bool | None = Field(None, title="Can Steal", description="mark as sibling can steal chore")
    startDate: str | None = Field(None, title="Start Date", description="date (yyyy-mm-dd) that you wish the chore to start showing up. (default is today)", max_length=10000)
    notes: str | None = Field(None, title="Notes", description="notes added to chore (visable only on reports, kids do not see this note, this is mostly just for the developer)", max_length=10000)
    requireObjectDetection: bool | None = Field(None, title="Require Object Detection", description="require use of camera to detect object detection tag order to check off chore")
    objectDetectionTag: str | None = Field(None, title="Object Detection Tag", description="tag for object detection to search for (required if requireObjectDetection is true)", max_length=10000)
    updatedByAutomation: bool | None = Field(None, title="Updated By Automation", description="true if chore updated via API from an Automation System")
    aiIcon: str | None = Field(None, title="AI icon", description="Notes if AI Icons should be used (n for no, y for yes, e for yes- error)", max_length=10000)
    isCalendar: bool | None = Field(None, title="Is Calendar", description="True if this is a calendar note instead of a chore.")


class UpdateChoreConfig(_Operation):
    """updates chore for given chore id."""
    operation: Literal["update_chore"] = Field("update_chore", json_schema_extra={"ui:hidden": True})
    idChoreList: int = Field(..., title="Id Chore List", description="id number of chore you wish to update")
    status: str | None = Field(None, title="Status", description="new status of chore", max_length=10000)
    stolen: bool | None = Field(None, title="Stolen", description="mark chore as stolen by sibling")
    stolenBy: str | None = Field(None, title="Stolen By", description="username of sibling that stole the chore (required if stolen is true)", max_length=10000)
    nfcTag: str | None = Field(None, title="NFC Tag", description="text field of NFC tag that is required to be scanned to check off this chore (normally null)", max_length=10000)
    notes: str | None = Field(None, title="Notes", description="notes field for chore", max_length=10000)
    latitude: int | None = Field(None, title="Latitude", description="GPS latitude of where the chore was marked")
    longitude: int | None = Field(None, title="Longitude", description="GPS longitude of where the chore was marked")
    altitude: int | None = Field(None, title="Altitude", description="GPS altitude of where the chore was marked")
    updatedByAutomation: bool | None = Field(None, title="Updated By Automation", description="true if updated via API by automation system")
    whereDay: Literal['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Weekly', 'Today'] | None = Field(None, title="Where Day", description="Where day equals...")
    whereStatus: str | None = Field(None, title="Where Status", description="Where status equals...", max_length=10000)
    whereName: str | None = Field(None, title="Where Name", description="Where chore name equals...", max_length=10000)


class DeleteChoreConfig(_Operation):
    """deletes chore for given chore id."""
    operation: Literal["delete_chore"] = Field("delete_chore", json_schema_extra={"ui:hidden": True})
    idChoreList: int = Field(..., title="Id Chore List", description="id of the chore you wish to delete")


class GetAllowanceConfig(_Operation):
    """returns allowance balance and allowance transactions."""
    operation: Literal["get_allowance"] = Field("get_allowance", json_schema_extra={"ui:hidden": True})
    kidUserId: int = Field(..., title="Kid User ID", description="userID of the kid")
    transactionDays: int | None = Field(None, title="Transaction Days", description="number of days you wish to search allowance transactions (default is 90 days)")


class AddAllowanceTransactionConfig(_Operation):
    """adds new allowance transaction to kidUserID."""
    operation: Literal["add_allowance_transaction"] = Field("add_allowance_transaction", json_schema_extra={"ui:hidden": True})
    kidUserId: int = Field(..., title="Kid User ID", description="userID of the kid")
    amount: float = Field(..., title="Amount", description="amount you wish to Add/Subtract (subtract value should be a negative value)", allow_inf_nan=False)
    description: str = Field(..., title="Description", description="Description (reason) of allowance transaction", max_length=10000)
    transactionType: Literal['Add', 'Subtract'] = Field(..., title="Transaction Type", description="Transaction Type (Add/Subtract)")


class ListWishlistConfig(_Operation):
    """Get list of wishlist items."""
    operation: Literal["list_wishlist"] = Field("list_wishlist", json_schema_extra={"ui:hidden": True})
    kidUserId: int | None = Field(None, title="Kid User ID", description="userID of the kid")


class CreateWishConfig(_Operation):
    """Add item to kid's wishlist."""
    operation: Literal["create_wish"] = Field("create_wish", json_schema_extra={"ui:hidden": True})
    kidUserId: int = Field(..., title="Kid User ID", description="userID of the kid")
    title: str = Field(..., title="Title", description="Item title", max_length=10000)
    description: str | None = Field(None, title="Description", description="Item Description", max_length=10000)
    priority: int | None = Field(None, title="Priority", description="Item Priority")
    link: str | None = Field(None, title="Link", description="URL Link to item", max_length=10000)


class UpdateWishConfig(_Operation):
    """Update item on kid's wishlist."""
    operation: Literal["update_wish"] = Field("update_wish", json_schema_extra={"ui:hidden": True})
    wishId: int = Field(..., title="Wish ID", description="Wish list item ID to update")
    title: str | None = Field(None, title="Title", description="Item title", max_length=10000)
    description: str | None = Field(None, title="Description", description="Item Description", max_length=10000)
    priority: int | None = Field(None, title="Priority", description="Item Priority")
    link: str | None = Field(None, title="Link", description="URL Link to item", max_length=10000)


class DeleteWishConfig(_Operation):
    """Delete item from wishlist."""
    operation: Literal["delete_wish"] = Field("delete_wish", json_schema_extra={"ui:hidden": True})
    wishId: int = Field(..., title="Wish ID", description="ID of wishlist item to delete")


class CreateShareLinkConfig(_Operation):
    """Create Share Link."""
    operation: Literal["create_share_link"] = Field("create_share_link", json_schema_extra={"ui:hidden": True})
    linkUserId: str = Field(..., title="Link User ID", description="User ID that the link should be authenticated to", max_length=10000)
    link: Literal['https://khome.kumpeapps.com/portal/wish-list.php', 'https://khome.kumpeapps.com/portal/chores-today.php'] = Field(..., title="Link", description="Link to share")
    scope: Literal['WishList', 'WishListAdmin', 'Chores', 'ChoresAdmin'] = Field(..., title="Scope", description="Authentication scope for link")
    scope2: Literal['WishList', 'WishListAdmin', 'Chores', 'ChoresAdmin'] | None = Field(None, title="Scope2", description="Authentication scope for link")
    scope3: Literal['WishList', 'WishListAdmin', 'Chores', 'ChoresAdmin'] | None = Field(None, title="Scope3", description="Authentication scope for link")
    scope4: Literal['WishList', 'WishListAdmin', 'Chores', 'ChoresAdmin'] | None = Field(None, title="Scope4", description="Authentication scope for link")


class OnNewAllowanceTransactionConfig(PollTriggerConfigBase):
    """Watch new allowance transactions within the provider's transactionDays window."""
    operation: Literal["on_new_allowance_transaction"] = Field("on_new_allowance_transaction",
        title="On New Allowance Transaction", json_schema_extra={
            "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On New Allowance Transaction"})
    kidUserId: int = Field(..., title="Child user ID")
    transactionDays: int = Field(90, ge=1, title="Transaction history days",
        description="Poll transactions from this many days. Existing transactions form the initial baseline; outages longer than this window may miss transactions.")


KumpeAppsOperation = Annotated[Union[
    OnNewAllowanceTransactionConfig,
    GetCurrentUserConfig,
    ListUsersConfig,
    UpdateUserConfig,
    CreateChildUserConfig,
    ListChoresConfig,
    CreateChoreConfig,
    UpdateChoreConfig,
    DeleteChoreConfig,
    GetAllowanceConfig,
    AddAllowanceTransactionConfig,
    ListWishlistConfig,
    CreateWishConfig,
    UpdateWishConfig,
    DeleteWishConfig,
    CreateShareLinkConfig
], Field(discriminator="operation")]


class KumpeAppsNodeConfig(NodeConfig[KumpeAppsOperation, KumpeAppsAuthKeyCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/kkid/user'), 'list_users': ('GET', '/kkid/userlist'), 'update_user': ('PUT', '/kkid/userlist'), 'create_child_user': ('POST', '/kkid/userlist'), 'list_chores': ('GET', '/kkid/chorelist'), 'create_chore': ('POST', '/kkid/chorelist'), 'update_chore': ('PUT', '/kkid/chorelist'), 'delete_chore': ('DELETE', '/kkid/chorelist'), 'get_allowance': ('GET', '/kkid/allowance'), 'add_allowance_transaction': ('POST', '/kkid/allowance'), 'list_wishlist': ('GET', '/kkid/wishlist'), 'create_wish': ('POST', '/kkid/wishlist'), 'update_wish': ('PUT', '/kkid/wishlist'), 'delete_wish': ('DELETE', '/kkid/wishlist'), 'create_share_link': ('GET', '/kkid/share')}

LIST_KEYS = {"get_current_user": "user", "list_users": "user", "list_chores": "chore", "list_wishlist": "wish"}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()
                if key.casefold() not in {"pass", "password", "plain_password", "remember_key", "apikey", "auth_key", "app_key", "tmdbkey"}}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class KumpeAppsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-kumpeapps"
    connection_evidence = ConnectionEvidence(noun="users", operation="list_users",
        label_keys=("username", "email", "firstName", "userId"))

    @classmethod
    def get_config_model(cls):
        return KumpeAppsNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_allowance_transaction":
            return bool(output.get("new_transaction_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        transactions = output.get("new_transactions") if isinstance(output, dict) else None
        if not isinstance(transactions, list):
            return super().resolve_agent_event(output)
        if not transactions:
            return None
        lines = [f"- User {item.get('userId')}: {item.get('transactionType')} {item.get('amount')} — "
                 f"{item.get('transactionDescription')} (transaction {item.get('transactionId')}, {item.get('date')})"
                 for item in transactions[:10]]
        if len(transactions) > 10:
            lines.append(f"- … and {len(transactions) - 10} more")
        return {"text": f"KumpeApps: {len(transactions)} new allowance transaction(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a KumpeApps auth key")
        config = self.config.config
        operation = config.operation
        is_poll = isinstance(config, OnNewAllowanceTransactionConfig)
        if is_poll:
            method, path = "GET", "/kkid/allowance"
            params = {"kidUserId": config.kidUserId, "transactionDays": config.transactionDays}
        else:
            method, path = ROUTES[operation]
            params = config.model_dump(exclude={"operation"}, exclude_none=True)
        # All v5 operation arguments, including mutation arguments, are query parameters.
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        secrets = [self.config.credentials.auth_key, getattr(config, "password", None), getattr(config, "tmdbKey", None)]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"X-Auth": self.config.credentials.auth_key, "Accept": "application/json"})
        except Exception:
            # Transport exceptions can contain query strings, including child-user passwords.
            raise ValueError("KumpeApps request did not complete; inspect any write before retrying") from None
        if len(response.content) > 5_000_000:
            raise ValueError("KumpeApps response exceeded the supported size")
        try:
            body = response.json() if response.content else None
        except ValueError:
            raise ValueError(f"KumpeApps returned non-JSON (HTTP {response.status_code})") from None
        if response.status_code in {204, 206} and (operation in LIST_KEYS or operation == "get_allowance" or is_poll):
            output = {"status": "success", "data": body, "items": [], "http_status": response.status_code}
        else:
            if response.status_code not in {200, 201}:
                message = body.get("message") or body.get("error") if isinstance(body, dict) else None
                raise ValueError(_redact(f"KumpeApps HTTP {response.status_code}: {message or 'request was not confirmed'}", secrets))
            if not isinstance(body, dict):
                raise ValueError("KumpeApps returned an unexpected response")
            if body.get("success") in (False, 0) or ("error" in body and body["error"]):
                raise ValueError(_redact(str(body.get("message") or body.get("error") or "KumpeApps rejected the request"), secrets))
            output = {"status": "success", "data": body, "http_status": response.status_code}
            if operation in LIST_KEYS:
                rows = body.get(LIST_KEYS[operation])
                if not isinstance(rows, list):
                    raise ValueError("KumpeApps returned an unexpected list response")
                output["items"] = rows
        if is_poll:
            rows = [] if response.status_code == 206 else body.get("allowanceTransaction")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or type(row.get("transactionId")) is not int for row in rows):
                raise ValueError("KumpeApps returned an unexpected allowance transaction list")
            rows = list({row["transactionId"]: row for row in rows}.values())
            fresh = await self._filter_unseen(rows, lambda row: str(row["transactionId"]))
            output = {"status": "success", "new_transactions": fresh, "new_transaction_count": len(fresh),
                      "kid_user_id": config.kidUserId}
        output = _redact(output, secrets)
        await self.emit(output)
        return output
