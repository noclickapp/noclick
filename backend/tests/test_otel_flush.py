"""Span-flush coverage for processes that may exit before a batch export.

The provider flush must remain safe, best-effort, and a no-op when tracing
is disabled.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).resolve().parent.parent


def test_flush_spans_calls_provider_force_flush():
    from utils import otel

    provider = MagicMock()
    with patch.object(otel, "_PROVIDER", provider):
        otel.flush_spans(timeout_millis=1234)
    provider.force_flush.assert_called_once_with(timeout_millis=1234)


def test_flush_spans_noop_without_provider():
    from utils import otel

    with patch.object(otel, "_PROVIDER", None):
        otel.flush_spans()  # must not raise


def test_flush_spans_swallows_provider_errors():
    from utils import otel

    provider = MagicMock()
    provider.force_flush.side_effect = RuntimeError("exporter down")
    with patch.object(otel, "_PROVIDER", provider):
        otel.flush_spans()  # must not raise


