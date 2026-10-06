"""Exact e49 endpoints.py lines 54–65, with the required os import."""

import os


def get_frontend_url() -> str:
    """The frontend base URL for login redirects and every minted shareable
    link (bridge /b pages, credential provide, shared agent pages). In
    DEV_MODE the default is the local dev server — a locally minted link
    pointing at prod is always wrong (2026-07-19: local share buttons copied
    noclick.com URLs whose ids don't exist there)."""
    explicit = os.getenv("FRONTEND_URL") or os.getenv("VITE_PUBLIC_URL")
    if explicit:
        return explicit
    if os.getenv("DEV_MODE") == "1":
        return "http://localhost:5173"
    return "https://noclick.com"
