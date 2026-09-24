"""
Image generation handler — DALL-E, Imagen, GPT image models, Gemini native.

Direct OpenRouter API call bypassing the LLM Agent wrapper, with R2 upload.
Imagen models route to a dedicated Gemini generateImages handler.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional

from nodes.agent.handlers._media_utils import fetch_image_as_base64
from utils.media_generation import (
    bill_openrouter,
    build_image_request,
    image_model_family,
    parse_image_response,
    post_image_request,
)

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

    is_gpt_image, _ = image_model_family(api_model)
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

    image_config = _get_openrouter_image_config(
        config,
        is_gemini_image,
        is_gpt_image,
    )
    seed = (
        _parse_optional_int(getattr(config, "openrouter_seed", ""), "OpenRouter seed")
        if is_gpt_image
        else None
    )
    body = build_image_request(
        api_model, messages, temperature=config.temperature,
        image_config=image_config or None, seed=seed,
    )

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

    raw_data = await post_image_request(api_key, body)
    text_content, extracted = parse_image_response(raw_data)
    logger.info(f"[Image] Response: total_images={len(extracted)}, text={len(text_content)} chars")

    # External HTTP URLs pass through unconditionally; data URIs are only
    # uploaded to R2 when workflow context is available.
    image_urls = []
    data_urls = [u for u in extracted if u.startswith("data:")]
    if data_urls:
        if node.user_id and node.workflow_id:
            image_urls = await node._upload_images_to_r2(data_urls)
        else:
            logger.warning(
                f"[Image] Skipping R2 upload for {len(data_urls)} data URI(s): "
                f"missing user_id/workflow_id"
            )
    image_urls.extend({"url": u} for u in extracted if u.startswith("http"))

    usage_data = raw_data.get("usage", {})
    if user_id:
        try:
            from decimal import Decimal

            charged = await bill_openrouter(
                # The raw runner; track_usage_event resolves the org owner
                # centrally and records the runner as metadata.actual_user_id.
                user_id=user_id,
                organization_id=node.organization_id,
                model=config.model,
                dollars=Decimal(str(usage_data.get("cost") or 0)),
                user_resource=user_resource,
                quantity=Decimal(str(usage_data.get("total_tokens", 0))),
                unit_type="tokens",
                metadata={
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "model": config.model,
                    "response_id": raw_data.get("id"),
                },
                sio=node.sio,
                sid=node.sid,
            )
            logger.info(f"[Image] Tracked cost: ${charged}")
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
