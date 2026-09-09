"""HTTP-level regression coverage for bounded, metered Apify runs."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.apify_runner import ApifyRunnerMixin


@pytest.fixture
def runner(monkeypatch):
    node = ApifyRunnerMixin()
    node.emit = AsyncMock()
    node._check_credits_or_raise = AsyncMock()
    node._get_apify_token = lambda: "test-token"
    node._track_apify_usage = AsyncMock()
    monkeypatch.setattr("nodes.core.apify_runner.asyncio.sleep", AsyncMock())
    return node


def transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.core.apify_runner.httpx.AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw),
    )


async def run(runner, **kw):
    return await runner._run_apify_actor("owner/scraper", {}, "test", "scraping", "reddit", **kw)


def metadata(**overrides):
    return {
        "id": "run-1",
        "status": "SUCCEEDED",
        "defaultDatasetId": "dataset-1",
        "defaultKeyValueStoreId": "store-1",
        "usageTotalUsd": 0.02,
        **overrides,
    }


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500])
async def test_provider_start_error_fails_tool(runner, monkeypatch, status):
    transport(
        monkeypatch,
        lambda r: httpx.Response(status, json={"error": {"message": "Provider unavailable"}}),
    )
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        await run(runner)
    runner.emit.assert_not_awaited()
    runner._track_apify_usage.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    ["http", "json", "shape", "item_error", "missing_dataset", "FAILED", "ABORTED", "TIMED-OUT"],
)
async def test_failed_or_unreadable_dataset_cannot_be_empty_success(runner, monkeypatch, failure):
    run_info = metadata()
    if failure in {"FAILED", "ABORTED", "TIMED-OUT"}:
        run_info["status"] = failure
    if failure == "missing_dataset":
        run_info.pop("defaultDatasetId")

    def respond(request):
        if "/datasets/" in request.url.path:
            if failure == "http":
                return httpx.Response(503, json={"error": {"message": "Dataset unavailable"}})
            if failure == "json":
                return httpx.Response(200, text="bad-json")
            if failure == "shape":
                return httpx.Response(200, json={})
            return httpx.Response(200, json=[{"error": "Profile not found"}])
        return httpx.Response(200, json={"data": run_info})

    transport(monkeypatch, respond)
    with pytest.raises(RuntimeError):
        await run(runner)
    runner.emit.assert_not_awaited()
    assert runner._track_apify_usage.await_count == 1


@pytest.mark.parametrize(
    "summary",
    [
        {"itemsTotal": 1, "requests": {"finished": 1}},
        {"itemsTotal": 0, "requests": {"finished": 1, "failed": 1}},
        {"itemsTotal": 0, "requests": {"finished": 1}, "skippedTotal": 1},
        {"itemsTotal": 0, "requests": {"finished": 1}, "inputWarnings": ["Ignored sort"]},
        {"itemsTotal": 0, "requests": {"finished": 1}, "chargeLimitReached": True},
        {"itemsTotal": 0, "requests": {"finished": 0}},
    ],
)
async def test_partial_scrape_rejected_even_when_actor_succeeded(runner, monkeypatch, summary):
    def respond(request):
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        if "/records/" in request.url.path:
            return httpx.Response(200, json=summary)
        return httpx.Response(200, json={"data": metadata()})

    transport(monkeypatch, respond)
    with pytest.raises(RuntimeError):
        await run(runner, summary_key="RUN-SUMMARY")
    runner.emit.assert_not_awaited()


async def test_successful_empty_listing_is_valid_with_completed_requests(runner, monkeypatch):
    def respond(request):
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        if "/records/" in request.url.path:
            return httpx.Response(
                200, json={"itemsTotal": 0, "requests": {"finished": 1, "failed": 0}}
            )
        return httpx.Response(200, json={"data": metadata()})

    transport(monkeypatch, respond)
    result = await run(runner, summary_key="RUN-SUMMARY")
    assert result["status"] == "success"
    assert result["data"] == {"items": [], "count": 0}


async def test_pages_all_rows_and_bills_final_cost_not_initial_start_charge(runner, monkeypatch):
    offsets = []

    def respond(request):
        if "/datasets/" in request.url.path:
            offset = int(request.url.params["offset"])
            offsets.append(offset)
            return httpx.Response(
                200, json=[{"id": i} for i in range(offset, min(offset + 1000, 1001))]
            )
        info = metadata()
        if "/actor-runs/" in request.url.path:
            info.update(
                usageTotalUsd=2.022,
                chargedEventCounts={"result": 1001},
                pricingInfo={
                    "pricingPerEvent": {"actorChargeEvents": {"result": {"isPrimaryEvent": True}}}
                },
            )
        return httpx.Response(200, json={"data": info})

    transport(monkeypatch, respond)
    result = await run(runner)
    assert offsets == [0, 1000]
    assert result["data"]["count"] == 1001
    assert runner._track_apify_usage.await_args.args[3:5] == (2.022, 1001)


@pytest.mark.parametrize("failure", ["poll", "cancel", "timeout"])
async def test_aborts_paid_run_when_polling_cannot_complete(runner, monkeypatch, failure):
    aborted = []

    def respond(request):
        if request.url.path.endswith("/abort"):
            aborted.append(request)
            return httpx.Response(200, json={"data": metadata(status="ABORTED")})
        if "/actor-runs/" in request.url.path and not aborted:
            if failure == "cancel":
                raise asyncio.CancelledError()
            return httpx.Response(503, json={"error": {"message": "Polling unavailable"}})
        return httpx.Response(
            200, json={"data": metadata(status="ABORTED" if aborted else "RUNNING")}
        )

    if failure == "timeout":
        monkeypatch.setattr("nodes.core.apify_runner.APIFY_ACTOR_TIMEOUT_SECONDS", -1)
    transport(monkeypatch, respond)
    with pytest.raises((RuntimeError, TimeoutError, asyncio.CancelledError)):
        await run(runner)
    assert len(aborted) == 1
    runner.emit.assert_not_awaited()
    assert runner._track_apify_usage.await_count == 1


async def test_credit_gate_prevents_provider_work(runner, monkeypatch):
    runner._check_credits_or_raise.side_effect = ValueError("Insufficient credits")

    def respond(request):
        pytest.fail("No provider call allowed after failed credit gate")

    transport(monkeypatch, respond)
    with pytest.raises(ValueError, match="Insufficient credits"):
        await run(runner)


async def test_result_billing_waits_past_startup_only_charge(runner, monkeypatch):
    polls = []

    def respond(request):
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"id": 1}, {"id": 2}])
        info = metadata(chargedEventCounts={"result": 0})
        if "/actor-runs/" in request.url.path:
            polls.append(request)
            if len(polls) >= 5:
                info.update(usageTotalUsd=0.024, chargedEventCounts={"result": 2})
        return httpx.Response(200, json={"data": info})

    transport(monkeypatch, respond)
    result = await run(runner, result_charge_event="result")
    assert len(polls) == 6
    assert result["status"] == "success"
    assert runner._track_apify_usage.await_args.args[3] == 0.024


async def test_unsettled_result_charges_are_not_silently_accepted(runner, monkeypatch):
    def respond(request):
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"id": 1}])
        return httpx.Response(200, json={"data": metadata(chargedEventCounts={"result": 0})})

    transport(monkeypatch, respond)
    with pytest.raises(RuntimeError, match="has not settled"):
        await run(runner, result_charge_event="result")
    runner.emit.assert_not_awaited()


async def test_result_counts_can_settle_before_aggregate_cost(runner, monkeypatch):
    polls = []

    def respond(request):
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"id": 1}])
        info = metadata(
            chargedEventCounts={"result": 1, "init": 1},
            pricingInfo={
                "pricingModel": "PAY_PER_EVENT",
                "pricingPerEvent": {
                    "actorChargeEvents": {
                        "result": {"eventPriceUsd": 0.002},
                        "init": {"eventPriceUsd": 0.02},
                    }
                },
            },
        )
        if "/actor-runs/" in request.url.path:
            polls.append(request)
            if len(polls) >= 4:
                info["usageTotalUsd"] = 0.022
        return httpx.Response(200, json={"data": info})

    transport(monkeypatch, respond)
    await run(runner, result_charge_event="result")
    assert len(polls) == 4
    assert runner._track_apify_usage.await_args.args[3] == 0.022
