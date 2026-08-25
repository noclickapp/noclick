"""
Imagen image generation handler — direct Gemini API (generateImages endpoint).

Unlike Gemini native image gen (which uses generateContent via OpenRouter),
Imagen models use a dedicated generateImages endpoint that supports parameters
such as negativePrompt, guidanceScale, seed, personGeneration, enhancePrompt,
addWatermark, safetySetting, and outputOptions.
"""

import asyncio
import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def execute_imagen_model(
    node,
    config,
    env_overrides: Optional[Dict[str, str]],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Direct call to Gemini API's generateImages endpoint for Imagen 3/4 models."""
    import asyncio
    import httpx

    api_key = None
    if env_overrides:
        api_key = env_overrides.get('GEMINI_API_KEY') or env_overrides.get('GOOGLE_API_KEY')
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY required for Imagen image generation")

    user_resource = env_overrides is not None

    # Standardized pre-flight gate (strict owner resolution + balance check +
    # exhausted-event emit + abort). See usage_tracker.enforce_credit_gate.
    if user_id:
        from billing.usage_tracker import usage_tracker as _usage_tracker
        await _usage_tracker.enforce_credit_gate(
            user_id,
            organization_id=node.organization_id,
            sio=node.sio,
            sid=node.sid,
            user_resource=user_resource,
            surface="imagen",
        )

    # Strip provider prefix: "gemini/imagen-3.0-generate-001" → "imagen-3.0-generate-001"
    model_name = config.model
    for prefix in ('gemini/', 'google/'):
        model_name = model_name.removeprefix(prefix)

    prompt = f"{config.system_prompt}\n\n{config.message}" if config.system_prompt else config.message

    # Build generateImages request body
    n_images = max(1, min(4, int(getattr(config, 'gemini_num_images', None) or 1)))
    body: Dict[str, Any] = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": n_images,
            "aspectRatio": getattr(config, 'gemini_aspect_ratio', None) or "1:1",
        },
    }
    params = body["parameters"]

    if getattr(config, 'imagen_negative_prompt', None):
        params["negativePrompt"] = config.imagen_negative_prompt
    if getattr(config, 'imagen_guidance_scale', None):
        try:
            params["guidanceScale"] = float(config.imagen_guidance_scale)
        except ValueError:
            pass
    if getattr(config, 'imagen_seed', None):
        try:
            params["seed"] = int(config.imagen_seed)
        except ValueError:
            pass
    if getattr(config, 'imagen_person_generation', None):
        params["personGeneration"] = config.imagen_person_generation
    if getattr(config, 'imagen_safety_setting', None):
        params["safetySetting"] = config.imagen_safety_setting
    if getattr(config, 'imagen_add_watermark', None) == "false":
        params["addWatermark"] = False
    # enhancePrompt: only Imagen 4
    if "imagen-4" in model_name.lower() and getattr(config, 'imagen_enhance_prompt', None):
        params["enhancePrompt"] = config.imagen_enhance_prompt == "true"
    output_mime = getattr(config, 'imagen_output_mime_type', None)
    if output_mime:
        params["outputOptions"] = {"mimeType": output_mime}

    await node.emit({'type': 'agent', 'status': 'running'})

    base_url = "https://generativelanguage.googleapis.com/v1beta"
    endpoint = f"{base_url}/models/{model_name}:generateImages"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(endpoint, headers=headers, json=body)
        if resp.status_code >= 400:
            error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_body.get("error", {}).get("message", resp.text)
            logger.error(f"[Imagen] API error {resp.status_code}: {resp.text}")
            raise ValueError(f"Imagen API error: {error_msg}")
        raw_data = resp.json()

    # Extract generated images: [{image: {imageBytes: "<base64>", mimeType: "image/png"}}]
    generated = raw_data.get("generatedImages") or raw_data.get("predictions") or []
    data_urls = []
    for item in generated:
        img = item.get("image") or item
        img_bytes = img.get("imageBytes") or img.get("bytesBase64Encoded", "")
        mime = img.get("mimeType", output_mime or "image/png")
        if img_bytes:
            data_urls.append(f"data:{mime};base64,{img_bytes}")

    if not data_urls:
        rai_reason = raw_data.get("raiFilteredReason") or raw_data.get("filterReason")
        if rai_reason:
            raise RuntimeError(f"Imagen blocked by content policy: {rai_reason}")
        raise RuntimeError("Imagen returned no images. Try a different prompt.")

    if node.user_id and node.workflow_id:
        image_urls = await node._upload_images_to_r2(data_urls)
    else:
        image_urls = [{"url": u} for u in data_urls]

    # Billing: Imagen 3 ~$0.04/image, Imagen 4 ~$0.08/image (wholesale — marked up to user).
    if user_id and not user_resource:
        try:
            from billing.usage_tracker import usage_tracker
            from billing.schema import UsageEventData
            from billing.markup import apply_gemini_markup

            per_image = Decimal("0.08") if "imagen-4" in model_name.lower() else Decimal("0.04")
            raw_cost = per_image * n_images
            total_cost = apply_gemini_markup(raw_cost, user_resource=False, model=config.model)
            usage_event = UsageEventData(
                # Raw runner; track_usage_event resolves to the org owner centrally.
                user_id=user_id,
                total_cost=total_cost,
                usage_type="ai_usage",
                usage_subtype=config.model,
                quantity=Decimal(str(n_images)),
                unit_type="images",
                user_resource=user_resource,
                organization_id=node.organization_id,
                metadata={"model": config.model, "n_images": n_images},
            )
            await usage_tracker.track_usage_event(
                usage_event,
                sio=node.sio,
                sid=node.sid,
            )
        except Exception as e:
            logger.warning(f"[Imagen] Failed to track cost: {e}")

    output: Dict[str, Any] = {
        'type': 'agent',
        'status': 'completed',
        'response': '',
        'model': config.model,
    }
    if image_urls:
        output['images'] = image_urls
        output['image_url'] = image_urls[0]['url']
    return output
