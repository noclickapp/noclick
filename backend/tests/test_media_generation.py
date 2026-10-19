"""utils/media_generation.py: images are one OpenRouter call, stored as
account files and billed from the provider's cost; videos are priced from
OpenRouter's per-second SKUs before anything runs, gated on that projection,
and finished by the minute poll (real Postgres), which bills and wakes the
coordinator."""

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from billing import gates
from billing.gates import GateDenied
from billing.usage_tracker import usage_tracker
from utils import media_generation as media
from utils.media_generation import projected_video_dollars
from tests.mocks.mock_asyncpg import MockNativePool

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
        return {"download_url": f"https://files.example/{kw['filename']}", "resource_id": str(uuid.uuid4()),
                "storage_ref": f"{kw['user_id']}/account/{kw['filename']}"}

    async def track(event, sio=None, sid=None):
        billed.append(event)
    monkeypatch.setattr("utils.resource_store.create_resource_from_bytes", store)
    monkeypatch.setattr(usage_tracker, "track_usage_event", track)
    # The payer bills as its caller priced it (Free/Member pricing: cloud/tests/test_free_member_postgres.py).
    monkeypatch.setattr(usage_tracker, "quote", AsyncMock(side_effect=lambda event: event.total_cost))
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
    made = await media.generate_image(None, user_id=USER, organization_id="org-1", prompt="a fern", aspect_ratio="16:9")
    sent = json.loads(call.calls.last.request.read())
    assert sent == {"model": "openai/gpt-image-2.5-sunburst", "prompt": "a fern", "n": 1, "aspect_ratio": "16:9"}
    assert made["images"][0]["url"] == "https://files.example/image-1.png"
    assert stored[0]["workflow_id"] is None and stored[0]["resource_type"] == "image" and stored[0]["body"] == PNG
    event = billed[0]
    assert event.user_id == USER and event.usage_subtype == "openai/gpt-image-2.5-sunburst"
    assert event.unit_type == "images" and event.total_cost >= Decimal("0.04") and event.user_resource is False
    gates.check_product.assert_awaited_once()
    # Judged on the account that pays: the organization's owner, its monthly cap included.
    assert gates.check_product.await_args.kwargs["organization_id"] == "org-1"


