"""Starting a WhatsApp QR scan, against WAHooks faked at its HTTP boundary.

The real ``wahooks`` SDK talks to a respx-mocked WAHooks API whose answers are
the API's own (``apps/api/src/connections/connections.controller.ts``):
get-or-create answers ``{id, status, qr}`` and, when its own ~20s poll found no
QR, ``{status: "pending", qr: null}`` ("fetch it separately"); ``GET
/connections/{id}/qr`` answers ``{value, mimetype}``, ``{connected: true}``, 503
while the session's worker starts, 404 for a connection it doesn't have;
``POST /connections`` answers the new connection with no QR.

Before: a pending answer was a failure with nothing logged, every fetched QR was
read from a ``qr`` key the API never sends (so a fresh connection and a
re-scan never produced one), and the connection the failed start was handed
stayed behind, stuck, for the next start to be handed again.
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
from utils.whatsapp_qr import start_qr_connection

pytestmark = pytest.mark.asyncio

API = "https://api.wahooks.com/api"
STARTING = httpx.Response(503, json={"statusCode": 503, "message": "Worker is starting up, please wait"})


def _qr(value):
    return httpx.Response(200, json={"value": value, "mimetype": "image/png"})


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
    result = await _start(postgres_db)
    assert result["success"] is True and result["connection_id"] == "conn-idle" and result["qr_code"] == "QR-IDLE"


async def test_a_pending_answer_is_waited_out_until_the_qr_comes(postgres_db, fake_redis, funded_owner, wahooks):
    wahooks.post("/connections/get-or-create").mock(
        return_value=httpx.Response(201, json={"id": "conn-new", "status": "pending", "qr": None}))
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


async def test_a_reconnect_waits_for_its_reset_session_to_show_a_qr(postgres_db, fake_redis, wahooks):
    """Re-scanning a credential's own connection: WAHooks resets a failed session
    on the QR fetch and answers 503 until it shows one; no new connection is made."""
    owner = await _seed_binding(postgres_db, "conn-own")
    credential_id = await postgres_db.fetchval(
        "SELECT id FROM credentials WHERE metadata->>'connection_id' = 'conn-own'")
    wahooks.get("/connections/conn-own/qr").mock(side_effect=[STARTING, _qr("QR-OWN")])
    get_or_create = wahooks.post("/connections/get-or-create")
    try:
        result = await _start(postgres_db, str(owner), reconnect_credential_id=str(credential_id))
    finally:
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")
    assert result["success"] is True and result["reconnect"] is True
    assert result["connection_id"] == "conn-own" and result["qr_code"] == "QR-OWN"
    assert get_or_create.call_count == 0
