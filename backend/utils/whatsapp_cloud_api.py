"""The Meta WhatsApp Cloud API for the number the account assistant texts from: one client, one pinned Graph version.
Keys come from the environment (on a self-hosted instance, Settings → Self-hosted puts them there)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v22.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
# Meta refuses a template body parameter past this.
TEMPLATE_BODY_LIMIT = 1024
TEMPLATE_LANGUAGE = "en"
UPLOAD_TIMEOUT_S = 120.0
# WhatsApp previews the first link in a text only when asked, and only one with a scheme.
_PREVIEWABLE_LINK = re.compile(r"https?://\S", re.I)
# The number people text, as Meta displays it; filled from Graph when the keys are saved in Settings.
DISPLAY_NUMBER_VAR = "WHATSAPP_DISPLAY_NUMBER"


class WhatsAppSendError(Exception):
    """A Graph call that did not do what was asked — a send, a receipt, a
    media fetch — with Meta's own error code when it gave one."""

    def __init__(self, message: str, *, code: Optional[int] = None, status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.status = status


def template_param(text: str, limit: int = TEMPLATE_BODY_LIMIT) -> str:
    """A template parameter: one line (Meta refuses newlines, tabs and runs of
    spaces in one), and past ``limit`` cut at a word with an ellipsis."""
    flat = " ".join(str(text).split())
    if len(flat) > limit:
        cut = flat.rfind(" ", 0, limit)
        flat = (flat[:cut] if cut > limit // 2 else flat[:limit - 1]).rstrip() + "…"
    return flat or "-"


def display_number() -> Optional[str]:
    """The number the assistant answers on over WhatsApp, or None when this instance has no WhatsApp line."""
    return os.getenv(DISPLAY_NUMBER_VAR, "").strip() or None


class CloudApi:
    ENV_VARS = ("WHATSAPP_CLOUD_API_TOKEN", "WHATSAPP_PHONE_NUMBER_ID")

    def __init__(self, token: str, phone_number_id: str, *, timeout: float = 20.0):
        self._token = token
        self._phone_number_id = phone_number_id
        self._timeout = timeout

    @property
    def phone_number_id(self) -> str:
        return self._phone_number_id

    @classmethod
    def from_env(cls) -> Optional["CloudApi"]:
        values = [os.getenv(name, "").strip() for name in cls.ENV_VARS]
        return cls(*values) if all(values) else None

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def phone_number(self) -> Dict[str, Any]:
        """The number this client sends from, as Meta lists it: {display_phone_number, verified_name, ...}."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{GRAPH_BASE}/{self._phone_number_id}", headers=self._headers(),
                    params={"fields": "display_phone_number,verified_name"},
                )
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"WhatsApp unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            raise WhatsAppSendError(f"WhatsApp refused the lookup: {error.get('message') or response.text[:200]}",
                                    code=error.get("code"), status=response.status_code)
        return response.json()

    async def get_media(self, media_id: str) -> Dict[str, Any]:
        """Where a received media item can be fetched from: {url, mime_type,
        file_size}. The URL is short-lived and only answers with our token."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{GRAPH_BASE}/{media_id}", headers=self._headers())
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"WhatsApp unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise WhatsAppSendError(f"WhatsApp media lookup failed: {response.text[:200]}", status=response.status_code)
        return response.json()

    async def download(self, url: str, *, max_bytes: int) -> bytes:
        """The bytes behind a media URL, refused past ``max_bytes``."""
        from utils.ssrf import assert_exact_url_origin

        # Only Meta's media origin may receive the bearer token.
        assert_exact_url_origin(url, "https://lookaside.fbsbx.com")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("GET", url, headers=self._headers()) as response:
                    if response.status_code != 200:
                        raise WhatsAppSendError(f"WhatsApp media download failed: HTTP {response.status_code}",
                                                status=response.status_code)
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise WhatsAppSendError(f"media larger than {max_bytes // (1024 * 1024)}MB")
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"WhatsApp unreachable: {type(exc).__name__}") from exc
        return b"".join(chunks)

    async def _send(self, payload: Dict[str, Any]) -> str:
        payload = {"messaging_product": "whatsapp", **payload}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{GRAPH_BASE}/{self._phone_number_id}/messages",
                    json=payload, headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"WhatsApp unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            raise WhatsAppSendError(
                f"WhatsApp send failed: {error.get('message') or response.text[:200]}",
                code=error.get("code"), status=response.status_code,
            )
        messages = response.json().get("messages") or [{}]
        return str(messages[0].get("id", ""))

    async def send_template(
        self, to_e164: str, name: str, *, body: List[str], button_url_param: Optional[str] = None,
        language: str = TEMPLATE_LANGUAGE,
    ) -> str:
        """An approved template, which WhatsApp delivers outside the 24-hour service window. Returns Meta's message
        id."""
        components: List[Dict[str, Any]] = []
        if body:
            components.append({"type": "body", "parameters": [{"type": "text", "text": template_param(p)} for p in body]})
        if button_url_param is not None:
            components.append({"type": "button", "sub_type": "url", "index": "0",
                               "parameters": [{"type": "text", "text": template_param(button_url_param, 200)}]})
        return await self._send({
            "to": to_e164.lstrip("+"), "type": "template",
            "template": {"name": name, "language": {"code": language}, "components": components},
        })

    async def mark_read(self, message_id: str, *, typing: bool = True) -> None:
        """Blue ticks, and while a reply is composed the typing indicator (Meta
        clears it on our next message or after 25s)."""
        payload: Dict[str, Any] = {"status": "read", "message_id": message_id}
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        await self._send(payload)

    async def upload_media(self, data: bytes, *, filename: str, mime_type: str) -> str:
        """Put a file on Meta's servers to send by its id: the media id. Meta refuses a type it doesn't take."""
        try:
            async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT_S) as client:
                response = await client.post(
                    f"{GRAPH_BASE}/{self._phone_number_id}/media", headers=self._headers(),
                    data={"messaging_product": "whatsapp", "type": mime_type},
                    files={"file": (filename, data, mime_type)},
                )
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"WhatsApp unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            raise WhatsAppSendError(f"WhatsApp refused the file: {error.get('message') or response.text[:200]}",
                                    code=error.get("code"), status=response.status_code)
        return str(response.json()["id"])

    async def send_media(self, to_e164: str, kind: str, *, link: Optional[str] = None, media_id: Optional[str] = None,
                         caption: str = "", filename: Optional[str] = None) -> str:
        """An image, video, audio or document by public link (Meta fetches it) or by an uploaded file's id, within 24h
        of the recipient's last message. A document shows ``filename``, whose extension picks its icon."""
        media: Dict[str, Any] = {"link": link} if link else {"id": media_id}
        if caption and kind != "audio":
            media["caption"] = caption[:1024]
        if filename and kind == "document":
            media["filename"] = filename
        return await self._send({"to": to_e164.lstrip("+"), "type": kind, kind: media})

    async def send_text(self, to_e164: str, text: str) -> str:
        """Free-form text: only within 24h of the recipient's last message. A link in it arrives as a preview card."""
        body: Dict[str, Any] = {"body": text[:4096]}
        if _PREVIEWABLE_LINK.search(body["body"]):
            body["preview_url"] = True
        return await self._send({"to": to_e164.lstrip("+"), "type": "text", "text": body})
