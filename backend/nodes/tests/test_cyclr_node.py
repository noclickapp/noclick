"""Unrun native Cyclr contract, parent, paging and privacy regression source."""
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import cyclr_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": node.TYPES[0], "access_token": "fixture-console-token", "account_id": "fixture-account", "region": "us"}
CYCLE_ID = "11111111-1111-4111-8111-111111111111"
STEP_ID = "22222222-2222-4222-8222-222222222222"
TEMPLATE_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ID = "44444444-4444-4444-8444-444444444444"
PRIVATE = {"Name": "PRIVATE NAME", "Description": "PRIVATE DESCRIPTION", "connectorAuthValue": "PRIVATE AUTH", "Settings": {"password": "PRIVATE PASSWORD"}, "Parameters": ["PRIVATE PARAMETERS"], "Url": "https://private.example.test/capability"}
ACCOUNT = {"Id": "fixture-account", "CreatedDate": "2026-10-07T00:00:00Z", "Timezone": "UTC", **PRIVATE}
CYCLE = {"Id": CYCLE_ID, "Status": "Stopped", "CreatedOnUtc": "2026-10-07T00:00:00Z", **PRIVATE}
STEP = {"Id": STEP_ID, "ActionType": "Action", **PRIVATE}
TEMPLATE = {"Id": TEMPLATE_ID, "ReleaseStatus": "Draft", **PRIVATE}
CONNECTOR = {"Id": 123, "Version": "1.0", "ReleaseVersion": "1.0", "IsSystemConnector": True, **PRIVATE}


@pytest.fixture
def transport(monkeypatch):
    calls = []
    state = {"status": 200, "content": None, "content_type": "application/json", "routes": {
        "/v1.0/accounts/fixture-account": ACCOUNT, "/v1.0/accounts": [ACCOUNT],
        "/v1.0/Cycles": [CYCLE], "/v1.0/Cycles/" + CYCLE_ID: CYCLE,
        "/v1.0/Cycles/" + CYCLE_ID + "/steps": [STEP],
        "/v1.0/Cycles/" + CYCLE_ID + "/steps/" + STEP_ID: STEP,
        "/v1.0/Templates": [TEMPLATE], "/v1.0/Templates/" + TEMPLATE_ID: TEMPLATE,
        "/v1.0/connectors": [CONNECTOR],
    }}
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def remote(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.cyclr.com"
        assert request.headers["Authorization"] == "Bearer " + CREDENTIAL["access_token"]
        assert CREDENTIAL["access_token"] not in str(request.url)
        if request.url.path.startswith("/v1.0/accounts"):
            assert "X-Cyclr-Account" not in request.headers
        else:
            assert request.headers["X-Cyclr-Account"] == CREDENTIAL["account_id"]
        kwargs = {"content": state["content"]} if state["content"] is not None else {"json": deepcopy(state["routes"][request.url.path])}
        return httpx.Response(state["status"], headers={"Content-Type": state["content_type"], "Retry-After": "10"}, **kwargs)
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(remote), **kwargs))
    return calls, state


@pytest.mark.parametrize("config", [node.GetAccount(), node.ListAccounts(), node.ListCycles(), node.GetCycle(cycle_id=CYCLE_ID), node.ListCycleSteps(cycle_id=CYCLE_ID), node.GetCycleStep(cycle_id=CYCLE_ID, step_id=STEP_ID), node.ListTemplates(), node.GetTemplate(template_id=TEMPLATE_ID), node.ListConnectorCatalog()])
async def test_nine_actual_routes_and_closed_private_projection(transport, config):
    calls, _ = transport
    result = await node.request_operation(CREDENTIAL, config)
    assert calls[0].url.path == "/v1.0/accounts/fixture-account"
    assert "data" in result
    assert all(value not in str(result) for value in ("PRIVATE", "capability", CREDENTIAL["access_token"], "connectorAuthValue", "Settings", "Parameters"))
    assert all(request.method == "GET" for request in calls)


async def test_names_opt_in_keeps_other_private_fields_excluded(transport):
    result = await node.request_operation(CREDENTIAL, node.GetCycle(cycle_id=CYCLE_ID, include_names=True))
    assert result["data"]["name"] == "PRIVATE NAME"
    assert "PRIVATE DESCRIPTION" not in str(result) and "PRIVATE AUTH" not in str(result)


async def test_execute_prevalidated_config_without_duplicate_raw_data(transport):
    config = node.CyclrNodeConfig.model_validate({"config": {"operation": "get_account"}, "credentials": CREDENTIAL})
    instance = node.CyclrNode(node_id="cyclr", node_type="automation-cyclr", node_data={}, config=config)
    result = await instance.execute({})
    assert result["status"] == "success" and result["data"]["id"] == CREDENTIAL["account_id"]
    assert len(transport[0]) == 1


@pytest.mark.parametrize("kind,path,change,config", [
    ("account", "/v1.0/accounts/fixture-account", "other-account", node.ListCycles()),
    ("cycle", "/v1.0/Cycles/" + CYCLE_ID, OTHER_ID, node.ListCycleSteps(cycle_id=CYCLE_ID)),
    ("step", "/v1.0/Cycles/" + CYCLE_ID + "/steps/" + STEP_ID, OTHER_ID, node.GetCycleStep(cycle_id=CYCLE_ID, step_id=STEP_ID)),
    ("template", "/v1.0/Templates/" + TEMPLATE_ID, OTHER_ID, node.GetTemplate(template_id=TEMPLATE_ID)),
])
async def test_response_parent_id_mismatch_never_accepted(transport, kind, path, change, config):
    calls, state = transport
    state["routes"][path] = {**state["routes"][path], "Id": change}
    with pytest.raises(ValueError, match="selected parent"):
        await node.request_operation(CREDENTIAL, config)
    assert calls[-1].url.path == path


