"""Image and video generation through OpenRouter, independent of any node.

Images: the agent node's image handler (chat completions with image
``modalities``) builds, sends, parses and bills through the helpers here;
``generate_image`` uses OpenRouter's dedicated ``/api/v1/images`` endpoint,
where image-output models such as the gpt-image family live. Videos are asynchronous (``/api/v1/videos``):
``start_video`` checks the request against the model's published limits,
prices the job from its per-second SKUs,
gates it (``billing/gates.py``) and records a ``video`` coordinator job;
``poll_video_jobs`` (run by the per-minute coordinator reconcile) finishes
it — download, store, bill the provider's reported cost — and wakes the
coordinator with the result.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API = "https://openrouter.ai/api/v1"
DEFAULT_IMAGE_MODEL = "openai/gpt-image-2.5-sunburst"
DEFAULT_VIDEO_MODEL = "google/veo-3.1-fast"
DEFAULT_VIDEO_SECONDS = 8
DEFAULT_VIDEO_RESOLUTION = "720p"
VIDEO_TIMEOUT_S = 30 * 60           # a job still pending after this is failed
VIDEO_MAX_BYTES = 200 * 1024 * 1024
_PRICING_TTL_S = 60 * 60
_pricing_cache: Dict[str, Any] = {"at": None, "models": {}}


class MediaError(RuntimeError):
    """A generation the person should hear about in plain words."""


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise MediaError("Media generation isn't configured on this instance (no OpenRouter key).")
    return key


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://noclick.com",
        "X-Title": "NoClick",
    }


# ── images ───────────────────────────────────────────────────────────────────

def image_model_family(model: str) -> Tuple[bool, bool]:
    """(is_gpt_image, is_dalle) for an OpenRouter image model id."""
    m = model.lower()
    return ("gpt" in m and "image" in m), ("dall-e" in m or "dalle" in m)


def build_image_request(
    model: str, messages: List[Dict[str, Any]], *, temperature: Optional[float] = None,
    image_config: Optional[Dict[str, Any]] = None, seed: Optional[int] = None,
) -> Dict[str, Any]:
    is_gpt_image, is_dalle = image_model_family(model)
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        # DALL-E is image-only; every other image model answers text + image.
        "modalities": ["image"] if is_dalle else ["image", "text"],
        "provider": {"sort": "throughput"},
    }
    if temperature is not None and not is_gpt_image and not is_dalle:
        body["temperature"] = temperature
    if image_config:
        body["image_config"] = image_config
    if is_gpt_image and seed is not None:
        body["seed"] = seed
    return body


async def post_image_request(api_key: str, body: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{OPENROUTER_API}/chat/completions", headers=_headers(api_key), json=body)
    if resp.status_code >= 400:
        logger.error("[Image] OpenRouter API error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(
            f"OpenRouter image request failed with HTTP {resp.status_code}: {resp.text[:1000]}"
        )
    return resp.json()


def _image_url(img: Dict[str, Any]) -> str:
    url = img.get("url", "")
    if url:
        return url
    image_url = img.get("image_url", "")
    if isinstance(image_url, str) and image_url:
        return image_url
    if isinstance(image_url, dict) and image_url.get("url"):
        return image_url["url"]
    data = img.get("data", "")
    if data:
        return f"data:{img.get('media_type', 'image/png')};base64,{data}"
    return ""


def parse_image_response(raw: Dict[str, Any]) -> Tuple[str, List[str]]:
    """(text, image urls — data URIs or http) from a chat-completions reply,
    wherever the provider put the images; a provider error or an empty reply
    raises with the provider's own reason."""
    choice = (raw.get("choices") or [{}])[0]
    error = choice.get("error")
    if error:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        kind = ((error.get("metadata") or {}).get("error_type", "") if isinstance(error, dict) else "")
        logger.error("[Image] OpenRouter error in choice: code=%s, type=%s, msg=%s", code, kind, message)
        if code == 429 or kind == "rate_limit_exceeded" or "rate_limit" in str(error).lower():
            raise RuntimeError(f"Image model rate-limited by provider (429): {message}")
        raise RuntimeError(f"Image model error from provider (code={code}): {message}")

    message = choice.get("message", {})
    content = message.get("content")
    texts: List[str] = []
    blocks: List[Dict[str, Any]] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "image_url":
                blocks.append(block)
    elif isinstance(content, str):
        texts.append(content)
    reasoning = [b for b in (message.get("reasoning_details") or [])
                 if isinstance(b, dict) and b.get("type") in ("image", "image_url")]
    images = list(message.get("images") or []) + list(choice.get("images") or []) + blocks + reasoning
    text = "".join(texts)
    if not images and not text:
        finish = str(choice.get("native_finish_reason", "unknown"))
        if any(k in finish.upper() for k in ("PROHIBITED_CONTENT", "CONTENT_FILTER", "SAFETY")):
            raise RuntimeError(
                f"Image generation blocked by content policy ({finish}). "
                f"Try a different prompt or a different image model."
            )
        raise RuntimeError(
            f"Image model returned no image and no text (native_finish={finish}). "
            f"Try again or use a different image model."
        )
    return text, [u for u in (_image_url(img) for img in images) if u]


