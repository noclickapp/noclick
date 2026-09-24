"""Bounded local probing; ffprobe never fetches a network URL."""

import asyncio
import json
import math
import tempfile


async def video_duration(data: bytes) -> float:
    if not data:
        raise ValueError("Video is empty")
    with tempfile.NamedTemporaryFile(suffix=".video") as media:
        media.write(data)
        media.flush()
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "format=duration", "-of", "json", media.name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
    try:
        duration = float(json.loads(stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise ValueError("Could not determine video duration") from None
    if process.returncode or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid video duration")
    return duration
