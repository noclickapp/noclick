"""WellnessLiving client, membership and attendance automation using a pasted JWT.

Each operation follows one endpoint in the provider's published production OpenAPI;
query parameters and form bodies remain separate, including on writes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class WellnessLivingTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="WellnessLiving Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://wellnessliving.dev/production/",
            "x-credential-instructions": "Paste an existing WellnessLiving JWT bearer token, without the Bearer prefix, and your business ID. Use a staff token with permission for your operations. The production API documents token issuance at GET /Core/Passport/Enter/Jwt/JwtToken.json after signing in through your own approved API application. NoClick does not sign in or renew this token; replace it when it expires. Choose the data centre that serves your business.",
        },
    )
    credential_type: Literal["wellnessliving_token"] = Field("wellnessliving_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Bearer token", repr=False, json_schema_extra={"ui:widget": "password"})
    business_id: str = Field(..., min_length=1, title="Business ID", description="Your WellnessLiving business key (BID).")
    region: Literal["us", "au"] = Field("us", title="Data centre", json_schema_extra={"enumNames": ["United States", "Australia"]})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value

    @field_validator("business_id", mode="before")
    @classmethod
    def business(cls, value):
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
            raise ValueError("Enter your business ID")
        return value.strip()


class _Business(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    k_business: str | None = Field(None, title="Business ID override", description="Leave empty to use the connected business.")


class _Client(_Business):
    uid: str = Field(..., min_length=1, title="Client user key")


class ListClients(_Business):
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    i_page_size: int = Field(150, ge=1, le=150, title="Page size")
    uid_last: str = Field("", title="Last user key", description="Empty for the first page; use next_uid_last from the previous page. Returns active client keys, not full profiles.")


class GetClient(_Client):
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    i_photo_height: int = Field(100, ge=1, title="Photo height")
    i_photo_width: int = Field(100, ge=1, title="Photo width")


class CreateClient(_Business):
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})
    text_firstname: str = Field(..., min_length=1, title="First name")
    text_lastname: str = Field(..., min_length=1, title="Last name")
    text_mail: str = Field(..., min_length=1, title="Email")


class CheckClientEmail(_Business):
    operation: Literal["check_client_email"] = Field("check_client_email", json_schema_extra={"ui:hidden": True})
    s_mail: str = Field(..., min_length=1, title="Client email")


class GetClientId(_Client):
    operation: Literal["get_client_id"] = Field("get_client_id", json_schema_extra={"ui:hidden": True})


class SetClientId(_Client):
    operation: Literal["set_client_id"] = Field("set_client_id", json_schema_extra={"ui:hidden": True})
    s_member: str = Field(..., min_length=1, title="Client ID", description="The business-specific client ID to assign.")


class ListGroups(_Business):
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})
    is_churn_risk: bool = Field(False, title="Include churn risk group")
    is_return_members: bool = Field(False, title="Include group members")


class ListClientGroups(_Business):
    operation: Literal["list_client_groups"] = Field("list_client_groups", json_schema_extra={"ui:hidden": True})
    uid_user: str = Field(..., min_length=1, title="Client user key")


class _GroupMember(_Business):
    uid_user: str = Field(..., min_length=1, title="Client user key")
    k_member_group: str = Field(..., min_length=1, title="Client group key", description="An existing group key, or quick for the quick group.")


class AddClientToGroup(_GroupMember):
    operation: Literal["add_client_to_group"] = Field("add_client_to_group", json_schema_extra={"ui:hidden": True})


class RemoveClientFromGroup(_GroupMember):
    operation: Literal["remove_client_from_group"] = Field("remove_client_from_group", json_schema_extra={"ui:hidden": True})


class GetVisitCount(_Client):
    operation: Literal["get_visit_count"] = Field("get_visit_count", json_schema_extra={"ui:hidden": True})


class GetVisitStatus(_Business):
    operation: Literal["get_visit_status"] = Field("get_visit_status", json_schema_extra={"ui:hidden": True})
    k_visit: str = Field(..., min_length=1, title="Visit key")
    k_timezone: str | None = Field(None, title="Time zone key")


class UpdateVisitStatus(_Business):
    operation: Literal["update_visit_status"] = Field("update_visit_status", json_schema_extra={"ui:hidden": True})
    k_visit: str = Field(..., min_length=1, title="Visit key")
    id_visit: Literal[1, 2, 3, 4, 5, 6, 7, 8] = Field(..., title="New visit status", json_schema_extra={"enumNames": ["Booked", "Waitlisted", "Attended", "Late cancel", "No show", "Cancelled", "Pending", "Removed"]})
    id_visit_from: Literal[1, 2, 3, 4, 5, 6, 7, 8] | None = Field(None, title="Expected previous status", description="Optional optimistic status check by the provider.")
    is_charge_fee: bool = Field(False, title="Charge applicable penalty", description="Explicitly enable to charge an applicable late cancel or no-show fee.")
    text_reason: str = Field("", title="Cancellation reason")
    is_mail: bool = Field(False, title="Send email notification")
    is_push: bool = Field(False, title="Send push notification")
    is_sms: bool = Field(False, title="Send SMS notification")


class CancelBooking(_Client):
    operation: Literal["cancel_booking"] = Field("cancel_booking", json_schema_extra={"ui:hidden": True})
    dt_date: str = Field(..., title="Session date in UTC", description="The session timestamp, for example 2026-11-09T12:00:00Z.")
    k_appointment: str = Field(..., min_length=1, title="Appointment key", description="Cancel this appointment booking. For class attendance, use Update Visit Status with the visit key.")
    is_backend: bool = Field(True, title="Act as staff")
    is_late_cancel: bool = Field(False, title="Apply late cancellation")


class ListPromotions(_Business):
    operation: Literal["list_promotions"] = Field("list_promotions", json_schema_extra={"ui:hidden": True})
    is_franchise: bool = Field(False, title="Include franchise purchase options")


class GetPromotion(_Business):
    operation: Literal["get_promotion"] = Field("get_promotion", json_schema_extra={"ui:hidden": True})
    k_promotion: str = Field(..., min_length=1, title="Purchase option key")


class GetSubscriptions(_Client):
    operation: Literal["get_subscriptions"] = Field("get_subscriptions", json_schema_extra={"ui:hidden": True})


class UpdateSubscriptions(_Client):
    operation: Literal["update_subscriptions"] = Field("update_subscriptions", json_schema_extra={"ui:hidden": True})
    is_subscribe: bool = Field(..., title="Email subscription")
    is_subscribe_sms: bool = Field(..., title="SMS subscription")


class ListStaffLocations(_Business):
    operation: Literal["list_staff_locations"] = Field("list_staff_locations", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[
    ListClients, GetClient, CreateClient, CheckClientEmail, GetClientId, SetClientId,
    ListGroups, ListClientGroups, AddClientToGroup, RemoveClientFromGroup,
    GetVisitCount, GetVisitStatus, UpdateVisitStatus, CancelBooking,
    ListPromotions, GetPromotion, GetSubscriptions, UpdateSubscriptions, ListStaffLocations,
], Field(discriminator="operation")]


class WellnessLivingConfig(NodeConfig[Operation, WellnessLivingTokenCredential]):
    pass


# Method, path, query fields, form fields. These fixed routes cannot be supplied by a workflow.
ROUTES = {
    "list_clients": ("GET", "/Wl/Login/Member/LoginMemberListAll.json", ("k_business", "i_page_size", "uid_last"), ()),
    "get_client": ("GET", "/Wl/Login/Login.json", ("k_business", "uid", "i_photo_height", "i_photo_width"), ()),
    "create_client": ("POST", "/Wl/Profile/Edit/Create.json", (), ("k_business", "text_firstname", "text_lastname", "text_mail")),
    "check_client_email": ("POST", "/Wl/Lead/LeadCheck.json", (), ("k_business", "s_mail")),
    "get_client_id": ("GET", "/Wl/Login/Member/LoginMember.json", ("k_business", "uid"), ()),
    "set_client_id": ("POST", "/Wl/Login/Member/LoginMember.json", ("k_business", "uid", "s_member"), ()),
    "list_groups": ("GET", "/Wl/Member/Group/GroupList/List.json", ("k_business", "is_churn_risk", "is_return_members"), ()),
    "list_client_groups": ("GET", "/Wl/Member/Group/User/UserGroup.json", ("k_business", "uid_user"), ()),
    "add_client_to_group": ("POST", "/Wl/Member/Group/User/UserGroup.json", ("k_business", "uid_user"), ("k_member_group",)),
    "remove_client_from_group": ("DELETE", "/Wl/Member/Group/User/UserGroup.json", ("k_business", "uid_user"), ("k_member_group",)),
    "get_visit_count": ("GET", "/Wl/Visit/VisitTotalCount.json", ("k_business", "uid"), ()),
    "get_visit_status": ("GET", "/Wl/Visit/VisitStatus.json", ("k_business", "k_visit", "k_timezone"), ()),
    "update_visit_status": ("POST", "/Wl/Visit/VisitStatus.json", ("k_business", "k_visit", "is_charge_fee", "text_reason"), ("id_mode", "id_visit", "id_visit_from", "is_mail", "is_push", "is_sms")),
    "cancel_booking": ("POST", "/Wl/Schedule/Cancel.json", ("k_business", "uid", "dt_date", "k_appointment", "is_backend", "is_late_cancel"), ()),
    "list_promotions": ("GET", "/Wl/Promotion/PromotionList.json", ("k_business", "is_franchise"), ()),
    "get_promotion": ("GET", "/Wl/Promotion/Promotion.json", ("k_business", "k_promotion"), ()),
    "get_subscriptions": ("GET", "/Wl/Business/User/Subscribe/Subscribe.json", ("k_business", "uid"), ()),
    "update_subscriptions": ("PUT", "/Wl/Business/User/Subscribe/Subscribe.json", ("k_business", "uid", "is_subscribe", "is_subscribe_sms"), ()),
    "list_staff_locations": ("GET", "/Wl/Staff/Location/List.json", ("k_business",), ()),
}


def _wire(values, names):
    return {name: ("true" if values[name] else "false") if isinstance(values[name], bool) else str(values[name])
            for name in names if values.get(name) is not None}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items() if key.lower() not in {"s_token", "access_token", "authorization"}}
    return value


class WellnessLivingNode(WorkflowNode):
    integration_type = "automation-wellnessliving"
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="client groups", label_keys=("text_title", "name", "id"))

    @classmethod
    def get_config_model(cls):
        return WellnessLivingConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a WellnessLiving bearer token and business ID")
        credential = self.config.credentials
        operation = self.config.config
        action = operation.operation
        method, path, query_fields, body_fields = ROUTES[action]
        values = operation.model_dump(exclude_none=True)
        values["k_business"] = values.get("k_business") or credential.business_id
        if action == "update_visit_status":
            values["id_mode"] = 28  # Wl.Mode.ModeSid.API
        headers = {"Authorization": "Bearer " + credential.access_token,
                   "Accept": "application/json", "X-Error-Rules": "default"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, f"https://{credential.region}.wellnessliving.com" + path,
                                            headers=headers, params=_wire(values, query_fields),
                                            data=_wire(values, body_fields) if body_fields else None)
        token = credential.access_token
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection text for the shared connect verdict.
            raise ValueError(_redact(f"WellnessLiving HTTP {response.status_code}: {response.text[:2000]}", token))
        if len(response.content) > 10_000_000:
            raise ValueError("WellnessLiving returned too much data; narrow the request")
        if response.content:
            if "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("WellnessLiving returned a non-JSON response")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("WellnessLiving returned invalid JSON") from None
            if not isinstance(body, dict):
                raise ValueError("WellnessLiving returned an unexpected response shape")
            if body.get("status", "ok") != "ok" or body.get("a_error") or body.get("error"):
                raise ValueError(_redact(str(body.get("message") or body.get("a_error") or body.get("error") or body["status"]), token))
        else:
            body = {}
        required = {
            "list_clients": "a_uid", "get_client": "s_first_name", "create_client": "uid",
            "check_client_email": "is_member", "get_client_id": "s_member", "set_client_id": "dt_member",
            "list_groups": "a_member_group", "list_client_groups": "a_group_info",
            "get_visit_count": "i_visit_total", "get_visit_status": "id_visit",
            "list_staff_locations": "a_location", "list_promotions": "a_promotion", "get_promotion": "a_promotion",
        }.get(action)
        if required and required not in body:
            raise ValueError(f"WellnessLiving response is missing {required}")
        output = {"status": "success", "operation": action, "data": _redact(body, token)}
        if action == "list_groups":
            if not isinstance(body["a_member_group"], list):
                raise ValueError("WellnessLiving client groups were not a list")
            output["items"] = _redact(body["a_member_group"], token)
        if action == "list_clients":
            rows = body["a_uid"]
            if not isinstance(rows, list) or any(not isinstance(uid, str) for uid in rows):
                raise ValueError("WellnessLiving client keys were not a list")
            if rows and rows[-1] == operation.uid_last:
                raise ValueError("WellnessLiving returned a nonadvancing client page")
            output["next_uid_last"] = rows[-1] if len(rows) == operation.i_page_size else None
            output["has_more"] = len(rows) == operation.i_page_size
        if method != "GET":
            output["write_acknowledged"] = True
        await self.emit(output)
        return output
