"""Native Everflow protocol fixtures; real HTTPX with synthetic transport."""
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from nodes import everflow_node as ef
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
NODE = "automation-everflow"
KEY = "synthetic-everflow-key-not-live"


@pytest.fixture
def ensure_native_db_pool():
    """Synthetic I/O boundaries do not initialize a real database pool."""
    yield


def blob(portal="network", **changes):
    return {"credential_type": f"everflow_{portal}_api_key", "api_key": KEY, "network_id": "1", **changes}


def item(kind="offer", identifier=7, **changes):
    return {ef.IDS[kind]: identifier, "network_id": 1, "name": "Owned fixture", "offer_status": "active", **changes}


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(calls=[], replies=[], callback=None)

    async def send(request):
        assert request.url.host == "api.eflow.team" and request.url.scheme == "https"
        assert request.headers["X-Eflow-API-Key"] == KEY
        state.calls.append(request)
        if state.callback:
            return await state.callback(request)
        assert state.replies, "Unexpected native request"
        code, payload = state.replies.pop(0)
        return httpx.Response(code, json=payload)

    real_client = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["verify"] is True and kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(send))

    monkeypatch.setattr(ef, "httpx", SimpleNamespace(AsyncClient=client, HTTPError=httpx.HTTPError, Timeout=httpx.Timeout))
    return state


async def run(operation, data=None, **arguments):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=arguments, user_id=USER, credential_data=data or blob())


@pytest.mark.asyncio
async def test_execute_uses_validated_credentials_without_raw_duplicate(transport):
    transport.replies = [(200, {"network_id": 1, "name": "Fixture network"})]
    config = ef.EverflowNode.parse_config({"config": {"operation": "get_network"}, "credentials": blob()})
    node = ef.EverflowNode(node_id="fixture", node_type=NODE, node_data={}, config=config, sio=None)
    result = await node.execute({})
    assert result["success"] is True and result["data"]["network_id"] == "1"
    assert [request.url.path for request in transport.calls] == ["/v1/networks"]


@pytest.mark.parametrize("tag", [None, "", "slack_bot_token", 42, {}, []])
def test_original_foreign_or_malformed_tag_refused_before_factory_reconciliation(tag):
    with pytest.raises((ValueError, TypeError)):
        NodeFactory.create_node(node_id="fixture", node_type=NODE, node_data={"config": {"operation": "list_offers"}, "credentials": blob(credential_type=tag), "credentialIds": {"everflow_network_api_key": "forged"}})


def test_tagless_raw_blob_refused_but_concrete_form_inserts_canonical_tag():
    with pytest.raises(ValueError):
        ef.EverflowNode.parse_config({"config": {"operation": "list_offers"}, "credentials": {"api_key": KEY, "network_id": "1"}})
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("everflow_network_api_key", {"api_key": KEY, "network_id": "1"})
    assert errors == {} and resolved[0] == NODE
    assert shaped["api_key"] == KEY and shaped["credential_type"] == "everflow_network_api_key"


@pytest.mark.parametrize("portal,prefix", [("network", "networks"), ("affiliate", "affiliates")])
@pytest.mark.asyncio
async def test_real_factory_run_portal_paging_query_and_exact_scope(transport, portal, prefix):
    transport.replies = [(200, {"network_id": 1, "name": "Fixture network"}), (200, {"offers": [item()], "paging": {"page": 1, "page_size": 1, "total_count": 2}})]
    first = await run("list_offers", blob(portal), page_size=1, search="fixture")
    token = first["pagination"]["next_page_token"]
    request = transport.calls[-1]
    assert request.url.path == f"/v1/{prefix}/offerstable"
    assert dict(request.url.params) == {"page": "1", "page_size": "1"}
    assert json.loads(request.content) == {"search_terms": [{"search_type": "name", "value": "fixture"}], "filters": {}}
    assert KEY not in json.dumps(first)
    transport.replies = [(200, {"network_id": 1}), (200, {"offers": [item(identifier=8)], "paging": {"page": 2, "page_size": 1, "total_count": 2}})]
    second = await run("list_offers", blob(portal), page_size=1, search="fixture", page_token=token)
    assert second["pagination"]["next_page_token"] is None
    with pytest.raises(ValueError):
        ef._page(ef.Session(blob(portal)), {"different": "filter"}, token)
    with pytest.raises(ValueError):
        ef._page(ef.Session(blob(portal, api_key="different-fixture-key")), {}, token)


@pytest.mark.asyncio
async def test_advertiser_has_bounded_offer_page_and_no_invented_identity(transport):
    transport.replies = [(200, {"offers": []})]
    result = await run("check_connection", blob("advertiser"))
    assert result["identity_verified"] is False and result["pagination"]["complete"] is None
    assert [r.url.path for r in transport.calls] == ["/v1/advertisers/offers"]
    with pytest.raises(ValueError):
        await run("create_channel", blob("affiliate"), name="Fixture", status="inactive")
    assert len(transport.calls) == 1


@pytest.mark.parametrize("paging,rows", [({"page": True, "page_size": 1, "total_count": 1}, [item()]), ({"page": 2, "page_size": 1, "total_count": 1}, [item()]), ({"page": 1, "page_size": 1, "total_count": 1}, []), ({"page": 1, "page_size": 1, "total_count": 0}, [item()])])
@pytest.mark.asyncio
async def test_nominal_200_bad_paging_refused(transport, paging, rows):
    transport.replies = [(200, {"network_id": 1}), (200, {"offers": rows, "paging": paging})]
    with pytest.raises(ValueError):
        await run("list_offers", page_size=1)


