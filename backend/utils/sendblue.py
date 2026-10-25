"""Sendblue, the provider behind an iMessage line: texts, media, typing indicators and read receipts on it. Sendblue
delivers over iMessage, and over SMS to a phone without it. Keys come from the environment (on a self-hosted instance,
Settings → Self-hosted puts them there)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.sendblue.com/api"
LINE_VAR = "SENDBLUE_NUMBER"


def line_number() -> Optional[str]:
    """The iMessage line the assistant answers on, or None when this instance has none."""
    return os.getenv(LINE_VAR, "").strip() or None


class SendblueError(Exception):
    """A Sendblue call that did not do what was asked, with its HTTP status and
    Sendblue's stable error key when it gave them."""

    def __init__(self, message: str, *, status: Optional[int] = None, key: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.key = key


class Sendblue:
    # The dashboard's "API Key" and "API Secret" (sent as sb-api-key-id / sb-api-secret-key), and the line.
    ENV_VARS = ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET", LINE_VAR)

    def __init__(self, key_id: str, secret: str, number: str, *, timeout: float = 20.0):
        self._key_id = key_id
        self._secret = secret
        self._number = number
        self._timeout = timeout

    @property
    def number(self) -> str:
        """The line, E.164: what people text, and what the assistant sends from."""
        return self._number

    @classmethod
    def from_env(cls) -> Optional["Sendblue"]:
        values = [os.getenv(name, "").strip() for name in cls.ENV_VARS]
        return cls(*values) if all(values) else None

    def _headers(self) -> Dict[str, str]:
        return {"sb-api-key-id": self._key_id, "sb-api-secret-key": self._secret}

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{API_BASE}/{path}", json=body, headers=self._headers())
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400 or str(data.get("status", "")).upper() == "ERROR":
            raise SendblueError(
                data.get("error_message") or data.get("message") or response.text[:300] or f"HTTP {response.status_code}",
                status=response.status_code, key=data.get("error_key"),
            )
        return data

    async def check_keys(self) -> None:
        """A read that only answers a valid key pair; raises with Sendblue's words when it refuses them."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{API_BASE}/v2/messages", headers=self._headers(), params={"limit": 1})
        except httpx.HTTPError as exc:
            raise SendblueError(f"Sendblue unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                data = response.json()
            except ValueError:
                data = {}
            raise SendblueError(data.get("error_message") or data.get("message") or response.text[:300]
                                or f"HTTP {response.status_code}", status=response.status_code,
                                key=data.get("error_key"))

    async def send(self, to: str, *, content: Optional[str] = None, media_url: Optional[str] = None) -> Optional[str]:
        """Send text, media or both; Sendblue's handle for the message."""
        body: Dict[str, Any] = {"number": to, "from_number": self._number}
        if content:
            body["content"] = content
        if media_url:
            body["media_url"] = media_url
        return (await self._post("send-message", body)).get("message_handle")

    async def typing(self, to: str) -> None:
        await self._post("send-typing-indicator", {"number": to, "from_number": self._number})

    async def mark_read(self, to: str) -> None:
        await self._post("mark-read", {"number": to, "from_number": self._number})

    async def share_profile(self, to: str) -> None:
        """Show the line's name and photo in this person's chat. iMessage shows a business line's profile only
        once it's shared into the chat, after the line has sent there; Sendblue drops a repeat within a day."""
        await self._post("v2/contact-sharing/share", {"fromNumber": self._number, "toNumber": to})

    async def download(self, url: str, *, max_bytes: int) -> Tuple[bytes, str]:
        """An inbound attachment (a public CDN link Sendblue sent) and its type, refused past ``max_bytes``."""
        from utils.ssrf import guarded_async_client

        chunks, size = [], 0
        try:
            async with guarded_async_client(timeout=self._timeout) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise SendblueError(f"attachment download failed: HTTP {response.status_code}", status=response.status_code)
                    content_type = response.headers.get("content-type", "")
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > max_bytes:
                            raise SendblueError(f"attachment larger than {max_bytes // (1024 * 1024)}MB")
                        chunks.append(part)
        except httpx.HTTPError as exc:
            raise SendblueError(f"attachment unreachable: {type(exc).__name__}") from exc
        return b"".join(chunks), content_type.split(";")[0].strip()
