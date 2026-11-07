"""Zenoti factory, dispatcher, picker and current-credential fixtures.

All credentials, rows and provider responses are synthetic; no E2E claim.
"""
import asyncio
import base64
import json
import socket
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import zenoti_node as zn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

C = "00000000-0000-4000-8000-000000000001"
G = "00000000-0000-4000-8000-000000000002"
S = "00000000-0000-4000-8000-000000000003"
E = "00000000-0000-4000-8000-000000000004"
OTHER = "00000000-0000-4000-8000-000000000005"
CREDS = {"credential_type": zn.FAMILIES[0], "api_key": "synthetic+/=zenoti-key"}
BEARER = {"credential_type": zn.FAMILIES[1], "access_token": "synthetic-user-token", "expires_at": "2099-01-01T00:00:00Z"}
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)
CENTER = {"id": C, "name": "Owned center", "code": "Center code", "phone": "Private", "email": "omit@example.invalid"}
SERVICE = {"id": S, "name": "Owned service", "duration": 30, "price_info": {"sale_price": 99}}
EMPLOYEE = {"id": E, "code": "Private", "personal_info": {"first_name": "Omit"}, "job_info": {"id": OTHER, "name": "Omit"}}
GUEST = {"id": G, "center_id": C, "code": "CRM-1", "preferred_service_id": S,
         "personal_info": {"first_name": "Omit", "email": "omit@example.invalid"},
         "address_info": {"street": "Omit"}, "preferences": {"receive_marketing_email": False},
         "tags": None, "referral": None, "primary_employee": None,
         "deposit_applicability": {"amount": 99}}
APPOINTMENT = {"appointment_group_id": OTHER, "center_id": C, "notes": "Omit", "invoice_id": OTHER,
               "price": {"final": 99}, "is_rebooking": False,
               "appointment_services": [{"appointment_id": E, "start_time": "2026-10-06T10:00:00", "appointment_status": 0, "service": SERVICE, "requested_therapist_id": E}]}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


class Response:
    def __init__(self, payload=None, *, status=200, raw=None, content_type="application/json"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.raw = raw if raw is not None else json.dumps(payload).encode()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw


def page(kind, rows, *, number=1, size=10, total=None, verified=True):
    return {kind: rows, **({"page_info": {"total": len(rows) if total is None else total, "page": number, "size": size}} if verified else {}), "error": None}


@pytest.fixture
def wire(monkeypatch):
    responses, calls = [], []
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(zn, "guarded_async_client", client)
    return SimpleNamespace(responses=responses, calls=calls)


async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=zn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)