async def test_step_membership_checked_before_detail_request(transport):
    calls, state = transport
    state["routes"]["/v1.0/Cycles/" + CYCLE_ID + "/steps"] = [{**STEP, "Id": OTHER_ID}]
    with pytest.raises(ValueError, match="does not belong"):
        await node.request_operation(CREDENTIAL, node.GetCycleStep(cycle_id=CYCLE_ID, step_id=STEP_ID))
    assert len(calls) == 3 and not any(request.url.path.endswith("/steps/" + STEP_ID) for request in calls)


async def test_documented_page_one_and_bound_continuation(transport):
    calls, _ = transport
    config = node.ListCycles(page_size=1)
    first = (await node.request_operation(CREDENTIAL, config))["data"]
    assert first["has_more"] is None and first["next_page_token"]
    assert dict(calls[-1].url.params) == {"pageSize": "1", "page": "1", "sortOrderAsc": "true", "includeIcons": "false", "includePrerequisites": "false", "countAllIncidents": "false", "orderBy": "UpdatedOnUtc"}
    second = node.ListCycles.model_validate({**config.model_dump(), "page_token": first["next_page_token"]})
    await node.request_operation(CREDENTIAL, second)
    assert calls[-1].url.params["page"] == "2"
    before = len(calls)
    with pytest.raises(ValueError, match="Continuation changed"):
        await node.request_operation(CREDENTIAL, node.ListCycles.model_validate({**second.model_dump(), "include_names": True}))
    assert len(calls) == before + 1  # Only the protected account binding precedes paging validation.


async def test_catalog_and_template_suppress_sensitive_expansions(transport):
    calls, _ = transport
    await node.request_operation(CREDENTIAL, node.ListConnectorCatalog())
    assert calls[-1].url.params["includeCustomConnectors"] == "false"
    await node.request_operation(CREDENTIAL, node.GetTemplate(template_id=TEMPLATE_ID))
    assert dict(calls[-1].url.params) == {"includeIcons": "false", "includePrerequisites": "false", "includeOptional": "false", "lookupCustomFields": "false"}


@pytest.mark.parametrize("status", [202, 204, 301, 400, 401, 403, 404, 429, 500])
async def test_non_200_never_success_or_error_body_disclosure(transport, status):
    calls, state = transport
    state.update(status=status, content=CREDENTIAL["access_token"].encode())
    with pytest.raises(node.CyclrAPIError) as caught:
        await node.request_operation(CREDENTIAL, node.GetAccount())
    assert caught.value.http_status == status and caught.value.retry_after == 10
    assert CREDENTIAL["access_token"] not in str(caught.value) and len(calls) == 1


@pytest.mark.parametrize("raw", [b'{"Id":"x","Id":"y"}', b'{"Id":NaN}', b'{"value":1e999}', b'<html>not JSON</html>'])
def test_duplicate_nonfinite_and_non_json_refused(raw):
    with pytest.raises(ValueError, match="JSON"):
        node.finite_json(raw)


@pytest.mark.parametrize("content_type", ["application/json", "text/json; charset=utf-8"])
async def test_both_documented_json_media_types(transport, content_type):
    _, state = transport
    state["content_type"] = content_type
    assert (await node.request_operation(CREDENTIAL, node.GetAccount()))["data"]["id"] == CREDENTIAL["account_id"]


async def test_oversized_response_never_returns_partial_result(transport):
    _, state = transport
    state["content"] = b" " * (node.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="2 MiB"):
        await node.request_operation(CREDENTIAL, node.GetAccount())


@pytest.mark.parametrize("rows", [[{"Id": True}], [CYCLE, CYCLE], {"items": [CYCLE]}, [CYCLE] * 101])
def test_shape_identity_duplicates_and_native_limit_loud(rows):
    with pytest.raises(ValueError):
        node.rows_value(rows, node.credential_value(CREDENTIAL), "cycle", limit=100)


@pytest.mark.parametrize("context", [{"account_id": "other"}, {"access_token": "forged"}, {"_credential_type": node.TYPES[0]}, {"field_scopes": {"cycle_id": [OTHER_ID]}}, {"region": "uk"}])
async def test_picker_private_scope_refusal_before_io(transport, context):
    calls, _ = transport
    with pytest.raises(ValueError):
        await node.CyclrNode.load_field_options("cycle_id", CREDENTIAL, context=context)
    assert calls == []


async def test_step_picker_exact_parent_id_labels_no_invented_paging(transport):
    calls, _ = transport
    result = await node.CyclrNode.load_field_options("step_id", CREDENTIAL, context={"cycle_id": CYCLE_ID}, search="2222")
    assert result == {"options": [{"value": STEP_ID, "label": "Step " + STEP_ID, "metadata": {"account_id": CREDENTIAL["account_id"], "cycle_id": CYCLE_ID}}], "next_page_token": None}
    assert len(calls) == 3
    with pytest.raises(ValueError, match="no documented pagination"):
        await node.CyclrNode.load_field_options("step_id", CREDENTIAL, context={"cycle_id": CYCLE_ID}, page_token="1")
    assert len(calls) == 3


@pytest.mark.parametrize("field,value", [("cycle_id", 123), ("cycle_id", True), ("account_id", "other"), ("headers", {"Authorization": "forged"}), ("connectorAuthValue", "private"), ("run", True)])
def test_raw_config_cannot_override_native_authority(field, value):
    raw = {"config": {"operation": "get_cycle", "cycle_id": CYCLE_ID, field: value}, "credentials": CREDENTIAL}
    assert node.CyclrNode.validate_config(raw)["valid"] is False
    with pytest.raises(ValueError):
        node.CyclrNode.parse_config(raw)
