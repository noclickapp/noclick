"""UNRUN native factory/connect/Agent dispatcher/socket/current-row fixtures.

Synthetic storage and transport seams exercise provider code; no live API,
keys, DNS changes or provider mock endpoints are used.
"""
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import porkbun_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect
from nodes.porkbun_node import CredentialValidationRow

NT = "automation-porkbun"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
KEY = {"credential_type": native.TYPE, "api_key": "synthetic-public-key", "secret_api_key": "synthetic-secret-key"}
DOMAIN = {"domain": "example.com", "status": "ACTIVE", "tld": "com", "createDate": "2021-01-15 10:00:00", "expireDate": "2027-01-15 10:00:00", "apiAccess": 1, "autoRenew": 1, "securityLock": 1, "whoisPrivacy": 1, "notLocal": 0, "labels": [{"title": "omit-label"}], "settings": "omit-settings"}
RECORD = {"id": "123456789", "name": "www.example.com", "type": "A", "content": "192.0.2.7", "ttl": "600", "prio": None, "notes": "omit-private-note"}


def catalog(rows=None, **extra):
    rows = [deepcopy(DOMAIN)] if rows is None else rows
    return {"status": "SUCCESS", "domains": rows, "count": len(rows), **extra}


def detail(value=None):
    return {"status": "SUCCESS", "domain": deepcopy(DOMAIN) if value is None else value}


def records(rows=None):
    return {"status": "SUCCESS", "records": [deepcopy(RECORD)] if rows is None else rows, "cloudflare": "enabled"}