def test_actual_factory_union_scope_and_original_family_guard():
    schema = zn.ZenotiNode.get_config_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 13
    for creds in (CREDS, BEARER):
        good = {"config": {"operation": "list_centers", "page": "1", "size": "10"}, "credentials": creds}
        node = NodeFactory.create_node(node_id="n", node_type=zn.NODE_TYPE, node_data=good, user_id="actor")
        assert node.config.config.page == 1 and node.config.config.size == 10
        assert node.config.credentials.credential_type == creds["credential_type"]
        for family in ("zenoti_oauth", "mailshake_api_key", None):
            bad_creds = {**creds, "credential_type": family}
            if family is None:
                bad_creds.pop("credential_type")
            bad = {**good, "credentials": bad_creds, "credential_id": "saved"}
            assert zn.ZenotiNode.validate_config(bad)["valid"] is False
            with pytest.raises(ValueError, match="family"):
                NodeFactory.create_node(node_id="n", node_type=zn.NODE_TYPE, node_data=bad, user_id="actor")
    untagged = {"config": {"operation": "check_api_access"}, "credentials": {"api_key": "synthetic-key"}}
    assert zn.ZenotiNode.parse_config(untagged).credentials.credential_type == zn.FAMILIES[0]
    with pytest.raises(ValueError):
        zn.ZenotiNode.parse_config({**untagged, "credentials": {"api_key": "synthetic-key", "access_token": "ambiguous"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("creds,prefix", [(CREDS, "apikey "), (BEARER, "bearer ")])
async def test_exact_auth_protected_access_and_conservative_evidence(monkeypatch, wire, creds, prefix):
    wire.responses.append(Response(page("centers", [], size=1)))
    result = await run("check_api_access", {"operation": "update_guest_crm_metadata"}, credential_data=creds)
    proof = result["data"]
    assert proof["protected_read_completed"] and not proof["account_identity_verified"] and not proof["write_permission_verified"]
    call = wire.calls[0]
    assert call["method"] == "GET" and call["url"] == zn.BASE + "/v1/centers" and call["params"] == {"Page": 1, "Size": 1}
    assert call["headers"]["Authorization"] == prefix + zn._secret(creds)
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    monkeypatch.setattr(run_op, "run_node_operation", AsyncMock(return_value=result))
    evidence = await collect_evidence(node_type=zn.NODE_TYPE, credential_data=creds, user_id="actor")
    assert evidence.reachable is True and zn.ZenotiNode.connection_evidence.proves == "reachability" and evidence.account_label is None and evidence.samples == []


@pytest.mark.asyncio
async def test_expired_token_and_invalid_config_fail_before_transport(wire):
    for creds in ({**BEARER, "expires_at": "2000-01-01T00:00:00Z"}, {**BEARER, "expires_at": "2099-01-01"}, {**CREDS, "api_key": "apikey key"}, {**CREDS, "api_key": "key\nvalue"}):
        with pytest.raises(ValueError):
            await run("check_api_access", credential_data=creds)
    for op, args in [("create_appointment", {}), ("list_centers", {"size": True}), ("list_centers", {"size": 101}), ("get_guest", {"center_id": C, "guest_id": "../guests"}), ("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": "new"}), ("list_guest_appointments", {"center_id": C, "guest_id": G, "start_date": "2026-10-31", "end_date": "2026-10-01"}), ("list_guest_appointments", {"center_id": C, "guest_id": G, "start_date": "2026-01-01", "end_date": "2026-03-01"})]:
        with pytest.raises(ValueError):
            await run(op, args)
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,route,kind,row", [
    ("list_centers", {}, "/v1/centers", "centers", CENTER),
    ("list_center_services", {"center_id": C}, "/v1/Centers/" + C + "/services", "services", SERVICE),
    ("list_center_employees", {"center_id": C}, "/v1/centers/" + C + "/employees", "employees", EMPLOYEE),
    ("list_center_guests", {"center_id": C, "last_updated": "2026-10-01"}, "/v1/guests", "guests", GUEST),
])
async def test_exact_native_lists_paging_and_private_output(wire, op, args, route, kind, row):
    wire.responses.append(Response(page(kind, [row])))
    got = await run(op, args)
    assert got["data"]["pagination_verified"] and got["data"]["next_page"] is None
    call = wire.calls[-1]
    assert call["url"] == zn.BASE + route and call["method"] == "GET"
    assert (call["params"].get("Page"), call["params"].get("Size")) == (1, 10) if op == "list_centers" else (call["params"].get("page"), call["params"].get("size")) == (1, 10)
    if op == "list_center_guests":
        assert call["params"]["center_id"] == C and call["params"]["last_updated"] == "2026-10-01"
    for private in ("Omit", "example.invalid", "personal_info", "preferences", "deposit_applicability", "price_info", "email", "phone"):
        assert private not in json.dumps(got)


