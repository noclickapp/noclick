"""Superwall wire, factory, paging and privacy regressions.

The real registered node/config/dispatcher/collector use a synthetic HTTPS
boundary. No live API credentials or provider calls are used.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from nodes import superwall_node as p
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
PROJECT, SECOND, APP, PRODUCT, ENTITLEMENT = "project_fixture", "project_second", "app_fixture", "product_fixture", "entitlement_fixture"
STAMP = "2026-10-01T12:30:00Z"
PRIVATE = "SYNTHETIC_PRIVATE_MARKER"


def blob(**changes):
    return {"credential_type": p.FAMILY, "api_key": "synthetic-issued-organization-key", "organization_id": "42",
        "allowed_project_ids_json": json.dumps([PROJECT, SECOND]), "witness_project_id": PROJECT,
        "read_scopes": "projects:read applications:read products:read entitlements:read charts:read", **changes}


def application(uid=APP, project_id=PROJECT):
    return {"id": uid, "project_id": project_id, "name": "Fixture App", "platform": "ios", "created_at": STAMP,
        "updated_at": STAMP, "integrated": True, "globally_disabled": False, "slug": "fixture-app", "archived_at": None,
        "bundle_id": "test.fixture.app", "public_api_key": PRIVATE, "revenue_cat_api_key": PRIVATE,
        "notification_redirect_url": "https://external.example.test/" + PRIVATE, "email": PRIVATE, "icon": PRIVATE}


def project(uid=PROJECT, organization_id=42, apps=None):
    return {"id": uid, "object": "project", "name": "Fixture Project", "organization_id": organization_id,
        "applications": [application(project_id=uid)] if apps is None else apps,
        "created_at": STAMP, "updated_at": STAMP, "archived": False, "metadata": {"private": PRIVATE}}


def product(uid=PRODUCT, project_id=PROJECT, application_id=APP):
    return {"id": uid, "object": "product", "project_id": project_id, "application_id": application_id,
        "identifier": "fixture.product", "name": "Fixture Product", "platform": "ios", "store": "app_store",
        "entitlements": [ENTITLEMENT], "created_at": STAMP, "updated_at": STAMP, "metadata": {"private": PRIVATE},
        "price": 999, "secret": PRIVATE}


def entitlement(uid=ENTITLEMENT):
    return {"id": uid, "object": "entitlement", "project_id": PROJECT, "application_id": APP,
        "identifier": "fixture.entitlement", "name": "Fixture Definition", "products": [PRODUCT],
        "created_at": STAMP, "updated_at": STAMP, "metadata": {"private": PRIVATE}, "grant_token": PRIVATE}


def listed(path, rows, more=False):
    return {"object": "list", "url": path, "data": rows, "has_more": more}


def definitions():
    return {"object": "chart_definitions", "x_axis": [{"key": "date", "name": "Date", "value_type": "date"}],
        "y_axis": [{"key": "count", "name": "Count", "value_type": "number"}],
        "chart_types": [{"key": "fixture_chart", "name": "Fixture Aggregate", "x_axis": "date", "y_axis": "count",
            "date_dimension": "installDate", "include": [PRIVATE]}], "filters": [{"value": PRIVATE}], "breakdowns": [PRIVATE]}


def chart():
    return {"object": "chart_data", "data": [{"x": "2026-10-01", "incomplete": True,
        "values": {PRIVATE: {"y": 3, "extra": PRIVATE}}}], "series": [{"key": PRIVATE, "breakdown": PRIVATE}],
        "x_axis": {"key": "date", "name": "Date", "value_type": "date"},
        "y_axis": {"key": "count", "name": "Count", "value_type": "number"}, "enriched_data": {"private": PRIVATE},
        "request_id": PRIVATE, "filters": [PRIVATE], "table": {"private": PRIVATE}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], after_headers=None, after_body=None)
    class Response:
        def __init__(self, payload, status, ctype):
            self.status_code, self.headers = status, {"content-type": ctype, "location": "https://external.example.test/" + PRIVATE}
            self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        async def __aenter__(self):
            if state.after_headers: state.after_headers()
            return self
        async def __aexit__(self, *_): return False
        async def aiter_bytes(self):
            yield self.payload
            if state.after_body: state.after_body()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def stream(self, method, url, **kwargs):
            state.calls.append((method, url, deepcopy(kwargs)))
            assert state.queue, "Unexpected provider request beyond fixture"
            item = state.queue.pop(0)
            if isinstance(item, BaseException): raise item
            return Response(*item) if isinstance(item, tuple) else Response(item, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p.httpx, "AsyncClient", client)
    return state


async def execute(args, data=None):
    node = NodeFactory.create_node("fixture-node", p.NODE_TYPE, {"config": args, "credentials": data or blob()}, user_id=USER)
    assert node.config.config.operation == args["operation"]
    return await node.execute({"operation": "grant_entitlement", "project_id": "injected"})


@pytest.mark.asyncio
async def test_real_registered_factory_dispatcher_header_and_safe_project_projection(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.SuperwallNode
    wire.queue = [project()]
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="get_project", arguments={"operation": "publish", "project_id": PROJECT}, user_id=USER, credential_data=blob())
    assert result["project"]["id"] == PROJECT and result["identity_verified"] is False
    assert result["project"]["applications"][0]["project_link_verified"] is True
    method, url, args = wire.calls[0]
    assert (method, url) == ("GET", p.ROOT + "/v2/projects/" + PROJECT)
    assert args["headers"] == {"Authorization": "Bearer " + blob()["api_key"], "Accept": "application/json"}
    assert args["params"] is None and "json" not in args and blob()["api_key"] not in url
    assert PRIVATE not in json.dumps(result) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_actual_connect_collector_requires_real_project_not_empty_identity(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [project(), listed("/v2/projects", [])]
    positive = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert positive.ok and positive.evidence.reachable is True and p.SuperwallNode.connection_evidence.proves == "reachability"
    assert positive.evidence.account_label is None
    unknown = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert unknown.evidence.reachable is None and unknown.verified_metadata() == {}


@pytest.mark.asyncio
async def test_lists_repeat_documented_filters_and_keep_cap_and_cursor_honest(wire):
    wire.queue = [project(), listed("/v2/products", [product()], True), listed("/v2/products", [product("product_second")])]
    result = await execute({"operation": "list_products", "project_id": PROJECT, "limit": 1, "max_pages": 2, "platform": "ios"})
    assert result["pages_read"] == 2 and result["has_more"] is False and result["complete_from_first_page"] is True
    assert wire.calls[1][2]["params"] == {"limit": "1", "project_id": PROJECT, "platform": "ios"}
    assert wire.calls[2][2]["params"] == {"limit": "1", "project_id": PROJECT, "platform": "ios", "starting_after": PRODUCT}
    wire.queue = [project(), listed("/v2/products", [product()], True)]
    capped = await execute({"operation": "list_products", "project_id": PROJECT, "limit": 1})
    assert capped["has_more"] and capped["next_starting_after"] == PRODUCT and not capped["complete_from_first_page"]
    wire.queue = [project(), listed("/v2/products", [product("product_second")])]
    later = await execute({"operation": "list_products", "project_id": PROJECT, "starting_after": PRODUCT})
    assert not later["has_more"] and not later["complete_from_first_page"] and PRIVATE not in json.dumps(later)


@pytest.mark.asyncio
async def test_project_list_org_archived_filter_and_organization_witness(wire):
    wire.queue = [listed("/v2/projects", [project()]), project(), {"object": "organization", "id": 42, "name": "Fixture Org", "can_manage": True, "key": PRIVATE}]
    result = await execute({"operation": "list_projects", "archived": False})
    assert result["data"][0]["id"] == PROJECT
    assert wire.calls[0][2]["params"] == {"organization_id": "42", "limit": "50", "archived": "false"}
    org = await execute({"operation": "get_organization"})
    assert org["organization"] == {"object": "organization", "id": 42, "name": "Fixture Org"} and not org["identity_verified"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["foreign-org", "foreign-project", "foreign-app", "duplicate-app", "bool-org"])
async def test_project_and_application_ancestry_rejects_before_child_read(wire, change):
    row = project()
    if change == "foreign-org": row["organization_id"] = 99
    if change == "foreign-project": row["id"] = "unapproved"
    if change == "foreign-app": row["applications"][0]["project_id"] = SECOND
    if change == "duplicate-app": row["applications"].append(application())
    if change == "bool-org": row["organization_id"] = True
    wire.queue = [row]
    with pytest.raises(RuntimeError): await execute({"operation": "get_product", "project_id": PROJECT, "product_id": PRODUCT})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_nullable_app_link_is_metadata_only_and_cannot_authorize_products(wire):
    wire.queue = [project(apps=[application(project_id=None)]), project(apps=[application(project_id=None)]), product()]
    result = await execute({"operation": "list_applications", "project_id": PROJECT})
    assert result["applications"][0]["project_link_verified"] is False
    with pytest.raises(RuntimeError, match="witnessed project/application"):
        await execute({"operation": "get_product", "project_id": PROJECT, "product_id": PRODUCT})
    assert PRIVATE not in json.dumps(result) and len(wire.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [listed("/v2/products", [product()]), listed("/v2/products", [], True), listed("/v2/entitlements", [product("product_second")])])
async def test_repeated_cursor_empty_continuation_and_wrong_list_url_fail(wire, second):
    wire.queue = [project(), listed("/v2/products", [product()], True), second]
    with pytest.raises(RuntimeError): await execute({"operation": "list_products", "project_id": PROJECT, "limit": 1, "max_pages": 2})


@pytest.mark.asyncio
async def test_product_and_entitlement_gets_match_requested_id_and_parent(wire):
    wire.queue = [project(), product(), project(), entitlement(), project(), product("unexpected")]
    assert (await execute({"operation": "get_product", "project_id": PROJECT, "product_id": PRODUCT}))["data"]["entitlements"] == [ENTITLEMENT]
    assert (await execute({"operation": "get_entitlement", "project_id": PROJECT, "entitlement_id": ENTITLEMENT}))["data"]["products"] == [PRODUCT]
    with pytest.raises(RuntimeError, match="unexpected resource ID"):
        await execute({"operation": "get_product", "project_id": PROJECT, "product_id": PRODUCT})


@pytest.mark.asyncio
async def test_aggregate_chart_is_documented_post_read_and_omits_series_and_enriched_labels(wire):
    wire.queue = [project(), application(), definitions(), chart()]
    result = await execute({"operation": "query_chart_data", "project_id": PROJECT, "application_id": APP, "chart_key": "fixture_chart", "max_data_points": 1})
    assert wire.calls[1][2]["params"] == {"organization_id": "42"}
    assert wire.calls[2][2]["params"] == {"application_id": APP}
    assert wire.calls[3][0:2] == ("POST", p.ROOT + "/v2/charts/data")
    assert wire.calls[3][2]["json"] == {"application_id": APP, "x_axis": "date", "y_axis": "count",
        "date_filter": {"dimension": "installDate", "preset": "last_7_days"}, "date_interval": "day", "breakdown": None, "max_data_points": 1}
    assert result["data"][0]["values"] == [{"series_ordinal": 0, "y": 3.0}]
    assert result["contains_incomplete"] and not result["completion_verified"] and result["series_mapping_verified"]
    assert PRIVATE not in json.dumps(result) and len(wire.calls) == 4


@pytest.mark.asyncio
async def test_nullable_chart_series_encoding_is_not_invented(wire):
    row = chart()
    row["series"][0]["key"] = None
    wire.queue = [project(), application(), definitions(), row]
    result = await execute({"operation": "query_chart_data", "project_id": PROJECT, "application_id": APP, "chart_key": "fixture_chart"})
    assert result["series_mapping_verified"] is False and PRIVATE not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["private-x", "wrong-axis", "unknown-series", "nonfinite", "too-many-points"])
async def test_chart_privacy_shape_axes_and_requested_cap_are_enforced(wire, change):
    row = chart()
    if change == "private-x": row["data"][0]["x"] = PRIVATE
    if change == "wrong-axis": row["x_axis"]["value_type"] = "string"
    if change == "unknown-series": row["series"][0]["key"] = "other"
    if change == "nonfinite": row["data"][0]["values"][PRIVATE]["y"] = float("inf")
    if change == "too-many-points": row["data"].append(deepcopy(row["data"][0]))
    wire.queue = [project(), application(), definitions(), row]
    with pytest.raises(RuntimeError) as caught:
        await execute({"operation": "query_chart_data", "project_id": PROJECT, "application_id": APP, "chart_key": "fixture_chart", "max_data_points": 1})
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
async def test_local_project_picker_does_not_claim_existence_and_child_picker_retains_page(wire):
    local = await p.SuperwallNode.load_field_options("project_id", blob(), context={"allowed_project_ids_json": '["injected"]'}, search="second")
    assert local["options"] == [{"value": SECOND, "label": SECOND}] and not wire.calls
    wire.queue = [project(), listed("/v2/products", [product()], True)]
    filtered = await p.SuperwallNode.load_field_options("product_id", blob(), context={"project_id": PROJECT}, search="missing")
    assert filtered == {"options": [], "has_more": True, "next_page_token": PRODUCT}
    with pytest.raises(ValueError): await p.SuperwallNode.load_field_options("application_id", blob(), context={"project_id": "unapproved"})
    assert len(wire.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,ctype", [(401, "application/json"), (403, "application/json"), (404, "application/json"), (202, "application/json"),
    (204, "application/json"), (302, "application/json"), (429, "application/json"), (500, "text/html"), (200, "text/html")])
async def test_safe_status_and_redirect_refusal_is_not_empty_success(wire, status, ctype):
    wire.queue = [({"error": PRIVATE}, status, ctype)]
    with pytest.raises((ValueError, RuntimeError)) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b'{"id":"a","id":"b"}', b'{"data":NaN}', b' ' * 2_000_001, httpx.ReadTimeout(PRIVATE)])
async def test_invalid_or_large_json_and_transport_failure_remain_safe(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_native_saved_grants_prevent_unapproved_project_or_scope_before_network(wire):
    with pytest.raises(ValueError): await execute({"operation": "get_project", "project_id": "unapproved"})
    with pytest.raises(ValueError): await execute({"operation": "get_product", "project_id": PROJECT, "product_id": PRODUCT}, blob(read_scopes="projects:read"))
    assert not wire.calls


@pytest.mark.parametrize("bad", [None, "", "superwall_oauth", False])
def test_original_family_is_checked_before_pydantic_defaults(bad):
    raw = {"config": {"operation": "check_connection"}, "credentials": blob(credential_type=bad)}
    assert p.SuperwallNode.validate_config(raw)["valid"] is False
    with pytest.raises(ValueError): p.SuperwallNode.parse_config(raw)


def test_actual_native_schema_is_masked_manual_exact_twelve_reads_with_parent_dependencies():
    schema = p.SuperwallNode.get_config_schema()
    model = schema["$defs"]["SuperwallOrganizationAPIKeyCredential"]
    assert model["title"] == "Superwall Organization API Key" and "x-credential-type" not in model
    assert model["properties"]["api_key"]["ui:widget"] == "password"
    assert model["properties"]["read_scopes"]["default"] == "projects:read"
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS)
    assert schema["$defs"]["QueryChartData"]["properties"]["application_id"]["x-dynamic-options"]["depends_on"] == "project_id"
    assert schema["$defs"]["QueryChartData"]["properties"]["chart_key"]["x-dynamic-options"]["depends_on"] == "application_id"
    assert p.SuperwallNode.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for data in (blob(api_key=""), blob(api_key="  "), blob(cookie=PRIVATE), blob(organization_id="0"), blob(allowed_project_ids_json='["a","a"]'), blob(witness_project_id="unapproved"), blob(read_scopes="projects:write")):
        with pytest.raises(ValueError) as caught: p.credential(data)
        assert PRIVATE not in str(caught.value)
    for args in ({"project_id": "https://external.example.test/secret"}, {"project_id": PROJECT, "limit": True}, {"project_id": PROJECT, "max_pages": 4}):
        with pytest.raises(ValueError): p.ListProducts(**args)


@pytest.mark.asyncio
async def test_direct_node_uses_typed_config_credentials(wire):
    config = p.SuperwallNodeConfig.model_validate({"config": {"operation": "get_project", "project_id": PROJECT}, "credentials": blob()})
    node = p.SuperwallNode(node_id="direct", node_type=p.NODE_TYPE, node_data={}, config=config)
    wire.queue = [project()]
    result = await node.execute({})
    assert result["project"]["id"] == PROJECT
    assert wire.calls[0][2]["headers"]["Authorization"] == "Bearer " + blob()["api_key"]


@pytest.mark.asyncio
async def test_explicit_missing_raw_credentials_do_not_fall_back(wire):
    config = p.SuperwallNodeConfig.model_validate({"config": {"operation": "check_connection"}, "credentials": blob()})
    node = p.SuperwallNode(node_id="direct", node_type=p.NODE_TYPE, node_data={"credentials": None}, config=config)
    with pytest.raises(ValueError, match="Connect a native"):
        await node.execute({})
    assert not wire.calls
