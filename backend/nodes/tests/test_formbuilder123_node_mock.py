"""Unrun native API v2 parse/execute/transport fixtures; all values synthetic."""
from copy import deepcopy
from contextlib import asynccontextmanager
import json
import logging
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import formbuilder123_node as F

USER = "00000000-0000-4000-8000-000000000001"
AUTH = {"credential_type": F.FAMILY, "region": "us", "token": "synthetic-v2-private-token"}
CONFIGS = {
    "check_connection": {}, "list_forms": {}, "get_form": {"form_id": "1"},
    "list_form_fields": {"form_id": "1"}, "get_form_field": {"form_id": "1", "field_id": "4"},
    "list_submissions": {"form_id": "1"}, "get_submission": {"form_id": "1", "submission_id": "7"},
    "list_groups": {}, "get_group": {"group_id": "2"}, "list_group_forms": {"group_id": "2"}, "list_users": {},
    "create_inactive_form": {"name": "New fixture", "group_id": "2"}, "rename_form": {"form_id": "1", "name": "Renamed fixture"},
    "move_form": {"form_id": "1", "group_id": "3"}, "deactivate_form": {"form_id": "1"},
    "create_group": {"name": "New folder", "parent_id": "2"}, "rename_group": {"group_id": "2", "name": "Renamed folder"},
}


class World:
    def __init__(self):
        self.calls, self.override, self.after_request = [], None, None
        self.forms = {"1": {"id": 1, "name": "Fixture form", "group_id": 2, "user_id": 11, "active": 0, "submissions_count": 1, "PRIVATE": "PRIVATE-DROP"}}
        self.groups = {"2": {"id": 2, "name": "Fixture folder", "parent_id": -1, "webhook_url": "https://private.invalid/PRIVATE-KEY"}, "3": {"id": 3, "name": "Destination", "parent_id": -1}}
        self.submission = {"id": 7, "form_id": 1, "entry_id": 8, "status": 1, "deleted": 0, "approved": 0, "date": "2026-10-06 09:00:00", "content": '{"health":"PRIVATE-ANSWER"}', "recipients": {"email": "PRIVATE-EMAIL"}, "payed": "PRIVATE-PAYMENT"}
    def paged(self, rows, request):
        size, number = int(request.url.params.get("per_page", "50")), int(request.url.params.get("page", "1"))
        return {"data": deepcopy(rows), "meta": {"pagination": {"total": len(rows), "count": len(rows), "per_page": size, "current_page": number, "total_pages": 1 if rows else 0, "links": {"next": "https://private.invalid/?JWT=PRIVATE-LINK"}}}, "status_code": 200}
    def handle(self, request):
        self.calls.append(request)
        if self.override:
            result = self.override(request)
            if result is not None: return result
        assert request.url.host in {"api.123formbuilder.com", "eu-api.123formbuilder.com"} and request.url.scheme == "https"
        assert "Authorization" not in request.headers and request.headers["Accept"] == "application/json"
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if method == "POST" or method == "PUT" and path.startswith("/v2/groups/"):
            assert body.pop("JWT") == AUTH["token"] and "JWT" not in request.url.params
        else: assert request.url.params["JWT"] == AUTH["token"] and "JWT" not in body
        assert "include_recipients" not in request.url.params
        status = 200
        if method == "GET":
            if path == "/v2/forms": result = self.paged(list(self.forms.values())[:int(request.url.params["per_page"])], request)
            elif path == "/v2/groups": result = self.paged(list(self.groups.values()), request)
            elif path == "/v2/users": result = self.paged([{"id": 11, "name": "PRIVATE-LOGIN", "email": "PRIVATE-EMAIL", "user_parent": 0, "admin": 1}], request)
            elif path == "/v2/forms/1/fields": result = {"data": {"id": 1, "controls": {"data": [{"id": 4, "form_id": 1, "name": "Fixture field", "type": 0, "required": 1, "values": "PRIVATE-CHOICES"}]}}, "status_code": 200}
            elif path == "/v2/forms/1/submissions": result = self.paged([self.submission], request)
            elif path == "/v2/forms/1/submissions/7": result = self.paged([self.submission], request)
            elif path == "/v2/groups/2/forms": result = {"data": {"id": 2, "forms": list(self.forms.values()), "webhook_url": "PRIVATE-WEBHOOK"}, "status_code": 200}
            elif path.startswith("/v2/forms/"): result = {"data": self.forms[path.split("/")[-1]], "status_code": 200}
            elif path.startswith("/v2/groups/"): result = {"data": self.groups[path.split("/")[-1]], "status_code": 200}
            else: raise AssertionError("Undocumented route used")
        elif method == "POST":
            assert request.headers["Content-Type"] == "application/json"
            status = 201
            if path == "/v2/forms":
                assert set(body) == {"name", "group_id", "active"} and body["active"] == 3
                self.forms["5"] = {"id": 5, **body}; result = {"data": self.forms["5"], "status_code": 201}
            else:
                assert path == "/v2/groups" and set(body) == {"name", "parent_id"}
                self.groups["6"] = {"id": 6, **body}; result = {"data": self.groups["6"], "status_code": 201}
        else:
            assert method == "PUT" and set(body) in ({"name"}, {"group_id"}, {"active"})
            collection = self.forms if path.startswith("/v2/forms/") else self.groups
            row = collection[path.split("/")[-1]]; row.update(body); result = {"data": row, "status_code": 200}
        if self.after_request: self.after_request(request)
        return httpx.Response(status, json=deepcopy(result))