@pytest.mark.asyncio
async def test_direct_resource_envelopes_and_org_metadata_do_not_invent_identity(wire):
    wire.responses.extend([Response({"center": CENTER}), Response({"org_name": "Owned business", "account_name": "Private", "security": "Omit"}), Response({"auto_generate_code": True, "guest_form_type": 0, "marketing_preferences": "Omit"}), Response(SERVICE), Response(GUEST), Response(page("employees", [EMPLOYEE], size=25))])
    assert (await run("get_center", {"center_id": C}))["data"]["id"] == C
    organization = (await run("get_organization_metadata"))["data"]
    settings = (await run("get_guest_configuration"))["data"]
    assert organization["metadata"] == {"org_name": "Owned business"} and not organization["account_identity_verified"]
    assert settings["metadata"] == {"auto_generate_code": True, "guest_form_type": 0}
    assert (await run("get_service", {"center_id": C, "service_id": S}))["data"]["service"]["id"] == S
    assert (await run("get_guest", {"center_id": C, "guest_id": G}))["data"]["id"] == G
    assert (await run("get_center_employee", {"center_id": C, "employee_id": E}))["data"]["employee"] == {"id": E, "job_info": {"id": OTHER}}
    assert "Omit" not in json.dumps(organization) + json.dumps(settings)


@pytest.mark.asyncio
async def test_appointments_require_guest_center_and_closed_metadata(wire):
    wire.responses.extend([Response(GUEST), Response(page("appointments", [APPOINTMENT]))])
    result = await run("list_guest_appointments", {"center_id": C, "guest_id": G, "start_date": "2026-10-01", "end_date": "2026-10-31"})
    assert wire.calls[-1]["params"] == {"page": 1, "size": 10, "start_date": "2026-10-01", "end_date": "2026-10-31"}
    assert result["data"]["results"][0]["appointment_services"][0]["appointment_status"] == 0
    for private in ("notes", "invoice", "price", "requested_therapist", "Omit"):
        assert private not in json.dumps(result)
    wire.responses.extend([Response({**GUEST, "center_id": OTHER})])
    with pytest.raises(zn.ZenotiAPIError, match="selected center"):
        await run("list_guest_appointments", {"center_id": C, "guest_id": G, "start_date": "2026-10-01", "end_date": "2026-10-02"})
    assert len(wire.calls) == 3


@pytest.mark.asyncio
async def test_full_profile_crm_roundtrip_preserves_nonchanges_and_separate_readback(wire):
    response = {**GUEST, "code": "CRM-2", "preferred_service_id": S}
    wire.responses.extend([Response(GUEST), Response(SERVICE), Response(response)])
    got = await run("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": "CRM-2", "preferred_service_id": S, "confirm_update": True})
    call = wire.calls[-1]
    assert call["method"] == "PUT" and call["url"] == zn.BASE + "/v1/guests/" + G
    assert call["json"] == response and "params" not in call
    assert call["json"]["personal_info"] == GUEST["personal_info"] and call["json"]["preferences"] == GUEST["preferences"]
    assert got["data"]["returned_changes_verified"] and not got["data"]["independent_readback_verified"] and not got["data"]["notification_behavior_verified"]
    assert "Omit" not in json.dumps(got) and "deposit" not in json.dumps(got)
    wire.responses.extend([Response(GUEST), Response(GUEST)])
    # Dispatcher blank normalization is exercised with a real preferred-service update.
    wire.responses[-1] = Response(SERVICE)
    wire.responses.append(Response(GUEST))
    got = await run("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": "", "preferred_service_id": S, "confirm_update": True})
    assert wire.calls[-1]["json"]["code"] == "CRM-1" and got["data"]["accepted"]


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [{k: v for k, v in GUEST.items() if k != "preferences"}, {**GUEST, "login_info": {"password": "never-send"}}, {**GUEST, "id": OTHER}, {**GUEST, "center_id": OTHER}])
async def test_update_snapshot_or_scope_mismatch_stops_before_put(wire, snapshot):
    wire.responses.extend([Response(snapshot)])
    with pytest.raises(ValueError):
        await run("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": "new", "confirm_update": True})
    assert len(wire.calls) == 1 and all(c["method"] == "GET" for c in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [Response({"error": {"code": 401, "message": CREDS["api_key"]}}), Response({**GUEST, "status": "rejected"}), Response({**GUEST, "id": OTHER}), Response({}), Response(GUEST, status=202), Response(GUEST, content_type="text/html"), Response(raw=b""), Response(raw=b'{"id":"x","value":NaN}'), Response(raw=b'{"value":1e309}'), Response(raw=b'[' * 2000 + b']' * 2000)])
