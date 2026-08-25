"""
Image generation handler — DALL-E, Imagen, GPT image models, Gemini native.

Direct OpenRouter API call bypassing the LLM Agent wrapper, with R2 upload.
Imagen models route to a dedicated Gemini generateImages handler.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, Optional

from nodes.agent.handlers._media_utils import fetch_image_as_base64

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _parse_gemini_image_urls(value: str) -> list:
    """Parse gemini_reference_image_url into a list of URL/resource-ID strings."""
    v = (value or "").strip()
    if not v:
        return []
    if v.startswith("["):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(u).strip() for u in parsed if u and str(u).strip()]
        except (json.JSONDecodeError, ValueError):
            pass
    if "," in v:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        if len(parts) > 1:
            return parts
    return [v]


def _is_valid_image_ref(ref: str) -> bool:
    """Return True if ref is a valid HTTP URL, data URI, or resource UUID."""
    ref = ref.strip()
    return bool(
        ref
        and (
            ref.startswith(("http://", "https://", "data:"))
            or (len(ref) == 36 and ref.count("-") == 4)
        )
    )


def _get_openrouter_image_config(
    config,
    is_gemini_image: bool,
    is_gpt_image: bool,
) -> Dict[str, Any]:
    """Build OpenRouter image_config for models that support image generation controls."""
    image_config: Dict[str, Any] = {}

    if is_gpt_image:
        aspect = getattr(config, "openrouter_image_aspect_ratio", "") or ""
        size = getattr(config, "openrouter_image_size", "") or ""
    elif is_gemini_image:
        aspect = getattr(config, "gemini_aspect_ratio", "") or ""
        size = getattr(config, "gemini_image_size", "") or ""
    else:
        return image_config

    if aspect and aspect != "1:1":
        image_config["aspect_ratio"] = aspect
    if size and size != "1K":
        image_config["image_size"] = size

    return image_config


def _parse_optional_int(value: Any, field_name: str) -> Optional[int]:
    """Parse optional integer config fields without silently accepting bad input."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


