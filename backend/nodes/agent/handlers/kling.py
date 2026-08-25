"""
Kling AI video/image generation handler.

ByteDance's Kling uses JWT auth (HS256) and async task polling.
Supports text-to-video, image-to-video, and image generation.
"""

import asyncio
import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from nodes.agent.handlers._media_utils import fetch_image_as_base64

logger = logging.getLogger(__name__)

KLING_API_BASE = "https://api.klingai.com"


async def _poll_task(node, client, poll_url, headers, jwt_generator) -> Dict[str, Any]:
    """Poll a Kling async task until completion or failure."""
    poll_interval = 10
    max_polls = 60

    for attempt in range(max_polls):
        await asyncio.sleep(poll_interval)
        await node.emit({'type': 'agent', 'status': 'running'})

        headers["Authorization"] = f"Bearer {jwt_generator()}"
        poll_resp = await client.get(poll_url, headers=headers)
        poll_data = poll_resp.json()
        task_data = poll_data.get("data", {})
        status = task_data.get("task_status", "unknown")

        logger.info(f"[Kling] Poll {attempt + 1}: status={status}")

        if status == "succeed":
            return task_data
        elif status == "failed":
            error_msg = task_data.get("task_status_msg", "Unknown error")
            raise RuntimeError(f"Kling generation failed: {error_msg}")

    raise TimeoutError(f"Kling generation timed out after {max_polls * poll_interval}s")


# ============================================================================
# Handler
# ============================================================================

