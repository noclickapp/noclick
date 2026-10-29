"""Starting a WhatsApp QR scan, against WAHooks faked at its HTTP boundary.

The real ``wahooks`` SDK talks to a respx-mocked WAHooks API whose answers are
the API's own (``apps/api/src/connections/connections.controller.ts``):
get-or-create answers ``{id, status, qr}`` and, when its own ~20s poll found no
QR, ``{status: "pending", qr: null}`` ("fetch it separately"); ``GET
/connections/{id}/qr`` answers ``{value, mimetype}``, ``{connected: true}``, 503
while the session's worker starts, 404 for a connection it doesn't have;
``GET /connections/{id}`` answers the row (``status`` scan_qr / pending /
failed / connected / stopped = deleted, ``phoneNumber`` once a phone linked);
``POST /connections/{id}/restart`` fully resets a session to scan_qr;
``POST /connections`` answers the new connection with no QR.

Before: a pending answer was a failure with nothing logged, every fetched QR was
read from a ``qr`` key the API never sends (so a fresh connection and a
re-scan never produced one), and the connection the failed start was handed
stayed behind, stuck, for the next start to be handed again.

Then: an unscanned session WAHooks recycles cycles QR → (nobody scans) FAILED →
health-cron restart → QR …, and a QR asked of it mid-restart gets WAHA's 422.
A Retry came back to that same session (still reserved, still "shown") and hit
the same failed window again, so the error screen never recovered.
"""
import logging
import uuid

import httpx
import pytest
import respx

import utils.whatsapp_qr as whatsapp_qr
from tests.test_whatsapp_qr_bind_guard import (  # noqa: F401 (fixtures)
    _PoolShim,
    _seed_binding,
    fake_redis,
    funded_owner,
)
from utils.whatsapp_qr import finalize_qr_connection, start_qr_connection

pytestmark = pytest.mark.asyncio

API = "https://api.wahooks.com/api"
STARTING = httpx.Response(503, json={"statusCode": 503, "message": "Worker is starting up, please wait"})
# WAHA's answer to a QR asked of a session that isn't showing one (mid-restart).
NOT_AS_EXPECTED = httpx.Response(422, json={
    "statusCode": 422, "message": "Session status is not as expected. Try again later or restart the session"})


def _qr(value):
    return httpx.Response(200, json={"value": value, "mimetype": "image/png"})


def _row(connection_id, status, phone=None):
    return httpx.Response(200, json={"id": connection_id, "status": status, "phoneNumber": phone})


@pytest.fixture
def wahooks(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "wh_test")
    monkeypatch.setattr(whatsapp_qr, "QR_POLL_S", 0.01)
    with respx.mock(base_url=API, assert_all_called=False) as api:
        yield api


async def _start(postgres_db, owner=None, **kwargs):
    return await start_qr_connection(_PoolShim(postgres_db), owner_id=owner or str(uuid.uuid4()), **kwargs)


async def test_a_waiting_qr_comes_back_at_once(postgres_db, fake_redis, funded_owner, wahooks):
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-idle", "status": "scan_qr", "qr": "QR-IDLE"}))
    wahooks.get("/connections/conn-idle").mock(return_value=_row("conn-idle", "scan_qr"))
    qr = wahooks.get("/connections/conn-idle/qr")
    result = await _start(postgres_db)
    assert result["success"] is True and result["connection_id"] == "conn-idle" and result["qr_code"] == "QR-IDLE"
    assert qr.call_count == 0


async def test_a_pending_answer_is_waited_out_until_the_qr_comes(postgres_db, fake_redis, funded_owner, wahooks):
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-new", "status": "pending", "qr": None}))
    wahooks.get("/connections/conn-new").mock(return_value=_row("conn-new", "pending"))
    qr = wahooks.get("/connections/conn-new/qr").mock(side_effect=[STARTING, STARTING, _qr("QR-NEW")])
    result = await _start(postgres_db)
    assert result["success"] is True and result["connection_id"] == "conn-new" and result["qr_code"] == "QR-NEW"
    assert qr.call_count == 3


