"""Exercise WellnessLiving's native factory and exact query/form boundaries.

Synthetic responses cover pagination, provider errors, manual credentials and
connection evidence without signing in to or changing a provider account.
"""
import json
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import wellnessliving_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-wellnessliving-jwt"
CREDENTIAL = {"credential_type": "wellnessliving_token", "access_token": TOKEN, "business_id": "business-42"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="wellnessliving-test", node_type="automation-wellnessliving",
                                   node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, body=None, status=200, content=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Golden cases retain provider field names. In particular, POST alone does not
# mean a field belongs in the body: the published contract distinguishes them.
CASES = [
    ({"operation": "list_clients"}, "GET", "/Wl/Login/Member/LoginMemberListAll.json", {"a_uid": ["client-1"]}),
    ({"operation": "get_client", "uid": "client-1"}, "GET", "/Wl/Login/Login.json", {"s_first_name": "Jane"}),
    ({"operation": "create_client", "text_firstname": "Jane", "text_lastname": "Doe", "text_mail": "jane@example.test"}, "POST", "/Wl/Profile/Edit/Create.json", {"uid": "client-1"}),
    ({"operation": "check_client_email", "s_mail": "jane@example.test"}, "POST", "/Wl/Lead/LeadCheck.json", {"is_member": True, "is_lead": False}),
    ({"operation": "get_client_id", "uid": "client-1"}, "GET", "/Wl/Login/Member/LoginMember.json", {"s_member": "M42"}),
    ({"operation": "set_client_id", "uid": "client-1", "s_member": "M42"}, "POST", "/Wl/Login/Member/LoginMember.json", {"dt_member": "2026-11-09T12:00:00Z"}),
    ({"operation": "list_groups"}, "GET", "/Wl/Member/Group/GroupList/List.json", {"a_member_group": [{"k_member_group": "group-1", "text_title": "Yoga members"}]}),
    ({"operation": "list_client_groups", "uid_user": "client-1"}, "GET", "/Wl/Member/Group/User/UserGroup.json", {"a_group_info": ["group-1"], "is_quick_group": False}),
    ({"operation": "add_client_to_group", "uid_user": "client-1", "k_member_group": "group-1"}, "POST", "/Wl/Member/Group/User/UserGroup.json", {"status": "ok"}),
    ({"operation": "remove_client_from_group", "uid_user": "client-1", "k_member_group": "group-1"}, "DELETE", "/Wl/Member/Group/User/UserGroup.json", {"status": "ok"}),
    ({"operation": "get_visit_count", "uid": "client-1"}, "GET", "/Wl/Visit/VisitTotalCount.json", {"i_visit_total": 17}),
    ({"operation": "get_visit_status", "k_visit": "visit-1"}, "GET", "/Wl/Visit/VisitStatus.json", {"id_visit": 1}),
    ({"operation": "update_visit_status", "k_visit": "visit-1", "id_visit": 3}, "POST", "/Wl/Visit/VisitStatus.json", {"status": "ok"}),
    ({"operation": "cancel_booking", "uid": "client-1", "k_appointment": "appointment-1", "dt_date": "2026-11-09T12:00:00Z"}, "POST", "/Wl/Schedule/Cancel.json", {"status": "ok"}),
    ({"operation": "list_promotions"}, "GET", "/Wl/Promotion/PromotionList.json", {"a_promotion": []}),
    ({"operation": "get_promotion", "k_promotion": "promotion-1"}, "GET", "/Wl/Promotion/Promotion.json", {"a_promotion": {"k_promotion": "promotion-1"}}),
    ({"operation": "get_subscriptions", "uid": "client-1"}, "GET", "/Wl/Business/User/Subscribe/Subscribe.json", {"is_subscribe": False, "is_subscribe_sms": False}),
    ({"operation": "update_subscriptions", "uid": "client-1", "is_subscribe": True, "is_subscribe_sms": False}, "PUT", "/Wl/Business/User/Subscribe/Subscribe.json", {"status": "ok"}),
    ({"operation": "list_staff_locations"}, "GET", "/Wl/Staff/Location/List.json", {"a_location": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_wellnessliving_operation_contract(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "us.wellnessliving.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-Error-Rules"] == "default"
    query, form = dict(request.url.params), parse_qs(request.content.decode(), keep_blank_values=True)
    if config["operation"] == "create_client":
        assert query == {}
        assert form == {"k_business": ["business-42"], "text_firstname": ["Jane"], "text_lastname": ["Doe"], "text_mail": ["jane@example.test"]}
    elif config["operation"] == "check_client_email":
        assert query == {} and form == {"k_business": ["business-42"], "s_mail": ["jane@example.test"]}
    else:
        assert query["k_business"] == "business-42"
    if config["operation"] in {"add_client_to_group", "remove_client_from_group"}:
        assert query == {"k_business": "business-42", "uid_user": "client-1"}
        assert form == {"k_member_group": ["group-1"]}
    if config["operation"] == "update_visit_status":
        assert query == {"k_business": "business-42", "k_visit": "visit-1", "is_charge_fee": "false", "text_reason": ""}
        assert form == {"id_mode": ["28"], "id_visit": ["3"], "is_mail": ["false"], "is_push": ["false"], "is_sms": ["false"]}
    if config["operation"] in {"set_client_id", "cancel_booking", "update_subscriptions"}:
        assert not request.content
    if method != "GET":
        assert result["write_acknowledged"] is True


@pytest.mark.asyncio
async def test_wellnessliving_client_cursor_and_business_override(monkeypatch):
    requests = transport(monkeypatch, {"a_uid": ["client-1", "client-2"]})
    result = await node({"operation": "list_clients", "i_page_size": 2, "k_business": "other-business"}).execute({})
    assert result["has_more"] and result["next_uid_last"] == "client-2"
    assert dict(requests[0].url.params) == {"k_business": "other-business", "i_page_size": "2", "uid_last": ""}
    requests = transport(monkeypatch, {"a_uid": []})
    result = await node({"operation": "list_clients", "uid_last": result["next_uid_last"]}).execute({})
    assert not result["has_more"] and result["next_uid_last"] is None
    assert requests[0].url.params["uid_last"] == "client-2"
    transport(monkeypatch, {"a_uid": ["client-2"]})
    with pytest.raises(ValueError, match="nonadvancing"):
        await node({"operation": "list_clients", "uid_last": "client-2"}).execute({})


@pytest.mark.asyncio
async def test_wellnessliving_au_origin_and_empty_write(monkeypatch):
    requests = transport(monkeypatch, content=b"")
    result = await node({"operation": "add_client_to_group", "uid_user": "client-1", "k_member_group": "quick"},
                        {**CREDENTIAL, "region": "au"}).execute({})
    assert requests[0].url.host == "au.wellnessliving.com"
    assert result["write_acknowledged"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Token expired"}), (403, {"message": "Access denied"}),
    (200, {"status": "access", "message": "Not allowed"}), (200, {"status": "ok", "a_error": {"field": "Invalid value"}})])
async def test_wellnessliving_errors_are_not_success_or_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status=status)
    with pytest.raises(ValueError):
        await node({"operation": "list_groups"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_wellnessliving_redacts_error_and_response_secrets(monkeypatch):
    transport(monkeypatch, {"message": "Rejected " + TOKEN}, status=401)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_groups"}).execute({})
    assert "Rejected" in str(exc.value) and TOKEN not in str(exc.value)
    transport(monkeypatch, {"a_member_group": [], "s_token": TOKEN, "message": TOKEN})
    result = await node({"operation": "list_groups"}).execute({})
    assert TOKEN not in json.dumps(result) and "s_token" not in result["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"a_member_group": None}])
async def test_wellnessliving_malformed_connection_response(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_groups"}).execute({})


def test_wellnessliving_manual_credential_and_fixed_origins():
    shaped = native.WellnessLivingTokenCredential.model_validate({"access_token": TOKEN, "business_id": " business-42 "})
    assert shaped.credential_type == "wellnessliving_token" and shaped.business_id == "business-42"
    for fields in ({"access_token": "Bearer " + TOKEN}, {"region": "evil.example.test"}, {"business_id": " "}, {"access_token": "https://example.test/token"}):
        with pytest.raises(ValidationError):
            native.WellnessLivingTokenCredential.model_validate({**CREDENTIAL, **fields})


@pytest.mark.asyncio
async def test_wellnessliving_connection_evidence_uses_account_groups(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    requests = transport(monkeypatch, {"a_member_group": [{"k_member_group": "group-1", "text_title": "Yoga members"}]})
    evidence = await collect_evidence(node_type="automation-wellnessliving", user_id="fixture-user", credential_data=CREDENTIAL)
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ["Yoga members"]
    assert len(requests) == 1 and requests[0].method == "GET"
