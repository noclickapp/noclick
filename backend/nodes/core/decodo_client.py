"""Bounded premium JSON retrieval, shared by scrapers that own their parsing."""

import asyncio
import json
import os
from decimal import Decimal
from urllib.parse import urlsplit

import httpx

DECODO_ENDPOINT = "https://scraper-api.decodo.com/v2/scrape"
REQUEST_TIMEOUT_SECONDS = 30
_gate = None
_gate_loop = None


def request_gate():
    global _gate, _gate_loop
    loop = asyncio.get_running_loop()
    if _gate is None or _gate_loop is not loop:
        _gate, _gate_loop = asyncio.Semaphore(3), loop
    return _gate


class DecodoError(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class DecodoJsonClient:
    def __init__(self, token):
        self.unit_cost = Decimal(os.getenv("DECODO_REQUEST_COST_USD", "0.001"))
        if not self.unit_cost.is_finite() or self.unit_cost <= 0:
            raise ValueError("DECODO_REQUEST_COST_USD must be a positive dollar amount")
        self.attempts = 0
        self.billable_requests = 0
        self.task_ids = []
        self.http = httpx.AsyncClient(
            headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
        )

    async def __aenter__(self):
        await self.http.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.http.__aexit__(*args)

    async def fetch_json(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Scraping requires a public HTTPS URL without credentials")
        for attempt in range(2):
            try:
                async with request_gate(), asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                    return await self._fetch_once(url)
            except (httpx.TransportError, TimeoutError):
                error = DecodoError("Decodo request timed out or could not connect", retryable=True)
            except DecodoError as exc:
                error = exc
            if not error.retryable or attempt:
                raise error
            await asyncio.sleep(1)

    async def _fetch_once(self, url):
        self.attempts += 1
        response = await self.http.post(
            DECODO_ENDPOINT,
            json={"target": "universal", "proxy_pool": "premium", "geo": "United States", "url": url},
        )
        if response.status_code != 200:
            messages = {
                401: "Decodo rejected the server's scraping token",
                402: "Decodo's scraping allowance is exhausted",
                403: "The Decodo account cannot access this scraping service",
                429: "Decodo's request limit was reached; try again later",
            }
            raise DecodoError(
                messages.get(response.status_code, f"Decodo request failed (HTTP {response.status_code})"),
                retryable=response.status_code in {500, 502, 503, 504, 524},
            )
        try:
            payload = response.json()
        except ValueError:
            # Successful HTTP responses with truncated JSON still consume provider credit.
            self.billable_requests += 1
            raise DecodoError("Decodo returned invalid response JSON", retryable=True) from None
        if not isinstance(payload, dict):
            self.billable_requests += 1
            raise DecodoError("Decodo returned an invalid response envelope")
        if payload.get("status") == "failed":
            code = payload.get("status_code")
            raise DecodoError(f"Decodo could not retrieve the page (status {code})", retryable=code == 613)
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            self.billable_requests += 1
            raise DecodoError("Decodo returned no page result")
        result = results[0]
        status = result.get("status_code")
        if isinstance(status, int) and 200 <= status < 500:
            self.billable_requests += 1
        task_id = result.get("task_id") or payload.get("task_id")
        if task_id:
            self.task_ids.append(str(task_id))
        if status != 200:
            raise DecodoError(
                f"Decodo could not retrieve the page (upstream status {status})",
                retryable=status in {500, 502, 503, 504, 524, 613, 15002},
            )
        data = result.get("content")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                raise DecodoError("Decodo returned malformed page JSON", retryable=True) from None
        if not isinstance(data, (dict, list)):
            raise DecodoError("Decodo returned no JSON page data")
        return data