async def test_a_fresh_connection_reads_its_qr(postgres_db, fake_redis, funded_owner, wahooks):
    # The idle connection is another owner's: a fresh one is made, which comes with no QR of its own.
    await _seed_binding(postgres_db, "conn-theirs")
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-theirs", "status": "scan_qr", "qr": "QR-THEIRS"}))
    wahooks.post("/connections").mock(
        return_value=httpx.Response(201, json={"id": "conn-fresh", "status": "scan_qr", "sessionName": "u_1_s_2"}))
    wahooks.get("/connections/conn-fresh/qr").mock(side_effect=[STARTING, _qr("QR-FRESH")])
    try:
        result = await _start(postgres_db)
    finally:
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")
    assert result["success"] is True and result["connection_id"] == "conn-fresh" and result["qr_code"] == "QR-FRESH"


async def test_no_qr_in_time_says_why_logs_it_and_deletes_the_connection(
        postgres_db, fake_redis, funded_owner, wahooks, monkeypatch, caplog):
    monkeypatch.setattr(whatsapp_qr, "QR_WAIT_S", 0.1)
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-stuck", "status": "pending", "qr": None}))
    wahooks.get("/connections/conn-stuck").mock(return_value=_row("conn-stuck", "pending"))
    wahooks.get("/connections/conn-stuck/qr").mock(return_value=STARTING)
    deleted = wahooks.delete("/connections/conn-stuck").mock(return_value=httpx.Response(200, json={}))
    with caplog.at_level(logging.WARNING, logger="utils.whatsapp_qr"):
        result = await _start(postgres_db)
    assert result == {"success": False, "message": whatsapp_qr.NO_QR_MESSAGE}
    assert "try again" in result["message"]
    [record] = [r for r in caplog.records if "No QR" in r.getMessage()]
    assert "conn-stuck" in record.getMessage() and "Worker is starting up" in record.getMessage()
    # Never handed to the next start: it's gone.
    assert deleted.call_count == 1


async def test_a_connection_a_credential_binds_is_never_deleted(postgres_db, fake_redis, funded_owner, wahooks,
                                                               monkeypatch):
    monkeypatch.setattr(whatsapp_qr, "QR_WAIT_S", 0.05)
    owner = await _seed_binding(postgres_db, "conn-mine")
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-mine", "status": "pending", "qr": None}))
    wahooks.get("/connections/conn-mine").mock(return_value=_row("conn-mine", "pending"))
    wahooks.get("/connections/conn-mine/qr").mock(return_value=STARTING)
    deleted = wahooks.delete("/connections/conn-mine").mock(return_value=httpx.Response(200, json={}))
    try:
        result = await _start(postgres_db, str(owner))
    finally:
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")
    assert result["success"] is False and deleted.call_count == 0


async def test_wahooks_not_answering_is_a_failure_with_its_reason(postgres_db, fake_redis, funded_owner, wahooks,
                                                                 caplog):
    wahooks.post("/connections/get-or-create").mock(side_effect=httpx.ReadTimeout("timed out"))
    with caplog.at_level(logging.WARNING, logger="utils.whatsapp_qr"):
        result = await _start(postgres_db)
    assert result == {"success": False, "message": whatsapp_qr.NO_QR_MESSAGE}
    assert any("ReadTimeout" in r.getMessage() for r in caplog.records)


async def test_a_second_start_shows_the_first_starts_qr_without_resetting_it(postgres_db, fake_redis, funded_owner,
                                                                            wahooks):
    """A page that starts twice (two renders, a retry) must not reset the
    session the first start is showing: WAHooks' get-or-create resets the idle
    session it hands out, so the second start reads the first's QR instead."""
    owner = str(uuid.uuid4())
    get_or_create = wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-shown", "status": "scan_qr", "qr": "QR-1"}))
    wahooks.get("/connections/conn-shown").mock(return_value=_row("conn-shown", "scan_qr"))
    wahooks.get("/connections/conn-shown/qr").mock(return_value=_qr("QR-2"))
    first = await _start(postgres_db, owner)
    second = await _start(postgres_db, owner)
    assert first["connection_id"] == second["connection_id"] == "conn-shown"
    assert second["qr_code"] == "QR-2" and get_or_create.call_count == 1
    # Another owner handed the same idle connection is given one of their own.
    wahooks.post("/connections").mock(return_value=httpx.Response(201, json={"id": "conn-other", "status": "scan_qr"}))
    wahooks.get("/connections/conn-other/qr").mock(return_value=_qr("QR-OTHER"))
    third = await _start(postgres_db)
    assert third["connection_id"] == "conn-other" and third["qr_code"] == "QR-OTHER"


