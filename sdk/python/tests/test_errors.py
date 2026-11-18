import pickle

import pytest

import noclick as nc
from noclick.exceptions import error_from_payload

SERVER_TYPES = {
    "invalid_request": (nc.InvalidRequest, 400),
    "unauthenticated": (nc.Unauthenticated, 401),
    "payment_required": (nc.PaymentRequired, 402),
    "plan_required": (nc.PlanRequired, 402),
    "price_exceeded": (nc.PriceExceeded, 402),
    "approval_required": (nc.ApprovalRequired, 402),
    "spend_cap_exceeded": (nc.SpendCapExceeded, 402),
    "spending_paused": (nc.SpendingPaused, 402),
    "permission_denied": (nc.PermissionDenied, 403),
    "policy_denied": (nc.PolicyDenied, 403),
    "not_found": (nc.NotFound, 404),
    "conflict": (nc.Conflict, 409),
    "not_available": (nc.NotAvailable, 409),
    "action_required": (nc.ActionRequired, 409),
    "needs_connection": (nc.NeedsConnection, 424),
    "credential_disconnected": (nc.CredentialDisconnected, 424),
    "quota_exceeded": (nc.QuotaExceeded, 429),
    "rate_limited": (nc.RateLimited, 429),
    "expired": (nc.Expired, 410),
    "upstream_error": (nc.UpstreamError, 503),
    "request_timeout": (nc.RequestTimeout, 503),
}


@pytest.mark.parametrize("type_,expected", SERVER_TYPES.items())
def test_every_server_type_maps_to_its_class(api, client, type_, expected):
    cls, status = expected
    api.get("/v1/users/t1").respond(status, json={"error": {
        "type": type_, "message": "nope", "next_step": "do the thing", "extra": 1,
    }})
    with pytest.raises(cls) as info:
        nc.User.get("t1")
    err = info.value
    assert isinstance(err, nc.Error)
    assert (err.type, err.message, err.next_step, err.status) == (type_, "nope", "do the thing", status)
    assert err.details == {"extra": 1} and err.extra == 1
    assert cls.http_status == status


def test_needs_connection_exposes_connect_url(api, client):
    api.post("/v1/connections/gmail/operations/send_email/run").respond(424, json={"error": {
        "type": "needs_connection", "message": "Connect Gmail first.",
        "next_step": "Send the user to connect_url.", "integration": "gmail",
        "connect_url": "https://noclick.com/c/abc",
    }})
    with pytest.raises(nc.NeedsConnection) as info:
        nc.Connection.from_name("gmail").run("send_email", {"to": "a@b.c"})
    assert info.value.connect_url == "https://noclick.com/c/abc"
    assert info.value.integration == "gmail"
    assert "Next step: Send the user" in str(info.value)


def test_a_refused_run_is_an_upstream_error_in_the_services_words_at_once(api, client):
    """A service's refusal answers 424, which the edge passes through and nothing retries: it used to be
    a 502, retried for minutes until a bare ServerError carrying the edge's page came back."""
    route = api.post("/v1/run").respond(424, json={"error": {
        "type": "upstream_error", "message": "Stripe refused stripe.list_charges (401): Invalid API Key provided.",
        "next_step": "Fix what the provider objected to, then retry.", "upstream_status": 401,
        "integration": "stripe", "operation": "list_charges",
    }})
    with pytest.raises(nc.UpstreamError) as info:
        nc.run("stripe.list_charges", {"limit": 3})
    err = info.value
    assert route.call_count == 1 and client.sleeps == []
    assert (err.status, err.upstream_status) == (424, 401) and "Invalid API Key" in err.message


@pytest.mark.parametrize("status", [503, 502])
def test_a_failed_service_is_an_upstream_error_once_retries_run_out(api, client, status):
    """It answers 503, which the edge passes through whole; the type decides the class whatever the status."""
    route = api.post("/v1/run").respond(status, json={"error": {
        "type": "upstream_error", "message": "Exa is unavailable right now.", "next_step": "Retry in a moment."}})
    with pytest.raises(nc.UpstreamError) as info:
        nc.run("exa.search", {"query": "x"})
    assert route.call_count == 3 and info.value.status == status and info.value.next_step == "Retry in a moment."


@pytest.mark.parametrize("status", [503, 504])
def test_a_timeout_is_request_timeout_naming_its_operation_and_isnt_retried(api, client, status):
    route = api.post("/v1/run").respond(status, headers={"x-should-retry": "false"}, json={"error": {
        "type": "request_timeout", "message": "The run is still going after 90 seconds.",
        "next_step": "Wait on the operation.", "operation_id": "op_1", "conversation": "c1"}})
    with pytest.raises(nc.RequestTimeout) as info:
        nc.run("exa.search", {"query": "x"})
    err = info.value
    assert route.call_count == 1 and client.sleeps == [] and isinstance(err, TimeoutError)
    assert (err.status, err.operation_id, err.conversation) == (status, "op_1", "c1")


def test_conflict_exposes_existing_id(api, client):
    api.post("/v1/users").respond(409, json={"error": {"type": "conflict", "message": "dup", "existing_id": "t9"}})
    with pytest.raises(nc.Conflict) as info:
        nc.User.create("user_42")
    assert info.value.existing_id == "t9"


def test_unknown_type_falls_back_by_status_and_keeps_type():
    err = error_from_payload({"error": {"type": "brand_new", "message": "m"}}, status=403)
    assert isinstance(err, nc.PermissionDenied) and err.type == "brand_new"
    err = error_from_payload({"error": {"type": "brand_new", "message": "m"}}, status=418)
    assert type(err) is nc.Error and err.type == "brand_new"


def test_non_json_5xx_is_server_error(api, client):
    api.get("/v1/users").respond(500, text="<html>oops</html>")
    with pytest.raises(nc.ServerError) as info:
        nc.User.list()
    assert info.value.status == 500 and "oops" in info.value.message


def test_request_id_is_kept(api, client):
    api.get("/v1/users/t1").respond(404, headers={"x-request-id": "req_1"},
                                      json={"error": {"type": "not_found", "message": "gone"}})
    with pytest.raises(nc.NotFound) as info:
        nc.User.get("t1")
    assert info.value.request_id == "req_1"


def test_errors_pickle():
    err = nc.NeedsConnection("m", next_step="n", details={"connect_url": "u"}, status=424)
    clone = pickle.loads(pickle.dumps(err))
    assert type(clone) is nc.NeedsConnection and clone.connect_url == "u" and clone.status == 424


def test_missing_attribute_raises_attribute_error():
    err = nc.Error("m", details={"present": 1})
    assert err.present == 1 and not hasattr(err, "absent")
