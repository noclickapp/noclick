"""Real local scheduler HTTP contract and PostgreSQL, with no external calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
async def local_scheduler(builder_request_db, monkeypatch):
    from utils import local_cron, cron_scheduler_client, coordinator_dispatch, coordinator_wakeup_routes
    from repositories.local_schedules import SCHEMA
    pool = builder_request_db[0]
    await pool.execute(SCHEMA)
    await pool.execute("TRUNCATE local_cron_schedules")
    app = FastAPI()
    app.include_router(local_cron.router)
    app.include_router(coordinator_wakeup_routes.router)
    monkeypatch.setattr(local_cron, "_get_pool", lambda: pool)
    monkeypatch.setattr(local_cron, "_schema_ready", True)
    monkeypatch.setattr(coordinator_wakeup_routes, "get_native_pool", lambda: pool)
    monkeypatch.setattr(coordinator_dispatch, "_callback_provider", AsyncMock(return_value="http://scheduler.test/internal/scheduler/coordinator"))
    monkeypatch.setenv("CRON_SCHEDULER_SECRET", "test-scheduler-secret")
    monkeypatch.setattr(cron_scheduler_client, "CRON_SCHEDULER_SECRET", "test-scheduler-secret")
    monkeypatch.setattr(cron_scheduler_client, "CRON_SCHEDULER_URL", "http://scheduler.test/local-cron")
    monkeypatch.setattr(cron_scheduler_client, "httpx", SimpleNamespace(
        AsyncClient=lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)), TimeoutException=httpx.TimeoutException))
    try:
        yield app, pool
    finally:
        await pool.execute("TRUNCATE local_cron_schedules")