def node(operation="list_domains", raw=KEY, **args):
    return NodeFactory.create_node(node_id="porkbun-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "api.porkbun.com" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b"" and not request.url.username and not request.url.password
        assert request.headers["X-API-Key"] == KEY["api_key"]
        assert request.headers["X-Secret-API-Key"] == KEY["secret_api_key"]
        assert "Authorization" not in request.headers
        assert all(value not in str(request.url) for value in (KEY["api_key"], KEY["secret_api_key"]))
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as instance:
            yield instance
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("args", [{"max_results": "1"}, {"max_results": True}, {"max_results": 101}, {"max_results": 0}, {"max_results": 20.5}, {"max_results": "20x"}, {"start": -1}, {"start": "0"}, {"start": True}, {"include_names": "false"}, {"host": "https://evil.example.test"}, {"operation": "ping"}, {"operation": "get_ip"}, {"operation": "edit_dns"}, {"operation": "check_domain"}, {"operation": "get_account"}, {"operation": "get_ssl"}])
def test_actual_factory_refuses_coercion_and_nonmetadata_scope(transport, args):
    with pytest.raises(ValueError):
        node(args.get("operation", "list_domains"), **{k: v for k, v in args.items() if k != "operation"})
    assert transport[0] == []


def test_actual_schema_defaults_literal_pair_and_parent_dependencies():
    schema = native.PorkbunNode.get_config_schema()
    refs = schema["properties"]["config"]["oneOf"]
    assert [schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in refs] == ["list_domains", "get_domain", "list_dns_records", "get_dns_record"]
    creds = schema["$defs"]["PorkbunCredential"]
    assert creds["required"] == ["api_key", "secret_api_key"]
    assert all(creds["properties"][key]["ui:widget"] == "password" for key in creds["required"])
    assert creds["properties"]["credential_type"]["const"] == native.TYPE
    assert "refresh_token" not in creds["properties"] and "host" not in creds["properties"]
    assert schema["$defs"]["ListDomains"]["properties"]["start"]["default"] == 0
    assert schema["$defs"]["ListDomains"]["properties"]["max_results"]["maximum"] == 100
    assert schema["$defs"]["GetDNSRecord"]["properties"]["record_id"]["x-dynamic-options"]["depends_on"] == "domain"
    assert schema["$defs"]["GetDomain"]["required"] == ["domain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[DOMAIN], []])
async def test_actual_visible_form_connect_is_reachability_not_identity(transport, rows):
    transport[1].append(catalog(rows))
    result = await validate_for_connect(credential_type=native.TYPE, credential_data={k: v for k, v in KEY.items() if k != "credential_type"}, user_id=USER)
    assert result.ok and result.credential_data["credential_type"] == native.TYPE
    assert result.evidence.reachable and native.PorkbunNode.connection_evidence.proves == "reachability" and not result.evidence.account_label
    assert "verified_as" not in result.verified_metadata()
    assert len(transport[0]) == 1 and transport[0][0].url.path.endswith("/domain/listAll")


@pytest.mark.asyncio
async def test_foreign_factory_and_preparsed_discriminator_are_zero_io(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "list_domains"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node()
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError):
        await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,sequence,last", [
    ("list_domains", {"start": 5}, [catalog()], "/domain/listAll"),
    ("get_domain", {"domain": "example.com"}, [catalog(), detail()], "/domain/get/example.com"),
    ("list_dns_records", {"domain": "example.com"}, [catalog(), detail(), records()], "/dns/retrieve/example.com"),
    ("get_dns_record", {"domain": "example.com", "record_id": RECORD["id"]}, [catalog(), detail(), records(), records()], "/dns/retrieve/example.com/123456789"),
])
async def test_actual_four_routes_and_exact_wrapper_projections(transport, operation, args, sequence, last):
    transport[1].extend(deepcopy(sequence))
    result = await node(operation, **args).execute({})
    assert result["status"] == "success" and result["operation"] == operation
    assert transport[0][-1].url.path == "/api/json/v3" + last
    assert all(word not in repr(result) for word in ("omit-", "192.0.2.7", "www.example.com", "example.com", "cloudflare", "apiAccess", "autoRenew", "securityLock", "whoisPrivacy"))
    assert dict(transport[0][0].url.params) == ({"start": "5", "includeLabels": "no"} if operation == "list_domains" else {"start": "0", "includeLabels": "no", "domain": "example.com"})
    if operation != "list_domains":
        assert dict(transport[0][1].url.params) == {"includeLabels": "no"}
        assert result["data"]["domain_metadata"]["createDate"] == DOMAIN["createDate"]
        assert result["data"]["domain_metadata"]["expireDate"] == DOMAIN["expireDate"]
    assert all(not req.url.params for req in transport[0][2:])


@pytest.mark.asyncio
async def test_actual_agent_dispatcher_page_count_is_not_account_total(transport):
    transport[1].append(catalog([DOMAIN, {**DOMAIN, "domain": "other.com"}]))
    result = await run_node_operation(node_type=NT, operation="list_domains", arguments={"start": 25, "max_results": 1}, user_id=USER, credential_data=KEY)
    data = result["data"]
    assert data["returned_count"] == 1 and data["observed_page_count"] == data["provider_page_count"] == 2 and data["truncated"]
    assert data["start"] == 25 and data["completion"] == "unknown" and not data["snapshot_consistent"]
    assert "total" not in data and "next" not in data and "next_page_token" not in data


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"domains": {}}, {"domains": [DOMAIN, DOMAIN]}, {"count": 1000}, {"count": True}, {"count": None}, {"status": "success"}, {"sandbox": "true"}])
async def test_malformed_catalog_shape_count_and_success_case_fail_closed(transport, bad):
    transport[1].append({**catalog(), **bad})
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.mark.asyncio
async def test_dates_have_no_legacy_alias_fallback_and_names_are_opt_in(transport):
    legacy = {k: v for k, v in DOMAIN.items() if k not in {"createDate", "expireDate"}}
    legacy.update(create_date="omit-legacy", expire_date="omit-legacy")
    transport[1].append(catalog([legacy], sandbox=True))
    data = (await node(include_names=True).execute({}))["data"]
    assert data["sandbox"] is True and data["items"][0]["domain"] == "example.com"
    assert "createDate" not in data["items"][0] and "expireDate" not in data["items"][0] and "omit" not in repr(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequence", [[catalog([])], [catalog([{**DOMAIN, "domain": "foreign.com"}])], [catalog(), detail({**DOMAIN, "domain": "foreign.com"})]])
async def test_domain_parent_refusal_never_sends_dns_read(transport, sequence):
    transport[1].extend(deepcopy(sequence))
    with pytest.raises(native.OutcomeUnverified):
        await node("list_dns_records", domain="example.com").execute({})
    assert all("/dns/" not in req.url.path for req in transport[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[RECORD, RECORD], [{**RECORD, "name": "www.foreign.com"}], [{**RECORD, "id": True}], [{**RECORD, "ttl": 600}], [{**RECORD, "prio": 10}], [{**RECORD, "type": "omit\nprivate"}]])
async def test_record_catalog_typed_parent_and_id_validation(transport, bad):
    transport[1].extend([catalog(), detail(), records(bad)])
    with pytest.raises(native.OutcomeUnverified):
        await node("list_dns_records", domain="example.com").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[], RECORD, [{**RECORD, "id": "99"}], [RECORD, RECORD], [{**RECORD, "name": "foreign.com"}], [{**RECORD, "ttl": "601"}]])
