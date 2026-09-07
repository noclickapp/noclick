"""Use real instrumentation/export to check synthetic verification redaction."""

import httpx
import pytest
from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from uvicorn.protocols.utils import get_path_with_query_string

from utils.instagram_webhook_privacy import (
    consume_instagram_verification_query,
    instagram_webhook_request_hook,
)
from utils.instagram_webhooks import instagram_handshake


@pytest.mark.parametrize("valid", [True, False])
async def test_verification_and_access_log_path_survive_real_span_redaction(monkeypatch, valid):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "synthetic-verification-token")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = FastAPI()
    scopes = []

    @app.get("/webhook/app/instagram")
    async def verify(request: Request):
        scopes.append(request.scope)
        return instagram_handshake(consume_instagram_verification_query(request))

    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider,
        server_request_hook=instagram_webhook_request_hook,
        http_capture_headers_server_request=[".*"],
    )
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
            response = await client.get(
                "/webhook/app/instagram",
                params={"hub.mode": "subscribe", "hub.challenge": "1234",
                        "hub.verify_token": "synthetic-verification-token" if valid else "synthetic-wrong-token"},
                headers={"X-Hub-Signature-256": "synthetic-signature"},
            )
        assert response.status_code == (200 if valid else 403)
        if valid:
            assert response.text == "1234"
        spans = exporter.get_finished_spans()
        assert spans
        for span in spans:
            rendered = str(dict(span.attributes or {}))
            assert "synthetic-verification-token" not in rendered
            assert "synthetic-wrong-token" not in rendered
            assert "synthetic-signature" not in rendered
        assert scopes[0]["query_string"] == b""
        assert "_instagram_callback_query" not in scopes[0]
        assert get_path_with_query_string(scopes[0]) == "/webhook/app/instagram"
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        provider.shutdown()


def test_other_routes_and_queries_unchanged():
    scope = {"path": "/webhook/app/slack", "query_string": b"ordinary=value"}
    instagram_webhook_request_hook(None, scope)
    assert scope == {"path": "/webhook/app/slack", "query_string": b"ordinary=value"}