async def test_a_reconnect_restarts_its_failed_session_then_waits_for_its_qr(postgres_db, fake_redis, wahooks):
    """Re-scanning a credential's own connection: its failed session is
    restarted first (a QR fetch alone resets it only when it happens to land
    on FAILED), then waited on; no new connection is made. The phone on it is
    the owner's own, so it doesn't bar the re-scan."""
    owner = await _seed_binding(postgres_db, "conn-own")
    credential_id = await postgres_db.fetchval(
        "SELECT id FROM credentials WHERE metadata->>'connection_id' = 'conn-own'")
    calls = []
    wahooks.get("/connections/conn-own").mock(return_value=_row("conn-own", "failed", phone="12025550105"))
    wahooks.post("/connections/conn-own/restart").mock(
        side_effect=lambda request: calls.append("restart") or _row("conn-own", "scan_qr"))
    answers = iter([NOT_AS_EXPECTED, STARTING, _qr("QR-OWN")])
    wahooks.get("/connections/conn-own/qr").mock(side_effect=lambda request: calls.append("qr") or next(answers))
    get_or_create = wahooks.post("/connections/get-or-create")
    try:
        result = await _start(postgres_db, str(owner), reconnect_credential_id=str(credential_id))
    finally:
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")
    assert result["success"] is True and result["reconnect"] is True
    assert result["connection_id"] == "conn-own" and result["qr_code"] == "QR-OWN"
    assert calls == ["restart", "qr", "qr", "qr"]
    assert get_or_create.call_count == 0


async def test_a_failed_recycled_connection_is_restarted_before_its_qr_is_shown(
        postgres_db, fake_redis, funded_owner, wahooks):
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-failed", "status": "pending", "qr": None}))
    wahooks.get("/connections/conn-failed").mock(return_value=_row("conn-failed", "failed"))
    restart = wahooks.post("/connections/conn-failed/restart").mock(return_value=_row("conn-failed", "scan_qr"))
    wahooks.get("/connections/conn-failed/qr").mock(side_effect=[STARTING, _qr("QR-FRESH-CYCLE")])
    result = await _start(postgres_db)
    assert result["success"] is True and result["qr_code"] == "QR-FRESH-CYCLE"
    assert restart.call_count == 1


async def test_a_422_from_a_session_mid_restart_is_waited_out(postgres_db, fake_redis, funded_owner, wahooks):
    """WAHA refuses the QR with 422 while the session restarts; that is a
    session still coming up, not a failed start."""
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-cycling", "status": "pending", "qr": None}))
    wahooks.get("/connections/conn-cycling").mock(return_value=_row("conn-cycling", "scan_qr"))
    qr = wahooks.get("/connections/conn-cycling/qr").mock(
        side_effect=[NOT_AS_EXPECTED, NOT_AS_EXPECTED, STARTING, _qr("QR-CYCLING")])
    deleted = wahooks.delete("/connections/conn-cycling")
    result = await _start(postgres_db)
    assert result["success"] is True and result["qr_code"] == "QR-CYCLING"
    assert qr.call_count == 4 and deleted.call_count == 0


async def test_get_or_create_tripping_on_a_session_mid_restart_mints_a_fresh_connection(
        postgres_db, fake_redis, funded_owner, wahooks):
    """WAHooks' own reset of the idle session it picked can hit WAHA's 422 and
    answer 400; asking it again would pick that same session."""
    wahooks.post("/connections/get-or-create").mock(return_value=httpx.Response(400, json={
        "statusCode": 400,
        "message": "WAHA API error: POST /api/sessions/start returned 422 - Session status is not as expected"}))
    wahooks.post("/connections").mock(return_value=httpx.Response(201, json={"id": "conn-fresh", "status": "pending"}))
    wahooks.get("/connections/conn-fresh/qr").mock(side_effect=[STARTING, _qr("QR-FRESH")])
    result = await _start(postgres_db)
    assert result["success"] is True and result["connection_id"] == "conn-fresh" and result["qr_code"] == "QR-FRESH"