async def test_record_by_id_must_be_one_matching_array_record(transport, bad):
    transport[1].extend([catalog(), detail(), records(), records(bad)])
    with pytest.raises(native.OutcomeUnverified):
        await node("get_dns_record", domain="example.com", record_id=RECORD["id"]).execute({})
    assert len(transport[0]) == 4


@pytest.mark.asyncio
async def test_missing_record_is_refused_before_by_id_route(transport):
    transport[1].extend([catalog(), detail(), records([])])
    with pytest.raises(native.OutcomeUnverified):
        await node("get_dns_record", domain="example.com", record_id="999").execute({})
    assert len(transport[0]) == 3


@pytest.mark.parametrize("value", ["https://example.com", "example.com/", "EXAMPLE.COM", "example.com.", "example%2ecom", "例子.com", "localhost", "example..com"])
def test_factory_domain_is_literal_safe_canonical_parent(value, transport):
    with pytest.raises(ValueError):
        node("get_domain", domain=value)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,category", [(400,"INVALID_API_KEYS_001","authentication"), (200,"API_KEY_REQUIRED","authentication"), (403,"DOMAIN_NOT_ALLOWED","permission"), (403,"IP_NOT_ALLOWED","permission"), (404,"DOMAIN_NOT_FOUND","resource"), (429,"omit-code","other"), (500,"omit-code","other")])
async def test_http_and_business_errors_redact_private_response_without_retry(transport, status, code, category):
    transport[1].append(httpx.Response(status, json={"status":"ERROR", "code":code, "account":"omit-account", "requestId":"omit-request", "message":"omit-secret " + KEY["secret_api_key"]}))
    with pytest.raises(native.ApiError) as error:
        await node().execute({})
    assert error.value.category == category and "omit" not in str(error.value) and KEY["secret_api_key"] not in str(error.value)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,ctype", [(b'{"status":"SUCCESS","status":"ERROR"}',"application/json"),(b'{"status":"SUCCESS","domains":[NaN]}',"application/json"),(b'omit-private',"text/plain")])
async def test_malformed_json_has_no_private_body_output(transport, body, ctype):
    transport[1].append(httpx.Response(200, content=body, headers={"content-type":ctype}))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.mark.asyncio
