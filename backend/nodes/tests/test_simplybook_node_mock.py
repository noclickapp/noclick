"""Real native parse/execute and HTTPS JSON-RPC fixtures."""
from copy import deepcopy
import json
from contextlib import asynccontextmanager
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import simplybook_node as F

USER = "00000000-0000-4000-8000-000000000001"
AUTH = {"credential_type": "simplybook_admin_user", "company_login": "synthetic-company", "user_login": "synthetic-admin", "user_password": "api_user_key_synthetic_fixture"}
BOOKING = {"id": 21, "event_id": 1, "unit_id": 2, "client_id": 3, "start_date_time": "2026-10-06 09:00:00", "end_date_time": "2026-10-06 10:00:00", "is_confirmed": 1, "code": "PRIVATE-CODE", "hash": "PRIVATE-HASH", "additional_fields": {"medical": "PRIVATE-HEALTH"}}


class World:
    def __init__(self):
        self.calls, self.override, self.after_request = [], None, None
        self.user = {"id": 7, "group": "admin", "is_blocked": 0, "unit_group_id": None, "email": "PRIVATE-EMAIL", "login": "PRIVATE-LOGIN"}
        self.clients = {"3": {"id": 3, "name": "Fixture Client", "email": "PRIVATE-EMAIL", "phone": "PRIVATE-PHONE", "is_email_unsubscribed": True, "is_sms_unsubscribed": True}}
        self.services = {"1": {"id": 1, "name": "Fixture Service", "duration": 60, "is_active": 1, "is_public": 1, "unit_map": [2], "picture_path": "PRIVATE-MEDIA"}}
        self.providers = {"2": {"id": 2, "name": "Fixture Provider", "is_active": 1, "is_visible": 1, "qty": 1, "email": "PRIVATE-EMAIL"}}
        self.comment = ""
    def handle(self, request):
        self.calls.append(request)
        assert request.method == "POST" and str(request.url).startswith(F.ORIGIN) and not request.url.query
        body = json.loads(request.content)
        assert set(body) == {"jsonrpc", "method", "params", "id"} and body["jsonrpc"] == "2.0" and isinstance(body["params"], list)
        method, args = body["method"], body["params"]
        if self.override:
            result = self.override(request, body)
            if result is not None: return result
        if method in {"getToken", "getUserToken"}:
            assert request.url.path == "/login" and "X-Token" not in request.headers and "X-User-Token" not in request.headers
            assert args[0] == AUTH["company_login"]
            result = "synthetic-company-token" if method == "getToken" else "synthetic-admin-token"
        else:
            assert request.headers["X-Company-Login"] == AUTH["company_login"]
            if request.url.path == "/admin/": assert request.headers["X-User-Token"] == "synthetic-admin-token" and "X-Token" not in request.headers
            else: assert request.url.path == "/" and request.headers["X-Token"] == "synthetic-company-token" and "X-User-Token" not in request.headers
            if method == "getCurrentUserDetails": result = self.user
            elif method == "getEventList": assert args == []; result = self.services
            elif method == "getUnitList": assert args == []; result = self.providers
            elif method == "getTimeframe": result = 30
            elif method == "getFirstWorkingDay": assert args == [{"unit_group_id": 2, "event_id": 1}]; result = "2026-10-06"
            elif method == "getWorkCalendar": assert args == [2026, 10, {"unit_group_id": 2, "event_id": 1}]; result = {"2026-10-06": {"from": "09:00:00", "to": "24:00:00", "is_day_off": "0", "PRIVATE": "DROP"}}
            elif method == "getStartTimeMatrix": assert args == ["2026-10-06", "2026-10-07", 1, 2, 1]; result = {"2026-10-06": ["09:00:00", "10:00:00"]}
            elif method == "getAvailableUnits": assert args == [1, "2026-10-06 09:00:00", 1, 2]; result = [2]
            elif method == "getClientList": assert len(args) == 2 and 1 <= args[1] <= 100; result = list(self.clients.values())[:args[1]]
            elif method == "getClientInfo": result = self.clients[str(args[0])]
            elif method == "addClient":
                assert args[1] is False and set(args[0]) <= {"name", "email", "phone"}
                self.clients["4"] = {"id": 4, **args[0]}; result = 4
            elif method == "editClient":
                self.clients[str(args[0])].update(args[1]); result = args[0]
            elif method == "getBookings":
                assert set(args[0]) <= {"date_from", "date_to", "event_id", "unit_group_id", "client_id", "booking_type", "order"}; result = [BOOKING]
            elif method == "getBookingDetails": assert args == [21]; result = BOOKING
            elif method == "getStatuses": result = [{"id": 5, "name": "Fixture Status", "PRIVATE": "DROP"}]
            elif method == "getBookingStatus": assert args == [21]; result = {"id": 5, "name": "Fixture Status"}
            elif method == "setBookingComment": assert args[0] == 21; self.comment = args[1]; result = None
            elif method == "getBookingComment": assert args == [21]; result = self.comment
            else: raise AssertionError("Unexpected native RPC method")
        if self.after_request: self.after_request(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": deepcopy(result), "id": str(body["id"])})


@pytest.fixture
def world(monkeypatch):
    result = World()
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(result.handle), **kwargs) as value: yield value
    monkeypatch.setattr(F, "guarded_async_client", client)
    return result


