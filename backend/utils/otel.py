"""OpenTelemetry tracing setup for shipping spans to Honeycomb.

Reads HONEYCOMB_API_KEY from the environment. If unset, init is a no-op so
local dev and CI don't need the key.
"""
import logging
import os
import socket

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

_INITIALIZED = False
_PROVIDER: TracerProvider | None = None

SERVICE_NAME = "noclick-backend"
HONEYCOMB_ENDPOINT = "https://api.honeycomb.io"


def init_otel() -> None:
    """Initialize the global TracerProvider. Idempotent and safe to call at import."""
    global _INITIALIZED, _PROVIDER
    if _INITIALIZED:
        return

    api_key = os.getenv("HONEYCOMB_API_KEY")
    if not api_key:
        logger.info("HONEYCOMB_API_KEY not set; OpenTelemetry tracing disabled")
        _INITIALIZED = True
        return

    instance_id = os.getenv("NOCLICK_INSTANCE_ID") or socket.gethostname()
    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", SERVICE_NAME),
        "service.version": os.getenv("OTEL_SERVICE_VERSION", "dev"),
        "deployment.environment.name": os.getenv(
            "DEPLOYMENT_ENVIRONMENT", "self-hosted"
        ),
        "service.instance.id": instance_id,
        "host.name": socket.gethostname(),
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=f"{HONEYCOMB_ENDPOINT}/v1/traces",
        headers={"x-honeycomb-team": api_key},
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _PROVIDER = provider
    _INITIALIZED = True
    logger.info("OpenTelemetry initialized → Honeycomb (instance=%s)", instance_id)


def flush_spans(timeout_millis: int = 5000) -> None:
    """Export any spans still buffered in the BatchSpanProcessor.

    The processor exports on a timer, so short-lived commands should flush
    before exiting. No-op when tracing is disabled; never raises.
    """
    if _PROVIDER is None:
        return
    try:
        _PROVIDER.force_flush(timeout_millis=timeout_millis)
    except Exception as e:
        logger.warning("OTel flush failed: %s", e)


def shutdown_otel(timeout_seconds: float = 3.0) -> None:
    """Flush pending spans and shut down the exporter. Call from app shutdown."""
    global _PROVIDER
    if _PROVIDER is None:
        return
    try:
        _PROVIDER.shutdown()
    except Exception as e:
        logger.warning("OTel shutdown failed: %s", e)


def get_tracer(name: str = SERVICE_NAME):
    return trace.get_tracer(name)