async def bill_openrouter(
    *, user_id: str, organization_id: Optional[str], model: str, dollars: Decimal,
    user_resource: bool, quantity: Decimal, unit_type: str, metadata: Dict[str, Any],
    sio=None, sid=None,
) -> Decimal:
    """Charge a provider cost with the OpenRouter markup; returns what was charged."""
    from billing.markup import apply_openrouter_markup
    from billing.schema import UsageEventData
    from billing.usage_tracker import usage_tracker

    total = apply_openrouter_markup(dollars, user_resource, model)
    await usage_tracker.track_usage_event(UsageEventData(
        user_id=user_id, total_cost=total, usage_type="ai_usage", usage_subtype=model,
        quantity=quantity, unit_type=unit_type, user_resource=user_resource,
        organization_id=organization_id, metadata=metadata,
    ), sio=sio, sid=sid)
    return total


async def _store(
    *, user_id: str, organization_id: Optional[str], body: bytes, content_type: str,
    filename: str, resource_type: str, metadata: Dict[str, Any],
) -> Dict[str, Any]:
    from utils.resource_store import create_resource_from_bytes

    stored = await create_resource_from_bytes(
        user_id=user_id, workflow_id=None, organization_id=organization_id, body=body,
        content_type=content_type, filename=filename, resource_type=resource_type, metadata=metadata,
    )
    return {"url": stored["download_url"], "resource_id": stored["resource_id"], "mime_type": content_type}


async def generate_image(
    pool, *, user_id: str, organization_id: Optional[str], prompt: str,
    model: Optional[str] = None, aspect_ratio: Optional[str] = None, email: Optional[str] = None,
) -> Dict[str, Any]:
    """One image on the platform key through OpenRouter's image endpoint
    (``/api/v1/images``, where image-output models live), stored as account
    files and billed to the account (its org owner under Owner Pays)."""
    from billing.gates import check_product
    from billing.usage_tracker import usage_tracker

    model = (model or DEFAULT_IMAGE_MODEL).removeprefix("openrouter/")
    await check_product(pool, "image_generation", user_id=user_id, email=email)
    await usage_tracker.enforce_credit_gate(user_id, organization_id=organization_id, user_resource=False,
                                            surface="image")
    body: Dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{OPENROUTER_API}/images", headers=_headers(_api_key()), json=body)
    if resp.status_code >= 400:
        logger.error("[Image] OpenRouter images error %s: %s", resp.status_code, resp.text)
        raise MediaError(f"The image model refused the request (HTTP {resp.status_code}): {resp.text[:300]}")
    raw = resp.json()
    images = []
    for i, item in enumerate(raw.get("data") or []):
        if not item.get("b64_json"):
            continue
        mime = item.get("media_type") or "image/png"
        ext = {"image/svg+xml": "svg", "image/jpeg": "jpg"}.get(mime, mime.split("/")[-1])
        images.append(await _store(
            user_id=user_id, organization_id=organization_id, body=base64.b64decode(item["b64_json"]),
            content_type=mime, filename=f"image-{i + 1}.{ext}", resource_type="image",
            metadata={"source": "coordinator", "model": model, "prompt": prompt[:500]},
        ))
    if not images:
        raise MediaError("The image model answered without an image; try rewording the request.")
    usage = raw.get("usage") or {}
    charged = await bill_openrouter(
        user_id=user_id, organization_id=organization_id, model=model,
        dollars=Decimal(str(usage.get("cost") or 0)), user_resource=False,
        quantity=Decimal(len(images)), unit_type="images",
        metadata={"model": model, "surface": "coordinator_image"},
    )
    return {"images": images, "model": model, "cost_usd": float(charged)}


# ── videos ───────────────────────────────────────────────────────────────────

