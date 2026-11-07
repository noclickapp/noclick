"""Actual native seams with synthetic DB/transport boundaries; source, not a live pass."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000003"
WORKFLOW = "00000000-0000-4000-8000-000000000004"
RETURN = "00000000-0000-4000-8000-000000000006"
SURVEY = "00000000-0000-4000-8000-000000000007"
PLACE = "00000000-0000-4000-8000-000000000008"
ORDER = "order-external-fixture-42"
TOKEN = "NDEyMzpmaXh0dXJlLWFjY291bnQtdG9rZW4tMDQy"
FAMILY = "parcellab_api_token"
ACCOUNT = 4123
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


def order(**extra):
    return {"account": ACCOUNT, "external_id": ORDER, "order_number": "fixture-order-42",
        "client_key": "fixture-shop", "destination_country_iso3": "DEU", "recipient_email": "private@example.test",
        "recipient_name": "Private recipient", "shipping_address": {"address_line": "Private address"},
        "payment_method": "private-card", "api_token": TOKEN, **extra}


def return_row(**extra):
    return {"account": ACCOUNT, "external_id": RETURN, "reference": "fixture-order-42", "status": "submitted",
        "customer_email": "private@example.test", "return_labels": [{"label_url": "https://private.invalid"}], **extra}


def page(rows, next=None, **extra):
    return {"results": rows, "next": next, "previous": None, **extra}


@pytest.fixture
def native(monkeypatch):
    from nodes import parcellab_node as provider
    from nodes.core import credential_connect, connection_evidence
    from repositories.credentials import credential_access_predicate
    from repositories.organization import OrgRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credentials, encryption, credential_approval

    state = SimpleNamespace(blob={"api_token": TOKEN}, allowed={USER}, requests=[], constructors=[], replies={},
        after_read=None, sql=[], approval=None, row={"id": CID, "owner_id": USER, "credential_type": FAMILY,
        "credential": b"synthetic-encrypted", "token_version": 7, "updated_at": NOW, "created_at": NOW,
        "revoked_at": None, "approval_revision": 0, "name": "Fixture token", "metadata": {}})

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, sql, *args):
            state.sql.append((sql, args))
            assert credential_access_predicate() in sql
            return deepcopy(state.row) if args[0] == CID and args[1] in state.allowed else None

    state.pool = Pool()
    state.crypto = MagicMock()
    state.crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    monkeypatch.setattr(encryption, "get_encryption", lambda: state.crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: state.crypto)
    monkeypatch.setattr(OrgRepo, "get_primary_org_id", AsyncMock(return_value=None))
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=OWNER))
    state.workflow_grant = AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", state.workflow_grant)
    state.admit = AsyncMock(side_effect=lambda **_: state.approval)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", state.admit)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    credential_connect._class_index.cache_clear()

    def respond(request):
        state.requests.append(request)
        reply = state.replies.get((request.method, request.url.path))
        if reply is None and request.url.path == "/v4/track/orders/" and request.method == "GET":
            reply = (200, page([order()]))
        assert reply is not None, (request.method, request.url.path)
        if isinstance(reply, Exception):
            raise reply
        status, body, *headers = reply
        result = httpx.Response(status, json=body, headers=headers[0] if headers else {})
        if request.method == "GET" and state.after_read:
            callback, state.after_read = state.after_read, None
            callback()
        return result

    original_client = httpx.AsyncClient

    class LocalClient(original_client):
        def __init__(self, *args, **kwargs):
            state.constructors.append(dict(kwargs))
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(provider.httpx, "AsyncClient", LocalClient)

    async def run(operation, arguments=None, *, saved=False, blob=None, workflow_id=None):
        from nodes.core.run_op import run_node_operation
        return await run_node_operation(node_type="automation-parcellab", operation=operation,
            arguments=arguments or {}, user_id=USER, pool=state.pool, organization_id=None,
            credential_id=CID if saved else None, credential_data=blob or {"api_token": TOKEN} if not saved else None,
            workflow_id=workflow_id)

    state.run = run
    yield state
    credential_connect._class_index.cache_clear()


async def test_actual_factory_connect_and_private_order_evidence(native):
    from nodes.core.credential_connect import shape_credential, validate_for_connect
    from nodes.core.registry import NodeFactory
    from nodes.parcellab_node import ParcelLabNode
    shaped, errors, resolved = shape_credential(FAMILY, {"api_token": TOKEN})
    assert not errors and resolved[0] == "automation-parcellab" and shaped["api_token"] == TOKEN
    assert ParcelLabNode.get_config_schema()["properties"]["config"]["discriminator"]["propertyName"] == "operation"
    assert len(ParcelLabNode.get_config_schema()["properties"]["config"]["discriminator"]["mapping"]) == 18
    assert NodeFactory.is_registered("automation-parcellab")
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={"api_token": TOKEN}, user_id=USER, pool=native.pool)
    assert verdict.ok and verdict.evidence.reachable is True
    assert [sample.label for sample in verdict.evidence.samples] == ["fixture-order-42"]
    assert native.requests[0].headers["Authorization"] == "Parcellab-API-Token " + TOKEN
    assert not native.requests[0].url.params and native.requests[0].url.host == "api.parcellab.com"
    assert all(c["trust_env"] is False and c["follow_redirects"] is False for c in native.constructors)
    assert "private@example.test" not in json.dumps(verdict.verified_metadata())


@pytest.mark.parametrize("blob", [{"api_token": "not-encoded"}, {"api_token": None}, {},
    {"api_token": "Bearer " + TOKEN}, {"api_token": TOKEN, "region": "private.invalid"}])
async def test_invalid_tokens_and_regions_have_field_errors_before_probe(native, blob):
    from nodes.core.credential_connect import validate_for_connect
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=blob, user_id=USER)
    assert not verdict.ok and verdict.field_errors and native.requests == []


@pytest.mark.parametrize("tag", [None, "", " ", 9, "slack_oauth", " parcellab_api_token "])
def test_factory_and_validation_refuse_supplied_foreign_raw_family(native, tag):
    from nodes.core.base import ConfigValidationError
    from nodes.core.registry import NodeFactory
    from nodes.parcellab_node import ParcelLabNode
    raw = {"config": {"operation": "list_orders"}, "credentials": {"credential_type": tag, "api_token": TOKEN}}
    assert ParcelLabNode.validate_config(raw)["valid"] is False
    with pytest.raises(ConfigValidationError):
        NodeFactory.create_node("fixture", "automation-parcellab", raw, user_id=USER)
    assert native.requests == []




async def test_actual_dispatcher_row_authority_overrides_stale_blob_without_account_query(native):
    native.blob["credential_type"] = "slack_oauth"
    result = await native.run("list_orders", saved=True)
    assert result["status"] == "success" and result["data"]["items"][0]["external_id"] == ORDER
    assert len(native.sql) >= 3
    assert "private@example.test" not in json.dumps(result) and TOKEN not in json.dumps(result)
    assert list(native.requests[0].url.params) == []


@pytest.mark.parametrize("change", ["reconnect", "lost_access", "revoked", "foreign"])
async def test_current_row_change_after_parent_read_blocks_child_write(native, change):
    native.replies[("GET", "/v4/track/orders/" + ORDER + "/")] = (200, order())
    def mutate():
        if change == "reconnect":
            native.blob["region"] = "us"
        elif change == "lost_access":
            native.allowed.clear()
        elif change == "revoked":
            native.row["revoked_at"] = NOW
        else:
            native.row["credential_type"] = "slack_oauth"
    native.after_read = mutate
    result = await native.run("update_order_tags", {"order_id": ORDER, "tags": ["fixture:tag"], "confirm_order_write": True}, saved=True)
    assert result["status"] == "error" and len(native.requests) == 1
    assert TOKEN not in json.dumps(result)


async def test_actual_canonical_workflow_owner_fallback_requires_positive_grant(native):
    native.allowed = {OWNER}
    native.row["owner_id"] = OWNER
    result = await native.run("list_orders", saved=True, workflow_id=WORKFLOW)
    assert result["status"] == "success" and native.workflow_grant.await_count >= 1
    native.requests.clear()
    native.workflow_grant.return_value = False
    with pytest.raises(ValueError):
        await native.run("list_orders", saved=True, workflow_id=WORKFLOW)
    assert native.requests == []


async def test_stored_evidence_and_picker_pending_admission_prevents_provider(native):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core.run_op import run_node_lookup
    native.approval = {"status": "pending", "id": "fixture-review", "new_request": False}
    evidence = await collect_evidence(node_type="automation-parcellab", credential_id=CID, user_id=USER, pool=native.pool)
    assert evidence.reachable is None and evidence.samples == [] and native.requests == []
    picker = await run_node_lookup(node_type="automation-parcellab", field_name="order_id", credential_id=CID,
        user_id=USER, pool=native.pool, organization_id=None)
    assert picker["status"] == "pending_approval" and native.requests == []




async def test_bound_cursor_paging_never_follows_provider_url_directly(native):
    native.replies[("GET", "/v4/track/orders/")] = (200, page([order()], "https://api.parcellab.com/v4/track/orders/?cursor=next-fixture"))
    first = await native.run("list_orders")
    token = first["data"]["next_page_token"]
    native.replies[("GET", "/v4/track/orders/")] = (200, page([order(external_id="order-other-fixture")]))
    second = await native.run("list_orders", {"page_token": token})
    assert second["status"] == "success" and native.requests[-1].url.params["cursor"] == "next-fixture"
    before = len(native.requests)
    changed = await native.run("list_orders", {"page_token": token, "order_number": "different"})
    assert changed["status"] == "error" and len(native.requests) == before
    changed = await native.run("list_orders", {"page_token": token}, blob={"api_token": TOKEN, "region": "eu"})
    assert changed["status"] == "error" and len(native.requests) == before


@pytest.mark.parametrize("next_link", ["https://private.invalid/steal", "http://api.parcellab.com/v4/track/orders/?cursor=x",
    "https://api.parcellab.com/v2/track/orders/?cursor=x", "https://api.parcellab.com/v4/track/orders/?account=99&cursor=x",
    "https://api.parcellab.com/v4/track/orders/?cursor=x&cursor=y", "https://api.us.parcellab.com/v4/track/orders/?cursor=x"])
async def test_paging_rejects_host_version_account_and_duplicate_query_changes(native, next_link):
    native.replies[("GET", "/v4/track/orders/")] = (200, page([order()], next_link))
    result = await native.run("list_orders")
    assert result["status"] == "error" and len(native.requests) == 1


@pytest.mark.parametrize("body", [{"results": {}}, {"results": [order(account=99)]},
    {"results": [order(), order()]}, {"results": [order(external_id="../../steal")]},
    {"results": [order()], "count": True}])
async def test_malformed_or_cross_account_collections_do_not_verify(native, body):
    from nodes.core.credential_connect import validate_for_connect
    native.replies[("GET", "/v4/track/orders/")] = (200, body)
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={"api_token": TOKEN}, user_id=USER)
    assert verdict.evidence.reachable is None and verdict.verified_metadata() == {}


@pytest.mark.parametrize("status", [202, 204, 301, 400, 401, 403, 429, 500])
async def test_transport_error_status_and_secret_body_are_safe(native, status):
    native.replies[("GET", "/v4/track/orders/")] = (status, {"detail": TOKEN}, {"Retry-After": "7"})
    result = await native.run("list_orders")
    assert result["status"] == "error" and result["status_code"] == status
    assert result["retry_after"] == 7 and TOKEN not in json.dumps(result)
    assert len(native.requests) == 1


async def test_empty_account_has_no_synthetic_identity(native):
    from nodes.core.credential_connect import validate_for_connect
    native.replies[("GET", "/v4/track/orders/")] = (200, page([]))
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={"api_token": TOKEN}, user_id=USER)
    assert verdict.evidence.reachable is True and verdict.evidence.samples == []
    assert verdict.evidence.account_label is None and "verified_as" not in verdict.verified_metadata()


async def test_order_write_exact_body_status_and_failed_mutation_contract(native):
    native.replies[("POST", "/v4/track/orders/")] = (201, order())
    result = await native.run("create_order", {"order_number": "fixture-order-42", "destination_country_iso3": "DEU", "confirm_order_write": True})
    assert result["status"] == "success" and result["data"]["verified_readback"] is None
    body = json.loads(native.requests[-1].content)
    assert body == {"account": ACCOUNT, "order_number": "fixture-order-42", "destination_country_iso3": "DEU", "recipient_email": "_unset", "tags": []}
    native.replies[("GET", "/v4/track/orders/" + ORDER + "/")] = (200, order())
    native.replies[("PUT", "/v4/track/orders/")] = (200, order(mutations=[{"type": "add_tracking", "result": {"success": False, "message": TOKEN}}]))
    failed = await native.run("add_tracking", {"order_id": ORDER, "courier": "dhl", "tracking_number": "fixture-tracking", "confirm_order_write": True})
    assert failed["status"] == "error" and TOKEN not in json.dumps(failed)
    mutation = json.loads(native.requests[-1].content)["mutations"][0]
    assert mutation == {"type": "add_tracking", "tracking": {"courier": "dhl", "tracking_number": "fixture-tracking", "notifications_inactive": True}}


async def test_return_parent_status_privacy_and_offset_picker(native):
    native.replies[("GET", "/v4/returns/return-registrations/" + RETURN + "/")] = (200, return_row())
    native.replies[("GET", "/v4/returns/return-registrations/" + RETURN + "/status/")] = (200, {
        "return_status": "in_transit", "description": "private configured text", "labels_available": False,
        "cancellable": False, "retention_offer_applied": False, "refund_information": {"private": True}})
    result = await native.run("get_return_status", {"return_id": RETURN})
    assert result["data"]["return_status"] == "in_transit" and "refund_information" not in result["data"]
    assert "private" not in json.dumps(result)
    native.replies[("GET", "/v4/returns/returns-configurations/")] = (200, page([{"id": 7, "account": ACCOUNT, "code": "fixture-return"}], "https://api.parcellab.com/v4/returns/returns-configurations/?limit=50&offset=50", count=51))
    from nodes.parcellab_node import ParcelLabNode
    picker = await ParcelLabNode.load_field_options("configuration_id", {"api_token": TOKEN})
    assert picker["options"] == [{"value": "7", "label": "fixture-return"}]
    assert picker["next_page_token"]


async def test_survey_write_and_pudo_lookup_are_native_closed_routes(native):
    native.replies[("GET", "/v4/survey/survey/" + SURVEY + "/")] = (200, {"id": SURVEY, "name": "Fixture survey", "config": {"private": TOKEN}})
    native.replies[("POST", "/v4/survey/survey/" + SURVEY + "/answer/")] = (200, {"detail": "Saved", "isComplete": True})
    result = await native.run("submit_survey_response", {"survey_id": SURVEY, "reference_id": RETURN,
        "reference_type": "return_registration", "answers": {"rating": 5}, "confirm_survey_write": True})
    assert result["data"] == {"survey_id": SURVEY, "accepted": True, "is_complete": True, "verified_readback": None}
    assert json.loads(native.requests[-1].content) == {"reference_id": RETURN, "reference_type": "return_registration", "data": {"rating": 5}, "is_complete": True}
    native.replies[("POST", "/v4/track/place-info/lookup/")] = (200, [{"external_id": PLACE,
        "name": "Public pickup", "courier": "dhl", "country_iso3": "DEU", "location": {"latitude": 52.5, "longitude": 13.4},
        "location_address": {"address_line": "Public street", "postal_code": "10115", "city": "Berlin", "country_iso3": "DEU"}}])
    result = await native.run("find_pudo_locations", {"courier": "dhl", "country_iso3": "DEU", "latitude": 52.5, "longitude": 13.4})
    assert result["data"]["items"][0]["external_id"] == PLACE
    assert json.loads(native.requests[-1].content)["account"] == ACCOUNT
    assert all(request.url.path.startswith("/v4/") for request in native.requests)


@pytest.mark.parametrize("operation,arguments,route,body,params", [
    ("get_order", {"order_id": ORDER}, "/v4/track/orders/" + ORDER + "/", order(), {}),
    ("get_return", {"return_id": RETURN}, "/v4/returns/return-registrations/" + RETURN + "/", return_row(), {}),
    ("list_returns", {"reference": "fixture-order-42"}, "/v4/returns/return-registrations/",
        page([return_row()]), {"limit": "50", "reference": "fixture-order-42"}),
    ("list_return_configurations", {}, "/v4/returns/returns-configurations/",
        page([{"account": ACCOUNT, "id": 7, "code": "fixture-return"}], count=1), {"limit": "50"}),
    ("get_return_configuration", {"configuration_id": "7"}, "/v4/returns/returns-configurations/7/",
        {"account": ACCOUNT, "id": 7, "code": "fixture-return"}, {}),
    ("list_return_document_templates", {}, "/v4/returns/document-templates/",
        page([{"account": ACCOUNT, "id": 9, "key": "fixture-template", "content": "private template content"}], count=1), {"limit": "50"}),
    ("get_survey", {"survey_id": SURVEY}, "/v4/survey/survey/" + SURVEY + "/",
        {"id": SURVEY, "name": "Fixture survey", "config": {"private": TOKEN}, "surveyUrl": "https://private.invalid"}, {}),
    ("get_pudo_location", {"place_id": PLACE}, "/v4/track/place-info/" + PLACE + "/",
        {"name": "Public pickup", "courier": "dhl", "country_iso3": "DEU", "location": {"latitude": 52.5, "longitude": 13.4},
        "location_address": {"address_line": "Public street", "city": "Berlin"}}, {}),
])
async def test_other_native_reads_use_exact_routes_types_and_safe_projection(native, operation, arguments, route, body, params):
    native.replies[("GET", route)] = (200, body)
    result = await native.run(operation, arguments)
    assert result["status"] == "success"
    assert native.requests[-1].url.path == route and dict(native.requests[-1].url.params) == params
    assert "private" not in json.dumps(result).lower() and TOKEN not in json.dumps(result)
    if operation == "get_pudo_location":
        assert result["data"]["requested_place_id"] == PLACE and result["data"]["external_id"] is None


@pytest.mark.parametrize("operation,args", [
    ("get_order_status", {"order_number": "fixture-order-42", "client_key": "fixture-shop"}),
    ("get_tracking_status", {"courier": "dhl", "tracking_number": "fixture-tracking"}),
])
async def test_delivery_status_account_binding_and_private_fields_are_not_identity(native, operation, args):
    native.replies[("GET", "/v4/track/orders/info/")] = (200, {"order_number": "fixture-order-42",
        "recipient_email": "private@example.test", "recipient_name": "Private recipient", "trackings": [{
        "tracking_number": "fixture-tracking", "reporting_info": {"is_delayed": False, "delivery_date": "2026-10-06"},
        "delivery_location": "Private address", "proof_of_delivery": {"signature": "Private signature"},
        "last_delivery_status": {"step": "Delivered", "status_code": "delivered", "status_text": "Delivered"}}]})
    result = await native.run(operation, args)
    assert result["status"] == "success" and "private" not in json.dumps(result).lower()
    query = dict(native.requests[-1].url.params)
    assert query["account"] == str(ACCOUNT) and "live_refresh" not in query and "recipient_email" not in query
    if operation == "get_tracking_status":
        assert query["single_tracking"] == "true" and query["courier"] == "dhl"
    from nodes.parcellab_node import ParcelLabNode
    assert ParcelLabNode.connection_evidence.operation == "list_orders"


async def test_tag_replacement_confirms_owned_order_body_without_private_metadata(native):
    native.replies[("GET", "/v4/track/orders/" + ORDER + "/")] = (200, order())
    native.replies[("PUT", "/v4/track/orders/")] = (200, order(tags=["fixture:tag"]))
    result = await native.run("update_order_tags", {"order_id": ORDER, "tags": ["fixture:tag"], "confirm_order_write": True})
    assert result["status"] == "success" and result["data"]["verified_readback"] is None
    assert json.loads(native.requests[-1].content) == {"account": ACCOUNT, "order_number": "fixture-order-42", "client_key": "fixture-shop", "tags": ["fixture:tag"]}


async def test_prediction_contract_is_exact_and_explicit_failure_is_not_success(native):
    route = "/v4/promise/prediction/predict/"
    details = {"min": 1, "max": 2, "likely": 1, "send_date": "2026-10-06", "earliest_date": "2026-10-07",
        "latest_date": "2026-10-08", "most_likely_date": "2026-10-07", "cutoff": -10, "earliest_locale": "private locale"}
    prediction = {"id": "fixture-method", "warehouse": "fixture-warehouse", "courier": "dhl",
        "courier_name": "DHL", "global_courier_service_level": "standard", "prediction": details}
    native.replies[("GET", route)] = (200, {"request_id": "fixture-prediction", "success": True, "prediction": [prediction]})
    result = await native.run("predict_delivery", {"destination_country_iso3": "DEU"})
    assert result["status"] == "success" and result["data"]["predictions"][0]["prediction"]["cutoff"] == -10
    assert "private" not in json.dumps(result)
    assert dict(native.requests[-1].url.params) == {"account": str(ACCOUNT), "destination_country_iso3": "DEU", "calibration": "balanced"}
    native.replies[("GET", route)] = (200, {"request_id": "fixture-prediction", "success": False, "prediction": []})
    assert (await native.run("predict_delivery", {"destination_country_iso3": "DEU"}))["status"] == "error"


async def test_malformed_token_object_is_refused_without_provider(native):
    import base64
    token = base64.urlsafe_b64encode(b"[]").decode()
    assert (await native.run("list_orders", {"page_token": token}))["status"] == "error"
    assert native.requests == []


async def test_list_returns_supports_documented_pending_payment_filter(native):
    # https://api.parcellab.com/v4/openapi: return-registration status query enum.
    native.replies[("GET", "/v4/returns/return-registrations/")] = (200, page([]))
    result = await native.run("list_returns", {"return_status": "pending_payment"})
    assert result["status"] == "success" and result["data"]["items"] == []
    assert native.requests[-1].url.path == "/v4/returns/return-registrations/"
    assert dict(native.requests[-1].url.params) == {"limit": "50", "status": "pending_payment"}


def test_uuid_fields_publish_existing_runtime_constraint():
    from nodes.parcellab_node import ParcelLabNode
    definitions = ParcelLabNode.get_config_schema()["$defs"]
    for model, field in (("Return", "return_id"), ("ReturnStatus", "return_id"),
                         ("Place", "place_id"), ("Survey", "survey_id"),
                         ("SubmitSurvey", "survey_id")):
        assert definitions[model]["properties"][field]["format"] == "uuid"


async def test_freshen_refuses_changed_saved_connection(native):
    from nodes.parcellab_node import freshen
    native.blob["region"] = "us"
    with pytest.raises(ValueError, match="connection changed"):
        await freshen({"api_token": TOKEN}, pool=native.pool, user_id=USER, credential_id=CID)
    assert native.requests == []