async def execute_kling_model(
    node,
    config,
    env_overrides: Optional[Dict[str, str]],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Fast-path for Kling AI video/image generation."""
    import jwt as pyjwt
    import httpx

    prompt = f"{config.system_prompt}\n\n{config.message}" if config.system_prompt else config.message
    user_resource = env_overrides is not None

    await node.emit({'type': 'agent', 'status': 'running'})

    # ── Resolve credentials ──────────────────────────────────────────────
    access_key = None
    secret_key = None
    if env_overrides:
        access_key = env_overrides.get('KLING_ACCESS_KEY')
        secret_key = env_overrides.get('KLING_SECRET_KEY')
    if not access_key:
        access_key = os.environ.get('KLING_ACCESS_KEY')
    if not secret_key:
        secret_key = os.environ.get('KLING_SECRET_KEY')
    if not access_key or not secret_key:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY are required for Kling AI generation")

    # ── Pre-flight credit gate (standardized) ────────────────────────────
    if node.user_id:
        from billing.usage_tracker import usage_tracker
        await usage_tracker.enforce_credit_gate(
            node.user_id,
            organization_id=node.organization_id,
            sio=node.sio,
            sid=node.sid,
            user_resource=user_resource,
            surface="kling",
        )

    # ── Generate JWT ─────────────────────────────────────────────────────
    def _generate_jwt() -> str:
        now = int(time.time())
        return pyjwt.encode(
            {"iss": access_key, "exp": now + 1800, "nbf": now - 5},
            secret_key, algorithm="HS256",
            headers={"alg": "HS256", "typ": "JWT"},
        )

    # ── Model resolution ─────────────────────────────────────────────────
    model_name = config.model.removeprefix("kling/")
    is_image_model = 'image' in model_name.lower()
    # Strip "-image" suffix before sending to API: "kling-v2-1-image" → "kling-v2-1"
    if is_image_model:
        model_name = model_name.removesuffix("-image")
    has_input_image = bool(config.kling_image_url)
    mode = config.kling_mode or "std"
    duration = int(config.kling_duration) if config.kling_duration else 5
    aspect_ratio = config.kling_aspect_ratio or "16:9"

    api_headers = {
        "Authorization": f"Bearer {_generate_jwt()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        if is_image_model:
            return await _execute_image(node, config, client, api_headers, _generate_jwt,
                                        model_name, prompt, aspect_ratio, has_input_image, user_resource)
        else:
            return await _execute_video(node, config, client, api_headers, _generate_jwt,
                                        model_name, prompt, mode, duration, aspect_ratio,
                                        has_input_image, user_resource)


async def _execute_image(node, config, client, api_headers, jwt_gen,
                         model_name, prompt, aspect_ratio, has_input_image, user_resource):
    """Kling image generation."""
    n_images = int(config.kling_image_count) if config.kling_image_count else 1
    body: Dict[str, Any] = {
        "model_name": model_name,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "n": max(1, min(9, n_images)),
    }
    if config.kling_negative_prompt:
        body["negative_prompt"] = config.kling_negative_prompt
    if config.kling_seed:
        body["seed"] = int(config.kling_seed)
    if has_input_image:
        img_b64, _ = await fetch_image_as_base64(config.kling_image_url)
        body["image"] = img_b64

    resp = await client.post(f"{KLING_API_BASE}/v1/images/generations", headers=api_headers, json=body)
    if resp.status_code >= 400:
        error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        error_msg = error_body.get("message", resp.text)
        if error_body.get("code") == 1102:
            raise ValueError("Kling API account balance is insufficient.")
        raise ValueError(f"Kling API error: {error_msg}")

    task_id = resp.json().get("data", {}).get("task_id")
    if not task_id:
        raise ValueError(f"No task_id in Kling image response: {resp.json()}")

    logger.info(f"[Kling] Image generation started: task_id={task_id}")
    result_data = await _poll_task(node, client, f"{KLING_API_BASE}/v1/images/generations/{task_id}",
                                   api_headers, jwt_gen)

    images = result_data.get("task_result", {}).get("images", [])
    if not images:
        raise ValueError(f"Kling image generation returned no images: {result_data}")

    cdn_urls = [img["url"] for img in images if img.get("url")]

    # Kling CDN URLs expire (~14 days). Mirror to R2 when we have workflow context
    # by downloading each image and passing data URIs into _upload_images_to_r2.
    if node.user_id and node.workflow_id:
        data_urls = []
        for cdn_url in cdn_urls:
            try:
                img_b64, mime = await fetch_image_as_base64(cdn_url)
                data_urls.append(f"data:{mime};base64,{img_b64}")
            except Exception as e:
                logger.warning(f"[Kling] Failed to download image for R2 mirror: {e}")
        image_urls = await node._upload_images_to_r2(data_urls) if data_urls else []
    else:
        logger.warning(
            f"[Kling] Skipping R2 mirror for {len(cdn_urls)} image(s): "
            f"missing user_id/workflow_id. URLs will expire."
        )
        image_urls = [{"url": u, "mime_type": "image/png"} for u in cdn_urls]

    # Track billing
    if not user_resource and node.user_id:
        try:
            from billing.usage_tracker import usage_tracker
            from billing.schema import UsageEventData
            from billing.markup import apply_kling_markup
            from billing.pricing import get_kling_image_cost

            raw_cost = get_kling_image_cost(model_name)
            total_cost = apply_kling_markup(raw_cost, user_resource=False, model=config.model)

            usage_event = UsageEventData(
                # Raw runner; track_usage_event resolves to the org owner centrally.
                user_id=node.user_id, total_cost=total_cost,
                usage_type="ai_usage", usage_subtype=config.model,
                quantity=Decimal("1"), unit_type="images",
                user_resource=False, organization_id=node.organization_id,
                metadata={"model": config.model, "n_images": len(image_urls)},
            )
            await usage_tracker.track_usage_event(
                usage_event,
                sio=node.sio,
                sid=node.sid,
            )
            logger.info(f"[Kling] Tracked image billing: cost=${total_cost:.6f}")
        except Exception as e:
            logger.warning(f"[Kling] Failed to track billing: {e}")

    return {
        "type": "agent", "status": "completed",
        "response": f"Generated {len(image_urls)} image(s)",
        "model": config.model, "temperature": config.temperature,
        "images": image_urls,
        "image_url": image_urls[0]["url"] if image_urls else None,
    }


async def _execute_video(node, config, client, api_headers, jwt_gen,
                         model_name, prompt, mode, duration, aspect_ratio,
                         has_input_image, user_resource):
    """Kling video generation."""
    body: Dict[str, Any] = {
        "model_name": model_name, "prompt": prompt,
        "duration": str(duration), "aspect_ratio": aspect_ratio, "mode": mode,
    }
    mn = model_name.lower()

    # Model-specific optional params
    if "v2-1-master" not in mn and "video-o1" not in mn and config.kling_negative_prompt:
        body["negative_prompt"] = config.kling_negative_prompt
    if config.kling_seed:
        body["seed"] = int(config.kling_seed)

    supports_cfg = any(s in mn for s in ["v1", "v3", "video-o1"]) and "v2" not in mn
    if supports_cfg and config.kling_cfg_scale:
        body["cfg_scale"] = float(config.kling_cfg_scale)

    supports_sound = any(s in mn for s in ["v2-5", "v2-6", "v3", "omni", "video-o1"])
    if supports_sound and config.kling_sound == "on":
        body["sound"] = "on"

    # Camera control: v1-6 only
    if "v1-6" in mn and config.kling_camera_type:
        camera: Dict[str, Any] = {"type": config.kling_camera_type}
        if config.kling_camera_type == "simple":
            camera["config"] = {
                "horizontal": int(config.kling_camera_horizontal or 0),
                "vertical": int(config.kling_camera_vertical or 0),
                "zoom": int(config.kling_camera_zoom or 0),
                "pan": int(config.kling_camera_pan or 0),
                "tilt": int(config.kling_camera_tilt or 0),
                "roll": int(config.kling_camera_roll or 0),
            }
        body["camera_control"] = camera

    if has_input_image:
        img_b64, _ = await fetch_image_as_base64(config.kling_image_url)
        body["image"] = img_b64
        supports_tail = any(s in mn for s in ["v1-6", "v2-1", "v2-6", "v3", "omni", "video-o1"])
        if supports_tail and config.kling_image_tail_url and mode == "pro":
            tail_b64, _ = await fetch_image_as_base64(config.kling_image_tail_url)
            body["image_tail"] = tail_b64
        endpoint = f"{KLING_API_BASE}/v1/videos/image2video"
        poll_base = f"{KLING_API_BASE}/v1/videos/image2video"
    else:
        endpoint = f"{KLING_API_BASE}/v1/videos/text2video"
        poll_base = f"{KLING_API_BASE}/v1/videos/text2video"

    resp = await client.post(endpoint, headers=api_headers, json=body)
    if resp.status_code >= 400:
        error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        error_msg = error_body.get("message", resp.text)
        if error_body.get("code") == 1102:
            raise ValueError("Kling API account balance is insufficient.")
        raise ValueError(f"Kling API error: {error_msg}")

    task_id = resp.json().get("data", {}).get("task_id")
    if not task_id:
        raise ValueError(f"No task_id in Kling video response: {resp.json()}")

    logger.info(f"[Kling] Video generation started: task_id={task_id}")
    result_data = await _poll_task(node, client, f"{poll_base}/{task_id}", api_headers, jwt_gen)

    videos = result_data.get("task_result", {}).get("videos", [])
    if not videos:
        raise ValueError(f"Kling video generation returned no videos: {result_data}")

    video_urls = [{"url": v["url"], "mime_type": "video/mp4"} for v in videos if v.get("url")]
    video_urls = await node._upload_videos_to_r2(video_urls)

    # Track billing
    if not user_resource and node.user_id:
        try:
            from billing.usage_tracker import usage_tracker
            from billing.schema import UsageEventData
            from billing.markup import apply_kling_markup
            from billing.pricing import get_kling_video_cost

            raw_cost = get_kling_video_cost(model_name, duration, mode)
            total_cost = apply_kling_markup(raw_cost, user_resource=False, model=config.model)

            usage_event = UsageEventData(
                # Raw runner; track_usage_event resolves to the org owner centrally.
                user_id=node.user_id, total_cost=total_cost,
                usage_type="ai_usage", usage_subtype=config.model,
                quantity=Decimal(str(duration)), unit_type="seconds",
                user_resource=False, organization_id=node.organization_id,
                metadata={"model": config.model, "duration_seconds": duration,
                          "mode": mode, "n_videos": len(video_urls)},
            )
            await usage_tracker.track_usage_event(
                usage_event,
                sio=node.sio,
                sid=node.sid,
            )
            logger.info(f"[Kling] Tracked video billing: duration={duration}s, cost=${total_cost:.6f}")
        except Exception as e:
            logger.warning(f"[Kling] Failed to track billing: {e}")

    return {
        "type": "agent", "status": "completed",
        "response": f"Generated {len(video_urls)} video(s)",
        "model": config.model, "temperature": config.temperature,
        "videos": video_urls,
        "video_url": video_urls[0]["url"],
    }