async def video_model(model: str) -> Optional[Dict[str, Any]]:
    """OpenRouter's spec for a video model — ``pricing_skus`` and the
    supported durations, resolutions and aspect ratios (cached an hour)."""
    fetched_at = _pricing_cache["at"]
    if fetched_at is None or time.monotonic() - fetched_at > _PRICING_TTL_S:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{OPENROUTER_API}/videos/models")
            resp.raise_for_status()
        _pricing_cache["models"] = {m["id"]: m for m in resp.json().get("data", [])}
        _pricing_cache["at"] = time.monotonic()
    return _pricing_cache["models"].get(model)


def _supported(spec: Dict[str, Any], field: str, value: Any, label: str) -> None:
    allowed = spec.get(field)
    if allowed and value not in allowed:
        raise MediaError(f"{spec['id']} supports {label} {', '.join(str(a) for a in allowed)}; not {value}.")


def projected_video_dollars(
    pricing: Dict[str, str], *, seconds: int, resolution: str, audio: bool,
) -> Optional[Decimal]:
    """Provider cost of one clip from its per-second SKUs; None for a model
    priced some other way (e.g. by video tokens), which can't be projected."""
    res = resolution.lower()
    sound = "with_audio" if audio else "without_audio"
    for key in (f"duration_seconds_{sound}_{res}", f"duration_seconds_{sound}",
                f"text_to_video_duration_seconds_{res}", f"duration_seconds_{res}", "duration_seconds"):
        if key in pricing:
            return Decimal(pricing[key]) * seconds
    for key in (f"cents_per_second_output_{res}", "cents_per_second_output",
                f"cents_per_video_output_second_{res}"):
        if key in pricing:
            dollars = Decimal(pricing[key]) / 100 * seconds
            floor = pricing.get("minimum_cents_per_generation")
            return max(dollars, Decimal(floor) / 100) if floor else dollars
    return None


def dollars_as_credits(dollars: Decimal, model: str) -> float:
    from billing.markup import apply_openrouter_markup, dollars_to_credits

    return float(dollars_to_credits(apply_openrouter_markup(dollars, False, model)))


