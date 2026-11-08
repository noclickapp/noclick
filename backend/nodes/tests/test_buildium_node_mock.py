"""Prepared source: actual native parser/execute and closed HTTP contracts."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import logging
import httpx
import pytest
from pydantic import TypeAdapter, ValidationError
from nodes import buildium_node as B

USER = "00000000-0000-4000-8000-000000000001"
AUTH = {"credential_type": B.FAMILY, "client_id": "synthetic-buildium-client", "client_secret": "synthetic-buildium-secret"}
CASES = {
    "check_connection": {}, "list_properties": {}, "get_property": {"property_id": "1"},
    "list_units": {"property_id": "1"}, "get_unit": {"property_id": "1", "unit_id": "2"},
    "list_tenants": {}, "get_tenant": {"tenant_id": "3"}, "list_listing_contacts": {},
    "get_listing_contact": {"listing_contact_id": "4"}, "list_work_orders": {}, "get_work_order": {"work_order_id": "5"},
    "list_tasks": {}, "get_task": {"task_id": "6"}, "list_task_categories": {}, "get_task_category": {"task_category_id": "7"},
    "list_property_notes": {"property_id": "1"}, "get_property_note": {"property_id": "1", "note_id": "8"},
    "create_property_note": {"property_id": "1", "note": "Fixture note"},
    "update_property_note": {"property_id": "1", "note_id": "8", "note": "Replacement note"},
    "create_task_category": {"name": "Fixture category"}, "rename_task_category": {"task_category_id": "7", "name": "Renamed category"},
}


class World:
    def __init__(self):
        self.calls, self.guard_calls, self.override, self.after_request = [], [], None, None
        self.rows = {
            "/v1/rentals": {"Id": 1, "Name": "Fixture property", "NumberUnits": 1, "IsActive": True, "OperatingBankAccountId": 999, "Reserve": 1234, "Address": {"AddressLine1": "PRIVATE-ADDRESS"}},
            "/v1/rentals/units": {"Id": 2, "PropertyId": 1, "UnitNumber": "Unit A", "MarketRent": 3456, "Address": {"AddressLine1": "PRIVATE-ADDRESS"}},
            "/v1/leases/tenants": {"Id": 3, "FirstName": "Fixture", "LastName": "Tenant", "TaxId": "PRIVATE-TAX", "DateOfBirth": "1970-01-01", "Email": "PRIVATE-EMAIL", "Leases": [{"AccountDetails": {"Balance": 999}}]},
            "/v1/rentals/units/listingcontacts": {"Id": 4, "Name": "Fixture contact", "Email": "PRIVATE-EMAIL", "PhoneNumber": "PRIVATE-PHONE"},
            "/v1/workorders": {"Id": 5, "Title": "Fixture work order", "Status": "New", "Task": {"Id": 6, "UnitAgreement": {"Href": "PRIVATE-URL"}}, "EntryNotes": "PRIVATE-ENTRY", "Amount": 999, "EntryContacts": [{"Email": "PRIVATE-EMAIL"}]},
            "/v1/tasks": {"Id": 6, "Title": "Fixture task", "TaskStatus": "New", "Property": {"Id": 1, "Type": "Rental", "Href": "PRIVATE-URL"}, "Description": "PRIVATE-DESCRIPTION", "RequestedByUserEntity": {"Email": "PRIVATE-EMAIL"}},
            "/v1/tasks/categories": {"Id": 7, "Name": "Fixture category", "IsSystemCategory": False, "SubCategories": []},
            "/v1/rentals/1/notes": {"Id": 8, "Note": "PRIVATE-NOTE", "LastUpdatedByUser": {"Id": 9, "FirstName": "PRIVATE-NAME", "Href": "PRIVATE-URL", "UpdatedDateTime": "2026-10-06T00:00:00Z"}},
        }
    def handle(self, request):
        self.calls.append(request)
        if self.after_request:
            self.after_request(request)
        if self.override:
            return self.override(request)
        path = request.url.path
        base = path if path in self.rows else path.rsplit("/", 1)[0]
        assert base in self.rows, path
        row = self.rows[base]
        if request.method in {"POST", "PUT"}:
            row.update(json.loads(request.content))
            return httpx.Response(201 if request.method == "POST" else 200, json=deepcopy(row))
        if path in self.rows:
            return httpx.Response(200, json=[deepcopy(row)], headers={"X-Total-Count": "1"})
        return httpx.Response(200, json=deepcopy(row))


@pytest.fixture
def world(monkeypatch):
    value = World()
    original_client = httpx.AsyncClient
    @asynccontextmanager
    async def client(**kwargs):
        value.guard_calls.append(kwargs)
        async with original_client(transport=httpx.MockTransport(value.handle), **{k: v for k, v in kwargs.items() if k != "require_public"}) as actual:
            yield actual
    monkeypatch.setattr(B.httpx, "AsyncClient", client)
    return value


async def execute(operation, arguments=None):
    config = {"credentials": deepcopy(AUTH), "config": {"operation": operation, **(arguments or CASES[operation])}}
    node = B.BuildiumNode(node_type=B.NODE_TYPE, user_id=USER, node_id="fixture", config=B.BuildiumNode.parse_config(config), node_data=config)
    return await node.execute({})


def test_every_operation_discriminates_and_generates_native_schema_without_id_validator_touching_operation():
    adapter = TypeAdapter(B.BuildiumOperation)
    assert set(CASES) == set(B.OPS)
    for operation, args in CASES.items():
        parsed = adapter.validate_python({"operation": operation, **args})
        assert parsed.operation == operation
    schema = B.BuildiumNode.get_config_schema()
    assert set(adapter.json_schema()["discriminator"]["mapping"]) == set(CASES)
    assert schema["$defs"]["BuildiumAPIKeyCredential"]["properties"]["client_secret"]["ui:sensitive"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(CASES))
async def test_actual_parse_execute_exact_auth_projection_and_documented_maintenance_readbacks(world, operation):
    result = await execute(operation)
    assert "PRIVATE-" not in json.dumps(result) and "Reserve" not in str(result) and "MarketRent" not in str(result)
    for request in world.calls:
        assert str(request.url).startswith(B.ORIGIN+"/v1/")
        assert request.headers["x-buildium-client-id"] == AUTH["client_id"]
        assert request.headers["x-buildium-client-secret"] == AUTH["client_secret"]
        assert request.headers["accept"] == "application/json"
        assert "authorization" not in request.headers and "JWT" not in request.url.params
        assert AUTH["client_secret"] not in str(request.url)
    assert all(k["trust_env"] is False and k["follow_redirects"] is False for k in world.guard_calls)
    writes = [r for r in world.calls if r.method != "GET"]
    if operation in {"create_property_note", "update_property_note", "create_task_category", "rename_task_category"}:
        assert len(writes) == 1 and result["readback_verified"] is True
        assert set(json.loads(writes[0].content)) == ({"Note"} if "property_note" in operation else {"Name"})
        assert world.calls[-1].method == "GET"
    else:
        assert writes == []
    if operation == "check_connection":
        assert result == {"reachable": True, "proves": "reachability", "identity_verified": False}
    if operation == "list_units":
        assert world.calls[-1].url.params.get_list("propertyids") == ["1"]


@pytest.mark.parametrize("bad", [0, -1, True, "01", "1/2", "2147483648", "https://private.invalid"])
def test_int32_id_refusal_is_before_provider(bad):
    with pytest.raises((ValidationError, ValueError)):
        B.BuildiumNode.parse_config({"credentials": AUTH, "config": {"operation": "get_property", "property_id": bad}})


@pytest.mark.parametrize("bad", [{}, {**AUTH, "credential_type": "slack_oauth"}, {**AUTH, "client_secret": 12}, {**AUTH, "client_id": ""}, {**AUTH, "client_secret": "https://private.invalid/key"}, {**AUTH, "token": "other"}])
def test_native_raw_credential_family_and_secret_shapes_refuse(bad):
    with pytest.raises(ValueError, match="native account"):
        B.BuildiumNode.parse_config({"credentials": bad, "config": {"operation": "check_connection"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["401", "403", "429", "503", "redirect", "error200", "invalidjson", "duplicate", "missingcount", "wrongcount"])
async def test_exact_http_json_paging_refusals_never_reflect_provider_input_or_retry(world, failure):
    def respond(_):
        if failure.isdigit() or failure == "redirect":
            return httpx.Response(int(failure) if failure.isdigit() else 302, json={"UserMessage": "PRIVATE-PROVIDER"}, headers={"Location": "https://private.invalid"})
        if failure == "invalidjson": return httpx.Response(200, content=b"PRIVATE-NOT-JSON")
        if failure == "duplicate": return httpx.Response(200, content=b'[{"Id":1,"Id":2}]', headers={"X-Total-Count": "1"})
        if failure == "error200": return httpx.Response(200, json={"UserMessage": "PRIVATE-PROVIDER"})
        return httpx.Response(200, json=[world.rows["/v1/rentals"]], headers={} if failure == "missingcount" else {"X-Total-Count": "0"})
    world.override = respond
    with pytest.raises(RuntimeError) as error:
        await execute("check_connection")
    assert len(world.calls) == 1 and "PRIVATE-" not in str(error.value)


@pytest.mark.asyncio
async def test_native_picker_pagination_is_key_parent_search_bound_and_empty_account_is_honest(world):
    def respond(request):
        offset = int(request.url.params["offset"])
        records = [{"Id": i+1, "Name": f"Property {i+1}"} for i in range(offset, min(offset+50, 51))]
        return httpx.Response(200, json=records, headers={"X-Total-Count": "51"})
    world.override = respond
    page = await B.BuildiumNode.load_field_options("property_id", AUTH)
    next_page = await B.BuildiumNode.load_field_options("property_id", AUTH, page_token=page["next_page_token"])
    assert len(page["options"]) == 50 and next_page["options"] == [{"value": "51", "label": "Property 51"}]
    before = len(world.calls)
    for changed in ({**AUTH, "client_id": "changed-client"}, {**AUTH, "client_secret": "changed-secret"}):
        with pytest.raises(ValueError): await B.BuildiumNode.load_field_options("property_id", changed, page_token=page["next_page_token"])
    with pytest.raises(ValueError): await B.BuildiumNode.load_field_options("unit_id", AUTH, context={})
    assert len(world.calls) == before
    world.override = lambda _: httpx.Response(200, json=[], headers={"X-Total-Count": "0"})
    assert (await execute("check_connection"))["identity_verified"] is False


@pytest.mark.asyncio
async def test_parent_foreign_unit_system_category_and_post_write_mismatch_fail_closed(world):
    world.rows["/v1/rentals/units"]["PropertyId"] = 99
    with pytest.raises(RuntimeError, match="another rental property"): await execute("get_unit")
    world.calls.clear(); world.rows["/v1/tasks/categories"]["IsSystemCategory"] = True
    with pytest.raises(ValueError, match="system"): await execute("rename_task_category")
    assert all(r.method == "GET" for r in world.calls)
    world.calls.clear()
    def mismatch(request):
        if request.method == "PUT": return httpx.Response(200, json={"Id": 8, "Note": "unchanged"})
        return httpx.Response(200, json=world.rows["/v1/rentals"] if request.url.path == "/v1/rentals/1" else world.rows["/v1/rentals/1/notes"])
    world.override = mismatch
    with pytest.raises(RuntimeError, match="readback"): await execute("update_property_note")
    assert len([r for r in world.calls if r.method == "PUT"]) == 1


@pytest.mark.asyncio
async def test_provider_scoped_http_logging_and_network_error_never_export_client_secret(world, caplog):
    caplog.set_level(logging.DEBUG, logger="httpx")
    def refuse(_):
        logging.getLogger("httpx").warning("PRIVATE-HEADER %s", AUTH["client_secret"])
        raise RuntimeError("PRIVATE-NETWORK "+AUTH["client_secret"])
    world.override = refuse
    with pytest.raises(RuntimeError) as error: await execute("check_connection")
    assert AUTH["client_secret"] not in caplog.text and "PRIVATE-" not in caplog.text+str(error.value)


@pytest.mark.parametrize("args", [{"updated_from": "2026-02-30"}, {"updated_from": "2026-01-01T00:00:00Z"}, {"updated_from": "2026-10-06", "updated_to": "2026-10-05"}])
def test_task_date_contract_refuses_invalid_or_reversed_days(args):
    with pytest.raises(ValidationError):
        TypeAdapter(B.BuildiumOperation).validate_python({"operation": "list_tasks", **args})
