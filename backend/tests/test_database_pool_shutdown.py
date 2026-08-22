"""Cancellation-safe shutdown coverage for the native asyncpg pool."""

import asyncio

import pytest

from utils import database_pool


class _PoolThatWaits:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.terminated = False

    async def close(self) -> None:
        self.close_started.set()
        await asyncio.Event().wait()

    def terminate(self) -> None:
        self.terminated = True


class _PoolThatFails:
    def __init__(self) -> None:
        self.terminated = False

    async def close(self) -> None:
        raise RuntimeError("close failed")

    def terminate(self) -> None:
        self.terminated = True


async def test_cancelled_close_terminates_captured_pool(monkeypatch):
    pool = _PoolThatWaits()
    monkeypatch.setattr(database_pool, "_native_pool", pool)
    monkeypatch.setattr(
        database_pool,
        "_native_pool_loop",
        asyncio.get_running_loop(),
    )

    close_task = asyncio.create_task(database_pool.close_native_pool())
    await pool.close_started.wait()
    close_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert pool.terminated
    assert database_pool._native_pool is None
    assert database_pool._native_pool_loop is None


async def test_failed_close_terminates_captured_pool(monkeypatch):
    pool = _PoolThatFails()
    monkeypatch.setattr(database_pool, "_native_pool", pool)
    monkeypatch.setattr(
        database_pool,
        "_native_pool_loop",
        asyncio.get_running_loop(),
    )

    await database_pool.close_native_pool()

    assert pool.terminated
    assert database_pool._native_pool is None
    assert database_pool._native_pool_loop is None