async def start_video(
    pool, *, user_id: str, organization_id: Optional[str], prompt: str, model: Optional[str] = None,
    seconds: Optional[int] = None, resolution: Optional[str] = None, aspect_ratio: Optional[str] = None,
    audio: bool = True, email: Optional[str] = None, continuation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Price, gate and submit one video; the job finishes in the background."""
    from billing.gates import check_product

    model = (model or DEFAULT_VIDEO_MODEL).removeprefix("openrouter/")
    seconds = int(seconds or DEFAULT_VIDEO_SECONDS)
    resolution = (resolution or DEFAULT_VIDEO_RESOLUTION).lower()
    spec = await video_model(model)
    if spec is None:
        raise MediaError(f"{model} isn't an OpenRouter video model.")
    _supported(spec, "supported_durations", seconds, "durations (seconds)")
    _supported(spec, "supported_resolutions", resolution, "resolutions")
    if aspect_ratio:
        _supported(spec, "supported_aspect_ratios", aspect_ratio, "aspect ratios")
    audio = audio and bool(spec.get("generate_audio", True))
    dollars = projected_video_dollars(spec.get("pricing_skus") or {}, seconds=seconds, resolution=resolution, audio=audio)
    if dollars is None:
        raise MediaError(f"{model} can't be priced before it runs; pick a model priced per second.")
    credits = dollars_as_credits(dollars, model)
    await check_product(pool, "video_generation", user_id=user_id, email=email, projected_credits=credits)

    params: Dict[str, Any] = {"duration": seconds, "resolution": resolution, "generate_audio": audio}
    if aspect_ratio:
        params["aspect_ratio"] = aspect_ratio
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{OPENROUTER_API}/videos", headers=_headers(_api_key()),
                                 json={"model": model, "prompt": prompt, **params})
    if resp.status_code >= 400:
        raise MediaError(f"The video model refused the request (HTTP {resp.status_code}): {resp.text[:300]}")
    submitted = resp.json()
    job_id = await pool.fetchval(
        """INSERT INTO coordinator_jobs (user_id, kind, status, spec, origin, continuation, send_to_phone)
           VALUES ($1::uuid, 'video', 'running', $2, '{"source": "coordinator"}'::jsonb, $3, $4) RETURNING id""",
        user_id, {"model": model, "prompt": prompt, "params": params, "provider_job_id": submitted["id"],
                  "projected_credits": credits, "organization_id": organization_id},
        continuation, (continuation or {}).get("channel", "web") != "web",
    )
    logger.info("[Video] submitted job=%s provider=%s model=%s credits=%.2f", job_id, submitted["id"], model, credits)
    return {"job_id": str(job_id), "model": model, "seconds": seconds, "resolution": resolution,
            "projected_credits": round(credits, 2)}


def video_view(row: Dict[str, Any]) -> Dict[str, Any]:
    spec = row["spec"]
    return {"job_id": str(row["id"]), "kind": "video", "status": row["status"], "model": spec["model"],
            "prompt": spec["prompt"][:500], "seconds": spec["params"].get("duration"),
            "resolution": spec["params"].get("resolution"), "projected_credits": round(spec["projected_credits"], 2),
            "result": row["result"], "error": row["error"]}


def video_summary(payload: Dict[str, Any]) -> str:
    if payload.get("result"):
        return f"Your video is ready: {payload['result']['url']}"
    return f"The video couldn't be made: {(payload.get('error') or '')[:500]}"


async def _poll_one(pool, client: httpx.AsyncClient, api_key: str, job: Dict[str, Any]) -> None:
    from coder.coordinator.jobs import finish_job

    spec = job["spec"]
    resp = await client.get(f"{OPENROUTER_API}/videos/{spec['provider_job_id']}", headers=_headers(api_key))
    resp.raise_for_status()
    state = resp.json()
    status = state.get("status")
    if status == "failed":
        await finish_job(pool, job["id"], status="failed", error=str(state.get("error") or "The video model failed.")[:1000])
        return
    if status != "completed":
        if time.time() - job["created_at"].timestamp() > VIDEO_TIMEOUT_S:
            await finish_job(pool, job["id"], status="failed", error="The video took too long and was abandoned.")
        return
    content = await client.get(f"{OPENROUTER_API}/videos/{spec['provider_job_id']}/content",
                               params={"index": 0}, headers=_headers(api_key), follow_redirects=True)
    content.raise_for_status()
    if len(content.content) > VIDEO_MAX_BYTES:
        await finish_job(pool, job["id"], status="failed", error="The video was larger than NoClick keeps.")
        return
    user_id, org = str(job["user_id"]), spec.get("organization_id")
    stored = await _store(
        user_id=user_id, organization_id=org, body=content.content,
        content_type=content.headers.get("content-type", "video/mp4").split(";")[0], filename="video.mp4",
        resource_type="video", metadata={"source": "coordinator", "model": spec["model"], "prompt": spec["prompt"][:500]},
    )
    reported = (state.get("usage") or {}).get("cost")
    if reported is None:
        # The job was priced from the provider's own SKUs before it ran.
        logger.warning("[Video] job %s reported no cost; charging its projection", job["id"])
        params = spec["params"]
        pricing = ((await video_model(spec["model"])) or {}).get("pricing_skus") or {}
        dollars = projected_video_dollars(pricing, seconds=params.get("duration", DEFAULT_VIDEO_SECONDS),
                                          resolution=params.get("resolution", DEFAULT_VIDEO_RESOLUTION),
                                          audio=params.get("generate_audio", True)) or Decimal(0)
    else:
        dollars = Decimal(str(reported))
    await bill_openrouter(
        user_id=user_id, organization_id=org, model=spec["model"], dollars=dollars, user_resource=False,
        quantity=Decimal(str(spec["params"].get("duration", DEFAULT_VIDEO_SECONDS))), unit_type="seconds",
        metadata={"model": spec["model"], "coordinator_job_id": str(job["id"]), "surface": "coordinator_video"},
    )
    await finish_job(pool, job["id"], status="completed", result={**stored, "cost_usd": float(dollars)})


async def poll_video_jobs(pool, limit: int = 20) -> None:
    """Advance running video jobs; each job is leased so two pollers never
    finish (and bill) the same one."""
    jobs = await pool.fetch(
        """WITH due AS (SELECT id FROM coordinator_jobs WHERE kind='video' AND status='running'
             AND (lease_until IS NULL OR lease_until < now()) ORDER BY created_at LIMIT $1 FOR UPDATE SKIP LOCKED)
           UPDATE coordinator_jobs j SET lease_until = now() + interval '5 minutes' FROM due WHERE j.id = due.id
           RETURNING j.*""", limit,
    )
    if not jobs:
        return
    api_key = _api_key()
    async with httpx.AsyncClient(timeout=120.0) as client:
        for job in jobs:
            try:
                await _poll_one(pool, client, api_key, dict(job))
            except Exception:
                logger.exception("[Video] polling job %s failed; it retries next minute", job["id"])
            # Still rendering (or a failed poll): the next minute looks again.
            await pool.execute("UPDATE coordinator_jobs SET lease_until = NULL WHERE id = $1 AND status = 'running'",
                               job["id"])