async def test_write_error_uncertainty_safe_messages_and_no_replay(wire, response):
    wire.responses.extend([Response(GUEST), response])
    with pytest.raises(zn.ZenotiAPIError, match="[Ww]rite outcome") as caught:
        await run("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": "CRM-2", "confirm_update": True})
    assert len(wire.calls) == 2 and CREDS["api_key"] not in str(caught.value) and "Omit" not in str(caught.value)


@pytest.mark.asyncio
async def test_missing_paging_does_not_claim_complete_absence_or_picker_success(wire):
    wire.responses.extend([Response(page("guests", [], verified=False))])
    result = await run("list_center_guests", {"center_id": C})
    assert not result["data"]["pagination_verified"] and result["data"]["possible_more"] and result["data"]["next_page"] is None
    wire.responses.extend([Response({"center": CENTER}), Response(page("employees", [EMPLOYEE], verified=False))])
    with pytest.raises(ValueError, match="page_info"):
        await zn.ZenotiNode.load_field_options("employee_id", CREDS, context={"center_id": C, "_user_id": "actor"})
    wire.responses.extend([Response(page("employees", [], verified=False))])
    with pytest.raises(ValueError, match="absence"):
        await run("get_center_employee", {"center_id": C, "employee_id": E})


@pytest.mark.asyncio
async def test_picker_token_current_scope_privacy_repeat_and_cap(wire):
    rows = [{**CENTER, "id": str(__import__('uuid').UUID(int=i + 1))} for i in range(25)]
    wire.responses.append(Response(page("centers", rows, size=25, total=26)))
    first = await zn.ZenotiNode.load_field_options("center_id", CREDS, context={"_user_id": "actor"})
    assert first["options"][0]["label"] == "Center " + rows[0]["id"] and "Owned center" not in json.dumps(first)
    for creds, actor in [(CREDS, "other"), ({**CREDS, "api_key": "rotated"}, "actor")]:
        with pytest.raises(ValueError, match="continuation"):
            await zn.ZenotiNode.load_field_options("center_id", creds, context={"_user_id": actor}, page_token=first["next_page_token"])
    wire.responses.append(Response(page("centers", [rows[0]], number=2, size=25, total=26)))
    with pytest.raises(zn.ZenotiAPIError, match="repeats"):
        await zn.ZenotiNode.load_field_options("center_id", CREDS, context={"_user_id": "actor"}, page_token=first["next_page_token"])
    saved = json.loads(base64.urlsafe_b64decode(first["next_page_token"] + "=" * (-len(first["next_page_token"]) % 4)))
    saved.update(page=40, seen=[])
    cursor = base64.urlsafe_b64encode(json.dumps(saved).encode()).decode().rstrip("=")
    wire.responses.append(Response(page("centers", rows, number=40, size=25, total=1001)))
    with pytest.raises(ValueError, match="1,000-record"):
        await zn.ZenotiNode.load_field_options("center_id", CREDS, context={"_user_id": "actor"}, page_token=cursor)
    assert len(wire.calls) == 3


@pytest.mark.asyncio
async def test_saved_credential_resolution_uses_staging_owner_fallback(monkeypatch):
    from utils import credentials
    resolver = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolver)
    pool = object()
    got = await zn._current_data(CREDS, credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="flow")
    assert got["api_key"] == CREDS["api_key"]
    resolver.assert_awaited_once_with("saved", "actor", pool, org_id="org", workflow_id="flow")
    for value in (None, {**CREDS, "credential_type": "other"}):
        resolver.return_value = value
        with pytest.raises(ValueError, match="unavailable"):
            await zn._current_data(CREDS, credential_id="saved", user_id="actor", pool=pool, organization_id="org")


