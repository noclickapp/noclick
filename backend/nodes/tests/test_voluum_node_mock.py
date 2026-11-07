"""Factory, wire and projection regressions using synthetic MockTransport data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging

import httpx
import pytest
from nodes import voluum_node as v
from nodes.core.registry import NodeFactory

ACCESS = "00000000-0000-4000-8000-000000000001"
WS = "00000000-0000-4000-8000-000000000002"
ID = "00000000-0000-4000-8000-000000000003"
NEXT = "00000000-0000-4000-8000-000000000004"
SECRET = "synthetic-voluum-secret-only"
CRED = {"credential_type": v.FAMILY, "access_id": ACCESS, "access_key": SECRET}

@pytest.fixture
def ensure_native_db_pool():
    yield

def entity(kind="campaign", name="fixture"):
    raw = {"id": ID, "name": name, "namePostfix": name, "workspace": {"id": WS},
           "allowedActions": ["EDIT", "DELETE"], "deleted": False, "tags": [],
           "url": "https://destination.example.test/?token=" + SECRET,
           "postbackUrl": SECRET, "note": {"note": SECRET}, "raw": SECRET}
    if kind == "campaign":
        raw.update({"costModel": {"type": "NOT_TRACKED"}, "trafficSource": {"id": ID},
                    "redirectTarget": {"redirectUrl": {"url": raw["url"], "redirectMode": "REGULAR"}}})
    elif kind == "offer":
        raw.update({"currencyCode": "USD", "payout": {"type": "AUTO"}})
    elif kind == "lander":
        raw.update({"shouldHaveTrackingScript": False, "landerType": "LANDER"})
    else:
        raw.update({"type": "CUSTOM", "skipSendingPostback": True, "impressionSpecific": False})
    return raw

@pytest.fixture
def wire(monkeypatch):
    state = {"requests": [], "rows": {kind: entity(kind) for kind in v._KINDS},
             "on_request": None, "failure": None, "next_id": None, "report": None}
    async def provider(request):
        state["requests"].append(request)
        if state["on_request"]:
            state["on_request"](request)
        assert request.url.scheme == "https" and request.url.host == "api.voluum.com"
        assert SECRET not in str(request.url)
        path = request.url.path
        if state["failure"]:
            return state["failure"](request)
        if path == "/auth/access/session":
            assert request.method == "POST" and "cwauth-token" not in request.headers
            assert json.loads(request.content) == {"accessId": ACCESS, "accessKey": SECRET}
            return httpx.Response(200, json={"token": SECRET, "expirationTimestamp":
                (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(), "inaugural": False})
        assert request.headers["cwauth-token"] == SECRET
        if path == "/startup":
            return httpx.Response(200, json={"responses": {"workspaces": {"status": 200,
                "body": {"workspaces": [{"id": WS, "name": "Owned workspace"}]}},
                "user": {"body": {"email": SECRET}}}})
        if path == "/column/info":
            return httpx.Response(200, json={"columnMappings": [{"key": key, "label": key,
                "type": "number", "canGroupBy": key in v._DIMENSIONS} for key in v._DIMENSIONS + v._METRICS]})
        if path == "/report":
            assert request.url.params["filter1"] == "campaignId" and request.url.params["filter1Value"] == ID
            assert request.url.params["workspaces"] == WS and request.url.params["groupBy"] == "campaignId"
            assert request.url.params.get_list("column")[:1] == ["campaignId"]
            return httpx.Response(200, json=state["report"] or {"rows": [{"campaignId": ID,
                "visits": 10, "private": SECRET}], "totals": {"visits": 100, "private": SECRET},
                "limit": 1, "offset": int(request.url.params["offset"]), "totalRows": 2,
                "truncated": True, "messages": [{"message": SECRET}]})
        for kind, (route, collection, _) in v._KINDS.items():
            if path == "/" + route:
                if request.method == "GET":
                    assert request.url.params["workspaceId"] == WS and int(request.url.params["limit"]) <= 100
                    return httpx.Response(200, json={collection: [state["rows"][kind]],
                        **({"nextId": state["next_id"]} if state["next_id"] else {})})
                if request.method == "DELETE":
                    assert json.loads(request.content) == {"ids": [ID]}
                    return httpx.Response(200, json={"status": "SUCCESSFUL", "items": [{"id": ID,
                        "status": "SUCCESSFUL", "error": SECRET, "references": []}]})
                body = json.loads(request.content)
                assert body["workspace"] == {"id": WS}
                state["rows"][kind].update(body)
                state["rows"][kind]["name"] = body.get("name", body.get("namePostfix"))
                return httpx.Response(200, json=state["rows"][kind])
            if path == f"/{route}/{ID}":
                if request.method == "PUT":
                    body = json.loads(request.content)
                    assert not ({"id", "allowedActions", "deleted", "raw"} & body.keys())
                    state["rows"][kind].update(body)
                    state["rows"][kind]["name"] = body.get("name", body.get("namePostfix"))
                return httpx.Response(200, json=state["rows"][kind])
        raise AssertionError("Unexpected native path")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
        original(transport=httpx.MockTransport(provider), **kwargs))
    return state

def node(operation, **fields):
    return NodeFactory.create_node(node_id="fixture", node_type=v.TYPE, node_data={
        "config": {"operation": operation, **fields}, "credentials": deepcopy(CRED)}, user_id=ACCESS)


@pytest.mark.parametrize("operation,field", [
    ("list_offers", "workspace_id"),
    ("get_campaign", "campaign_id"),
    ("get_offer", "offer_id"),
    ("get_lander", "lander_id"),
    ("get_traffic_source", "traffic_source_id"),
])
def test_static_validation_rejects_invalid_resource_ids(operation, field):
    fields = {"workspace_id": WS}
    if field != "workspace_id":
        fields[field] = ID
    valid = {"config": {"operation": operation, **fields}, "credentials": deepcopy(CRED)}
    assert v.VoluumNode.validate_config(valid)["valid"] is True
    invalid = deepcopy(valid)
    invalid["config"][field] = "not-a-uuid"
    assert v.VoluumNode.validate_config(invalid)["valid"] is False
    with pytest.raises(ValueError):
        node(operation, **{**fields, field: "not-a-uuid"})


@pytest.mark.parametrize("destination", ["not-a-url", "ftp://destination.example.test", "https://user:password@destination.example.test"])
def test_static_validation_rejects_invalid_destination_urls(destination):
    data = {"config": {"operation": "create_offer", "workspace_id": WS,
                       "name": "fixture", "destination_url": destination}, "credentials": deepcopy(CRED)}
    assert v.VoluumNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError):
        node("create_offer", workspace_id=WS, name="fixture", destination_url=destination)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", v.OPERATIONS)
async def test_actual_factory_all_native_operations_and_write_readbacks(wire, operation):
    fields = {}
    if operation not in {"test_connection", "list_workspaces", "list_report_columns"}:
        fields["workspace_id"] = WS
    kind = next((kind for kind in v._KINDS if kind in operation), None)
    if operation.startswith(("get_", "update_", "archive_")) and kind:
        fields[v._KINDS[kind][2]] = ID
    if operation.startswith(("create_", "update_")):
        fields["name"] = "changed"
    if operation.startswith("create_") and kind != "traffic_source":
        fields["destination_url"] = "https://destination.example.test/path"
    if operation == "create_campaign":
        fields["traffic_source_id"] = ID
    if operation == "get_campaign_report":
        fields.update({"campaign_id": ID, "from_time": "2026-10-01T00:00:00Z",
                       "to_time": "2026-10-02T00:00:00Z", "limit": 1})
    result = await node(operation, **fields).run({})
    assert result["status"] == "success" and SECRET not in json.dumps(result)
    assert wire["requests"][0].url.path == "/auth/access/session"
    if operation.startswith(("create_", "update_")):
        assert result["readback_verified"] is True and wire["requests"][-1].method == "GET"
    if operation == "test_connection":
        assert result["data"]["identity_verified"] is False

@pytest.mark.asyncio
async def test_catalog_cursor_binding_and_exact_provider_cursor(wire):
    wire["next_id"] = NEXT
    token = (await node("list_offers", workspace_id=WS, limit=1).run({}))["next_page_token"]
    wire["next_id"] = None
    await node("list_offers", workspace_id=WS, limit=1, page_token=token).run({})
    assert wire["requests"][-1].url.params["nextId"] == NEXT
    before = len(wire["requests"])
    for fields in ({"limit": 2}, {"name": "other"}, {"include_archived": True}, {"workspace_id": NEXT}):
        with pytest.raises(ValueError, match="continuation"):
            await node("list_offers", **{"workspace_id": WS, "limit": 1, "page_token": token, **fields}).run({})
    assert len(wire["requests"]) == before

@pytest.mark.asyncio
async def test_report_actual_applied_limit_totals_and_filter_bound_offset(wire):
    config = {"workspace_id": WS, "campaign_id": ID, "from_time": "2026-10-01T00:00:00Z",
              "to_time": "2026-10-02T00:00:00Z", "limit": 10}
    result = await node("get_campaign_report", **config).run({})
    assert result["totals"] == {"visits": 100} and result["time_range_truncated"] is True
    wire["report"] = {"rows": [{"campaignId": ID, "visits": 1}], "totals": {"visits": 100},
        "limit": 1, "offset": 1, "totalRows": 2, "truncated": False, "messages": []}
    await node("get_campaign_report", **config, page_token=result["next_page_token"]).run({})
    assert wire["requests"][-1].url.params["offset"] == "1"
    before = len(wire["requests"])
    with pytest.raises(ValueError, match="continuation"):
        await node("get_campaign_report", **{**config, "currency": "EUR"}, page_token=result["next_page_token"]).run({})
    assert len(wire["requests"]) == before

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 409, 429, 500])
async def test_safe_http_categories_and_no_retry(wire, status):
    wire["failure"] = lambda request: httpx.Response(status, text=SECRET)
    with pytest.raises(ValueError) as error:
        await node("test_connection").run({})
    assert SECRET not in str(error.value) and f"HTTP {status}" in str(error.value)
    assert len(wire["requests"]) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["expired", "text", "empty", "malformed", "oversized", "accepted", "no-content"])
async def test_session_rejects_unconfirmed_expired_or_non_json_completion(wire, mode):
    cases = {"expired": httpx.Response(200, json={"token": SECRET, "expirationTimestamp": "2001-01-01T00:00:00Z"}),
        "text": httpx.Response(200, text=SECRET),
        "empty": httpx.Response(200, content=b"", headers={"content-type": "application/json"}),
        "malformed": httpx.Response(200, content=b"{" + SECRET.encode(), headers={"content-type": "application/json"}),
        "oversized": httpx.Response(200, content=b"x" * (v.MAX_BYTES+1), headers={"content-type": "application/json"}),
        "accepted": httpx.Response(202), "no-content": httpx.Response(204)}
    wire["failure"] = lambda request: cases[mode]
    with pytest.raises(ValueError) as error:
        await node("test_connection").run({})
    assert SECRET not in str(error.value) and len(wire["requests"]) == 1

@pytest.mark.asyncio
async def test_wrong_parent_permission_and_non_direct_campaign_stop_before_mutation(wire):
    wire["rows"]["offer"]["workspace"] = {"id": NEXT}
    with pytest.raises(ValueError, match="workspace"):
        await node("get_offer", workspace_id=WS, offer_id=ID).run({})
    wire["rows"]["campaign"]["redirectTarget"] = {"inlineFlow": {"private": SECRET}}
    with pytest.raises(ValueError, match="direct-URL"):
        await node("update_campaign_metadata", workspace_id=WS, campaign_id=ID, name="fixture").run({})
    wire["rows"]["lander"]["allowedActions"] = []
    with pytest.raises(ValueError, match="permission"):
        await node("archive_lander", workspace_id=WS, lander_id=ID).run({})
    assert not any(request.method in {"PUT", "DELETE"} for request in wire["requests"])

@pytest.mark.asyncio
async def test_documented_account_shared_reads_do_not_authorize_workspace_writes(wire):
    wire["rows"]["offer"]["workspace"] = None
    result = await node("get_offer", workspace_id=WS, offer_id=ID).run({})
    assert result["data"]["shared"] is True and result["data"]["workspace_id"] is None
    with pytest.raises(ValueError, match="shared records are read-only"):
        await node("archive_offer", workspace_id=WS, offer_id=ID).run({})
    assert not any(request.method == "DELETE" for request in wire["requests"])

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204])
async def test_write_accepted_or_empty_completion_never_claims_confirmed_readback(wire, status):
    wire["failure"] = lambda request: httpx.Response(status) if request.method == "PUT" else None
    # The response override applies only to the selected write, not its session/GETs.
    original = wire["failure"]
    wire["failure"] = None
    def on_request(request):
        wire["failure"] = original if request.method == "PUT" else None
    wire["on_request"] = on_request
    result = await node("update_offer_metadata", workspace_id=WS, offer_id=ID, name="fixture").run({})
    assert result["completion_confirmed"] is False and result["http_status"] == status
    assert "readback_verified" not in result and wire["requests"][-1].method == "PUT"

@pytest.mark.asyncio
async def test_archive_contradiction_and_report_count_conflict_are_unconfirmed(wire):
    def archive(request):
        if request.method == "DELETE":
            wire["failure"] = lambda _: httpx.Response(200, json={"status": "FAILED",
                "items": [{"id": ID, "status": "SUCCESSFUL", "error": SECRET}]})
    wire["on_request"] = archive
    with pytest.raises(ValueError, match="contradicts"):
        await node("archive_offer", workspace_id=WS, offer_id=ID).run({})
    wire["on_request"], wire["failure"] = None, None
    wire["report"] = {"rows": [{"campaignId": ID, "visits": 1}], "totals": {},
                      "limit": 1, "offset": 0, "totalRows": 0}
    with pytest.raises(ValueError, match="report page"):
        await node("get_campaign_report", workspace_id=WS, campaign_id=ID,
            from_time="2026-10-01T00:00:00Z", to_time="2026-10-02T00:00:00Z").run({})

@pytest.mark.asyncio
async def test_concurrent_other_http_log_is_preserved(wire, caplog):
    arrived, proceed = asyncio.Event(), asyncio.Event()
    async def private_log():
        with v._private_http():
            logging.getLogger("httpx").info("cwauth-token %s", SECRET)
            arrived.set()
            await proceed.wait()
    async def other_log():
        await arrived.wait()
        logging.getLogger("httpx").info("unrelated ordinary request")
        proceed.set()
    caplog.set_level(logging.INFO, logger="httpx")
    await asyncio.gather(private_log(), other_log())
    assert SECRET not in caplog.text and "unrelated ordinary request" in caplog.text
