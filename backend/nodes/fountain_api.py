"""Bounded Fountain Private Hire transport and hiring-metadata projections.

This module implements only the documented Hire resource paths. Secure applicant
data, communication history, documents and provider error bodies never become output.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

import httpx
from utils.ssrf import guarded_async_client

BASES = {"main": "https://api.fountain.com/v2", "us-2": "https://us-2.fountain.com/api/v2"}
MAX_BYTES = 4 * 1024 * 1024
CONSENT_FIELDS = ("consent_sms_transactional", "consent_sms_marketing",
                  "consent_calls_transactional", "consent_calls_marketing")


def resource_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Fountain resource ID must be a UUID.")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError("Fountain resource ID must be a UUID.") from None
    if str(parsed) != value.lower():
        raise ValueError("Fountain resource ID must be a canonical UUID.")
    return str(parsed)


def cursor_value(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+=/-]{1,4096}", value):
        raise ValueError("Fountain cursor is invalid.")
    return value


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _contains_credential(value, secret):
    pending, count = [value], 0
    while pending:
        current = pending.pop()
        count += 1
        if count > 100000:
            raise ValueError("Fountain JSON exceeds the native structural bound.")
        if isinstance(current, str) and secret in current:
            return True
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return False


def retry_after(value: str | None) -> int | None:
    if not value:
        return None
    if re.fullmatch(r"[0-9]{1,12}", value):
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0, math.ceil((date - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


async def request(credential: dict, method: str, path: str, *, params=None, body=None, recheck=None):
    # Paths are assembled internally from these fixed resources and UUIDs.
    if not re.fullmatch(r"/(?:funnels(?:/[0-9a-f-]{36}(?:/stages)?)?|stages/[0-9a-f-]{36}|applicants(?:/[0-9a-f-]{36})?)", path):
        raise ValueError("Unsupported Fountain resource path.")
    if method not in {"GET", "POST", "PUT", "DELETE"}:
        raise ValueError("Unsupported Fountain method.")
    if recheck:
        await recheck()
    headers = {"X-ACCESS-TOKEN": credential["api_key"], "Accept": "application/json"}
    url = BASES[credential["tenant"]] + path
    payload = None if body is None else json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
    if payload is not None:
        if len(payload) > 65536:
            raise ValueError("Fountain request exceeds the native body limit.")
        headers["Content-Type"] = "application/json"
    try:
        async with guarded_async_client(require_public=True, timeout=30.0,
                                        follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, headers=headers, params=params, content=payload) as response:
                status = response.status_code
                if status in {401, 403}:
                    raise ValueError("Fountain authentication failed or this Private Hire resource is forbidden (401/403).")
                if status == 429:
                    delay = retry_after(response.headers.get("Retry-After"))
                    suffix = "" if delay is None else f" Retry after {delay} seconds."
                    raise ValueError("Fountain rate limit reached (429)." + suffix)
                expected = {"GET": 200, "POST": 201, "PUT": 200, "DELETE": 204}[method]
                if status != expected:
                    raise ValueError(f"Fountain request failed (HTTP {status}); no write retry was performed.")
                if status == 204:
                    result = None
                else:
                    media = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
                    if media != "application/json":
                        raise ValueError("Fountain returned an unsupported response media type.")
                    collected = bytearray()
                    async for chunk in response.aiter_bytes():
                        collected.extend(chunk)
                        if len(collected) > MAX_BYTES:
                            raise ValueError("Fountain response exceeds the native size limit.")
                    try:
                        result = json.loads(collected, object_pairs_hook=_object_pairs,
                                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                    except (ValueError, UnicodeError):
                        raise ValueError("Fountain returned malformed JSON.") from None
                    if not isinstance(result, dict) or "error" in result or "errors" in result:
                        raise ValueError("Fountain returned an invalid resource envelope.")
                    if _contains_credential(result, credential["api_key"]):
                        raise ValueError("Fountain response contained credential material; output withheld.")
    except httpx.HTTPError:
        raise ValueError("Fountain transport failed; write outcome may be unknown. Read back before retrying.") from None
    if recheck:
        await recheck()
    return result


def _scalar(source, key, kind=str):
    value = source.get(key)
    if value is None:
        return None
    if type(value) is not kind or (kind is str and len(value) > 8192):
        raise ValueError("Fountain metadata has an invalid field shape.")
    return value


def project(source: Any, resource: str, *, expected_id=None, opening_id=None):
    if not isinstance(source, dict):
        raise ValueError("Fountain resource has an invalid shape.")
    ident = resource_id(source.get("id"))
    if expected_id is not None and ident != expected_id:
        raise ValueError("Fountain returned a different resource.")
    fields = {
        "opening": ("title", "external_title", "custom_id", "brand", "time_zone", "created_at", "job_type", "job_industry", "job_hours"),
        "stage": ("title", "type", "parent_id"),
        "applicant": ("name", "first_name", "last_name", "email", "phone_number", "created_at", "updated_at", "application_locale"),
    }[resource]
    result = {"id": ident}
    for field in fields:
        if field in source:
            result[field] = _scalar(source, field)
    if resource == "opening":
        for field in ("active", "is_private", "is_hiring_funnel", "is_visible_to_applicant"):
            if field in source:
                result[field] = _scalar(source, field, bool)
    if resource == "stage":
        for field in ("position", "num_applicants"):
            if field in source:
                result[field] = _scalar(source, field, int)
    if resource == "applicant":
        funnel = source.get("funnel")
        if not isinstance(funnel, dict):
            raise ValueError("Fountain applicant is missing its opening binding.")
        parent = resource_id(funnel.get("id"))
        if opening_id is not None and parent != opening_id:
            raise ValueError("Fountain applicant belongs to a different opening.")
        result["funnel"] = {"id": parent, "title": _scalar(funnel, "title")}
        if source.get("stage") is not None:
            stage = source["stage"]
            if not isinstance(stage, dict):
                raise ValueError("Fountain applicant stage has an invalid shape.")
            result["stage"] = {"id": resource_id(stage.get("id")), "title": _scalar(stage, "title"), "type": _scalar(stage, "type")}
        # The four values are readback evidence, not editable consent inputs.
        for field in CONSENT_FIELDS:
            if field in source:
                result[field] = _scalar(source, field, bool)
    return result


def page(source, key, resource, *, limit=100, opening_id=None):
    if not isinstance(source, dict) or not isinstance(source.get(key), list):
        raise ValueError("Fountain list has an invalid envelope.")
    if len(source[key]) > limit:
        raise ValueError("Fountain list exceeded the requested native bound.")
    rows = [project(row, resource, opening_id=opening_id) for row in source[key]]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Fountain list contains duplicate resource IDs.")
    pagination = source.get("pagination")
    result = {"data": rows, "count": len(rows), "pagination": None,
              "next_page": None, "next_cursor": None, "complete": None}
    if pagination is None:
        return result
    if not isinstance(pagination, dict):
        raise ValueError("Fountain pagination has an invalid shape.")
    projected = {}
    for field in ("first", "last", "previous", "current", "next"):
        value = pagination.get(field)
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError("Fountain pagination has an invalid page.")
        if field in pagination:
            projected[field] = value
    for field in ("current_cursor", "next_cursor"):
        if field in pagination:
            value = pagination[field]
            projected[field] = None if value in (None, "") else cursor_value(value)
    current, following, last = (projected.get(field) for field in ("current", "next", "last"))
    if current is not None and last is not None and current > last:
        raise ValueError("Fountain pagination exceeds its last page.")
    if current is not None and following is not None and following <= current:
        raise ValueError("Fountain pagination does not advance.")
    if last is not None and following is not None and following > last:
        raise ValueError("Fountain pagination exceeds its last page.")
    if projected.get("next_cursor") is not None and projected.get("next_cursor") == projected.get("current_cursor"):
        raise ValueError("Fountain cursor does not advance.")
    if current is not None and last is not None and current < last and "next" in projected and following is None and projected.get("next_cursor") is None:
        raise ValueError("Fountain pagination is missing its remaining continuation.")
    result.update(pagination=projected, next_page=following, next_cursor=projected.get("next_cursor"))
    if "next" in projected or "next_cursor" in projected:
        result["complete"] = following is None and projected.get("next_cursor") is None
    return result
