"""Fulcrum contracts through the native factory and staging credential resolver.

HTTP and credential loading are synthetic boundaries. These
fixtures are unrun source and do not prove provider, public DNS or live DB access.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import fulcrum_node as fc
from nodes.core.registry import NODE_REGISTRY, NodeFactory

USER = "66666666-6666-4666-8666-666666666666"
OWNER = "77777777-7777-4777-8777-777777777777"
NODE = "automation-fulcrum"
FORM = "11111111-1111-4111-8111-111111111111"
OTHER_FORM = "22222222-2222-4222-8222-222222222222"
RECORD = "33333333-3333-4333-8333-333333333333"
PROJECT = "44444444-4444-4444-8444-444444444444"
CHOICES = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "fulcrum_api_token", "api_token": "fixture-token", **updates}


def form():
    return {"id": FORM, "name": "Fixture form", "version": 2, "title_field_keys": ["text"],
        "elements": [{"type": "TextField", "key": "text", "label": "Name"},
            {"type": "Section", "label": "Details", "elements": [
                {"type": "TextField", "key": "number", "label": "Count", "numeric": True}]},
            {"type": "CalculatedField", "key": "computed", "label": "Calculated"},
            {"type": "Repeatable", "key": "children", "label": "Children", "elements": [
                {"type": "TextField", "key": "child", "label": "Child"}]}],
        "script": "private form code", "data_events": "private"}


def record(**updates):
    return {"id": RECORD, "form_id": FORM, "version": 2,
        "latitude": 0.0, "longitude": 0.0, "form_values": {"text": "Fixture", "number": "0"},
        "created_by": "private person", "gps_accuracy": 5, **updates}


def make_node(operation, data=None, **config):
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **config},
        "credentials": credential() if data is None else data}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        status, payload = state.responses.pop(0)
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(fc, "guarded_async_client", client)
    return state



def test_actual_factory_schema_and_required_field_contracts():
    assert NODE_REGISTRY[NODE] is fc.FulcrumNode
    schema = fc.FulcrumNode.get_config_schema()
    members = schema["properties"]["config"]["oneOf"]
    ops = {schema["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in members}
    assert len(ops) == 20 and {"create_record", "update_record", "set_record_field"} <= ops
    cred = schema["$defs"]["FulcrumAPITokenCredential"]
    assert cred["required"] == ["api_token"] and "x-oauth-provider" not in cred
    assert cred["properties"]["api_token"]["minLength"] == 1
    fields = schema["$defs"]["FulcrumSetRecordFieldConfig"]["properties"]
    assert fields["record_id"]["x-dynamic-options"]["depends_on"] == "form_id"
    assert fields["field_key"]["x-dynamic-options"]["depends_on"] == "form_id"
    node = make_node("set_record_field", form_id=FORM, record_id=RECORD, field_key="text", value=None)
    assert node.config.config.value is None and node.config.config.skip_workflows is True
    # Manager metadata must remain compatible with the actual factory, without
    # becoming user-selectable authentication fields.
    make_node("list_forms", credential(token_version=9, updated_at="2026-01-01T00:00:00Z"))
    with pytest.raises(ValidationError):
        fc.FulcrumCreateRecordConfig(form_id=FORM, latitude=0, longitude=0)
    with pytest.raises(ValidationError):
        fc.FulcrumCreateRecordConfig(form_id=FORM, latitude=91, longitude=0, form_values={})
    with pytest.raises(ValidationError):
        fc.FulcrumListFormsConfig(organization_id=OWNER, sql="untrusted")


@pytest.mark.parametrize("value", ["", "token\nheader", " "])
def test_invalid_token_shape_before_provider(value):
    with pytest.raises(ValueError):
        fc._credential(credential(api_token=value))
    with pytest.raises(ValueError):
        fc._credential({"credential_type": "other", "api_token": "fixture"})


@pytest.mark.asyncio
async def test_exact_header_root_metadata_projection_and_no_query_token(http):
    http.responses = [(200, {"forms": [form()], "current_page": 1, "total_pages": 1, "total_count": 1})]
    out = await make_node("list_forms").execute({})
    request = http.calls[0]
    assert str(request.url).startswith(fc.API_ROOT + "/forms.json?")
    assert request.headers["X-ApiToken"] == "fixture-token"
    assert "token" not in str(request.url) and "authorization" not in request.headers
    assert request.url.params["schema"] == "false" and request.url.params["per_page"] == "25"
    assert out["items"][0]["name"] == "Fixture form" and "elements" not in out["items"][0]
    assert "script" not in out["items"][0] and out["snapshot"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("skip", [True, False])
async def test_patch_preserves_omitted_fields_and_explicit_null_with_controls(http, skip):
    http.responses = [(200, {"form": form()}), (200, {"record": record()}),
        (200, {"record": record(form_values={"text": None, "number": "0"})})]
    out = await make_node("set_record_field", form_id=FORM, record_id=RECORD,
        field_key="text", value=None, skip_workflows=skip, skip_webhooks=skip).execute({})
    request = http.calls[-1]
    assert request.method == "PATCH" and json.loads(request.content) == {"record": {"form_values": {"text": None}}}
    assert request.headers["X-SkipWorkflows"] == str(skip).lower()
    assert request.headers["X-SkipWebhooks"] == str(skip).lower()
    assert out["record"]["form_values"]["text"] is None and "created_by" not in out["record"]
    assert all(r.method == "GET" for r in http.calls[:-1])


@pytest.mark.asyncio
async def test_create_record_uses_documented_200_and_preserves_zero_empty(http):
    http.responses = [(200, {"form": form()}), (200, {"record": record(form_values={"text": "", "number": "0"})})]
    out = await make_node("create_record", form_id=FORM, latitude=0, longitude=0,
        form_values={"text": "", "number": "0"}).execute({})
    body = json.loads(http.calls[-1].content)["record"]
    assert body == {"form_id": FORM, "latitude": 0.0, "longitude": 0.0, "form_values": {"text": "", "number": "0"}}
    assert http.calls[-1].method == "POST" and out["http_status"] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["child", "foreign", "computed", "children"])
async def test_current_form_unknown_calculated_and_repeatable_patch_refusal(http, key):
    http.responses = [(200, {"form": form()}), (200, {"record": record()})]
    with pytest.raises(ValueError):
        await make_node("set_record_field", form_id=FORM, record_id=RECORD, field_key=key, value=None).execute({})
    assert len(http.calls) == 2 and all(r.method == "GET" for r in http.calls)


@pytest.mark.asyncio
async def test_foreign_form_record_never_written(http):
    http.responses = [(200, {"form": form()}), (200, {"record": record(form_id=OTHER_FORM)})]
    with pytest.raises(RuntimeError, match="another form"):
        await make_node("delete_record", form_id=FORM, record_id=RECORD).execute({})
    assert all(r.method == "GET" for r in http.calls)


@pytest.mark.asyncio
async def test_missing_current_form_schema_never_becomes_empty_writable_form(http):
    http.responses = [(200, {"form": {"id": FORM, "name": "Incomplete"}})]
    with pytest.raises(RuntimeError, match="field limit"):
        await make_node("create_record", form_id=FORM, latitude=0, longitude=0, form_values={}).execute({})
    assert len(http.calls) == 1 and http.calls[0].method == "GET"


@pytest.mark.asyncio
async def test_project_put_merges_current_metadata_and_reads_back(http):
    old = {"id": PROJECT, "name": "Existing", "description": "Retained", "created_by": "private",
        "status": "Active", "customer": "Existing customer", "external_job_id": "job-1",
        "start_date": "2026-01-01", "end_date": None, "project_manager_id": OWNER}
    http.responses = [(200, {"project": old}), (200, {}), (200, {"project": {**old, "name": "Renamed"}})]
    out = await make_node("update_project", project_id=PROJECT, name="Renamed").execute({})
    assert json.loads(http.calls[1].content) == {"project": {
        **{key: value for key, value in old.items() if key not in {"id", "created_by"}}, "name": "Renamed"}}
    assert [r.method for r in http.calls] == ["GET", "PUT", "GET"]
    assert out["project"]["name"] == "Renamed" and "created_by" not in out["project"]
    assert "project_manager_id" not in out["project"]


@pytest.mark.asyncio
async def test_metadata_readback_mismatch_cannot_claim_success(http):
    old = {"id": PROJECT, "name": "Existing", "description": "Retained"}
    http.responses = [(200, {"project": old}), (200, {}), (200, {"project": old})]
    with pytest.raises(RuntimeError, match="could not be confirmed"):
        await make_node("update_project", project_id=PROJECT, name="Renamed").execute({})


@pytest.mark.asyncio
async def test_choice_replacement_empty_and_project_delete_204(http):
    old = {"id": CHOICES, "name": "Choices", "choices": [{"label": "One", "value": "one"}]}
    http.responses = [(200, {"choice_list": old}), (200, {}), (200, {"choice_list": {**old, "choices": []}})]
    out = await make_node("update_choice_list", choice_list_id=CHOICES, choices=[]).execute({})
    assert json.loads(http.calls[1].content) == {"choice_list": {"name": "Choices", "choices": []}}
    assert out["choice_list"]["choices"] == []
    http.responses = [(200, {"project": {"id": PROJECT, "name": "Disposable"}}), (204, None)]
    out = await make_node("delete_project", project_id=PROJECT).execute({})
    assert out == {"deleted": True, "project_id": PROJECT, "http_status": 204}


@pytest.mark.asyncio
async def test_record_list_parent_filters_and_epoch_seconds(http):
    http.responses = [(200, {"form": form()}), (200, {"records": [record()], "current_page": 1, "total_pages": 1})]
    out = await make_node("list_records", form_id=FORM, updated_since=1720000000, updated_before=1730000000).execute({})
    params = http.calls[-1].url.params
    assert params["form_id"] == FORM and params["updated_since"] == "1720000000"
    assert params["updated_before"] == "1730000000" and out["items"][0]["form_id"] == FORM


@pytest.mark.asyncio
async def test_history_preserves_versions_without_private_editor_identity(http):
    versions = [record(version=1, history_id="first", history_change_type="c", history_changed_by="Private"),
        record(version=2, history_id="second", history_change_type="u")]
    http.responses = [(200, {"form": form()}), (200, {"record": record()}), (200, {"records": versions})]
    out = await make_node("get_record_history", form_id=FORM, record_id=RECORD).execute({})
    assert [row["version"] for row in out["records"]] == [1, 2]
    assert [row["history_id"] for row in out["records"]] == ["first", "second"]
    assert "history_changed_by" not in out["records"][0] and out["complete"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 201])
async def test_documented_project_create_empty_body_has_no_fabricated_identity(http, status):
    http.responses = [(status, {})]
    out = await make_node("create_project", name="Disposable").execute({})
    assert out == {"created": True, "project": None, "http_status": status}
    assert json.loads(http.calls[0].content) == {"project": {"name": "Disposable"}}


@pytest.mark.asyncio
async def test_picker_zero_match_keeps_own_cursor_and_rejects_other_search_token(http):
    http.responses = [(200, {"forms": [form()], "current_page": 1, "total_pages": 2})]
    result = await fc.FulcrumNode.load_field_options("form_id", credential(), search="missing")
    assert result["options"] == [] and result["next_page_token"]
    before = len(http.calls)
    with pytest.raises(ValueError, match="does not match"):
        await fc.FulcrumNode.load_field_options("form_id", credential(), search="different", page_token=result["next_page_token"])
    with pytest.raises(ValueError, match="does not match"):
        await fc.FulcrumNode.load_field_options("form_id", credential(api_token="reconnected"), search="missing", page_token=result["next_page_token"])
    assert len(http.calls) == before


@pytest.mark.asyncio
async def test_record_and_field_picker_use_current_form_ancestry(http):
    http.responses = [(200, {"form": form()}), (200, {"records": [record()], "total_pages": 1})]
    out = await fc.FulcrumNode.load_field_options("record_id", credential(), context={"form_id": FORM}, search="Fixture")
    assert out["options"] == [{"value": RECORD, "label": "Fixture"}]
    assert http.calls[-1].url.params["form_id"] == FORM
    http.responses = [(200, {"form": form()})]
    out = await fc.FulcrumNode.load_field_options("field_key", credential(), context={"form_id": FORM})
    assert {row["value"] for row in out["options"]} == {"text", "number"}
    assert out["next_page_token"] is None
    before = len(http.calls)
    with pytest.raises(ValueError):
        await fc.FulcrumNode.load_field_options("record_id", credential(), context={"form_id": "bad"})
    with pytest.raises(ValueError):
        await fc.FulcrumNode.load_field_options("field_key", credential(), context={"form_id": FORM}, page_token="fake")
    assert len(http.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"forms": {}}, {"forms": [], "success": False},
    {"error": "fixture-token private-provider-message"}, {"forms": [{"id": FORM, "name": {}}]}])
async def test_malformed_or_outer_error_cannot_be_empty_success(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError) as failed:
        await make_node("list_forms").execute({})
    assert "fixture-token" not in str(failed.value) and "private-provider-message" not in str(failed.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_static_safe_unknown_access(http, status):
    http.responses = [(status, {"error": "fixture-token https://private.example"})]
    with pytest.raises(RuntimeError) as failed:
        await make_node("list_forms").execute({})
    assert "fixture-token" not in str(failed.value) and "private.example" not in str(failed.value)
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_nonrotating_token_hook(http):
    assert await fc.FulcrumNode.freshen_credential(credential()) == credential()
    assert http.calls == []


@pytest.mark.asyncio
async def test_saved_execution_loads_current_staging_credential(http, monkeypatch):
    resolver = AsyncMock(return_value=credential(api_token="current-token"))
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", resolver)
    node = make_node("list_forms")
    node.node_data["credential_id"] = "saved-id"
    node._approval_pool = object()
    http.responses = [(200, {"forms": [form()], "total_pages": 1})]
    await node.execute({})
    resolver.assert_awaited_once()
    assert resolver.call_args.kwargs["credential_id"] == "saved-id"
    assert http.calls[0].headers["X-ApiToken"] == "current-token"


@pytest.mark.asyncio
async def test_unavailable_saved_connection_prevents_provider_io(http, monkeypatch):
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", AsyncMock(return_value=None))
    node = make_node("list_forms")
    node.node_data["credential_id"] = "saved-id"
    node._approval_pool = object()
    with pytest.raises(ValueError, match="unavailable"):
        await node.execute({})
    assert http.calls == []


@pytest.mark.asyncio
async def test_validate_access_uses_bounded_protected_forms(http):
    http.responses = [(200, {"forms": [form()], "total_pages": 1})]
    assert await fc.FulcrumNode.validate_credential_access(credential()) == {"valid": True}
    assert http.calls[0].url.params["per_page"] == "1"