async def test_bound_and_local_diagnostics_keep_unrelated_logs(transport, caplog):
    logger = logging.getLogger("httpx")
    def observed(request):
        logger.warning("%s %s %s", request.headers["X-API-Key"], request.headers["X-Secret-API-Key"], "omit-private-domain")
        return catalog()
    transport[1].append(observed)
    with caplog.at_level(logging.WARNING):
        await node().execute({})
        logger.warning("Ordinary unrelated message")
    assert "Porkbun transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert all(value not in caplog.text for value in (KEY["api_key"], KEY["secret_api_key"], "omit-private-domain"))
    transport[1].append(httpx.Response(200, content=b" "*(native.MAX_BODY+1),headers={"content-type":"application/json"}))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.fixture
def stored(monkeypatch):
    state = {"accessible": True, "row": CredentialValidationRow(native.TYPE,USER,1,datetime(2026,10,1,tzinfo=timezone.utc),1,None,deepcopy(KEY))}
    async def fetch(pool, identifier, principal, organization_id=None):
        assert identifier == CID and principal == USER and organization_id is None
        return state["row"] if state["accessible"] else None
    async def get_credential(identifier, principal, pool, org=None):
        row = await fetch(pool, identifier, principal, org)
        return deepcopy(row.credential) if row and row.revoked_at is None else None
    monkeypatch.setattr("utils.credentials.get_credential", get_credential)
    monkeypatch.setattr(native,"fetch_validation_authority",fetch)
    monkeypatch.setattr(native,"get_encryption",lambda:SimpleNamespace(decrypt_credential=lambda raw:deepcopy(raw)))
    return state


@pytest.mark.asyncio
async def test_saved_missing_caller_and_stale_either_key_fail_before_io(stored, transport):
    instance=NodeFactory.create_node(node_id="saved",node_type=NT,node_data={"credential_id":CID,"config":{"operation":"list_domains"},"credentials":KEY},sio=None,sid=None)
    with pytest.raises(ValueError):
        await instance.execute({})
    for key in ("api_key","secret_api_key"):
        with pytest.raises(ValueError):
            await native.Authority.create({**KEY,key:"stale"},pool=object(),user_id=USER,credential_id=CID,organization_id=None)
    stored["row"]=replace(stored["row"],credential={**KEY,"secret_api_key":True})
    with pytest.raises(ValueError) as error:
        await native.Authority.create(KEY,pool=object(),user_id=USER,credential_id=CID,organization_id=None)
    assert KEY["api_key"] not in str(error.value) and KEY["secret_api_key"] not in str(error.value) and not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["owner","version","approval","revoked","access","kind","original_kind","key","secret"])
async def test_actual_saved_execute_discards_racing_row_authority(stored,transport,change):
    instance=node();instance.node_data.update({"credential_id":CID,"_approval_pool":object()})
    def changed(request):
        if change=="access":stored["accessible"]=False
        else:
            delta={"owner":{"owner_id":CID},"version":{"token_version":2},"approval":{"approval_revision":2},"revoked":{"revoked_at":datetime.now(timezone.utc)},"kind":{"credential_type":"foreign"},"original_kind":{"credential":{**KEY,"credential_type":"foreign"}},"key":{"credential":{**KEY,"api_key":"changed"}},"secret":{"credential":{**KEY,"secret_api_key":"changed"}}}[change]
            stored["row"]=replace(stored["row"],**delta)
        return catalog()
    transport[1].append(changed)
    with pytest.raises(ValueError):await instance.execute({})
    assert len(transport[0])==1


@pytest.mark.asyncio
async def test_saved_scoped_record_picker_and_actor_refusal(stored,transport):
    fresh=await native.PorkbunNode.freshen_credential(KEY,pool=object(),user_id=USER,credential_id=CID,organization_id=None)
    transport[1].extend([catalog(),detail(),records()])
    result=await native.PorkbunNode.load_field_options(field_name="record_id",credential_data=fresh,context={"_user_id":USER,"domain":"example.com"})
    assert result=={"options":[{"value":RECORD["id"],"label":"A record 123456789"}],"next_page_token":None}
    for kwargs in ({"context":{"_user_id":CID,"domain":"example.com"}},{"context":{"_user_id":USER}},{"page_token":"foreign"},{"field_name":"token"}):
        with pytest.raises(ValueError):await native.PorkbunNode.load_field_options(**{"field_name":"record_id","credential_data":fresh,"context":{"_user_id":USER,"domain":"example.com"},**kwargs})
    assert len(transport[0])==3
    stored["accessible"]=False
    with pytest.raises(ValueError):await native.PorkbunNode.load_field_options(field_name="domain",credential_data=fresh,context={"_user_id":USER})


