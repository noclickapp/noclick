"""Minimal diagnostics compatibility surface for community execution code."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter()


def _get_rss_mb() -> float:
    return 0.0


def start_memory_monitor() -> None:
    return None


async def stop_memory_monitor() -> None:
    await asyncio.sleep(0)
