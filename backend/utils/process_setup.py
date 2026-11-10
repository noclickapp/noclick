"""The logging and outbound tracing every backend process sets up once.

server.py runs it as the app is assembled; a process that serves without
server.py (the hosted voice bridge and credential proxy) runs it as it starts,
so its logs read the same and its outbound HTTP calls and queries are spans
like the app's. Spans leave the process once ``utils.otel.init_otel`` starts
the exporter.
"""
import logging

from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from utils.outbound_trace_privacy import OutboundTraceProvider

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

_configured = False


def configure_process() -> None:
    """INFO logs in one format, and a span for each outbound request and query. Idempotent."""
    global _configured
    if _configured:
        return
    _configured = True
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    outbound = OutboundTraceProvider()
    HTTPXClientInstrumentor().instrument(tracer_provider=outbound)
    # LiteLLM's streaming completion path uses aiohttp, not httpx; both client
    # instrumentors are needed to capture all outbound LLM/API traffic.
    AioHttpClientInstrumentor().instrument(tracer_provider=outbound)
    # asyncpg: per-query spans for DB-latency attribution. Must run before the
    # first pool is created so the monkey-patch is in place on every connection.
    AsyncPGInstrumentor().instrument()