async def test_get_or_create_refusing_the_account_is_an_honest_failure(postgres_db, fake_redis, funded_owner,
                                                                       wahooks):
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(403, json={"statusCode": 403, "message": "Set up billing before creating"}))
    created = wahooks.post("/connections")
    result = await _start(postgres_db)
    assert result == {"success": False, "message": whatsapp_qr.NO_QR_MESSAGE}
    assert created.call_count == 0


async def _failed_first_scan(postgres_db, wahooks, owner):
    """A first start shows conn-a's QR; nobody scans it and its session fails."""
    wahooks.post("/connections/get-or-create").mock(side_effect=[
        httpx.Response(201, json={"id": "conn-a", "status": "scan_qr", "qr": "QR-A"}),
        httpx.Response(201, json={"id": "conn-b", "status": "scan_qr", "qr": "QR-B"}),
    ])
    conn_a = wahooks.get("/connections/conn-a").mock(return_value=_row("conn-a", "scan_qr"))
    wahooks.get("/connections/conn-b").mock(return_value=_row("conn-b", "scan_qr"))
    first = await _start(postgres_db, owner)
    assert first["connection_id"] == "conn-a" and first["qr_code"] == "QR-A"
    conn_a.mock(return_value=_row("conn-a", "failed"))
    return {
        "qr_a": wahooks.get("/connections/conn-a/qr"),
        "restart_a": wahooks.post("/connections/conn-a/restart"),
        "deleted_a": wahooks.delete("/connections/conn-a").mock(return_value=httpx.Response(200, json={})),
    }


async def test_a_retry_after_the_status_poll_saw_the_scan_fail_starts_on_another_connection(
        postgres_db, fake_redis, funded_owner, wahooks):
    owner = str(uuid.uuid4())
    routes = await _failed_first_scan(postgres_db, wahooks, owner)

    poll = await finalize_qr_connection(
        _PoolShim(postgres_db), owner_id=owner, connection_id="conn-a", user_tier="free", encryption=None)
    assert poll["success"] is False and poll["status"] == "error"
    # Let go of and deleted, so nothing hands it out again.
    assert routes["deleted_a"].call_count == 1
    assert fake_redis.store.get("whatsapp:qr:reserved:conn-a") is None
    assert fake_redis.store.get(f"whatsapp:qr:shown:{owner}") is None

    retry = await _start(postgres_db, owner)
    assert retry["success"] is True and retry["connection_id"] == "conn-b" and retry["qr_code"] == "QR-B"
    assert routes["qr_a"].call_count == 0 and routes["restart_a"].call_count == 0


async def test_a_retry_never_reshows_a_connection_whose_session_failed(postgres_db, fake_redis, funded_owner,
                                                                       wahooks):
    """The page gave up on its own (its poll window ran out) before any poll saw
    the failure: the Retry still lets that connection go instead of re-showing it."""
    owner = str(uuid.uuid4())
    routes = await _failed_first_scan(postgres_db, wahooks, owner)

    retry = await _start(postgres_db, owner)
    assert retry["success"] is True and retry["connection_id"] == "conn-b" and retry["qr_code"] == "QR-B"
    assert routes["qr_a"].call_count == 0 and routes["restart_a"].call_count == 0
    assert routes["deleted_a"].call_count == 1
    assert fake_redis.store.get("whatsapp:qr:reserved:conn-a") is None
    assert fake_redis.store[f"whatsapp:qr:shown:{owner}"] == b"conn-b"


