"""utils/media_generation.py: images are one OpenRouter call, stored as
account files and billed from the provider's cost; videos are priced from
OpenRouter's per-second SKUs before anything runs, gated on that projection,
and finished by the minute poll (real Postgres), which bills and wakes the
coordinator."""

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from billing import gates
from billing.gates import GateDenied
from billing.usage_tracker import usage_tracker
from utils import media_generation as media
from utils.media_generation import projected_video_dollars

USER = "22222222-2222-2222-2222-222222222222"

VEO_FAST = {"duration_seconds_with_audio": "0.12", "duration_seconds_with_audio_720p": "0.10",
            "duration_seconds_without_audio": "0.10"}
VEO_SPEC = {"id": "google/veo-3.1-fast", "pricing_skus": VEO_FAST, "supported_durations": [4, 6, 8],
            "supported_resolutions": ["720p", "1080p", "4K"], "supported_aspect_ratios": ["16:9", "9:16"],
            "generate_audio": True}
RUNWAY = {"cents_per_second_output": "28", "minimum_cents_per_generation": "56"}
SEEDANCE = {"video_tokens": "0.0000107"}
PNG = b"\x89PNG\r\n\x1a\nfake"


def test_a_clip_is_priced_from_the_sku_that_matches_it():
    assert projected_video_dollars(VEO_FAST, seconds=8, resolution="720p", audio=True) == Decimal("0.80")
    assert projected_video_dollars(VEO_FAST, seconds=8, resolution="1080p", audio=True) == Decimal("0.96")
    assert projected_video_dollars(VEO_FAST, seconds=4, resolution="1080p", audio=False) == Decimal("0.40")
    # Cents per second, with the provider's floor per generation.
    assert projected_video_dollars(RUNWAY, seconds=1, resolution="720p", audio=True) == Decimal("0.56")
    assert projected_video_dollars(RUNWAY, seconds=5, resolution="720p", audio=True) == Decimal("1.40")
    # Token-priced models can't be projected, so they're refused rather than guessed.
    assert projected_video_dollars(SEEDANCE, seconds=5, resolution="720p", audio=True) is None


