"""
Video generation handler: one OpenRouter video job through the machinery the
coordinator uses (``utils/media_generation.py``), priced from the model's
per-second SKUs and gated on that projection before anything runs, recorded as
a ``video`` job, then stored and charged once by the shared poller.

Like every media fast path, the node returns its media as its output, so it
drives its own job and waits for it, bounded by the job's own timeout. If the
wait is cut short (a stopped run, a lost container), the per-minute poll
finishes the job, keeps the file with the workflow and charges it once.

A node that brings its own Google key runs a Veo model on Google AI Studio with
that key instead, and is charged nothing. An old video id (an older
client's default "veo-3") runs as the OpenRouter model it was renamed to
(``model_catalog.current_video_model``).
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from nodes.agent.handlers._media_utils import fetch_image_as_base64
from repositories.coordinator_jobs import AGENT_NODE_SOURCE
from utils import media_generation as media
from utils.model_catalog import current_video_model

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 10.0
# Veo's own passthrough for a negative prompt; only the matched provider's options are forwarded.
_VEO_PROVIDERS = ("google-vertex", "google-ai-studio")

AISTUDIO_API = "https://generativelanguage.googleapis.com/v1beta"
# OpenRouter's Veo ids (the ones migration 20261009130000_agent_video_openrouter_models
# renamed saved nodes to) as Google AI Studio names them; any other id is sent as named.
AISTUDIO_MODELS = {
    "veo-3.1": "veo-3.1-generate-preview",
    "veo-3.1-fast": "veo-3.1-fast-generate-preview",
    "veo-3.1-lite": "veo-3.1-lite-generate-preview",
}
AISTUDIO_POLL_S = 15
AISTUDIO_MAX_POLLS = 40
# A Google credential's key, as the node's credential env carries it (config/providers.py).
OWN_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY")


async def execute_video_model(
    node,
    config,
    env_overrides: Optional[Dict[str, str]],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Generate one video, on the node's own Google key when it has one, else on
    the platform's OpenRouter key, and return it."""
    from utils.database_pool import get_native_pool

    if not user_id:
        raise ValueError("Video generation needs the account it runs for.")
    prompt = f"{config.system_prompt}\n\n{config.message}" if config.system_prompt else config.message
    model = current_video_model(config.model)
    await node.emit({"type": "agent", "status": "running"})
    own_key = next((env_overrides[k] for k in OWN_KEYS if (env_overrides or {}).get(k)), None)
    if own_key:
        return await _veo_on_own_key(node, config, model, own_key, prompt)

    # The Video Settings are shown for Veo models only (VideoConfig's ui:show-if);
    # any other model takes the durations and resolutions it publishes.
    settings: Dict[str, Any] = {}
    if "veo" in model.lower():
        settings = {"seconds": int(config.veo_duration_seconds), "resolution": config.veo_resolution,
                    "aspect_ratio": config.veo_aspect_ratio}
        if config.veo_negative_prompt:
            settings["provider_options"] = {
                slug: {"parameters": {"negativePrompt": config.veo_negative_prompt}} for slug in _VEO_PROVIDERS}
    if config.veo_image_url:
        image_b64, mime = await fetch_image_as_base64(config.veo_image_url)
        settings["first_frame"] = f"data:{mime};base64,{image_b64}"

    pool = get_native_pool()
    started = await media.start_video(
        pool, user_id=user_id, organization_id=node.organization_id, prompt=prompt, model=model,
        source=AGENT_NODE_SOURCE, workflow_id=node.workflow_id, node_id=node.node_id, **settings,
    )
    job = await _wait(node, pool, started["job_id"])
    if job["status"] != "completed":
        raise RuntimeError(f"Video generation failed: {job['error']}")

    video = {key: job["result"][key] for key in ("url", "resource_id", "mime_type")}
    return {
        "type": "agent",
        "status": "completed",
        "response": "Generated 1 video",
        "model": config.model,
        "temperature": config.temperature,
        "videos": [video],
        "video_url": video["url"],
    }


async def _wait(node, pool, job_id: str) -> Dict[str, Any]:
    """The job once it's finished; it fails itself past ``VIDEO_TIMEOUT_S``."""
    deadline = time.monotonic() + media.VIDEO_TIMEOUT_S + 2 * POLL_INTERVAL_S
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_S)
        job = await media.advance_video_job(pool, job_id)
        if job["status"] != "running":
            return job
        await node.emit({"type": "agent", "status": "running"})
    raise TimeoutError(f"The video didn't finish within {media.VIDEO_TIMEOUT_S // 60} minutes; "
                       "if it finishes later, it's saved to this workflow's files.")


async def _veo_on_own_key(node, config, model: str, api_key: str, prompt: str) -> Dict[str, Any]:
    """A Veo model (``model``, its OpenRouter id) on Google AI Studio with the
    node's own key: Google bills its owner, so nothing is gated or charged here."""
    import httpx

    bare = model
    for prefix in ("google/", "gemini/"):
        bare = bare.removeprefix(prefix)
    model = AISTUDIO_MODELS.get(bare, bare)
    duration = min((4, 6, 8), key=lambda s: abs(s - int(config.veo_duration_seconds)))
    params: Dict[str, Any] = {"aspectRatio": config.veo_aspect_ratio, "durationSeconds": duration,
                              "resolution": config.veo_resolution}
    if config.veo_negative_prompt:
        params["negativePrompt"] = config.veo_negative_prompt
    instance: Dict[str, Any] = {"prompt": prompt}
    if config.veo_image_url:
        image_b64, mime = await fetch_image_as_base64(config.veo_image_url)
        instance["image"] = {"bytesBase64Encoded": image_b64, "mimeType": mime}
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{AISTUDIO_API}/models/{model}:predictLongRunning", headers=headers,
                                 json={"instances": [instance], "parameters": params})
        if resp.status_code >= 400:
            raise RuntimeError(f"Google refused the video request (HTTP {resp.status_code}): {resp.text[:300]}")
        operation = resp.json().get("name")
        if not operation:
            raise RuntimeError(f"Google started no video job: {resp.text[:300]}")
        logger.info("[Video] Veo on the owner's key started: operation=%s model=%s", operation, model)
        for _ in range(AISTUDIO_MAX_POLLS):
            await asyncio.sleep(AISTUDIO_POLL_S)
            await node.emit({"type": "agent", "status": "running"})
            poll = await client.get(f"{AISTUDIO_API}/{operation}", headers=headers)
            poll.raise_for_status()
            state = poll.json()
            if state.get("done"):
                break
        else:
            raise TimeoutError(f"The video didn't finish within {AISTUDIO_MAX_POLLS * AISTUDIO_POLL_S // 60} minutes.")
    if state.get("error"):
        raise RuntimeError(f"Video generation failed: {state['error'].get('message') or state['error']}")
    response = state.get("response", {})
    samples = response.get("generateVideoResponse", response).get("generatedSamples", [])
    videos = [{"url": s["video"]["uri"], "mime_type": s["video"].get("mimeType", "video/mp4")}
              for s in samples if s.get("video", {}).get("uri")]
    if not videos:
        raise RuntimeError(f"Google returned no video: {str(state)[:300]}")
    videos = await node._upload_videos_to_r2(videos, api_key=api_key)
    return {
        "type": "agent",
        "status": "completed",
        "response": f"Generated {len(videos)} video{'s' if len(videos) != 1 else ''}",
        "model": config.model,
        "temperature": config.temperature,
        "videos": videos,
        "video_url": videos[0]["url"],
    }
