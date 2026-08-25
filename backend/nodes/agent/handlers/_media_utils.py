"""
Shared media utilities for handlers that need to download/decode images or videos.
"""

import re
from functools import lru_cache
from typing import List, Tuple

# Detects HTTP(S) URLs whose path ends with a known image extension
_IMAGE_EXT_RE = re.compile(
    r'https?://[^\s,\'"<>()]+\.(?:png|jpe?g|gif|webp|bmp|tiff?|svg)(?:[?#][^\s,\'"<>()]*)?',
    re.IGNORECASE,
)
# Workflow-resource URLs are images regardless of extension, so they get their
# own rule. The base is edition-dependent (our CDN when hosted, the operator's
# storage when self-hosted), so build the pattern from the configured base.
@lru_cache(maxsize=1)
def _asset_url_re():
    from utils.hosted_defaults import assets_base_url

    try:
        base = assets_base_url()
    except Exception:
        # Unconfigured install: extension-based detection below still applies.
        return None
    return re.compile(re.escape(base.rstrip('/')) + r'/[^\s,\'"<>()]+', re.IGNORECASE)

# MIME types accepted by all major vision providers via OpenRouter
_VISION_OK_MIME: frozenset = frozenset({'image/jpeg', 'image/png', 'image/webp', 'image/gif'})


def extract_inline_image_urls(text: str) -> List[str]:
    """Scan message text for image URLs that should be injected as multimodal content.

    Detects workflow-resource CDN URLs and any HTTP(S) URL whose path ends with a
    common image extension. Returns a deduplicated, order-preserving list.
    """
    seen: set = set()
    found: List[str] = []
    for pattern in (p for p in (_IMAGE_EXT_RE, _asset_url_re()) if p is not None):
        for m in pattern.finditer(text):
            url = m.group(0).rstrip('.,;:\'\")')
            if url not in seen:
                seen.add(url)
                found.append(url)
    return found


async def fetch_image_bounded(url: str, max_bytes: int = 10 * 1024 * 1024) -> Tuple[str, str]:
    """Fetch an image and return (base64_str, mime_type), aborting early if it exceeds max_bytes.

    Thin wrapper over the shared media resolver (data URI / resource UUID /
    HTTP(S) URL handling + streamed size cap), kept for the vision callers that
    want base64 with an image default mime.
    """
    from nodes.core.media_resolver import resolve_media_input

    resolved = await resolve_media_input(
        url, max_bytes=max_bytes, default_mime="image/jpeg"
    )
    return resolved.base64, resolved.mime_type


async def fetch_image_as_base64(url: str) -> Tuple[str, str]:
    """
    Fetch an image from URL, resource ID, or data URI and return (base64_str, mime_type).

    Supports:
    - Workflow resource UUIDs (resolved via DB + presigned URL)
    - data: URIs (decoded inline)
    - HTTP URLs (downloaded and encoded)
    """
    from nodes.core.media_resolver import resolve_media_input

    resolved = await resolve_media_input(url, default_mime="image/jpeg")
    return resolved.base64, resolved.mime_type