@pytest.fixture
def seams(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    stored, billed = [], []

    async def store(**kw):
        stored.append(kw)
        return {"download_url": f"https://files.example/{kw['filename']}", "resource_id": str(uuid.uuid4())}

    async def track(event, sio=None, sid=None):
        billed.append(event)
    monkeypatch.setattr("utils.resource_store.create_resource_from_bytes", store)
    monkeypatch.setattr(usage_tracker, "track_usage_event", track)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(gates, "check_product", AsyncMock())
    media._pricing_cache.update(at=None, models={})
    return stored, billed


@respx.mock
async def test_an_image_is_stored_as_an_account_file_and_billed(seams):
    stored, billed = seams
    call = respx.post("https://openrouter.ai/api/v1/images").mock(return_value=httpx.Response(200, json={
        "created": 1, "data": [{"b64_json": "iVBORw0KGgpmYWtl", "media_type": "image/png"}],
        "usage": {"cost": 0.04, "total_tokens": 1200},
    }))
    made = await media.generate_image(None, user_id=USER, organization_id=None, prompt="a fern", aspect_ratio="16:9")
    sent = json.loads(call.calls.last.request.read())
    assert sent == {"model": "openai/gpt-image-2.5-sunburst", "prompt": "a fern", "n": 1, "aspect_ratio": "16:9"}
    assert made["images"][0]["url"] == "https://files.example/image-1.png"
    assert stored[0]["workflow_id"] is None and stored[0]["resource_type"] == "image" and stored[0]["body"] == PNG
    event = billed[0]
    assert event.user_id == USER and event.usage_subtype == "openai/gpt-image-2.5-sunburst"
    assert event.unit_type == "images" and event.total_cost >= Decimal("0.04") and event.user_resource is False
    gates.check_product.assert_awaited_once()


@respx.mock
async def test_a_refusal_or_an_empty_answer_is_said_plainly(seams):
    _, billed = seams
    route = respx.post("https://openrouter.ai/api/v1/images")
    route.mock(return_value=httpx.Response(400, json={"error": {"message": "prompt rejected by safety system"}}))
    with pytest.raises(media.MediaError, match="safety"):
        await media.generate_image(None, user_id=USER, organization_id=None, prompt="x")
    route.mock(return_value=httpx.Response(200, json={"data": [], "usage": {"cost": 0}}))
    with pytest.raises(media.MediaError, match="without an image"):
        await media.generate_image(None, user_id=USER, organization_id=None, prompt="x")
    assert billed == []


@respx.mock
async def test_a_video_is_refused_before_it_runs_when_it_cannot_be_afforded(seams):
    respx.get("https://openrouter.ai/api/v1/videos/models").mock(return_value=httpx.Response(200, json={
        "data": [VEO_SPEC, {"id": "bytedance/seedance-2.5", "pricing_skus": SEEDANCE}]}))
    submit = respx.post("https://openrouter.ai/api/v1/videos")
    gates.check_product.side_effect = GateDenied("credits", "Video generation needs 12 credits and the account has 3.0.")
    with pytest.raises(GateDenied):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves")
    projected = gates.check_product.await_args.kwargs["projected_credits"]
    assert projected == media.dollars_as_credits(Decimal("0.80"), "google/veo-3.1-fast")
    with pytest.raises(media.MediaError, match="priced"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", model="bytedance/seedance-2.5")
    # A request outside the model's published limits is refused with what it supports.
    with pytest.raises(media.MediaError, match="durations .* 4, 6, 8; not 5"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", seconds=5)
    with pytest.raises(media.MediaError, match="aspect ratios 16:9, 9:16; not 1:1"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", aspect_ratio="1:1")
    assert not submit.called


@pytest.fixture
async def media_db(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs,
    )
    user_id = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    try:
        yield pool, user_id
    finally:
        await pool.close()


@respx.mock
async def test_a_finished_video_is_stored_billed_once_and_wakes_the_coordinator(seams, media_db, monkeypatch):
    stored, billed = seams
    pool, user_id = media_db
    dispatched = []
    monkeypatch.setattr("utils.coordinator_dispatch.dispatch_event", AsyncMock(side_effect=lambda p, e: dispatched.append(e)))
    respx.get("https://openrouter.ai/api/v1/videos/models").mock(return_value=httpx.Response(200, json={
        "data": [VEO_SPEC]}))
    respx.post("https://openrouter.ai/api/v1/videos").mock(return_value=httpx.Response(202, json={
        "id": "vid-1", "status": "pending", "polling_url": "https://openrouter.ai/api/v1/videos/vid-1"}))
    status = respx.get("https://openrouter.ai/api/v1/videos/vid-1").mock(
        return_value=httpx.Response(200, json={"id": "vid-1", "status": "processing"}))
    respx.get("https://openrouter.ai/api/v1/videos/vid-1/content").mock(
        return_value=httpx.Response(200, content=b"mp4bytes", headers={"content-type": "video/mp4"}))
    continuation = {"epoch": "", "depth": 0, "request": "make a clip", "channel": "whatsapp_text", "turn_id": "t1"}

    job = await media.start_video(pool, user_id=user_id, organization_id=None, prompt="waves at dusk",
                                  continuation=continuation)
    await media.poll_video_jobs(pool)  # still rendering: nothing billed or woken
    assert billed == [] and dispatched == []

    status.mock(return_value=httpx.Response(200, json={"id": "vid-1", "status": "completed", "usage": {"cost": 0.8}}))
    await media.poll_video_jobs(pool)
    await media.poll_video_jobs(pool)  # a finished job is never billed twice
    row = await pool.fetchrow("SELECT kind, status, result FROM coordinator_jobs WHERE id = $1::uuid", job["job_id"])
    assert row["kind"] == "video" and row["status"] == "completed" and row["result"]["cost_usd"] == 0.8
    assert row["result"]["url"] == "https://files.example/video.mp4"
    assert len(billed) == 1 and billed[0].unit_type == "seconds" and stored[0]["resource_type"] == "video"

    wakeup = await pool.fetchrow("SELECT source, context, payload, send_to_phone FROM coordinator_wakeups "
                                 "WHERE source_id = $1::uuid", job["job_id"])
    assert wakeup["source"] == "job" and wakeup["send_to_phone"] is True and wakeup["payload"]["kind"] == "video"
    assert wakeup["context"]["request"] == "make a clip" and wakeup["payload"]["result"]["url"].endswith("video.mp4")
    assert len(dispatched) == 1




def test_image_counts_are_a_billable_unit():
    # Imagen and Kling image handlers bill per image; the event must validate
    # (a rejected event is only logged, so an invalid unit meant no charge).
    from billing.schema import UsageEventData

    event = UsageEventData(user_id=USER, total_cost=Decimal("0.08"), usage_type="ai_usage",
                           usage_subtype="imagen-4", quantity=Decimal(1), unit_type="images")
    assert event.unit_type == "images"
