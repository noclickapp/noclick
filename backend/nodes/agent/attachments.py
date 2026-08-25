"""User-attached files on an agent chat turn (config.message_attachments).

Pure helpers shared by AgentNode._execute_impl: normalize the raw FE payload,
split image vs file attachments for chat-history persistence, and format the
pre-dispatch message block all six harnesses (SDK llm + 5 CLI sandboxes) see.
The block carries permanent resource URLs (the CDN when hosted, the operator's
own storage when self-hosted — see utils.hosted_defaults) — the SDK path's inline
image extraction (handlers/_media_utils.extract_inline_image_urls) turns image
URLs into vision blocks, and CLI harnesses fetch any URL from the sandbox.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ATTACHMENTS_BLOCK_HEADER = "--- Attached files ---"

# Media fast-path model types (agent_node's dispatch fork). For these,
# config.message is the GENERATION PROMPT — attached images must ride the
# handlers' structured input-image seams, never the message text.
MEDIA_MODEL_TYPES = ("image", "video", "kling")

# Composed under the URL list so agents know the files are user-provided and
# how to reach non-image contents (SDK vision handles images separately).
_ATTACHMENTS_BLOCK_HINT = (
    "The user attached these files to this message. "
    "Fetch a URL (e.g. with curl) if you need a file's contents."
)


def normalize_message_attachments(raw: Any) -> List[Dict[str, Any]]:
    """Validate + normalize ``config.message_attachments`` into
    ``[{url, name, mime_type, size_bytes, resource_id}]``. Entries without a
    usable http(s) URL are dropped — the URL is the one field every consumer
    (message block, persistence, vision injection) needs."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        name = item.get("name")
        size = item.get("size_bytes")
        out.append({
            "url": url,
            "name": (str(name).strip() if name else "") or url.rsplit("/", 1)[-1],
            "mime_type": str(item.get("mime_type") or "application/octet-stream").lower(),
            "size_bytes": int(size) if isinstance(size, (int, float)) and size >= 0 else None,
            "resource_id": str(item["resource_id"]) if item.get("resource_id") else None,
        })
    return out


def split_attachment_media(
    attachments: List[Dict[str, Any]],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """(image_urls, file_attachments) for chat-history persistence: images
    restore as image_url content items (the transcript already renders them),
    other files restore as chip metadata on the user bubble."""
    image_urls = [a["url"] for a in attachments if a["mime_type"].startswith("image/")]
    files = [
        {"name": a["name"], "url": a["url"], "mime_type": a["mime_type"]}
        for a in attachments
        if not a["mime_type"].startswith("image/")
    ]
    return image_urls, files


def _human_size(size_bytes: Optional[int]) -> Optional[str]:
    if size_bytes is None:
        return None
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return None


def format_attachments_block(attachments: List[Dict[str, Any]]) -> str:
    """The message block delivered to the model — one line per file with name,
    mime, size, and the fetchable URL."""
    lines = []
    for a in attachments:
        meta = a["mime_type"]
        size = _human_size(a["size_bytes"])
        if size:
            meta += f", {size}"
        lines.append(f"- {a['name']} ({meta}): {a['url']}")
    return "\n".join([ATTACHMENTS_BLOCK_HEADER, *lines, _ATTACHMENTS_BLOCK_HINT])


def apply_media_attachment_images(config: Any, attachments: List[Dict[str, Any]]) -> int:
    """Feed attached images into a media model's structured input-image seam
    (mutates ``config`` pre-dispatch; handlers stay untouched):

      - image  → merged into ``gemini_reference_image_url`` (multi-image; the
                 handler injects refs as multimodal content for Gemini/GPT
                 image models and ignores them for DALL-E/Imagen)
      - video  → ``veo_image_url`` (image-to-video frame; first image, only
                 when the user didn't set one)
      - kling  → ``kling_image_url`` (same single-image fallback)

    Returns how many attached images were delivered. Non-image attachments
    have no media seam and are skipped (they still persist to the transcript).
    """
    image_urls = [a["url"] for a in attachments if a["mime_type"].startswith("image/")]
    skipped = len(attachments) - len(image_urls)
    if skipped:
        logger.info(
            f"[attachments] {skipped} non-image attachment(s) skipped for "
            f"media model (no input seam)"
        )
    if not image_urls:
        return 0
    model_type = getattr(config, "model_type", "llm")
    if model_type == "image":
        from nodes.agent.handlers.image import _parse_gemini_image_urls

        existing = _parse_gemini_image_urls(
            getattr(config, "gemini_reference_image_url", "") or ""
        )
        config.gemini_reference_image_url = json.dumps(image_urls + existing)
        return len(image_urls)
    field = {"video": "veo_image_url", "kling": "kling_image_url"}[model_type]
    if getattr(config, field, "") or "":
        logger.info(
            f"[attachments] {field} already set — attached image(s) not applied"
        )
        return 0
    setattr(config, field, image_urls[0])
    if len(image_urls) > 1:
        logger.info(
            f"[attachments] {model_type} takes one input image — using the "
            f"first of {len(image_urls)}"
        )
    return 1