CONFIGS = {
    "check_connection": {}, "list_services": {}, "get_service": {"service_id": "1"},
    "list_providers": {"service_id": "1"}, "get_provider": {"service_id": "1", "provider_id": "2"}, "get_timeframe": {},
    "get_first_working_day": {"service_id": "1", "provider_id": "2"},
    "get_work_calendar": {"service_id": "1", "provider_id": "2", "year": 2026, "month": 10},
    "get_available_start_times": {"service_id": "1", "provider_id": "2", "date_from": "2026-10-06", "date_to": "2026-10-07"},
    "get_available_providers": {"service_id": "1", "provider_id": "2", "date_time": "2026-10-06 09:00:00"},
    "get_current_user": {}, "list_clients": {}, "get_client": {"client_id": "3"},
    "create_client": {"name": "New Fixture", "email": "new@synthetic.invalid"}, "update_client_name": {"client_id": "3", "name": "Renamed Fixture"},
    "list_bookings": {"date_from": "2026-10-06", "date_to": "2026-10-07", "service_id": "1", "provider_id": "2", "client_id": "3"},
    "get_booking": {"booking_id": "21"}, "list_booking_statuses": {}, "get_booking_status": {"booking_id": "21"},
    "update_booking_comment": {"booking_id": "21", "comment": "Private fixture comment"},
}


def test_discriminated_operation_adapter_and_schema_cover_every_native_operation():
    adapter = TypeAdapter(F.SimplyBookOperation)
    schema = adapter.json_schema()
    assert schema["discriminator"]["propertyName"] == "operation"
    assert set(schema["discriminator"]["mapping"]) == set(CONFIGS) == set(F.OPS)
    for operation, config in CONFIGS.items():
        data = {"operation": operation, **deepcopy(config)}
        for field in ("service_id", "provider_id", "client_id", "booking_id"):
            if field in data: data[field] = int(data[field])
        parsed = adapter.validate_python(data).model_dump()
        assert parsed["operation"] == operation
        for field in ("service_id", "provider_id", "client_id", "booking_id"):
            if field in config: assert parsed[field] == config[field]
        ref = schema["discriminator"]["mapping"][operation].split("/")[-1]
        assert schema["$defs"][ref]["properties"]["operation"]["const"] == operation


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", F.OPS)
async def test_real_parsed_native_execute_exact_rpc_and_projection(world, operation):
    data = {"config": {"operation": operation, **CONFIGS[operation]}, "credentials": deepcopy(AUTH)}
    model = F.SimplyBookNode.parse_config(data)
    node = F.SimplyBookNode("fixture", "automation-simplybook", data, config=model, user_id=USER)
    output = await node.execute({})
    assert "PRIVATE-" not in str(output) and "Private fixture comment" not in str(output) and AUTH["user_password"] not in str(output)
    assert json.loads(world.calls[0].content)["method"] == "getUserToken"
    assert sum(json.loads(r.content)["method"] == "getUserToken" for r in world.calls) == 1
    if operation in {"create_client", "update_client_name", "update_booking_comment"}: assert output["readback_verified"] is True
    if operation == "get_work_calendar": assert output["calendar"]["2026-10-06"]["to"] == "24:00:00"
    if operation == "check_connection": assert output["proves"] == "reachability" and output["identity_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("family", F.FAMILIES)
async def test_family_headers_login_parameters_and_no_oauth(world, family):
    auth = {"credential_type": family, "company_login": AUTH["company_login"]}
    auth.update({"api_key": "synthetic-company-key"} if family == F.FAMILIES[0] else {"user_login": AUTH["user_login"], "user_password": AUTH["user_password"]} if family == F.FAMILIES[1] else {"token": "synthetic-company-token"} if family == F.FAMILIES[2] else {"user_token": "synthetic-admin-token"})
    output = await F.records(auth, {"operation": "check_connection"})
    assert output["reachable"] is True
    assert len(world.calls) == (2 if family in F.FAMILIES[:2] else 1)
    if family == F.FAMILIES[0]: assert json.loads(world.calls[0].content)["params"] == [AUTH["company_login"], "synthetic-company-key"]
    if family in F.FAMILIES[:2]: assert not any(k in auth for k in ("access_token", "expires_at", "refresh_token"))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "shop_user", "station_user", "unknown"])
async def test_current_role_refuses_management_before_mutation(world, role):
    world.user["group"] = role
    with pytest.raises(ValueError): await F.records(AUTH, {"operation": "create_client", "name": "Blocked"})
    assert [json.loads(r.content)["method"] for r in world.calls] == ["getUserToken", "getCurrentUserDetails"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["rpc", "wrong_id", "html", "missing_result", "invalid_token", "duplicate_json", "status429", "status503"])