@pytest.mark.asyncio
async def test_picker_refuses_oversized_observed_catalog(stored,transport):
    fresh=await native.PorkbunNode.freshen_credential(KEY,pool=object(),user_id=USER,credential_id=CID,organization_id=None)
    transport[1].append(catalog([{**DOMAIN,"domain":f"domain{i}.com"} for i in range(101)]))
    with pytest.raises(native.OutcomeUnverified,match="picker bound"):
        await native.PorkbunNode.load_field_options(field_name="domain",credential_data=fresh,context={"_user_id":USER})
    assert len(transport[0])==1




@pytest.mark.asyncio
@pytest.mark.parametrize("change",[None,"authorization","owner"])
async def test_actual_workflow_owner_fallback_keeps_trusted_context(monkeypatch,transport,change):
    owner="33333333-3333-4333-8333-333333333333";workflow="44444444-4444-4444-8444-444444444444";organization="55555555-5555-4555-8555-555555555555";pool=object();state={"owner":owner,"authorized":True};principals=[]
    row=CredentialValidationRow(native.TYPE,owner,1,datetime(2026,10,1,tzinfo=timezone.utc),1,None,deepcopy(KEY))
    async def fetch(pool,identifier,principal,org=None):
        assert identifier==CID and org==organization;principals.append(principal);return row if principal==owner else None
    async def get_owner(actual_pool,actual_workflow):
        assert actual_pool is pool and actual_workflow==workflow;return state["owner"]
    async def allowed(actual_pool,actual_workflow,identifier):
        assert actual_pool is pool and actual_workflow==workflow and identifier==CID;return state["authorized"]
    async def get_credential(identifier, principal, pool, org=None):
        row = await fetch(pool, identifier, principal, org)
        return deepcopy(row.credential) if row and row.revoked_at is None else None
    monkeypatch.setattr("utils.credentials.get_credential", get_credential)
    monkeypatch.setattr(native,"fetch_validation_authority",fetch)
    monkeypatch.setattr(native,"get_encryption",lambda:SimpleNamespace(decrypt_credential=lambda raw:deepcopy(raw)))
    monkeypatch.setattr("utils.credentials.get_workflow_owner_id",get_owner);monkeypatch.setattr("utils.credentials.is_credential_authorized_for_workflow",allowed)
    monkeypatch.setattr(native,"get_workflow_owner_id",get_owner);monkeypatch.setattr(native,"is_credential_authorized_for_workflow",allowed)
    monkeypatch.setattr("utils.credentials.credential_lender",AsyncMock(return_value=None))
    monkeypatch.setattr(native,"credential_lender",AsyncMock(return_value=None))
    instance=NodeFactory.create_node(node_id="fallback",node_type=NT,node_data={"config":{"operation":"list_domains"},"credentials":deepcopy(KEY),"credential_id":CID,"_approval_pool":pool},user_id=USER,organization_id=organization,workflow_id=workflow,sio=None,sid=None)
    def changed(request):
        if change=="authorization":state["authorized"]=False
        if change=="owner":state["owner"]=CID
        return catalog()
    transport[1].append(changed)
    if change is None:
        assert (await instance.execute({}))["data"]["returned_count"]==1 and principals[:2]==[USER,owner]
    else:
        with pytest.raises(ValueError):await instance.execute({})
    assert len(transport[0])==1
