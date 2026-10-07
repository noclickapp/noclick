"""Prepared native Uptime.com identity, wire, paging and privacy regressions.

Real node/factory/dispatcher/schema/collector seams use synthetic responses.
These fixtures are UNRUN and do not establish API entitlement or live access.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from nodes import uptimecom_node as p
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
USER_PK, CHECK, SECOND, TAG, PAGE, OUTAGE = "7", "123", "124", "4", "5", "789"
PRIVATE = "SYNTHETIC_PRIVATE_MARKER"
STAMP, END = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"


def blob(**changes):
    return {"credential_type": p.FAMILY, "api_key": "synthetic-issued-key", "expected_user_pk": USER_PK,
        "approved_resources_json": json.dumps({"checks": [CHECK, SECOND], "tags": [TAG], "statuspages": [PAGE]}),
        "include_labels": False, **changes}


def me(**changes):
    return {"pk": int(USER_PK), "is_active": True, "is_api_enabled": True, "email": PRIVATE,
        "first_name": PRIVATE, "account": {"name": PRIVATE, "trial_expires": PRIVATE}, "password": PRIVATE, **changes}


def check(uid=CHECK):
    return {"pk": int(uid), "name": PRIVATE, "monitoring_service_type": "HTTP", "state_is_up": True,
        "is_paused": False, "state_changed_at": STAMP, "created_at": STAMP, "modified_at": STAMP,
        "msp_password": PRIVATE, "msp_headers": PRIVATE, "msp_address": PRIVATE, "url": PRIVATE}


def tag(uid=TAG): return {"pk": int(uid), "tag": PRIVATE, "color_hex": "#123456", "url": PRIVATE}


def page(uid=PAGE):
    return {"pk": int(uid), "name": PRIVATE, "page_type": "PUBLIC", "visibility_level": "PUBLIC",
        "public_url": PRIVATE, "private_url": PRIVATE, "security": {"password": PRIVATE}}


def outage(uid=OUTAGE, parent=CHECK):
    return {"pk": int(uid), "check_pk": int(parent), "check_monitoring_service_type": "HTTP", "state_is_up": False,
        "num_locations_down": 2, "ignored": False, "created_at": STAMP, "resolved_at": "", "duration_secs": "42",
        "check_name": PRIVATE, "check_address": PRIVATE, "all_alerts": [{"diagnostic": PRIVATE, "ip": PRIVATE}]}


def current_status():
    return {**page(), "global_is_operational": True,
        "components": [{"pk": 6, "name": PRIVATE, "status": "operational", "service_id": int(CHECK), "is_group": False, "url": PRIVATE},
            {"pk": 8, "name": PRIVATE, "status": "partial-outage", "service_id": 999, "is_group": False},
            {"pk": 9, "name": PRIVATE, "status": "operational", "service_id": None, "is_group": True}],
        "active_incidents": [{"description": PRIVATE}], "upcoming_maintenance": [{"description": PRIVATE}],
        "metrics": [{"url": PRIVATE, "name": PRIVATE}]}


def stats():
    return {"pk": int(CHECK), "start_date": STAMP, "end_date": END, "statistics": [{"opaque": PRIVATE}],
        "totals": {"undocumented": PRIVATE}, "available_locations": [PRIVATE]}


def listed(rows, count=None, next_link=None):
    return {"count": len(rows) if count is None else count, "results": rows, "next": next_link, "previous": PRIVATE}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], after_headers=None, after_body=None)
    class Response:
        def __init__(self, payload, status, ctype):
            self.status_code, self.headers = status, {"content-type": ctype, "location": PRIVATE}
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
            assert state.queue, "Unexpected request beyond synthetic fixture"
            value = state.queue.pop(0)
            if isinstance(value, BaseException): raise value
            return Response(*value) if isinstance(value, tuple) else Response(value, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


async def execute(config, data=None, inputs=None):
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": config, "credentials": data or blob()}, user_id=USER)
    return await node.execute(inputs or {})


@pytest.mark.asyncio
async def test_real_factory_dispatcher_uses_saved_config_and_token_header(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.UptimeComNode
    wire.queue = [me(), me()]
    result = await execute({"operation": "check_connection"}, inputs={"operation": "create_check", "include_labels": True})
    assert result == {"status": "success", "user_pk": 7, "is_active": True, "is_api_enabled": True,
        "identity_verified": True, "account_ownership_verified": False}
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="check_connection", arguments={}, user_id=USER, credential_data=blob())
    assert result["identity_verified"] and not result["account_ownership_verified"]
    for method, url, options in wire.calls:
        assert method == "GET" and url == p.ROOT + "/auth/me/" and options["params"] is None
        assert options["headers"] == {"Authorization": "Token synthetic-issued-key", "Accept": "application/json", "Content-Type": "application/json"}
        assert "api_key" not in url and "Bearer" not in options["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_real_connect_collector_only_accepts_protected_user_pk(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [me(), {}]
    checked = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert checked.evidence.reachable is True and checked.evidence.account_label == "7"
    assert checked.evidence.proves == "account" and PRIVATE not in str(checked)
    unknown = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert unknown.evidence.reachable is None and not unknown.verified_metadata()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"pk": 8}, {"pk": True}, {"is_active": False}, {"is_api_enabled": False}])
async def test_user_witness_refuses_foreign_disabled_or_malformed_principal_before_catalog(wire, change):
    wire.queue = [me(**change), check()]
    with pytest.raises((ValueError, RuntimeError)): await execute({"operation": "get_check", "check_id": CHECK})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"operation": "get_check", "check_id": "999"},
    {"operation": "get_tag", "tag_id": "999"}, {"operation": "get_status_page", "status_page_id": "999"},
    {"operation": "get_outage", "check_id": "999", "outage_id": OUTAGE}])
async def test_selected_grants_are_checked_before_any_provider_request(wire, config):
    with pytest.raises(ValueError, match="approved-ID"): await execute(config)
    assert not wire.calls


@pytest.mark.asyncio
async def test_all_read_operations_project_only_typed_metadata(wire):
    cases = [({"operation": "list_checks"}, [me(), listed([check(), check("999")])]),
        ({"operation": "get_check", "check_id": CHECK}, [me(), check()]),
        ({"operation": "list_tags"}, [me(), listed([tag()])]),
        ({"operation": "get_tag", "tag_id": TAG}, [me(), tag()]),
        ({"operation": "list_outages", "check_id": CHECK}, [me(), check(), listed([outage()])]),
        ({"operation": "get_outage", "check_id": CHECK, "outage_id": OUTAGE}, [me(), check(), outage()]),
        ({"operation": "list_status_pages"}, [me(), listed([page()])]),
        ({"operation": "get_status_page", "status_page_id": PAGE}, [me(), page()]),
        ({"operation": "get_status_page_current_status", "status_page_id": PAGE}, [me(), page(), current_status()]),
        ({"operation": "get_check_statistics", "check_id": CHECK, "start_date": STAMP, "end_date": END}, [me(), check(), stats()])]
    for config, responses in cases:
        wire.queue = responses
        result = await execute(config)
        assert result["status"] == "success" and result["identity_verified"] and not result["account_ownership_verified"]
        assert PRIVATE not in json.dumps(result) and not wire.queue
        if config["operation"] == "list_checks": assert result["filtered_count"] == 1 and result["returned_count"] == 1
        if config["operation"] == "get_status_page_current_status":
            assert [row["pk"] for row in result["data"]["components"]] == [6, 9]
            assert result["data"]["filtered_component_count"] == 1 and result["data"]["active_incident_count"] == 1
        if config["operation"] == "get_check_statistics":
            assert result["statistic_record_count"] == 1 and result["totals_present"] and result["opaque_values_omitted"]
            assert wire.calls[-1][2]["params"] == {"start_date": STAMP, "end_date": END, "include_alerts": "false", "locations_response_times": "false", "download": "false", "pdf": "false"}
    assert all(method == "GET" and url.startswith(p.ROOT + "/") for method, url, _ in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,response", [("get_check", check("999")), ("get_outage", outage(parent=SECOND)),
    ("get_outage", outage("999")), ("list_outages", listed([outage(parent=SECOND)])),
    ("get_status_page_current_status", {**current_status(), "pk": 99}),
    ("get_check_statistics", {**stats(), "end_date": STAMP})])
async def test_actual_selected_and_nested_parent_witnesses_cannot_be_inferred(wire, operation, response):
    config = {"operation": operation}
    if operation == "get_status_page_current_status":
        config["status_page_id"] = PAGE
        wire.queue = [me(), page(), response]
    else:
        config["check_id"] = CHECK
        if operation == "get_outage": config["outage_id"] = OUTAGE
        if operation == "get_check_statistics": config.update(start_date=STAMP, end_date=END)
        wire.queue = [me(), response] if operation == "get_check" else [me(), check(), response]
    with pytest.raises(RuntimeError): await execute(config)


@pytest.mark.asyncio
async def test_names_opt_in_is_saved_only_and_pickers_keep_filtered_page_continuation(wire):
    wire.queue = [me(), check(), me(), check(), me(), listed([check()], count=50,
        next_link=p.ROOT + "/checks/?page=2&page_size=25&ordering=pk"), me(), check(), listed([outage()])]
    hidden = await execute({"operation": "get_check", "check_id": CHECK}, inputs={"include_labels": True})
    shown = await execute({"operation": "get_check", "check_id": CHECK}, blob(include_labels=True))
    assert "name" not in hidden["data"] and shown["data"]["name"] == PRIVATE
    assert "msp_password" not in shown["data"] and "url" not in shown["data"]
    options = await p.UptimeComNode.load_field_options("check_id", blob(), search=PRIVATE)
    assert options == {"options": [], "has_more": True, "next_page_token": "2"}
    options = await p.UptimeComNode.load_field_options("outage_id", blob(), context={"check_id": CHECK})
    assert options == {"options": [{"value": OUTAGE, "label": OUTAGE}], "has_more": False, "next_page_token": None}
    assert wire.calls[-1][2]["params"]["check_pk"] == CHECK


@pytest.mark.asyncio
async def test_documented_filters_repeat_on_validated_next_page_without_following_link(wire):
    suffix = "/checks/?page=2&page_size=25&ordering=pk&search=hello+world&monitoring_service_type=HTTP&is_paused=false&state_is_up=true"
    wire.queue = [me(), listed([check()], count=50, next_link=p.ROOT + suffix), me(), listed([check(SECOND)], count=26)]
    config = {"operation": "list_checks", "search": "hello world", "monitoring_service_type": "HTTP", "is_paused": False, "state_is_up": True}
    first = await execute(config)
    assert first["next_page"] == 2 and first["has_more"] and len(wire.calls) == 2
    second = await execute({**config, "page": 2})
    assert not second["has_more"] and not second["complete_from_first_page"] and len(wire.calls) == 4
    assert wire.calls[1][2]["params"] == {**wire.calls[3][2]["params"], "page": "1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing-next", "foreign-host", "foreign-path", "duplicate-query", "changed-filter",
    "backwards", "empty-more", "count", "unfinished-final", "exhausted-more", "bool-pk", "duplicate-pk", "bare-list"])
async def test_paging_and_shape_refusal_never_becomes_invented_completion(wire, change):
    value = listed([check()])
    link = p.ROOT + "/checks/?page=2&page_size=25&ordering=pk"
    if change == "missing-next": del value["next"]
    if change == "foreign-host": value["next"] = link.replace("uptime.com", "external.example.test")
    if change == "foreign-path": value["next"] = link.replace("/checks/", "/auth/me/")
    if change == "duplicate-query": value["next"] = link + "&page=2"
    if change == "changed-filter": value["next"] = link + "&search=extra"
    if change == "backwards": value["next"] = link.replace("page=2", "page=1")
    if change == "empty-more": value = listed([], count=50, next_link=link)
    if change == "count": value["count"] = 0
    if change == "unfinished-final": value["count"] = 2
    if change == "exhausted-more": value["next"] = link
    if change == "bool-pk": value["results"][0]["pk"] = True
    if change == "duplicate-pk": value = listed([check(), check()])
    if change == "bare-list": value = [check()]
    wire.queue = [me(), value]
    with pytest.raises(RuntimeError): await execute({"operation": "list_checks"})
    assert len(wire.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,ctype", [(401, "application/json"), (403, "application/json"), (404, "application/json"),
    (422, "application/json"), (202, "application/json"), (204, "application/json"), (302, "application/json"),
    (429, "application/json"), (500, "text/html"), (200, "text/html")])
async def test_status_and_media_failures_remain_safe_and_do_not_retry(wire, status, ctype):
    wire.queue = [({"error": PRIVATE}, status, ctype)]
    with pytest.raises((ValueError, RuntimeError)) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b'{"pk":7,"pk":8}', b'{"pk":NaN}', b' ' * 2_000_001, httpx.ReadTimeout(PRIVATE)])
async def test_duplicate_nonfinite_large_json_and_transport_errors_do_not_leak(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.parametrize("bad", [None, "", "uptimecom_bearer", False])
def test_original_family_is_checked_before_model_defaults(bad):
    raw = {"config": {"operation": "check_connection"}, "credentials": blob(credential_type=bad)}
    assert p.UptimeComNode.validate_config(raw)["valid"] is False
    with pytest.raises(ValueError): p.UptimeComNode.parse_config(raw)


def test_actual_schema_has_eleven_reads_masked_manual_key_and_parent_scope():
    schema = p.UptimeComNode.get_config_schema()
    model = schema["$defs"]["UptimeComAPITokenCredential"]
    assert model["title"] == "Uptime.com API Token" and "x-credential-type" not in model
    assert model["properties"]["api_key"]["ui:widget"] == "password" and "expected_user_pk" in model["required"]
    assert model["properties"]["include_labels"]["default"] is False
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS) and len(p.OPS) == 11
    assert schema["$defs"]["GetOutage"]["properties"]["outage_id"]["x-dynamic-options"]["depends_on"] == "check_id"
    assert p.UptimeComNode.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for raw in (blob(api_key=""), blob(api_key="Bearer " + PRIVATE), blob(password=PRIVATE), blob(expected_user_pk="0"),
        blob(approved_resources_json='{"checks":["123","123"],"tags":[],"statuspages":[]}'), blob(include_labels="true")):
        with pytest.raises(ValueError) as caught: p.credential(raw)
        assert PRIVATE not in str(caught.value)
    for args in ({"page_size": 101}, {"page_size": True}, {"page": 0}, {"page": True}):
        with pytest.raises(ValueError): p.ListChecks(**args)
    for dates in ((END, STAMP), (STAMP, "2026-12-01T00:00:00Z"), ("2026-10-01", END)):
        with pytest.raises(ValueError): p.GetCheckStatistics(check_id=CHECK, start_date=dates[0], end_date=dates[1])


@pytest.mark.asyncio
async def test_opaque_outage_strings_are_omitted_and_bad_documented_timestamps_refuse(wire):
    wire.queue = [me(), check(), {**outage(), "resolved_at": PRIVATE, "duration_secs": PRIVATE},
        me(), {**check(), "state_changed_at": PRIVATE}]
    result = await execute({"operation": "get_outage", "check_id": CHECK, "outage_id": OUTAGE})
    assert "resolved_at" not in result["data"] and "duration_secs" not in result["data"] and PRIVATE not in json.dumps(result)
    with pytest.raises(RuntimeError): await execute({"operation": "get_check", "check_id": CHECK})