async def test_real_transport_refusals_are_sanitized_and_unretried(world, failure):
    def override(_request, body):
        if failure == "rpc": return httpx.Response(200, json={"jsonrpc": "2.0", "id": str(body["id"]), "error": {"code": -32020, "message": "PRIVATE-EMAIL", "data": AUTH}})
        if failure == "wrong_id": return httpx.Response(200, json={"id": "other", "result": "PRIVATE-TOKEN"})
        if failure == "html": return httpx.Response(200, text="<p>PRIVATE-TOKEN</p>")
        if failure == "missing_result": return httpx.Response(200, json={"id": body["id"], "error": None})
        if failure == "invalid_token": return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"token": "PRIVATE-TOKEN"}})
        if failure == "duplicate_json": return httpx.Response(200, content=b'{"id":1,"id":2,"result":"PRIVATE-TOKEN"}')
        return httpx.Response(429 if failure == "status429" else 503, json={"message": "PRIVATE-TOKEN"})
    world.override = override
    with pytest.raises(RuntimeError) as error: await F.records(AUTH, {"operation": "check_connection"})
    assert "PRIVATE-" not in str(error.value) and AUTH["user_password"] not in str(error.value) and len(world.calls) == 1
    if failure == "rpc": assert isinstance(error.value, F.SimplyBookRPCError) and error.value.rpc_code == -32020


@pytest.mark.asyncio
async def test_catalogue_picker_local_paging_int64_and_parent_scope(world):
    world.services = {str(i): {"id": i, "name": f"Service {i}"} for i in range(1, 61)}
    first = await F.SimplyBookNode.load_field_options("service_id", AUTH)
    assert len(first["options"]) == 50 and first["next_page_token"]
    second = await F.SimplyBookNode.load_field_options("service_id", AUTH, page_token=first["next_page_token"])
    assert len(second["options"]) == 10 and second["next_page_token"] is None
    before = len(world.calls)
    with pytest.raises(ValueError): await F.SimplyBookNode.load_field_options("service_id", AUTH, search="changed", page_token=first["next_page_token"])
    with pytest.raises(ValueError): await F.SimplyBookNode.load_field_options("provider_id", AUTH, context={})
    assert len(world.calls) == before
    world.services["1"]["name"] = "Changed current catalogue"
    with pytest.raises(ValueError, match="catalogue changed"): await F.SimplyBookNode.load_field_options("service_id", AUTH, page_token=first["next_page_token"])
    large = 9223372036854775807
    world.services = {str(large): {"id": large, "name": "Large ID", "unit_map": [2]}}
    output = await F.records(AUTH, {"operation": "get_service", "service_id": str(large)})
    assert output["record"]["id"] == str(large)
    options = await F.SimplyBookNode.load_field_options("provider_id", AUTH, context={"service_id": str(large)})
    assert options["options"] == [{"label": "Fixture Provider", "value": "2"}]


@pytest.mark.asyncio
async def test_foreign_provider_and_failed_readback_cannot_report_success(world):
    with pytest.raises(ValueError): await F.records(AUTH, {"operation": "get_first_working_day", "service_id": "1", "provider_id": "99"})
    assert not any(json.loads(r.content)["method"] == "getFirstWorkingDay" for r in world.calls)
    def override(_request, body):
        if body["method"] == "getClientInfo": return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"id": 4, "name": "Wrong name"}})
    world.override = override
    with pytest.raises(RuntimeError): await F.records(AUTH, {"operation": "create_client", "name": "Expected"})
    assert sum(json.loads(r.content)["method"] == "addClient" for r in world.calls) == 1


@pytest.mark.parametrize("bad", [True, 0, -1, "9223372036854775808", "https://synthetic.invalid", "1/2"])
def test_bad_identifiers_and_discriminator_are_local_safe_refusals(bad):
    with pytest.raises(ValueError): F.SimplyBookNode.parse_config({"credentials": AUTH, "config": {"operation": "get_service", "service_id": bad}})
    assert F.SimplyBookNode.validate_config({"credentials": {**AUTH, "credential_type": "slack_oauth"}, "config": {"operation": "check_connection"}})["valid"] is False


@pytest.mark.parametrize("change", [
    {"company_login": "https://synthetic.invalid"}, {"company_login": "../foreign"}, {"company_login": 42},
    {"user_password": "https://synthetic.invalid/PRIVATE-KEY"}, {"user_password": "YOUR_API_KEY"},
    {"user_password": {"secret": "PRIVATE-KEY"}}, {"credential_type": "slack_oauth"},
    {"token": "borrowed-company-token"}, {"user_login": "bad\nPRIVATE-LOGIN"},
])
def test_raw_auth_admission_shape_refuses_foreign_or_malformed_values_before_transport(world, change):
    with pytest.raises(ValueError) as error:
        F.SimplyBookNode.parse_config({"config": {"operation": "check_connection"}, "credentials": {**AUTH, **change}})
    assert "PRIVATE-" not in str(error.value) and AUTH["user_password"] not in str(error.value) and world.calls == []