@respx.mock
@pytest.mark.parametrize("found", [True, False])
async def test_an_image_whose_answer_carries_no_cost_is_priced_from_openrouters_record(seams, monkeypatch, found):
    from utils.openrouter_cost import CostUnknown

    _, billed = seams
    lookup = AsyncMock(return_value=Decimal("0.05")) if found else AsyncMock(side_effect=CostUnknown("none"))
    monkeypatch.setattr("utils.openrouter_cost.generation_cost", lookup)
    monkeypatch.setattr(usage_tracker, "_impl", SimpleNamespace())  # a platform that charges for usage
    respx.post("https://openrouter.ai/api/v1/images").mock(return_value=httpx.Response(200, json={
        "id": "gen-img", "data": [{"b64_json": "iVBORw0KGgpmYWtl", "media_type": "image/png"}], "usage": {}}))
    made = await media.generate_image(None, user_id=USER, organization_id=None, prompt="a fern")
    lookup.assert_awaited_once_with("gen-img")
    if found:
        assert billed[0].cost_usd == Decimal("0.05") and made["cost_usd"] == float(billed[0].total_cost)
    else:
        # Priced nowhere: logged, never charged as $0.
        assert billed == [] and made["cost_usd"] is None and made["images"]


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
    from billing.markup import apply_openrouter_markup, dollars_to_credits
    assert projected == float(dollars_to_credits(apply_openrouter_markup(Decimal("0.80"), False, "google/veo-3.1-fast")))
    # ... and priced for the account that pays: the quote is asked for the payer's price of the clip.
    assert usage_tracker.quote.await_args.args[0].cost_usd == Decimal("0.80")
    with pytest.raises(media.MediaError, match="priced"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", model="bytedance/seedance-2.5")
    # A request outside the model's published limits is refused with what it supports.
    with pytest.raises(media.MediaError, match="durations .* 4, 6, 8; not 5"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", seconds=5)
    with pytest.raises(media.MediaError, match="aspect ratios 16:9, 9:16; not 1:1"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", aspect_ratio="1:1")
    # A model that can't start from an image says so, and an id OpenRouter doesn't list names the default.
    with pytest.raises(media.MediaError, match="can't start from an image"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", first_frame="data:x")
    with pytest.raises(media.MediaError, match="isn't an OpenRouter video model .*google/veo-3.1-fast"):
        await media.start_video(None, user_id=USER, organization_id=None, prompt="waves", model="veo-3")
    assert not submit.called


@respx.mock
async def test_unset_settings_fit_the_model_and_the_request_carries_what_was_asked(seams):
    # A model without 8s or 720p (MiniMax's Hailuo) still runs on its defaults: the nearest duration, its first resolution.
    hailuo = {"id": "minimax/hailuo-2.3", "pricing_skus": {"duration_seconds": "0.0817"}, "supported_durations": [6, 10],
              "supported_resolutions": ["1080p"], "supported_frame_images": ["first_frame"], "generate_audio": False}
    respx.get("https://openrouter.ai/api/v1/videos/models").mock(return_value=httpx.Response(200, json={
        "data": [hailuo]}))
    submit = respx.post("https://openrouter.ai/api/v1/videos").mock(return_value=httpx.Response(202, json={
        "id": "gen-vid-1", "status": "pending"}))
    pool = MockNativePool({"INSERT INTO coordinator_jobs": "job-1"})

    job = await media.start_video(pool, user_id=USER, organization_id="org-1", prompt="waves", model="openrouter/minimax/hailuo-2.3",
                                  first_frame="data:image/png;base64,iVBORw0KGgo=", source="agent_node",
                                  workflow_id="wf-1", node_id="agent-1",
                                  provider_options={"minimax": {"parameters": {"prompt_optimizer": False}}})
    assert (job["seconds"], job["resolution"]) == (6, "1080p")
    assert json.loads(submit.calls.last.request.read()) == {
        "model": "minimax/hailuo-2.3", "prompt": "waves", "duration": 6, "resolution": "1080p", "generate_audio": False,
        "frame_images": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                          "frame_type": "first_frame"}],
        "provider": {"options": {"minimax": {"parameters": {"prompt_optimizer": False}}}}}
    # The ledger row names who started it and keeps the file's workflow; the gate read the org's payer.
    insert = pool.fetchval.await_args.args
    assert insert[3] == {"source": "agent_node"} and insert[6:] == ("wf-1", "agent-1")
    assert gates.check_product.await_args.kwargs["organization_id"] == "org-1"


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


@respx.mock
async def test_a_finished_video_that_reports_no_cost_is_charged_its_projection(seams, media_db, monkeypatch):
    stored, billed = seams
    pool, user_id = media_db
    monkeypatch.setattr("utils.coordinator_dispatch.dispatch_event", AsyncMock())
    models = respx.get("https://openrouter.ai/api/v1/videos/models").mock(return_value=httpx.Response(200, json={
        "data": [VEO_SPEC]}))
    respx.post("https://openrouter.ai/api/v1/videos").mock(return_value=httpx.Response(202, json={"id": "vid-2"}))
    respx.get("https://openrouter.ai/api/v1/videos/vid-2").mock(
        return_value=httpx.Response(200, json={"id": "vid-2", "status": "completed"}))
    respx.get("https://openrouter.ai/api/v1/videos/vid-2/content").mock(
        return_value=httpx.Response(200, content=b"mp4bytes", headers={"content-type": "video/mp4"}))

    job = await media.start_video(pool, user_id=user_id, organization_id=None, prompt="waves")
    spec = await pool.fetchval("SELECT spec FROM coordinator_jobs WHERE id = $1::uuid", job["job_id"])
    # Its price list is gone by the time it finishes: the projection made when it was submitted is charged.
    models.mock(return_value=httpx.Response(503))
    media._pricing_cache.update(at=None, models={})
    await media.poll_video_jobs(pool)

    [event] = billed
    assert event.cost_usd == Decimal(spec["projected_usd"]) > 0




def test_image_counts_are_a_billable_unit():
    # Imagen and Kling image handlers bill per image; the event must validate
    # (a rejected event is only logged, so an invalid unit meant no charge).
    from billing.schema import UsageEventData

    event = UsageEventData(user_id=USER, total_cost=Decimal("0.08"), usage_type="ai_usage",
                           usage_subtype="imagen-4", quantity=Decimal(1), unit_type="images")
    assert event.unit_type == "images"
