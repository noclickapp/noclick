"""Prepared IONOS Cloud wire, paging, ancestry and projection regressions.

Real native factory, dispatcher, connect and schema seams use synthetic HTTP.
These fixtures provide no live entitlement or UI evidence.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from nodes import ionoscloud_node as p
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
DC = "15f67991-0f51-4efc-a8ad-ef1fb31a480c"
SECOND = "15f67991-0f51-4efc-a8ad-ef1fb31a480d"
FOREIGN = "15f67991-0f51-4efc-a8ad-ef1fb31a480e"
SERVER = "15f67991-0f51-4efc-a8ad-ef1fb31a480f"
PRIVATE = "SYNTHETIC_PRIVATE_MARKER"


def blob(**changes):
    return {"credential_type": p.FAMILY, "token": "synthetic-issued-token", "contract_number": None,
        "include_labels": False, "approved_datacenter_ids_json": json.dumps([DC, SECOND]), **changes}


def datacenter(uid=DC):
    return {"id": uid, "type": "datacenter", "href": PRIVATE,
        "properties": {"location": "us/las", "version": 8, "name": PRIVATE,
            "description": PRIVATE, "ipv6CidrBlock": PRIVATE, "secAuthProtection": True,
            "features": [PRIVATE], "defaultSecurityGroupId": PRIVATE},
        "metadata": {"state": "AVAILABLE", "createdDate": "2026-10-07T00:00:00Z",
            "createdBy": PRIVATE, "createdByUserId": PRIVATE, "lastModifiedBy": PRIVATE, "lastModifiedByUserId": PRIVATE},
        "entities": {"servers": {"items": [{"password": PRIVATE}], "href": PRIVATE}}}


def server(uid=SERVER):
    return {"id": uid, "type": "server", "href": PRIVATE,
        "properties": {"type": "ENTERPRISE", "vmState": "RUNNING", "name": PRIVATE,
            "hostname": PRIVATE, "cpuFamily": PRIVATE, "cores": 4, "ram": 4096,
            "nicMultiQueue": True, "templateUuid": PRIVATE, "bootCdrom": {"id": PRIVATE},
            "bootVolume": {"href": PRIVATE}, "enabledFeatures": [PRIVATE]},
        "metadata": {"state": "BUSY", "lastModifiedDate": "2026-10-07T00:00:00Z",
            "createdBy": PRIVATE, "createdByUserId": PRIVATE, "lastModifiedBy": PRIVATE, "lastModifiedByUserId": PRIVATE},
        "entities": {"nics": {"items": [{"ip": PRIVATE}], "href": PRIVATE}}}


def collection(rows, *, more=False, offset=None, limit=None):
    result = {"type": "collection", "items": rows, "href": PRIVATE,
        "_links": {"self": PRIVATE, **({"next": "https://attacker.example/credential"} if more else {})}}
    if offset is not None: result["offset"] = offset
    if limit is not None: result["limit"] = limit
    return result


def option(value, parent=None):
    return {"value": value, "label": value, "metadata": {"parent_id": parent, "identity_verified": False}}


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
            assert state.queue, "Unexpected request beyond synthetic boundary"
            value = state.queue.pop(0)
            if isinstance(value, BaseException): raise value
            return Response(*value) if isinstance(value, tuple) else Response(value, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


async def execute(config, data=None, inputs=None):
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": config, "credentials": data or blob()}, user_id=USER)
    return await node.execute(inputs or {})



@pytest.mark.asyncio
async def test_actual_factory_dispatcher_contract_header_fixed_depth_and_no_input_overlay(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.IONOSCloudNode
    wire.queue = [collection([datacenter()], more=True), collection([])]
    result = await execute({"operation": "check_connection"}, blob(contract_number=123),
        {"contract_number": 456, "operation": "start", "depth": 10, "token": PRIVATE})
    assert result["witness_verified"] and result["contract_number"] == 123 and result["has_more"]
    assert not result["identity_verified"] and not result["account_ownership_verified"]
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="check_connection",
        arguments={}, user_id=USER, credential_data=blob())
    assert result["received_count"] == 0 and not result["has_more"]
    for index, (method, url, kwargs) in enumerate(wire.calls):
        assert method == "GET" and url == p.ROOT + "/datacenters"
        assert kwargs["params"] == {"depth": 1, "offset": 0, "limit": 1}
        assert kwargs["headers"] == {"Authorization": "Bearer synthetic-issued-token", "Accept": "application/json",
            "Content-Type": "application/json", **({"X-Contract-Number": "123"} if index == 0 else {})}


@pytest.mark.asyncio
async def test_actual_connect_empty_catalog_only_reachability_and_malformed_unknown(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [collection([]), {"items": []}]
    result = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert result.evidence.reachable is True and p.IONOSCloudNode.connection_evidence.proves == "reachability"
    assert result.evidence.account_label is None and "verified_as" not in result.verified_metadata()
    unknown = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert unknown.evidence.reachable is None and not unknown.verified_metadata()


@pytest.mark.asyncio
async def test_all_closed_reads_remove_entities_links_users_network_and_configuration(wire):
    cases = [
        ({"operation": "list_datacenters", "offset": 10}, [collection([datacenter(), datacenter(FOREIGN)], offset=10, limit=50)]),
        ({"operation": "get_datacenter", "datacenter_id": DC}, [collection([datacenter()]), datacenter()]),
        ({"operation": "list_servers", "datacenter_id": DC}, [collection([datacenter()]), datacenter(), collection([server()])]),
        ({"operation": "get_server", "datacenter_id": DC, "server_id": SERVER},
            [collection([datacenter()]), datacenter(), collection([server()]), server()])]
    for config, responses in cases:
        wire.queue = responses
        result = await execute(config, blob(contract_number=123))
        assert result["status"] == "success" and PRIVATE not in json.dumps(result) and not wire.queue
        assert not result["identity_verified"] and not result["account_ownership_verified"]
        if config["operation"] == "list_datacenters": assert result["filtered_count"] == 1
        if "server" in config["operation"]: assert result["datacenter_id"] == DC and result["parent_link_verified"]
    for _, url, kwargs in wire.calls:
        assert url.startswith(p.ROOT + "/datacenters")
        assert kwargs["headers"]["X-Contract-Number"] == "123"
        assert kwargs["params"]["depth"] == (1 if url.endswith(("/datacenters", "/servers")) else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unapproved", "missing-datacenter", "foreign-datacenter", "missing-server", "foreign-server"])
async def test_current_parent_catalog_and_exact_details_required(wire, kind):
    wire.queue = [collection([] if kind == "missing-datacenter" else [datacenter()]),
        datacenter(FOREIGN if kind == "foreign-datacenter" else DC),
        collection([] if kind == "missing-server" else [server()]),
        server(FOREIGN if kind == "foreign-server" else SERVER)]
    config = {"operation": "get_server", "datacenter_id": FOREIGN if kind == "unapproved" else DC, "server_id": SERVER}
    with pytest.raises((ValueError, RuntimeError)): await execute(config)
    assert len(wire.calls) == {"unapproved": 0, "missing-datacenter": 1, "foreign-datacenter": 2,
        "missing-server": 3, "foreign-server": 4}[kind]


@pytest.mark.asyncio
async def test_optional_properties_and_names_require_saved_opt_in(wire):
    sparse = {"id": DC, "type": "datacenter"}
    wire.queue = [collection([sparse]), sparse, collection([datacenter()]), datacenter()]
    hidden = await execute({"operation": "get_datacenter", "datacenter_id": DC}, inputs={"include_labels": True})
    shown = await execute({"operation": "get_datacenter", "datacenter_id": DC}, blob(include_labels=True))
    assert hidden["data"] == sparse and shown["data"]["properties"]["name"] == PRIVATE
    assert PRIVATE not in json.dumps({**shown["data"], "properties": {k: v for k, v in shown["data"]["properties"].items() if k != "name"}})


@pytest.mark.asyncio
async def test_documented_numeric_next_offset_never_reads_or_follows_link(wire):
    wire.queue = [collection([datacenter()], more=True, offset=0.0, limit=1.0),
        collection([], offset=1, limit=1)]
    first = await execute({"operation": "list_datacenters", "limit": 1})
    second = await execute({"operation": "list_datacenters", "offset": first["next_offset"], "limit": 1})
    assert first["has_more"] and first["next_offset"] == 1
    assert not second["has_more"] and second["next_offset"] is None
    assert "total" not in first and "attacker" not in json.dumps(first)
    assert [call[2]["params"]["offset"] for call in wire.calls] == [0, 1]


@pytest.mark.asyncio
async def test_duplicates_within_requested_bound_and_bounded_witness_are_rejected(wire):
    wire.queue = [collection([datacenter(), datacenter()])]
    with pytest.raises(RuntimeError, match="repeated"):
        await execute({"operation": "list_datacenters", "limit": 2})
    wire.calls.clear()
    wire.queue = [collection([datacenter("dc-" + str(page * 100 + item)) for item in range(100)], more=True)
        for page in range(p.WITNESS_PAGES)]
    with pytest.raises(ValueError, match="completion is unverified"):
        await execute({"operation": "get_datacenter", "datacenter_id": DC})
    assert len(wire.calls) == p.WITNESS_PAGES and not wire.queue
    assert [call[2]["params"]["offset"] for call in wire.calls] == list(range(0, 1000, 100))


@pytest.mark.asyncio
async def test_picker_continuation_sealed_to_parent_search_saved_contract_and_token(wire):
    rows = [datacenter("dc-" + str(i)) for i in range(100)]
    raw = blob(approved_datacenter_ids_json='["dc-0"]')
    wire.queue = [collection(rows, more=True)]
    result = await p.IONOSCloudNode.load_field_options("datacenter_id", raw, search="dc")
    assert result["options"] == [option("dc-0")] and result["next_page_token"]
    token = result["next_page_token"]
    for altered, search in [(blob(**{**raw, "contract_number": 99}), "dc"),
        (blob(**{**raw, "token": "synthetic-other-token"}), "dc"), (raw, "different")]:
        with pytest.raises(ValueError): await p.IONOSCloudNode.load_field_options("datacenter_id", altered, page_token=token, search=search)
    wire.queue = [collection([], offset=100, limit=100)]
    end = await p.IONOSCloudNode.load_field_options("datacenter_id", raw, page_token=token, search="dc")
    assert not end["has_more"] and end["next_page_token"] is None and len(wire.calls) == 2
    parent_token = p.cursor(blob(), "server_id", DC, "", 100, 100)
    with pytest.raises(ValueError):
        await p.IONOSCloudNode.load_field_options("server_id", blob(), context={"datacenter_id": SECOND}, page_token=parent_token)
    assert len(wire.calls) == 2


@pytest.mark.asyncio
async def test_nested_server_picker_requires_current_parent_and_never_returns_names_by_input(wire):
    wire.queue = [collection([datacenter()]), datacenter(), collection([server()])]
    result = await p.IONOSCloudNode.load_field_options("server_id", blob(), context={"datacenter_id": DC, "include_labels": True})
    assert result["options"] == [option(SERVER, DC)] and result["next_page_token"] is None
    assert [call[2]["params"]["depth"] for call in wire.calls] == [1, 0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"type": "collection"}, {"type": "collection", "items": {}},
    collection([datacenter(), datacenter()]), collection([{**datacenter(), "id": True}]),
    collection([{**datacenter(), "type": "server"}]), collection([{**datacenter(), "metadata": {"state": "FAKE"}}]),
    collection([], more=True), collection([], offset=True), collection([], limit=2),
    {**collection([]), "_links": None}, collection([datacenter(), datacenter(SECOND)])])
async def test_unknown_envelopes_types_duplicates_page_shapes_never_succeed(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError): await execute({"operation": "check_connection"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,ctype", [(401, {"message": PRIVATE}, "application/json"),
    (402, {"message": PRIVATE}, "application/json"), (403, {"message": PRIVATE}, "application/json"),
    (404, {"message": PRIVATE}, "application/json"), (202, {}, "application/json"),
    (302, {}, "application/json"), (429, {}, "application/json"), (500, {}, "text/html"),
    (200, {}, "text/html"), (200, b'{"type":"collection","type":"server"}', "application/json"),
    (200, b'[NaN]', "application/json"), (200, b' ' * 2_000_001, "application/json")])
async def test_error_body_redirects_and_transport_strings_never_escape(wire, status, payload, ctype):
    wire.queue = [(payload, status, ctype)]
    with pytest.raises((ValueError, RuntimeError)) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


def test_actual_schema_and_original_family_guards_int32_contract_and_page_bounds():
    schema = p.IONOSCloudNode.get_config_schema()
    model = schema["$defs"]["IONOSCloudBearerCredential"]
    assert model["title"] == "IONOS Cloud Bearer Token" and "x-credential-type" not in model
    assert model["properties"]["token"]["ui:widget"] == "password"
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS) and len(p.OPS) == 5
    assert schema["$defs"]["GetServer"]["properties"]["server_id"]["x-dynamic-options"]["depends_on"] == "datacenter_id"
    assert p.IONOSCloudNode.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for changes in ({"credential_type": None}, {"credential_type": "ionos_basic"}, {"token": "Bearer " + PRIVATE},
        {"password": PRIVATE}, {"contract_number": True}, {"contract_number": "123"},
        {"contract_number": 2**31}, {"approved_datacenter_ids_json": "[123]"}, {"include_labels": "true"}):
        raw = {"config": {"operation": "check_connection"}, "credentials": blob(**changes)}
        assert p.IONOSCloudNode.validate_config(raw)["valid"] is False
        with pytest.raises(ValueError) as caught: p.IONOSCloudNode.parse_config(raw)
        assert PRIVATE not in str(caught.value)
    for value in (True, "", "../x", "https://invalid/", 123):
        with pytest.raises(ValueError): p.resource_id(value)
    for values in ({"limit": True}, {"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 2**31}):
        with pytest.raises(ValueError): p.ListDatacenters(**values)
    with pytest.raises(ValueError): p.ListServers(datacenter_id=DC, depth=10)
