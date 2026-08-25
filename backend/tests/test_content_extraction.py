"""General content-extraction layer (utils/content_extraction.py).

Contracts under test:
- free CPU path extracts text-layer documents and never bills;
- the inline char budget truncates with an explanatory note;
- a scanned PDF (no text layer) is REFUSED unless allow_ai=True with a
  billing context — AI is never implicit;
- the AI OCR path credit-gates BEFORE any model call (a gate raise means
  zero spend) and charges pages x AI_EXTRACTION_PRICE_PER_PAGE with
  usage_subtype extraction/ai_ocr through the organization attribution policy choke point;
- the per-document page cap bounds the worst-case charge;
- inline_enrich_attachments enriches at most N attachments, free path only,
  and never raises (failed attachments keep metadata + a note).
"""

import asyncio
import io
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing.pricing import AI_EXTRACTION_PRICE_PER_PAGE
from utils import content_extraction as ce


from tests.mocks.pdf_fixtures import blank_pdf as _blank_pdf
from tests.mocks.pdf_fixtures import text_pdf as _text_pdf


TEST_USER = "00000000-0000-4000-8000-000000000001"


def _billing() -> ce.BillingContext:
    return ce.BillingContext(user_id=TEST_USER, organization_id=None, workflow_id="w1", node_id="n1")


# ── Free CPU path ────────────────────────────────────────────────────────────

def test_document_path_extracts_and_never_bills():
    with patch("billing.usage_tracker.usage_tracker") as tracker:
        result = asyncio.run(ce.extract_content(
            _text_pdf(), mime_type="application/pdf", filename="a.pdf"
        ))
    assert result.method == "document"
    assert "$10" in result.text
    assert result.cost_charged is None
    tracker.enforce_credit_gate.assert_not_called()
    tracker.track_usage_event.assert_not_called()


def test_char_budget_truncates_with_note():
    data = ("row of text\n" * 5000).encode()
    result = asyncio.run(ce.extract_content(
        data, mime_type="text/plain", filename="big.txt", char_budget=1000
    ))
    assert result.truncated
    assert "[truncated" in result.text
    assert result.total_chars > 1000


def test_oversize_and_unsupported_are_refused():
    with pytest.raises(ce.ExtractionError, match="capped"):
        asyncio.run(ce.extract_content(
            b"x" * (ce.MAX_EXTRACT_BYTES + 1), mime_type="text/plain", filename="x.txt"
        ))
    with pytest.raises(ce.ExtractionError, match="Cannot extract"):
        asyncio.run(ce.extract_content(b"\x00", mime_type="application/zip", filename="x.zip"))


# ── AI OCR gating + billing ──────────────────────────────────────────────────

def test_scanned_pdf_refused_without_allow_ai():
    with pytest.raises(ce.ExtractionError, match="no extractable text layer"):
        asyncio.run(ce.extract_content(
            _blank_pdf(), mime_type="application/pdf", filename="scan.pdf"
        ))


def test_ai_ocr_requires_billing_context():
    with pytest.raises(ce.ExtractionError, match="billing context"):
        asyncio.run(ce.extract_content(
            _blank_pdf(), mime_type="application/pdf", filename="scan.pdf", allow_ai=True
        ))


def test_ai_ocr_gates_before_model_and_charges_per_page():
    calls = []
    pages = 3
    pdf = _blank_pdf(pages)

    async def gate(*a, **k):
        calls.append("gate")

    async def model(*a, **k):
        calls.append("model")
        resp = MagicMock()
        resp.choices[0].message.content = "OCR TEXT"
        return resp

    async def track(event, **k):
        calls.append("track")
        assert event.usage_subtype == "extraction/ai_ocr"
        assert event.total_cost == AI_EXTRACTION_PRICE_PER_PAGE * pages
        assert event.quantity == Decimal(pages)
        assert event.user_id == TEST_USER

    with patch("billing.usage_tracker.usage_tracker") as tracker, \
         patch("litellm.acompletion", side_effect=model):
        tracker.enforce_credit_gate = AsyncMock(side_effect=gate)
        tracker.track_usage_event = AsyncMock(side_effect=track)
        result = asyncio.run(ce.extract_content(
            pdf, mime_type="application/pdf", filename="scan.pdf",
            allow_ai=True, billing=_billing(),
        ))

    assert calls == ["gate", "model", "track"]
    assert result.method == "ai_ocr"
    assert result.pages == pages
    assert result.cost_charged == AI_EXTRACTION_PRICE_PER_PAGE * pages


def test_gate_raise_means_zero_model_spend():
    from billing.exceptions import InsufficientBalanceError

    with patch("billing.usage_tracker.usage_tracker") as tracker, \
         patch("litellm.acompletion", new_callable=AsyncMock) as model:
        tracker.enforce_credit_gate = AsyncMock(side_effect=InsufficientBalanceError("no credits"))
        with pytest.raises(InsufficientBalanceError):
            asyncio.run(ce.extract_content(
                _blank_pdf(), mime_type="application/pdf", filename="scan.pdf",
                allow_ai=True, billing=_billing(),
            ))
        model.assert_not_called()
        tracker.track_usage_event.assert_not_called()


def test_ai_ocr_page_cap():
    pdf = _blank_pdf(ce.AI_OCR_MAX_PAGES + 1)
    with patch("litellm.acompletion", new_callable=AsyncMock) as model:
        with pytest.raises(ce.ExtractionError, match="capped at"):
            asyncio.run(ce.extract_content(
                pdf, mime_type="application/pdf", filename="scan.pdf",
                allow_ai=True, billing=_billing(),
            ))
        model.assert_not_called()


# ── Inline enrichment (natural surfacing) ────────────────────────────────────

def test_inline_enrich_caps_and_notes():
    pdf = _text_pdf("hello doc")
    records = [
        ce.attachment_record(filename=f"d{i}.pdf", mime_type="application/pdf",
                             size_bytes=len(pdf), source="test", attachment_id=str(i))
        for i in range(5)
    ] + [
        ce.attachment_record(filename="pic.png", mime_type="image/png",
                             size_bytes=10, source="test", attachment_id="img"),
    ]

    async def fetch(rec):
        return pdf

    out = asyncio.run(ce.inline_enrich_attachments(records, fetch))
    enriched = [r for r in out if "text" in r]
    assert len(enriched) == ce.INLINE_ENRICH_MAX_ATTACHMENTS
    assert all("hello doc" in r["text"] for r in enriched)
    # image: not extractable (until the image-description method lands), no text, no crash
    assert "text" not in out[-1]


def test_inline_enrich_never_raises_on_fetch_failure():
    records = [ce.attachment_record(filename="a.pdf", mime_type="application/pdf",
                                    size_bytes=10, source="test", attachment_id="1")]

    async def fetch(rec):
        raise RuntimeError("provider 500")

    out = asyncio.run(ce.inline_enrich_attachments(records, fetch))
    assert out[0]["note"] == "provider 500"
    assert "text" not in out[0]


def test_scanned_note_survives_inline_enrich():
    """A scanned PDF in the inline path yields the escape-hatch note, not AI spend."""
    pdf = _blank_pdf()
    records = [ce.attachment_record(filename="scan.pdf", mime_type="application/pdf",
                                    size_bytes=len(pdf), source="test", attachment_id="1")]

    async def fetch(rec):
        return pdf

    with patch("litellm.acompletion", new_callable=AsyncMock) as model:
        out = asyncio.run(ce.inline_enrich_attachments(records, fetch))
        model.assert_not_called()
    assert "no extractable text layer" in out[0]["note"]