@pytest.mark.asyncio
async def test_cross_network_wrong_id_and_secret_relationship_not_exposed(transport):
    transport.replies = [(200, {"network_id": 1}), (200, item(network_id=2))]
    with pytest.raises(ValueError):
        await run("get_offer", offer_id="7")
    transport.replies = [(200, {"network_id": 1}), (200, item(identifier=8))]
    with pytest.raises(ValueError):
        await run("get_offer", offer_id="7")
    transport.replies = [(200, {"network_id": 1}), (200, item(name=KEY, relationship={"api_keys": KEY}, destination_url="https://private.example.test/?token=secret"))]
    result = await run("get_offer", offer_id="7")
    assert KEY not in json.dumps(result) and "relationship" not in result["data"] and "destination_url" not in result["data"]


@pytest.mark.parametrize("code,body", [(401, {"Error": "No authentication method found"}), (403, {"Error": "Out of realm"}), (429, {"error": KEY}), (302, {"location": "https://private.example.test"}), (202, {}), (204, {})])
@pytest.mark.asyncio
async def test_status_case_variants_and_no_false_completed_probe(transport, code, body):
    transport.replies = [(code, body)]
    result = await run("check_connection")
    assert result["success"] is False and result["http_status"] == code and result["status_code"] == code and KEY not in json.dumps(result)
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_channel_create_replace_delete_require_real_readback(transport):
    channel = item("channel", status="inactive")
    transport.replies = [(200, {"network_id": 1}), (200, channel), (200, channel)]
    created = await run("create_channel", name="Owned fixture", status="inactive")
    assert created["readback_verified"] is True and created["data"]["network_channel_id"] == "7"
    transport.replies = [(200, {"network_id": 1}), (200, channel), (200, {**channel, "name": "Updated"}), (200, {**channel, "name": "Updated"})]
    updated = await run("update_channel", channel_id="7", expected_name="Owned fixture", name="Updated", status="inactive")
    assert updated["readback_verified"] is True
    request = transport.calls[-2]
    assert request.method == "PUT" and json.loads(request.content) == {"name": "Updated", "status": "inactive"}
    transport.replies = [(200, {"network_id": 1}), (200, channel), (200, {"result": True}), (404, {"error": "Can't find entry in the database"})]
    deleted = await run("delete_channel", channel_id="7", expected_name="Owned fixture")
    assert deleted["data"]["absence_verified"] is True
    transport.replies = [(200, {"network_id": 1}), (200, {"network_id": 1, "name": "Owned fixture"})]
    unknown = await run("create_channel", name="Owned fixture", status="inactive")
    assert unknown["status"] == "unknown" and unknown["acknowledgement"] == {"http_status": 200}


@pytest.mark.asyncio
async def test_channel_delete_nonboolean_ack_or_failed_absence_stays_unknown(transport):
    channel = item("channel", status="inactive")
    for ack, remaining in [({"result": 1}, None), ({"result": True}, channel), ({"result": True}, {"Error": "Out of realm"})]:
        transport.replies = [(200, {"network_id": 1}), (200, channel), (200, ack)]
        if remaining is not None:
            transport.replies.append((403 if "Error" in remaining else 200, remaining))
        result = await run("delete_channel", channel_id="7", expected_name="Owned fixture")
        assert result["status"] == "unknown" and result["success"] is False


@pytest.mark.asyncio
async def test_reports_exact_decimal_provider_summary_and_offer_auto_advertiser_dimension(transport):
    async def send(request):
        if request.url.path == "/v1/networks":
            return httpx.Response(200, json={"network_id": 1})
        body = json.loads(request.content)
        assert body["currency_id"] == "USD" and body["timezone_id"] == 90
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, content=b'{"total_click":3,"revenue":123.4567890123456789,"profit":-0.00000000000001}')
        assert body["columns"] == [{"column": "offer"}]
        return httpx.Response(200, content=b'{"table":[{"columns":[{"column_type":"offer","id":"7","label":"Fixture"},{"column_type":"advertiser","id":"0","label":"Unknown"}],"reporting":{"total_click":3,"revenue":123.4567890123456789}}],"incomplete_results":true}')
    transport.callback = send
    args = {"from_date": "2026-01-01", "to_date": "2026-01-08", "timezone_id": "90", "currency_id": "USD"}
    table = await run("get_report", **args)
    assert table["data"]["table"][0]["reporting"]["revenue"] == "123.4567890123456789"
    assert table["pagination"]["complete"] is False
    summary = await run("get_report_summary", **args)
    assert summary["data"]["metrics"]["revenue"] == "123.4567890123456789"
    assert summary["data"]["metrics"]["profit"] == "-1E-14"
    assert ef._metrics({"revenue": Decimal("0.001")}) == {"revenue": "0.001"}


@pytest.mark.parametrize("value", [True, 0, "01", "../7", "7/8", -1])
def test_hostile_ids_are_local_errors(value):
    with pytest.raises(ValueError):
        ef.GetOffer(offer_id=value)


@pytest.mark.asyncio
async def test_redirect_oversize_and_invalid_count_are_not_success(transport):
    async def send(request):
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
    transport.callback = send
    result = await run("check_connection")
    assert result["success"] is False
    with pytest.raises(ValueError):
        ef._metrics({"total_click": True})
    with pytest.raises(ValueError):
        ef._metrics({"revenue": Decimal("NaN")})
