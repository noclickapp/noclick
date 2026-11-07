"""Native Vendasta factory/execute, transport, scope and mutation regressions.

Only the HTTPS boundary is synthetic; the registered factory, config union,
dispatcher, collector and provider request/projection code stay real.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from nodes import vendasta_node as v
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation


USER = "00000000-0000-4000-8000-000000000001"
FIELD = "fixture-name"


def blob(**changes):
    return {"credential_type": v.FAMILY, "access_token": "synthetic-issued-token",
            "namespace": "fixture-namespace", "environment": "demo",
            "scope": "crm", "expires_at": "2099-01-01T00:00:00Z",
            "read_fields_csv": FIELD, "write_fields_csv": FIELD, **changes}


def schema(kind="Contact", **changes):
    return {"fieldId": FIELD, "externalId": "standard__first_name", "fieldName": "Fixture Name",
            "crmObjectType": kind, "fieldType": "FIELD_TYPE_STRING", "readonly": False, **changes}


def record(record_id="fixture-contact", **changes):
    return {"crmObjectId": record_id, "namespace": "fixture-namespace",
            "fields": [{"fieldId": FIELD, "stringValue": "Fixture"},
                       {"fieldId": "private-unselected", "stringValue": "SYNTHETIC_PRIVATE_FRAGMENT"}], **changes}


def page(key, values, more=False, cursor=None):
    return {key: values, "pagingMetadata": {"hasMore": more, "nextCursor": cursor, "totalResults": "0"}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], options=[], after_headers=None)

    class Response:
        def __init__(self, payload, status, content_type):
            self.status_code, self.headers = status, {"content-type": content_type}
            self.payload = json.dumps(payload).encode()
        async def __aenter__(self):
            if state.after_headers: state.after_headers()
            return self
        async def __aexit__(self, *_): return False
        async def aiter_bytes(self): yield self.payload

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def stream(self, method, url, **kwargs):
            state.calls.append((method, url, deepcopy(kwargs)))
            assert state.queue, "Unexpected request beyond the scoped fixture"
            value = state.queue.pop(0)
            if isinstance(value, BaseException): raise value
            if isinstance(value, tuple): return Response(*value)
            return Response(value, 200, "application/json")

    def client(**kwargs):
        state.options.append(kwargs)
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(v, "guarded_async_client", client)
    return state


async def execute(args, data=None):
    node = NodeFactory.create_node("fixture-node", v.NODE_TYPE,
        {"config": args, "credentials": data or blob()}, user_id=USER)
    assert node.config.config.operation == args["operation"]
    return await node.execute({})


@pytest.mark.asyncio
async def test_parsed_config_credentials_work_without_raw_node_data(wire):
    # Verbatim successful response from the provider's first-call example:
    # https://developers.vendasta.com/getting-started/authorization/calling-apis/
    response = {
        "fieldSchemas": [{"fieldId": "standard__email", "externalId": "standard__email",
                          "fieldName": "Email", "fieldType": "FIELD_TYPE_EMAIL",
                          "crmObjectType": "Contact"}],
        "pagingMetadata": {"hasMore": True, "nextCursor": "..."},
    }
    wire.queue = [response]
    config = v.VendastaNodeConfig.model_validate({
        "config": {"operation": "check_connection"},
        "credentials": blob(namespace="AG-EXAMPLE"),
    })
    node = v.VendastaNode("parsed-config", v.NODE_TYPE, {}, config, sio=None)
    out = await node.execute({})
    assert out["records"] == response["fieldSchemas"]
    assert out["has_more"] is True and out["next_cursor"] == "..."
    assert wire.calls[0][2]["json"]["namespace"] == "AG-EXAMPLE"
    assert wire.calls[0][2]["headers"]["Authorization"] == "Bearer synthetic-issued-token"


@pytest.mark.asyncio
async def test_invalid_raw_credentials_do_not_fall_back_to_parsed_config(wire):
    config = v.VendastaNodeConfig.model_validate({
        "config": {"operation": "check_connection"}, "credentials": blob(),
    })
    node = v.VendastaNode("parsed-config", v.NODE_TYPE, {"credentials": {}}, config, sio=None)
    with pytest.raises(ValueError, match="Connect a native Vendasta supplied access token"):
        await node.execute({})
    assert not wire.calls


@pytest.mark.asyncio
async def test_registered_real_factory_and_single_inputs_dispatcher(wire):
    assert NODE_REGISTRY[v.NODE_TYPE] is v.VendastaNode
    wire.queue = [page("crmObjects", [record()])]
    result = await run_node_operation(node_type=v.NODE_TYPE, operation="list_contacts",
        arguments={"operation": "delete_account"}, user_id=USER, credential_data=blob())
    assert result["records"][0]["crmObjectId"] == "fixture-contact"
    assert "SYNTHETIC_PRIVATE_FRAGMENT" not in json.dumps(result)
    assert result["identity_verified"] is False
    assert wire.calls[0][:2] == ("POST", "https://demo.apigateway.co/grpc/v1/crm/contact/list")
    assert wire.calls[0][2]["json"]["namespace"] == "fixture-namespace"


@pytest.mark.asyncio
async def test_cursor_repeats_filters_search_sort_and_truncation_is_explicit(wire):
    filters = {"operator": "FILTER_GROUP_OPERATOR_AND", "filters": [
        {"fieldId": FIELD, "operator": "FILTER_OPERATOR_IS", "values": [{"string": "Fixture"}]}]}
    sorts = [{"fieldId": FIELD, "sortDirection": "SORT_DIRECTION_ASCENDING"}]
    wire.queue = [page("crmObjects", [record("one")], True, "cursor-one"),
                  page("crmObjects", [record("two")], True, "cursor-two")]
    out = await execute({"operation": "list_contacts", "search": "Fixture", "max_pages": 2,
                         "filters_json": json.dumps(filters), "sort_json": json.dumps(sorts)})
    first, second = [call[2]["json"] for call in wire.calls]
    assert {k: val for k, val in first.items() if k != "pagingOptions"} == {k: val for k, val in second.items() if k != "pagingOptions"}
    assert second["pagingOptions"] == {"pageSize": "100", "cursor": "cursor-one"}
    assert second["filtersV2"] == filters and second["sortBy"] == sorts
    assert out["has_more"] is True and out["next_cursor"] == "cursor-two"


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [page("crmObjects", [record("one")]),
    page("crmObjects", [record("two")], True, "cursor-one"), {"crmObjects": []}])
async def test_repeated_ids_cursors_or_unknown_paging_fail(wire, second):
    wire.queue = [page("crmObjects", [record("one")], True, "cursor-one"), second]
    with pytest.raises(RuntimeError):
        await execute({"operation": "list_contacts", "max_pages": 2})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,ctype,payload", [(202, "application/json", {}),
    (204, "application/json", {}), (302, "application/json", {}),
    (500, "text/html", {"message": "SYNTHETIC_PROVIDER_FRAGMENT"}),
    (200, "text/html", {}), (200, "application/json", {"error": "SYNTHETIC_PROVIDER_FRAGMENT"})])
async def test_non_contract_status_or_envelope_cannot_be_success(wire, status, ctype, payload):
    wire.queue = [(payload, status, ctype)]
    with pytest.raises(RuntimeError) as caught:
        await execute({"operation": "check_connection"})
    assert "SYNTHETIC_PROVIDER_FRAGMENT" not in str(caught.value)
    assert len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_refusal_is_safe_and_not_retried(wire, status):
    wire.queue = [({"message": "SYNTHETIC_PROVIDER_FRAGMENT"}, status, "application/json")]
    with pytest.raises(ValueError, match=f"HTTP {status}") as caught:
        await execute({"operation": "list_contacts"})
    assert "SYNTHETIC_PROVIDER_FRAGMENT" not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_empty_connect_uses_actual_collector_and_only_proves_reachability(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [page("fieldSchemas", [])]
    verdict = await cc.validate_for_connect(credential_type=v.FAMILY, credential_data=blob(), user_id=USER)
    assert verdict.ok and verdict.node_type == v.NODE_TYPE
    assert verdict.evidence.reachable is True
    assert v.VendastaNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.account_label is None and not verdict.evidence.samples


@pytest.mark.asyncio
async def test_update_uses_explicit_fields_mask_and_exact_readback(wire):
    wire.queue = [{"crmObjects": [record()]}, {"fieldSchemas": [schema()]}, {},
                  {"crmObjects": [record(fields=[{"fieldId": FIELD, "stringValue": "Changed"}])]}]
    out = await execute({"operation": "update_contact", "record_id": "fixture-contact",
        "effects_confirmed": True, "fields_json": json.dumps([{"fieldId": FIELD, "stringValue": "Changed"}])})
    write = wire.calls[2][2]["json"]
    assert write == {"namespace": "fixture-namespace", "crmObject": {"crmObjectId": "fixture-contact",
        "fields": [{"fieldId": FIELD, "stringValue": "Changed"}]}, "fieldMask": {"paths": ["fields." + FIELD]}}
    assert wire.calls[3][2]["json"]["fieldMask"] == {"paths": ["fields." + FIELD]}
    assert out["mutation_completed"] is True and out["record_id"] == "fixture-contact"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [({}, 403, "application/json"), httpx.ReadTimeout("synthetic-timeout")])
async def test_accepted_create_retains_id_when_readback_refused(wire, failure):
    wire.queue = [{"fieldSchemas": [schema()]}, {"crmObjectId": "created-fixture"}, failure]
    out = await execute({"operation": "create_contact", "effects_confirmed": True,
        "fields_json": json.dumps([{"fieldId": FIELD, "stringValue": "Fixture"}])})
    assert out["status"] == "error" and out["mutation_accepted"] is True
    assert out["record_id"] == "created-fixture" and out["readback_completed"] is False
    assert "idempotencyId" not in wire.calls[1][2]["json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field_change", [{"readonly": True}, {"fieldType": "FIELD_TYPE_CURRENCY"},
    {"externalId": "private_secret"}, {"fieldId": "wrong-id"}])
async def test_schema_write_denials_happen_before_mutation(wire, field_change):
    wire.queue = [{"crmObjects": [record()]}, {"fieldSchemas": [schema(**field_change)]}]
    with pytest.raises(ValueError):
        await execute({"operation": "update_contact", "record_id": "fixture-contact", "effects_confirmed": True,
            "fields_json": json.dumps([{"fieldId": FIELD, "stringValue": "Fixture"}])})
    assert len(wire.calls) == 2 and not any(c[1].endswith("/update") for c in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("op,before,after", [("soft_delete_contact", None, "2026-10-06T00:00:00Z"),
    ("restore_contact", "2026-10-06T00:00:00Z", v.ZERO_DATE)])
async def test_soft_delete_and_restore_read_deleted_state_without_erasure(wire, op, before, after):
    wire.queue = [{"crmObjects": [record(deleted=before)]}, {}, {"crmObjects": [record(deleted=after)]}]
    # Omitted protobuf timestamp and explicit zero timestamp mean active.
    if before is None: wire.queue[0]["crmObjects"][0].pop("deleted")
    out = await execute({"operation": op, "record_id": "fixture-contact", "effects_confirmed": True})
    assert out["mutation_completed"] is True and out["permanently_erased"] is False
    assert out["soft_deleted"] is op.startswith("soft_delete")
    assert wire.calls[-1][2]["json"]["projectionFilters"] == [{"filterType": "PROJECTION_FILTER_TYPE_INCLUDE_DELETED"}]


@pytest.mark.asyncio
async def test_association_requires_direction_status_and_both_scoped_record_witnesses(wire):
    row = {"associationId": "edge-one", "associationType": "Contact-Company", "fromId": "fixture-contact", "toId": "fixture-company"}
    wire.queue = [{"crmObjects": [record()]}, {**page("associations", [row]), "statusCode": ["200"]},
                  {"crmObjects": [record("fixture-company")]}]
    out = await execute({"operation": "list_associations", "association_type": "Contact-Company", "from_id": "fixture-contact"})
    assert out["records"] == [row]
    assert [call[1].split("/crm/")[1] for call in wire.calls] == ["contact/get-multi", "association/list", "company/get-multi"]
    assert wire.calls[1][2]["json"]["filtersV2"]["filters"][0]["fieldId"] == "association_type"


@pytest.mark.asyncio
async def test_picker_cursor_is_bound_to_search_and_namespace(wire):
    wire.queue = [page("crmObjects", [record()], True, "position")]
    out = await v.VendastaNode.load_field_options("record_id", blob(), {"operation": "get_contact"}, search="Fixture")
    assert out["options"] == [{"value": "fixture-contact", "label": "fixture-contact"}]
    with pytest.raises(ValueError, match="different query or namespace"):
        await v.VendastaNode.load_field_options("record_id", blob(namespace="other"), {"operation": "get_contact"}, page_token=out["next_page_token"], search="Fixture")
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_raw_family_scope_expiry_and_namespace_checks_make_zero_requests(wire):
    for change in ({"credential_type": "marketplace_api_key"}, {"scope": "crm.company:read"},
                   {"expires_at": "2000-01-01T00:00:00Z"}):
        with pytest.raises(ValueError): await execute({"operation": "list_contacts"}, blob(**change))
    with pytest.raises(ValueError):
        await v.request(blob(), "contact", "list", {"namespace": "other"})
    assert not wire.calls


def test_real_native_schema_and_manual_family_form_contract():
    schema_value = v.VendastaNode.get_config_schema()
    refs = schema_value["properties"]["config"].get("oneOf") or schema_value["properties"]["config"].get("anyOf")
    assert set(v.OPS) == {schema_value["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in refs}
    c = schema_value["$defs"]["VendastaAccessTokenCredential"]
    assert c["title"] == "Vendasta Access Token" and "x-credential-type" not in c
    assert c["properties"]["access_token"]["ui:widget"] == "password"
    assert {"environment", "namespace", "expires_at", "scope"} <= set(c["required"])
