"""
Video generation handler — Veo (Google), Sora (OpenAI), RunwayML.

Routes to Google AI Studio REST API for Veo, LiteLLM for other providers.
Video generation is async with polling.
"""

import asyncio
import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def execute_video_model(
    node,
    config,
    env_overrides: Optional[Dict[str, str]],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Fast-path for video generation models."""
    import httpx

    prompt = f"{config.system_prompt}\n\n{config.message}" if config.system_prompt else config.message
    model_lower = config.model.lower()
    user_resource = env_overrides is not None

    await node.emit({'type': 'agent', 'status': 'running'})

    if 'gemini/' in model_lower or 'google/' in model_lower:
        return await _execute_veo(node, config, env_overrides, user_id, prompt, user_resource)
    else:
        return await _execute_litellm_video(node, config, env_overrides, user_id, prompt, user_resource)


async def _execute_veo(node, config, env_overrides, user_id, prompt, user_resource) -> Dict[str, Any]:
    """Google Veo via AI Studio REST API."""
    import httpx

    api_key = None
    if env_overrides:
        api_key = env_overrides.get('GEMINI_API_KEY') or env_overrides.get('GOOGLE_API_KEY')
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY required for Google Veo video generation")

    # Pre-flight credit gate (standardized). See usage_tracker.enforce_credit_gate.
    if node.user_id:
        from billing.usage_tracker import usage_tracker
        await usage_tracker.enforce_credit_gate(
            node.user_id,
            organization_id=node.organization_id,
            sio=node.sio,
            sid=node.sid,
            user_resource=user_resource,
            surface="veo",
        )

    # Resolve model name
    model_name = config.model
    for prefix in ('gemini/', 'google/'):
        model_name = model_name.removeprefix(prefix)

    _AISTUDIO_ALIASES: Dict[str, str] = {
        'veo-3.1-generate-001': 'veo-3.1-generate-preview',
        'veo-3.1-fast-generate-001': 'veo-3.1-fast-generate-preview',
    }
    model_name = _AISTUDIO_ALIASES.get(model_name, model_name)

    base_url = "https://generativelanguage.googleapis.com/v1beta"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    veo_version = 2 if 'veo-2' in model_name.lower() else 3

    # Parse duration
    try:
        duration = int(config.veo_duration_seconds)
    except (ValueError, AttributeError):
        duration = 8
    if veo_version == 2:
        duration = max(5, min(8, duration))
    else:
        duration = min([4, 6, 8], key=lambda x: abs(x - duration))

    params: Dict[str, Any] = {
        "aspectRatio": config.veo_aspect_ratio,
        "durationSeconds": duration,
        "resolution": config.veo_resolution,
    }
    if config.veo_negative_prompt:
        params["negativePrompt"] = config.veo_negative_prompt

    # Build instance — optionally include image for image-to-video
    instance: Dict[str, Any] = {"prompt": prompt}
    if config.veo_image_url:
        from nodes.agent.handlers._media_utils import fetch_image_as_base64
        img_b64, img_mime = await fetch_image_as_base64(config.veo_image_url)
        instance["image"] = {"bytesBase64Encoded": img_b64, "mimeType": img_mime}

    body = {"instances": [instance], "parameters": params}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/models/{model_name}:predictLongRunning",
            headers=headers, json=body,
        )
        if resp.status_code >= 400:
            logger.error(f"[Video] Veo API error {resp.status_code}: {resp.text}")
            resp.raise_for_status()

        operation_name = resp.json().get("name")
        if not operation_name:
            raise ValueError(f"No operation name in predictLongRunning response: {resp.json()}")

        logger.info(f"[Video] Veo generation started: operation={operation_name}")

        # Poll until done
        poll_interval = 15
        max_polls = 40
        poll_data: Dict[str, Any] = {}

        for attempt in range(max_polls):
            await asyncio.sleep(poll_interval)
            await node.emit({'type': 'agent', 'status': 'running'})

            poll_resp = await client.get(f"{base_url}/{operation_name}", headers=headers)
            poll_data = poll_resp.json()
            logger.info(f"[Video] Poll {attempt + 1}: done={poll_data.get('done', False)}")

            if poll_data.get("done"):
                break
        else:
            raise TimeoutError(f"Video generation timed out after {max_polls * poll_interval}s")

    # Extract video URLs
    response_data = poll_data.get("response", {})
    video_response = response_data.get("generateVideoResponse", response_data)
    samples = video_response.get("generatedSamples", [])

    if not samples:
        raise ValueError(f"Video generation returned no samples: {poll_data}")

    video_urls = [
        {"url": s["video"]["uri"], "mime_type": s["video"].get("mimeType", "video/mp4")}
        for s in samples if s.get("video", {}).get("uri")
    ]
    if not video_urls:
        raise ValueError(f"No video URIs in response samples: {samples}")

    # Upload to R2
    video_urls = await node._upload_videos_to_r2(video_urls, api_key=api_key)

    # Track billing
    if not user_resource and node.user_id:
        try:
            from billing.usage_tracker import usage_tracker
            from billing.schema import UsageEventData
            from billing.markup import apply_gemini_markup
            from billing.pricing import get_veo_cost, VEO_PRICE_PER_SECOND

            n_videos = len(video_urls)
            price_per_sec = VEO_PRICE_PER_SECOND.get(model_name, Decimal("0.50"))
            raw_cost = get_veo_cost(model_name, duration, n_videos)
            total_cost = apply_gemini_markup(raw_cost, user_resource=False, model=config.model)

            usage_event = UsageEventData(
                # Raw runner; track_usage_event resolves to the org owner centrally.
                user_id=node.user_id,
                total_cost=total_cost,
                usage_type="ai_usage",
                usage_subtype=config.model,
                quantity=Decimal(str(duration * n_videos)),
                unit_type="seconds",
                user_resource=False,
                organization_id=node.organization_id,
                metadata={
                    "model": config.model,
                    "n_videos": n_videos,
                    "duration_seconds": duration,
                    "price_per_second": str(price_per_sec),
                },
            )
            await usage_tracker.track_usage_event(
                usage_event,
                sio=node.sio,
                sid=node.sid,
            )
            logger.info(f"[Video] Tracked Veo billing: videos={n_videos}, duration={duration}s, cost=${total_cost:.6f}")
        except Exception as e:
            logger.warning(f"[Video] Failed to track billing: {e}")

    return {
        "type": "agent",
        "status": "completed",
        "response": f"Generated {len(video_urls)} video(s)",
        "model": config.model,
        "temperature": config.temperature,
        "videos": video_urls,
        "video_url": video_urls[0]["url"],
    }


async def _execute_litellm_video(node, config, env_overrides, user_id, prompt, user_resource) -> Dict[str, Any]:
    """Other video providers (OpenAI Sora, Azure) via LiteLLM."""
    import litellm
    from coder.openai_agent.billing import ENV_MASK, _PROVIDER_KEY_ALIASES
    from utils.thread_env import override_env

    # Pre-flight credit gate (standardized). See usage_tracker.enforce_credit_gate.
    if node.user_id:
        from billing.usage_tracker import usage_tracker
        await usage_tracker.enforce_credit_gate(
            node.user_id,
            organization_id=node.organization_id,
            sio=node.sio,
            sid=node.sid,
            user_resource=user_resource,
            surface="video",
        )

    loop = asyncio.get_event_loop()

    effective_env: Dict[str, str] = {}
    if env_overrides:
        effective_env = {**ENV_MASK, **env_overrides}
        for user_key, litellm_key in _PROVIDER_KEY_ALIASES.items():
            if user_key in env_overrides:
                effective_env[litellm_key] = env_overrides[user_key]

    def _with_env(fn, **kwargs):
        if effective_env:
            with override_env(**effective_env):
                return fn(**kwargs)
        return fn(**kwargs)

    init_response = await loop.run_in_executor(
        None,
        lambda: _with_env(litellm.video_generation, model=config.model, prompt=prompt),
    )
    logger.info(f"[Video] LiteLLM video generation started: id={getattr(init_response, 'id', 'N/A')}")

    video_id = init_response.id
    poll_interval = 15
    max_polls = 40
    status_response = None

    for attempt in range(max_polls):
        await asyncio.sleep(poll_interval)
        await node.emit({'type': 'agent', 'status': 'running'})

        status_response = await loop.run_in_executor(
            None,
            lambda: _with_env(litellm.video_status, id=video_id, model=config.model),
        )
        current_status = getattr(status_response, 'status', 'unknown')
        logger.info(f"[Video] Poll {attempt + 1}: status={current_status}")

        if current_status == 'completed':
            break
        if current_status in ('failed', 'error', 'cancelled'):
            err = (
                getattr(status_response, 'error', None)
                or getattr(status_response, 'failure_reason', None)
                or 'Unknown provider error'
            )
            raise RuntimeError(f"Video generation failed ({current_status}): {err}")
    else:
        raise TimeoutError(f"Video generation timed out after {max_polls * poll_interval}s")

    video_url = getattr(status_response, 'video_url', None)
    if not video_url:
        raise ValueError("Video generation completed but no video_url in response")

    # Billing — track whatever cost LiteLLM reports on the completion response.
    # Sora/RunwayML pricing isn't in billing/pricing.py yet, so we rely on the
    # provider-reported cost (via litellm.completion_cost / response._hidden_params)
    # and skip billing if unavailable (logged, not silent).
    if not user_resource and node.user_id:
        try:
            from billing.usage_tracker import usage_tracker
            from billing.schema import UsageEventData
            from billing.markup import apply_openrouter_markup
            from decimal import Decimal

            raw_cost: Optional[Decimal] = None
            hidden = getattr(status_response, '_hidden_params', None) or {}
            if isinstance(hidden, dict) and hidden.get('response_cost') is not None:
                raw_cost = Decimal(str(hidden['response_cost']))
            if raw_cost is None:
                try:
                    computed = litellm.completion_cost(completion_response=status_response)
                    if computed:
                        raw_cost = Decimal(str(computed))
                except Exception:
                    raw_cost = None

            if raw_cost and raw_cost > 0:
                total_cost = apply_openrouter_markup(raw_cost, user_resource=False, model=config.model)
                usage_event = UsageEventData(
                    # Raw runner; track_usage_event resolves to the org owner centrally.
                    user_id=node.user_id,
                    total_cost=total_cost,
                    usage_type="ai_usage",
                    usage_subtype=config.model,
                    quantity=Decimal("1"),
                    unit_type="videos",
                    user_resource=False,
                    organization_id=node.organization_id,
                    metadata={"model": config.model, "video_id": video_id},
                )
                await usage_tracker.track_usage_event(
                    usage_event,
                    sio=node.sio,
                    sid=node.sid,
                )
                logger.info(f"[Video] Tracked LiteLLM billing: cost=${total_cost:.6f}")
            else:
                logger.warning(
                    f"[Video] No cost reported by LiteLLM for {config.model}; "
                    f"skipping usage tracking. Add pricing to billing/pricing.py."
                )
        except Exception as e:
            logger.warning(f"[Video] Failed to track LiteLLM billing: {e}")

    logger.info(f"[Video] Complete: {video_url[:80]}...")
    return {
        'type': 'agent',
        'status': 'completed',
        'response': 'Video generated successfully',
        'model': config.model,
        'temperature': config.temperature,
        'video_url': video_url,
        'videos': [{'url': video_url}],
    }
