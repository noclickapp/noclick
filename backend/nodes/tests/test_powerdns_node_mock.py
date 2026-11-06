"""UNRUN actual PowerDNS factory/connect/dispatcher/current-row/socket seams."""
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import powerdns_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect
from nodes.powerdns_node import PowerDNSAuthorityRow as CredentialValidationRow

NT = "automation-powerdns"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
KEY = {"credential_type": native.TYPE, "api_origin": "https://dns.example.com:8443", "api_key": "synthetic-issued-key", "server_id": "localhost"}
SERVER = {"id": "localhost", "type": "Server", "daemon_type": "authoritative", "version": "5.0.0", "config_url": "omit-capability", "zones_url": "omit-capability", "url": "omit-capability"}
ZONE = {"id": "example.test.", "name": "example.test.", "type": "Zone", "kind": "Native", "serial": 42, "notified_serial": 41, "last_check": 0, "masters": ["omit-IP"], "account": "omit-account", "zone": "omit-zonefile", "nsec3param": "omit-key", "master_tsig_key_ids": ["omit-key"], "url": "omit-capability"}
RR = {"name": "www.example.test.", "type": "A", "ttl": 300, "records": [{"content": "omit-RDATA", "disabled": False}], "comments": [{"content": "omit-comment", "account": "omit-account"}]}