@pytest.fixture
def world(monkeypatch):
    result = World()
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["require_public"] is True and kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        kwargs.pop("require_public")
        async with httpx.AsyncClient(transport=httpx.MockTransport(result.handle), **kwargs) as value: yield value
    monkeypatch.setattr(F, "guarded_async_client", client)
    return result


def test_actual_discriminated_adapter_schema_covers_every_operation_and_integer_ids():
    adapter = TypeAdapter(F.FormBuilder123Operation); schema = adapter.json_schema()
    assert set(schema["discriminator"]["mapping"]) == set(CONFIGS) == set(F.OPS)
    for op, config in CONFIGS.items():
        data = {"operation": op, **deepcopy(config)}
        for key, value in config.items():
            if key.endswith("_id"): data[key] = int(value)
        model = adapter.validate_python(data)
        assert model.operation == op
        for key, value in config.items():
            if key.endswith("_id"): assert getattr(model, key) == value


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", F.OPS)
async def test_actual_native_parse_execute_and_closed_wire(world, operation):
    data = {"credentials": deepcopy(AUTH), "config": {"operation": operation, **CONFIGS[operation]}}
    node = F.FormBuilder123Node("fixture", F.NODE_TYPE, data, config=F.FormBuilder123Node.parse_config(data), user_id=USER)
    output = await node.execute({})
    assert "PRIVATE-" not in str(output) and AUTH["token"] not in str(output)
    if operation in {"create_inactive_form", "rename_form", "move_form", "deactivate_form", "create_group", "rename_group"}: assert output["readback_verified"] is True
    if operation == "check_connection": assert output == {"reachable": True, "proves": "reachability", "identity_verified": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", [("us", "api.123formbuilder.com"), ("eu", "eu-api.123formbuilder.com")])
async def test_fixed_regions_and_query_token_logging_privacy(world, caplog, region, host):
    def log(request): logging.getLogger("httpx").warning("PRIVATE-REQUEST %s %s", request.url, AUTH["token"])
    world.after_request = log
    with caplog.at_level(logging.WARNING): await F.records({**AUTH, "region": region}, {"operation": "check_connection"})
    assert world.calls[0].url.host == host and "PRIVATE-" not in caplog.text and AUTH["token"] not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status429", "status503", "error200", "wrong_status", "invalid_json", "duplicate_json", "pagination"])
async def test_exact_error_and_envelope_contract_no_retry_or_reflection(world, failure):
    def override(request):
        if failure.startswith("status"): return httpx.Response(int(failure[-3:]), json={"error": AUTH})
        if failure == "error200": return httpx.Response(200, json={"error": {"message": AUTH}, "status_code": 200})
        if failure == "wrong_status": return httpx.Response(200, json={"status_code": 401, "data": []})
        if failure == "invalid_json": return httpx.Response(200, content=b"PRIVATE-TOKEN")
        if failure == "duplicate_json": return httpx.Response(200, content=b'{"status_code":200,"status_code":401}')
        result = world.paged([], request); result["meta"]["pagination"]["current_page"] = 9
        return httpx.Response(200, json=result)
    world.override = override
    with pytest.raises(RuntimeError) as error: await F.records(AUTH, {"operation": "check_connection"})
    assert AUTH["token"] not in str(error.value) and "PRIVATE-" not in str(error.value) and len(world.calls) == 1


@pytest.mark.asyncio
async def test_real_numeric_picker_cursor_bound_to_token_parent_search_and_region(world):
    def paged(request):
        if request.url.path != "/v2/forms": return None
        number = int(request.url.params["page"])
        rows = [{"id": i, "name": "Paged form"} for i in (range(1, 51) if number == 1 else [51])]
        return httpx.Response(200, json={"data": rows, "status_code": 200, "meta": {"pagination": {"count": len(rows), "total": 51, "current_page": number, "per_page": 50, "total_pages": 2, "links": {"next": "https://private.invalid/?JWT=PRIVATE-LINK"}}}})
    world.override = paged
    first = await F.FormBuilder123Node.load_field_options("form_id", AUTH)
    second = await F.FormBuilder123Node.load_field_options("form_id", AUTH, page_token=first["next_page_token"])
    assert second == {"options": [{"value": "51", "label": "Paged form"}], "next_page_token": None}
    before = len(world.calls)
    for changed in ({**AUTH, "region": "eu"}, {**AUTH, "token": "changed-token"}):
        with pytest.raises(ValueError): await F.FormBuilder123Node.load_field_options("form_id", changed, page_token=first["next_page_token"])
    with pytest.raises(ValueError): await F.FormBuilder123Node.load_field_options("form_id", AUTH, search="changed", page_token=first["next_page_token"])
    with pytest.raises(ValueError): await F.FormBuilder123Node.load_field_options("field_id", AUTH, context={})
    assert len(world.calls) == before


@pytest.mark.asyncio
async def test_actual_int64_path_and_result_preserve_ids_above_javascript_precision(world):
    large = 9223372036854775807
    world.forms[str(large)] = {"id": large, "name": "Large fixture"}
    result = await F.records(AUTH, {"operation": "get_form", "form_id": str(large)})
    assert result["record"]["id"] == str(large) and world.calls[0].url.path == "/v2/forms/"+str(large)


@pytest.mark.asyncio
async def test_nested_parent_witness_and_management_readback_refuse_foreign_success(world):
    world.submission["form_id"] = 99
    with pytest.raises(RuntimeError): await F.records(AUTH, {"operation": "get_submission", "form_id": "1", "submission_id": "7"})
    def ignore_write(request):
        if request.method == "PUT": return httpx.Response(200, json={"status_code": 200, "data": world.forms["1"]})
    world.override = ignore_write
    with pytest.raises(RuntimeError): await F.records(AUTH, {"operation": "rename_form", "form_id": "1", "name": "Expected name"})
    assert sum(r.method == "PUT" for r in world.calls) == 1


@pytest.mark.parametrize("change", [{"credential_type": "slack_oauth"}, {"region": "other"}, {"token": 123}, {"token": {}}, {"token": "YOUR_API_KEY"}, {"token": "https://private.invalid/PRIVATE-TOKEN"}, {"token": "bad\nPRIVATE-TOKEN"}, {"api_key": "legacy-v1-key"}, {"password": "PRIVATE-PASSWORD"}])
def test_raw_credential_shape_refusal_is_safe_before_native_transport(world, change):
    with pytest.raises(ValueError) as error: F.FormBuilder123Node.parse_config({"credentials": {**AUTH, **change}, "config": {"operation": "check_connection"}})
    assert "PRIVATE-" not in str(error.value) and AUTH["token"] not in str(error.value) and world.calls == []


@pytest.mark.parametrize("bad", [True, -1, 0, "9223372036854775808", "1/2", "https://private.invalid"])
def test_int64_identifiers_fail_safely_in_actual_native_model(bad):
    with pytest.raises(ValueError): F.FormBuilder123Node.parse_config({"credentials": AUTH, "config": {"operation": "get_form", "form_id": bad}})