async def execute_image_model(
    node,
    config,
    env_overrides: Optional[Dict[str, str]],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Direct LLM call for image generation models, bypassing the LLM Agent wrapper."""
    import asyncio
    import httpx

    # Imagen models (imagen-3.x, imagen-4.x) use the Gemini generateImages endpoint,
    # not the OpenRouter chat completions endpoint used by generic image models.
    model_lower = config.model.lower()
    if "imagen" in model_lower and "openrouter/" not in model_lower:
        from nodes.agent.handlers.imagen import execute_imagen_model

        return await execute_imagen_model(node, config, env_overrides, user_id)

    # Resolve API key
    api_key = None
    if env_overrides:
        api_key = env_overrides.get("OPENROUTER_API_KEY")
    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not available for image model")

    # Strip openrouter/ prefix — done first so model type detection works
    api_model = config.model.removeprefix("openrouter/")
    api_model_lower = api_model.lower()

    is_gpt_image = "gpt" in api_model_lower and "image" in api_model_lower
    # DALL-E is image-only (no text output); all other image models output text+image
    is_dalle = "dall-e" in api_model_lower or "dalle" in api_model_lower
    # Google/Gemini native image models support image_config + multimodal input via OpenRouter
    is_gemini_image = any(
        kw in api_model_lower
        for kw in [
            "google/",
            "gemini-2.0-flash-preview-image",
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image",
            "gemini-3-pro-image",
        ]
    )

    # Build messages — inject reference images as multimodal content for Gemini native models
    messages = []
    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})
    _ref_urls = [
        u
        for u in _parse_gemini_image_urls(
            getattr(config, "gemini_reference_image_url", "") or ""
        )
        if _is_valid_image_ref(u)
    ]
    logger.info(
        f"[Image] Reference images — raw: "
        f"{repr((getattr(config, 'gemini_reference_image_url', '') or '')[:200])}, "
        f"valid URLs: {len(_ref_urls)}"
    )
    if (is_gemini_image or is_gpt_image) and _ref_urls:
        content: list = [{"type": "text", "text": config.message}]
        for _ref_url in _ref_urls:
            try:
                img_b64, mime_type = await fetch_image_as_base64(_ref_url)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    }
                )
            except Exception as fetch_err:
                logger.warning(
                    f"[Image] Failed to fetch reference image, skipping: {_ref_url[:100]!r} — {fetch_err}"
                )
        if len(content) == 1:
            messages.append({"role": "user", "content": config.message})
        else:
            messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": config.message})

    body: Dict[str, Any] = {
        "model": api_model,
        "messages": messages,
        "stream": False,
        "modalities": ["image"] if is_dalle else ["image", "text"],
        "provider": {"sort": "throughput"},
    }
    if config.temperature is not None and not is_gpt_image and not is_dalle:
        body["temperature"] = config.temperature

    image_config = _get_openrouter_image_config(
        config,
        is_gemini_image,
        is_gpt_image,
    )
    if image_config:
        body["image_config"] = image_config

    if is_gpt_image:
        seed = _parse_optional_int(
            getattr(config, "openrouter_seed", ""),
            "OpenRouter seed",
        )
        if seed is not None:
            body["seed"] = seed

    await node.emit({"type": "agent", "status": "running"})

    # Standardized pre-flight gate (strict owner resolution + balance check +
    # exhausted-event emit + abort). See usage_tracker.enforce_credit_gate.
    user_resource = env_overrides is not None
    if user_id:
        from billing.usage_tracker import usage_tracker as _usage_tracker
        await _usage_tracker.enforce_credit_gate(
            user_id,
            organization_id=node.organization_id,
            sio=node.sio,
            sid=node.sid,
            user_resource=user_resource,
            surface="image",
        )

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://noclick.com",
                "X-Title": "NoClick",
            },
            json=body,
        )
        if resp.status_code >= 400:
            error_body = resp.text
            logger.error(
                f"[Image] OpenRouter API error {resp.status_code}: {error_body}"
            )
            raise RuntimeError(
                f"OpenRouter image request failed with HTTP {resp.status_code}: "
                f"{error_body[:1000]}"
            )
        raw_data = resp.json()

    raw_choice = raw_data.get("choices", [{}])[0]

    # Check for inline errors
    choice_error = raw_choice.get("error")
    if choice_error:
        err_code = choice_error.get("code") if isinstance(choice_error, dict) else None
        err_msg = (
            choice_error.get("message", str(choice_error))
            if isinstance(choice_error, dict)
            else str(choice_error)
        )
        err_type = (
            (choice_error.get("metadata") or {}).get("error_type", "")
            if isinstance(choice_error, dict)
            else ""
        )
        logger.error(
            f"[Image] OpenRouter error in choice: code={err_code}, type={err_type}, msg={err_msg}"
        )
        is_rate_limit = (
            err_code == 429
            or err_type == "rate_limit_exceeded"
            or "rate_limit" in str(choice_error).lower()
        )
        if is_rate_limit:
            raise RuntimeError(f"Image model rate-limited by provider (429): {err_msg}")
        raise RuntimeError(
            f"Image model error from provider (code={err_code}): {err_msg}"
        )

    raw_message = raw_choice.get("message", {})
    content = raw_message.get("content")

    # Parse content blocks
    text_parts: list[str] = []
    content_image_blocks: list[dict] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "image_url":
                content_image_blocks.append(block)
    elif isinstance(content, str):
        text_parts.append(content)

    text_content = "".join(text_parts)

    # Extract reasoning_details images
    reasoning_image_blocks: list[dict] = []
    reasoning_details = raw_message.get("reasoning_details") or []
    if isinstance(reasoning_details, list):
        for block in reasoning_details:
            if isinstance(block, dict) and block.get("type", "") in (
                "image",
                "image_url",
            ):
                reasoning_image_blocks.append(block)

    # Merge all image sources
    choice_images = list(raw_choice.get("images") or [])
    raw_images = (
        list(raw_message.get("images") or [])
        + choice_images
        + content_image_blocks
        + reasoning_image_blocks
    )

    logger.info(
        f"[Image] Response: content_blocks={len(content) if isinstance(content, list) else 'n/a'}, "
        f"total_images={len(raw_images)}, text={len(text_content)} chars"
    )

    if not raw_images and not text_content:
        native_finish = raw_choice.get("native_finish_reason", "unknown")
        native_upper = str(native_finish).upper()
        if (
            "PROHIBITED_CONTENT" in native_upper
            or "CONTENT_FILTER" in native_upper
            or "SAFETY" in native_upper
        ):
            raise RuntimeError(
                f"Image generation blocked by content policy ({native_finish}). "
                f"Try a different prompt or a different image model."
            )
        raise RuntimeError(
            f"Image model returned no image and no text (native_finish={native_finish}). "
            f"Try again or use a different image model."
        )

    def _extract_image_url(img: dict) -> str:
        url = img.get("url", "")
        if url:
            return url
        image_url = img.get("image_url", "")
        if isinstance(image_url, str) and image_url:
            return image_url
        if isinstance(image_url, dict):
            u = image_url.get("url", "")
            if u:
                return u
        data = img.get("data", "")
        if data:
            media_type = img.get("media_type", "image/png")
            return f"data:{media_type};base64,{data}"
        return ""

    # Assemble image URLs — external HTTP URLs pass through unconditionally;
    # data URIs are only uploaded to R2 when workflow context is available.
    image_urls = []
    if raw_images:
        extracted = [_extract_image_url(img) for img in raw_images]
        data_urls = [u for u in extracted if u.startswith("data:")]
        external_urls = [u for u in extracted if u.startswith("http")]
        if data_urls:
            if node.user_id and node.workflow_id:
                image_urls = await node._upload_images_to_r2(data_urls)
            else:
                logger.warning(
                    f"[Image] Skipping R2 upload for {len(data_urls)} data URI(s): "
                    f"missing user_id/workflow_id"
                )
        for ext_url in external_urls:
            image_urls.append({"url": ext_url})

    # Track billing
    usage_data = raw_data.get("usage", {})
    cost = usage_data.get("cost")
    if user_id:
        try:
            from billing.usage_tracker import usage_tracker
            from billing.schema import UsageEventData
            from decimal import Decimal
            from billing.markup import apply_openrouter_markup

            total_cost = Decimal(str(cost)) if cost else Decimal("0")
            total_cost = apply_openrouter_markup(
                total_cost, user_resource, config.model
            )
            total_tokens = usage_data.get("total_tokens", 0)

            usage_event = UsageEventData(
                # Pass the raw runner; track_usage_event resolves to the org
                # owner centrally (organization attribution policy choke point) and records the runner
                # as metadata.actual_user_id.
                user_id=user_id,
                total_cost=total_cost,
                usage_type="ai_usage",
                usage_subtype=config.model,
                quantity=Decimal(str(total_tokens)),
                unit_type="tokens",
                user_resource=user_resource,
                organization_id=node.organization_id,
                metadata={
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "model": config.model,
                    "response_id": raw_data.get("id"),
                },
            )
            await usage_tracker.track_usage_event(
                usage_event,
                sio=node.sio,
                sid=node.sid,
            )
            logger.info(f"[Image] Tracked cost: ${total_cost}, tokens={total_tokens}")
        except Exception as e:
            logger.warning(f"[Image] Failed to track cost: {e}")

    output = {
        "type": "agent",
        "status": "completed",
        "response": text_content,
        "model": config.model,
        "temperature": config.temperature,
    }
    if image_urls:
        output["images"] = image_urls
        output["image_url"] = image_urls[0]["url"]

    return output