@pytest.mark.parametrize("status,phone", [("scan_qr", "15550100001"), ("failed", "15550100001"), ("connected", None)])
async def test_a_recycled_connection_holding_a_whatsapp_login_is_never_shown(
        postgres_db, fake_redis, funded_owner, wahooks, status, phone):
    """Security: a reused session that carries someone's WhatsApp login (a phone
    number on it, or connected) must never reach another owner, neither as a QR
    nor as a credential: a fresh connection is minted, the recycled one is let
    go untouched, and finalize refuses to bind it for this owner."""
    owner = str(uuid.uuid4())
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-linked", "status": "scan_qr", "qr": "QR-LINKED"}))
    row = wahooks.get("/connections/conn-linked").mock(return_value=_row("conn-linked", status, phone))
    restart = wahooks.post("/connections/conn-linked/restart")
    linked_qr = wahooks.get("/connections/conn-linked/qr")
    deleted = wahooks.delete("/connections/conn-linked")
    wahooks.post("/connections").mock(return_value=httpx.Response(201, json={"id": "conn-fresh", "status": "pending"}))
    wahooks.get("/connections/conn-fresh/qr").mock(return_value=_qr("QR-FRESH"))

    result = await _start(postgres_db, owner)

    assert result["success"] is True and result["connection_id"] == "conn-fresh" and result["qr_code"] == "QR-FRESH"
    assert "QR-LINKED" not in str(result)
    assert restart.call_count == linked_qr.call_count == deleted.call_count == 0
    assert fake_redis.store.get("whatsapp:qr:reserved:conn-linked") is None

    row.mock(return_value=_row("conn-linked", "connected", "15550100001"))
    bind = await finalize_qr_connection(
        _PoolShim(postgres_db), owner_id=owner, connection_id="conn-linked", user_tier="free", encryption=None)
    assert bind["success"] is False and "credential_id" not in bind
    assert await postgres_db.fetchval(
        "SELECT count(*) FROM credentials WHERE metadata->>'connection_id' = 'conn-linked'") == 0


async def test_a_recycled_session_that_comes_up_logged_in_is_never_bound(
        postgres_db, fake_redis, funded_owner, wahooks):
    """No one was shown its QR after WAHooks reset it, so a recycled session
    that reports a linked phone while it is waited on carries someone else's
    login (an auth that survived the reset)."""
    owner = str(uuid.uuid4())
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-revived", "status": "pending", "qr": None}))
    wahooks.get("/connections/conn-revived").mock(return_value=_row("conn-revived", "pending"))
    wahooks.get("/connections/conn-revived/qr").mock(side_effect=[STARTING, httpx.Response(200, json={"connected": True})])
    wahooks.post("/connections").mock(return_value=httpx.Response(201, json={"id": "conn-fresh", "status": "pending"}))
    wahooks.get("/connections/conn-fresh/qr").mock(return_value=_qr("QR-FRESH"))

    result = await _start(postgres_db, owner)

    assert result["success"] is True and result["connection_id"] == "conn-fresh"
    assert fake_redis.store.get("whatsapp:qr:reserved:conn-revived") is None


async def test_the_status_poll_hands_the_page_the_current_qr(postgres_db, fake_redis, funded_owner, wahooks):
    """WhatsApp rotates the linking code while it waits; the poll carries the
    current one to the page showing it, and to no one else."""
    owner = str(uuid.uuid4())
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-live", "status": "scan_qr", "qr": "QR-1"}))
    wahooks.get("/connections/conn-live").mock(return_value=_row("conn-live", "scan_qr"))
    qr = wahooks.get("/connections/conn-live/qr").mock(return_value=_qr("QR-2"))
    await _start(postgres_db, owner)

    poll = await finalize_qr_connection(
        _PoolShim(postgres_db), owner_id=owner, connection_id="conn-live", user_tier="free", encryption=None)
    assert poll == {"success": True, "status": "pending", "message": "Waiting for QR code scan...", "qr_code": "QR-2"}

    stranger = await finalize_qr_connection(
        _PoolShim(postgres_db), owner_id=str(uuid.uuid4()), connection_id="conn-live", user_tier="free",
        encryption=None)
    assert stranger["status"] == "pending" and "qr_code" not in stranger
    assert qr.call_count == 1


async def test_the_socket_status_reply_carries_the_current_qr(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    import wss.handlers.oauth.whatsapp_qr_handler as handler_module
    from wss.receiver.client_events import WhatsAppQRStatusRequest

    monkeypatch.setattr(handler_module, "get_encryption", MagicMock())
    monkeypatch.setattr(handler_module, "finalize_qr_connection", AsyncMock(return_value={
        "success": True, "status": "pending", "message": "Waiting for QR code scan...", "qr_code": "QR-2"}))
    sent = AsyncMock()
    monkeypatch.setattr(handler_module, "send_event", sent)
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    handler = handler_module.WhatsAppQRHandler(sio)
    handler.get_pool = AsyncMock(return_value=object())

    await handler.check_status("sid-1", WhatsAppQRStatusRequest(request_id="r1", connection_id="conn-live"))

    reply = sent.await_args.args[2].data
    assert reply["status"] == "pending" and reply["qr_code"] == "QR-2"