@pytest.mark.asyncio
async def test_credential_probe_tristate(wire):
    wire.responses.append(Response(page("centers", [], size=1)))
    assert await zn.ZenotiNode.validate_credential_access(CREDS) == (True, None)
    wire.responses.append(Response({}, status=401))
    assert (await zn.ZenotiNode.validate_credential_access(CREDS))[0] is False
    wire.responses.append(Response({}, status=503))
    assert (await zn.ZenotiNode.validate_credential_access(CREDS))[0] is None


@pytest.mark.asyncio
async def test_rotation_between_profile_and_put_and_serialized_bound_stop_before_write(monkeypatch, wire):
    wire.responses.extend([Response(GUEST)])
    monkeypatch.setattr(zn, "_current_data", AsyncMock(side_effect=[CREDS, CREDS, {**CREDS, "token_version": 9}]))
    with pytest.raises(ValueError, match="changed"):
        await run("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": "new", "confirm_update": True})
    assert len(wire.calls) == 1
    monkeypatch.setattr(zn, "_current_data", AsyncMock(return_value=CREDS))
    wire.responses.extend([Response(GUEST)])
    # Response profile fits its response cap; the body grows beyond it on mutation.
    new_code = "x" * 80
    monkeypatch.setattr(zn, "MAX_BYTES", len(json.dumps(GUEST).encode()) + 1)
    with pytest.raises(ValueError, match="request bound"):
        await run("update_guest_crm_metadata", {"center_id": C, "guest_id": G, "guest_code": new_code, "confirm_update": True})
    assert len(wire.calls) == 2 and all(c["method"] == "GET" for c in wire.calls)


@pytest.mark.asyncio
async def test_redaction_opaque_status_and_json_bounds(monkeypatch, wire):
    wire.responses.append(Response(page("centers", [{**CENTER, "name": "synthetic%2b%2F%3dzenoti-key", "status": {"future": True}}])))
    assert (await run("list_centers"))["data"]["results"][0]["name"] == "[redacted]"
    nested = {}
    for _ in range(34):
        nested = {"nested": nested}
    wire.responses.append(Response({"centers": [], "meta": nested}))
    with pytest.raises(zn.ZenotiAPIError, match="JSON"):
        await run("list_centers")


def documented(name):
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures" / "zenoti" / (name + ".json")).read_text())["body"]


@pytest.mark.asyncio
async def test_documented_guest_empty_service_preference(wire):
    guest = documented("guest")
    wire.responses.append(Response(guest))
    got = await run("get_guest", {"guest_id": guest["id"], "center_id": guest["center_id"]})
    assert got["data"]["id"] == guest["id"]
    assert "preferred_service_id" not in got["data"]
    assert "personal_info" not in got["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,section", [("get_organization_metadata", "general"), ("get_guest_configuration", "guest")])
async def test_documented_organization_envelope(wire, operation, section):
    settings = documented("settings")
    wire.responses.append(Response(settings))
    got = await run(operation)
    assert got["data"]["section"] == section
    assert got["data"]["metadata"]
    assert "payment" not in got["data"]["metadata"]


@pytest.mark.asyncio
async def test_documented_services_preserve_metadata_without_price_info(wire):
    body = documented("services")
    wire.responses.append(Response(body))
    got = await run("list_center_services", {"center_id": C, "size": body["page_info"]["size"]})
    assert got["data"]["results"][0]["id"] == body["services"][0]["id"]
    assert "price_info" not in json.dumps(got)


@pytest.mark.asyncio
async def test_documented_guest_appointments_include_other_centers(wire):
    guest, appointments = documented("guest"), documented("appointments")
    wire.responses.extend([Response(guest), Response(appointments)])
    got = await run("list_guest_appointments", {"guest_id": guest["id"], "center_id": guest["center_id"], "start_date": "2019-08-29", "end_date": "2019-08-29"})
    assert got["data"]["results"][0]["center_id"] == appointments["appointments"][0]["center_id"]
    assert got["data"]["results"][0]["center_id"] != guest["center_id"]
    assert "invoice_id" not in json.dumps(got)