def node(operation="list_servers", raw=KEY, **args):
    return NodeFactory.create_node(node_id="powerdns-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "dns.example.com" and request.url.port == 8443 and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b"" and not request.url.username and not request.url.password
        assert KEY["api_key"] not in str(request.url) and request.headers["X-API-Key"] == KEY["api_key"]
        calls.append(request)
        value = responses.pop(0)
        if callable(value): value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as instance:
            yield instance
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("args", [{"max_results": "1"}, {"max_results": True}, {"max_results": 0}, {"max_results": 201}, {"max_results": "20x"}, {"max_results": 20.5}, {"include_names": "false"}, {"offset": 1}, {"host": "https://evil.example.test"}, {"operation": "notify"}, {"operation": "delete_zone"}, {"operation": "export"}])
def test_real_factory_refuses_types_bounds_and_control_routes(transport, args):
    with pytest.raises(ValueError): node(args.get("operation", "list_servers"), **{k:v for k,v in args.items() if k != "operation"})
    assert transport[0] == []


@pytest.mark.parametrize("origin", ["http://dns.example.com", "https://localhost", "https://127.0.0.1:8443", "https://[::1]", "https://dns.example.com/api/v1", "https://user:key@dns.example.com", "https://dns.example.com?key=private", "https://dns.example.com#private", "https://dns.example.com:0", "https://dns.local"])
def test_local_origin_validation_refuses_unsafe_boundaries(origin):
    with pytest.raises(ValueError): native.credential({**KEY, "api_origin": origin})


@pytest.mark.parametrize("locator", ["..", "../config", "%2fconfig", "%252fconfig", "zone?secret=value", "zone#secret", 42, "zone\\private", "%broken"])
def test_locator_is_not_arbitrary_path(locator):
    with pytest.raises(ValueError): native.resource_id(locator)


@pytest.mark.asyncio
async def test_real_foreign_factory_and_preparsed_execution_have_zero_io(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "list_servers"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node(); instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_real_visible_form_connect_is_resource_reachability_not_identity(transport):
    transport[1].append([SERVER])
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={k:v for k,v in KEY.items() if k != "credential_type"}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert verdict.evidence.reachable is True and native.PowerDNSNode.connection_evidence.proves == "reachability" and not verdict.evidence.account_label
    assert [r.url.path for r in transport[0]] == ["/api/v1/servers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,responses,paths", [
    ("list_servers", {}, [[SERVER]], ["/servers"]),
    ("get_server", {}, [[SERVER], SERVER], ["/servers", "/servers/localhost"]),
    ("list_zones", {}, [[SERVER], [ZONE]], ["/servers", "/servers/localhost/zones"]),
    ("get_zone", {"zone_id": ZONE["id"]}, [[SERVER], [ZONE], ZONE], ["/servers", "/servers/localhost/zones", "/servers/localhost/zones/example.test."]),
    ("list_rrsets", {"zone_id": ZONE["id"]}, [[SERVER], [ZONE], {**ZONE, "rrsets": [RR]}], ["/servers", "/servers/localhost/zones", "/servers/localhost/zones/example.test."]),
])
async def test_real_closed_routes_and_default_private_projection(transport, operation, args, responses, paths):
    transport[1].extend(deepcopy(responses))
    result = await node(operation, **args).execute({})
    assert "omit" not in repr(result) and "example.test." not in repr(result)
    assert [r.url.path for r in transport[0]] == ["/api/v1" + path for path in paths]
    if operation in {"list_zones", "get_zone", "list_rrsets"}:
        assert dict(transport[0][1].url.params) == {"dnssec": "false"}
    if operation in {"get_zone", "list_rrsets"}:
        assert dict(transport[0][-1].url.params) == {"rrsets": "true" if operation == "list_rrsets" else "false", "record_count": "false"}
    if operation == "list_rrsets":
        assert result["data"]["rrset_metadata"]["items"] == [{"type": "A", "ttl": 300}]


@pytest.mark.asyncio
async def test_dispatcher_local_cap_does_not_invent_pagination_or_total(transport):
    transport[1].extend([[SERVER], [ZONE, {**ZONE, "id": "other.test."}]])
    result = await run_node_operation(node_type=NT, operation="list_zones", arguments={"max_results": 1}, user_id=USER, credential_data=KEY)
    assert result["data"] == {"items": [{"type": "Zone", "kind": "Native", "serial": 42, "notified_serial": 41, "last_check": 0}], "returned_count": 1, "observed_array_count": 2, "local_limit": 1, "truncated": True, "provider_pagination": False, "completion": "unknown", "snapshot_consistent": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", [[], [{**SERVER, "daemon_type": "recursor"}], [{**SERVER, "id": "other"}], [SERVER, SERVER], {}])
async def test_empty_wrong_daemon_or_malformed_catalog_cannot_prove_witness(transport, catalog):
    transport[1].append(catalog)
    with pytest.raises(native.OutcomeUnverified): await node("list_zones").execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_guessed_zone_name_is_refused_before_detail_request(transport):
    transport[1].extend([[SERVER], [ZONE]])
    with pytest.raises(native.OutcomeUnverified):
        await node("get_zone", zone_id="guessed.test.").execute({})
    assert len(transport[0]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", [[ZONE], {**ZONE, "id": "other.test."}, {}, {**ZONE, "serial": True}])
async def test_detail_object_contract_and_exact_catalog_parent(transport, detail):
    transport[1].extend([[SERVER], [ZONE], detail])
    with pytest.raises(native.OutcomeUnverified): await node("get_zone", zone_id=ZONE["id"]).execute({})


@pytest.mark.asyncio
async def test_name_and_provider_count_opt_in_never_expand_dns_record_data(transport):
    transport[1].extend([[SERVER], [ZONE], {**ZONE, "rrsets": [RR, {**RR, "name": "second.example.test."}], "record_count": 9}])
    result = await node("list_rrsets", zone_id=ZONE["id"], include_names=True, include_record_count=True, max_results=1).execute({})
    data = result["data"]
    assert data["id"] == ZONE["id"] and data["name"] == ZONE["name"] and data["record_count"] == 9
    assert data["rrset_metadata"]["items"] == [{"type": "A", "ttl": 300, "name": RR["name"]}]
    assert data["rrset_metadata"]["returned_count"] == 1 and "omit" not in repr(data)
    assert dict(transport[0][-1].url.params)["record_count"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [None, True, "2", -1])
async def test_explicit_record_count_must_be_supplied_strict_integer(transport, count):
    detail = {**ZONE, **({} if count is None else {"record_count": count})}
    transport[1].extend([[SERVER], [ZONE], detail])
    with pytest.raises(native.OutcomeUnverified):
        await node("get_zone", zone_id=ZONE["id"], include_record_count=True).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
async def test_safe_status_errors_without_body_or_retries(transport, status):
    transport[1].append(httpx.Response(status, json={"error": "omit-private"}))
    with pytest.raises(native.ApiError) as error: await node().execute({})
    assert error.value.status_code == status and "omit" not in str(error.value) and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,ctype", [(b'{"id":1,"id":2}', "application/json"), (b'[NaN]', "application/json"), (b'omit-private', "text/plain")])
async def test_strict_json_errors_are_private(transport, body, ctype):
    transport[1].append(httpx.Response(200, content=body, headers={"content-type": ctype}))
    with pytest.raises(native.OutcomeUnverified): await node().execute({})


@pytest.mark.asyncio
async def test_saved_actor_picker_preserves_internal_id_and_no_name_default(stored, transport):
    fresh = await native.PowerDNSNode.freshen_credential(KEY, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    transport[1].extend([[SERVER], [ZONE]])
    picked = await native.PowerDNSNode.load_field_options(field_name="zone_id", credential_data=fresh, context={"_user_id": USER})
    assert picked == {"options": [{"value": ZONE["id"], "label": "Zone 1"}], "next_page_token": None}
    for change in [{"context": {"_user_id": CID}}, {"page_token": "untrusted"}, {"field_name": "key"}]:
        with pytest.raises(ValueError):
            await native.PowerDNSNode.load_field_options(**{"field_name": "zone_id", "credential_data": fresh, "context": {"_user_id": USER}, **change})
    assert len(transport[0]) == 2
    stored["accessible"] = False
    with pytest.raises(ValueError): await native.PowerDNSNode.load_field_options(field_name="zone_id", credential_data=fresh, context={"_user_id": USER})
    assert len(transport[0]) == 2


@pytest.mark.asyncio
async def test_private_request_diagnostics_are_local(transport, caplog):
    logger = logging.getLogger("httpx")
    def observed(request):
        logger.warning("%s %s", request.headers["X-API-Key"], "omit-zone-name")
        return [deepcopy(SERVER)]
    transport[1].append(observed)
    with caplog.at_level(logging.WARNING):
        await node().execute({}); logger.warning("Ordinary unrelated message")
    assert "PowerDNS transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert KEY["api_key"] not in caplog.text and "omit-zone-name" not in caplog.text

@pytest.fixture
def stored(monkeypatch):
    state = {"accessible": True, "row": CredentialValidationRow(native.TYPE, USER, 1, datetime(2026,10,1,tzinfo=timezone.utc), 1, None, deepcopy(KEY))}
    async def fetch(pool, identifier):
        assert identifier == CID
        return state["row"] if state["accessible"] else None
    async def resolve(identifier, principal, pool, org_id=None):
        assert identifier == CID and principal == USER and org_id is None
        row = state["row"]
        return {**deepcopy(row.credential), "credential_type": row.credential_type} if state["accessible"] and row.revoked_at is None else None
    monkeypatch.setattr(native, "load_authority_row", fetch)
    monkeypatch.setattr("utils.credentials.get_credential", resolve)
    monkeypatch.setattr(native, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda raw: deepcopy(raw)))
    return state


@pytest.mark.asyncio
async def test_saved_missing_caller_stale_and_corrupt_original_are_zero_io(stored, transport):
    instance = NodeFactory.create_node(node_id="saved", node_type=NT, node_data={"credential_id": CID, "config": {"operation": "list_servers"}, "credentials": KEY}, sio=None, sid=None)
    with pytest.raises(ValueError): await instance.execute({})
    with pytest.raises(ValueError): await native.Authority.create({**KEY, "api_key": "stale"}, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    stored["row"] = replace(stored["row"], credential={**KEY, "api_key": True})
    with pytest.raises(ValueError) as error: await native.Authority.create(KEY, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    assert KEY["api_key"] not in str(error.value) and transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "version", "approval", "revoked", "access", "kind", "original_kind", "token", "witness"])
async def test_actual_saved_execute_discards_racing_authority_and_response(stored, transport, change):
    instance = node(); instance.node_data.update({"credential_id": CID, "_approval_pool": object()})
    def changed(request):
        if change == "access": stored["accessible"] = False
        else:
            delta = {"owner": {"owner_id": CID}, "version": {"token_version": 2}, "approval": {"approval_revision": 2}, "revoked": {"revoked_at": datetime.now(timezone.utc)}, "kind": {"credential_type": "foreign"}, "original_kind": {"credential": {**KEY, "credential_type": "foreign"}}, "token": {"credential": {**KEY, "api_key": "changed"}}, "witness": {"credential": {**KEY, "server_id": "other"}}}[change]
            stored["row"] = replace(stored["row"], **delta)
        return [deepcopy(SERVER)]
    transport[1].append(changed)
    with pytest.raises(ValueError): await instance.execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "authorization", "owner"])
async def test_actual_execute_fallback_revalidates_workflow_owner_and_org(monkeypatch, transport, change):
    owner = "33333333-3333-4333-8333-333333333333"
    workflow = "44444444-4444-4444-8444-444444444444"
    organization = "55555555-5555-4555-8555-555555555555"
    pool = object(); state = {"owner": owner, "authorized": True}; principals = []
    row = CredentialValidationRow(native.TYPE, owner, 1, datetime(2026,10,1,tzinfo=timezone.utc), 1, None, deepcopy(KEY))
    async def fetch(identifier, principal, actual_pool, org=None):
        assert identifier == CID and org == organization
        principals.append(principal)
        return deepcopy(row.credential) if principal == owner else None
    async def get_owner(actual_pool, actual_workflow):
        assert actual_pool is pool and actual_workflow == workflow
        return state["owner"]
    async def allowed(actual_pool, actual_workflow, identifier):
        assert actual_pool is pool and actual_workflow == workflow and identifier == CID
        return state["authorized"]
    monkeypatch.setattr("utils.credentials.get_credential", fetch)
    monkeypatch.setattr(native, "load_authority_row", AsyncMock(return_value=row))
    monkeypatch.setattr("utils.credentials.credential_lender", AsyncMock(return_value=None))
    monkeypatch.setattr(native, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda raw: deepcopy(raw)))
    monkeypatch.setattr("utils.credentials.get_workflow_owner_id", get_owner)
    monkeypatch.setattr("utils.credentials.is_credential_authorized_for_workflow", allowed)
    instance = NodeFactory.create_node(node_id="fallback", node_type=NT, node_data={"config": {"operation": "list_servers"}, "credentials": deepcopy(KEY), "credential_id": CID, "_approval_pool": pool}, user_id=USER, organization_id=organization, workflow_id=workflow, sio=None, sid=None)
    def changed(request):
        if change == "authorization": state["authorized"] = False
        if change == "owner": state["owner"] = CID
        return [deepcopy(SERVER)]
    transport[1].append(changed)
    if change is None:
        assert (await instance.execute({}))["data"]["items"][0]["id"] == "localhost"
        assert principals[:2] == [USER, owner] and len(transport[0]) == 1
    else:
        with pytest.raises(ValueError): await instance.execute({})
        assert len(transport[0]) == 1



@pytest.mark.asyncio
async def test_response_body_limit_has_no_partial_output(transport):
    transport[1].append(httpx.Response(200, content=b" " * (native.MAX_BODY + 1), headers={"content-type": "application/json"}))
    with pytest.raises(native.OutcomeUnverified): await node().execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rrsets", [[RR, RR], [{**RR, "ttl": True}], [{**RR, "type": "A\nprivate"}], {}])
async def test_rrset_metadata_shapes_and_duplicate_parent_names_are_unverified(transport, rrsets):
    transport[1].extend([[SERVER], [ZONE], {**ZONE, "rrsets": rrsets}])
    with pytest.raises(native.OutcomeUnverified):
        await node("list_rrsets", zone_id=ZONE["id"]).execute({})
    assert len(transport[0]) == 3


def test_schema_required_locator_and_exact_operation_contract():
    schema = native.PowerDNSNode.get_config_schema()
    assert schema["$defs"]["PowerDNSCredential"]["properties"]["credential_type"]["const"] == native.TYPE
    assert schema["$defs"]["GetZone"]["required"] == ["zone_id"]
    assert schema["$defs"]["ListRRSets"]["required"] == ["zone_id"]
    assert schema["$defs"]["GetZone"]["properties"]["include_record_count"]["default"] is False
    assert schema["$defs"]["ListServers"]["properties"]["max_results"]["maximum"] == 200


def test_actual_server_default_schema_preserves_required_zone_constraints():
    schema = native.PowerDNSNode.get_config_schema()
    field = schema["$defs"]["PowerDNSCredential"]["properties"]["server_id"]
    assert field["default"] == "localhost" and field["type"] == "string"
    assert field["maxLength"] == 512 and "minLength" not in field
    shaped = native.PowerDNSCredential.model_validate({key: value for key, value in KEY.items() if key != "server_id"})
    assert shaped.server_id == "localhost"
    for name in ("GetZone", "ListRRSets"):
        assert "zone_id" in schema["$defs"][name]["required"]
        assert schema["$defs"][name]["properties"]["zone_id"]["minLength"] == 1
        assert schema["$defs"][name]["properties"]["zone_id"]["maxLength"] == 512


@pytest.mark.parametrize("identifier", ["", " ", "..", "%2fconfig", True, 42, {}])
def test_actual_default_bearing_server_field_keeps_strict_runtime_id_refusal(identifier):
    with pytest.raises(ValueError) as error:
        native.PowerDNSCredential.model_validate({**KEY, "server_id": identifier})
    assert KEY["api_key"] not in str(error.value)


# Exact examples from the provider, including the absent optional zone type:
# https://docs.powerdns.com/authoritative/http-api/server.html#listing-all-servers
# https://docs.powerdns.com/authoritative/http-api/zone.html#listing-all-zones
# https://docs.powerdns.com/authoritative/http-api/zone.html#listing-a-zone
DOCUMENTED_SERVERS = [{'autoprimaries_url': '/api/v1/servers/localhost/autoprimaries{/autoprimary}',
  'config_url': '/api/v1/servers/localhost/config{/config_setting}',
  'daemon_type': 'authoritative',
  'id': 'localhost',
  'type': 'Server',
  'url': '/api/v1/servers/localhost',
  'version': '4.6.1',
  'zones_url': '/api/v1/servers/localhost/zones{/zone}'}]

DOCUMENTED_ZONES = [{'account': '',
  'dnssec': False,
  'edited_serial': 2022040504,
  'id': 'example.org.',
  'kind': 'Native',
  'last_check': 0,
  'masters': [],
  'name': 'example.org.',
  'notified_serial': 0,
  'serial': 2022040504,
  'url': '/api/v1/servers/localhost/zones/example.org.'}]

DOCUMENTED_ZONE_DETAIL = {'account': '',
 'api_rectify': False,
 'dnssec': False,
 'edited_serial': 2022040501,
 'id': 'example.org.',
 'kind': 'Native',
 'last_check': 0,
 'master_tsig_key_ids': [],
 'masters': [],
 'name': 'example.org.',
 'notified_serial': 0,
 'nsec3narrow': False,
 'nsec3param': '',
 'rrsets': [{'comments': [],
             'name': 'example.org.',
             'records': [{'content': 'a.misconfigured.dns.server.invalid. hostmaster.example.org. '
                                     '2022040501 10800 3600 604800 3600',
                          'disabled': False}],
             'ttl': 3600,
             'type': 'SOA'},
            {'comments': [],
             'name': 'example.org.',
             'records': [{'content': 'ns1.example.org.', 'disabled': False},
                         {'content': 'ns2.example.org.', 'disabled': False}],
             'ttl': 3600,
             'type': 'NS'}],
 'serial': 2022040501,
 'slave_tsig_key_ids': [],
 'soa_edit': '',
 'soa_edit_api': 'DEFAULT',
 'url': '/api/v1/servers/localhost/zones/example.org.'}

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_zones", "get_zone", "list_rrsets"])
async def test_provider_zone_examples_without_optional_type(transport, operation):
    responses = [DOCUMENTED_SERVERS, DOCUMENTED_ZONES]
    args = {"include_names": True}
    if operation != "list_zones":
        responses.append(DOCUMENTED_ZONE_DETAIL)
        args["zone_id"] = DOCUMENTED_ZONE_DETAIL["id"]
    transport[1].extend(deepcopy(responses))
    result = await node(operation, **args).execute({})
    data = result["data"]
    zone_metadata = data["items"][0] if operation == "list_zones" else data
    assert result["status"] == "success"
    assert zone_metadata["id"] == "example.org."
    assert zone_metadata["kind"] == "Native"
    assert "type" not in zone_metadata
    assert "records" not in repr(data) and "content" not in repr(data)
    if operation == "list_rrsets":
        assert data["rrset_metadata"]["items"] == [
            {"name": "example.org.", "type": "SOA", "ttl": 3600},
            {"name": "example.org.", "type": "NS", "ttl": 3600},
        ]
    assert len(transport[0]) == len(responses)


@pytest.mark.parametrize("marker", [None, "string", "Server", 1])
def test_provider_optional_zone_type_still_rejects_invalid_marker(marker):
    with pytest.raises(native.OutcomeUnverified):
        native.zone({**DOCUMENTED_ZONE_DETAIL, "type": marker})


def test_public_transport_refuses_install_wide_private_opt_out(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    with pytest.raises(native.SSRFError, match="public-only"):
        native.guarded_async_client(require_public=True)
