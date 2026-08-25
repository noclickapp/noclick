"""General content-extraction layer: attachment/document bytes → text an LLM can read.

One entry point — ``extract_content`` — shared by every email pathway (Gmail /
Outlook fetch ops, the inbound-email trigger) and any future caller. Documents
extract through the existing ``nodes.core.document_ingest.extract_text``
pipeline (pure CPU, free, size-capped). Scanned PDFs with no text layer fall
back to AI OCR — credit-gated and charged flat per page
(``billing.pricing.AI_EXTRACTION_PRICE_PER_PAGE``). The method registry is
deliberately general: image/video description land here later as new AI
methods without reshaping callers.

Two hard rules every caller inherits:
  - **AI is never implicit.** ``allow_ai=False`` is the default; only explicit
    fetch-attachment operations (where the user/agent asked for this document)
    may pass ``allow_ai=True`` with a billing context. Inline auto-enrichment
    on message fetches uses the free CPU path only.
  - **Document parsing never blocks the event loop.** CPU extraction runs in
    a worker thread and the byte limit bounds resource use.
"""

import asyncio
import base64
import io
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
MAX_EXTRACT_BYTES = 15 * 1024 * 1024      # refuse to parse anything bigger
INLINE_BYTES_THRESHOLD = 512 * 1024       # base for the inline-enrichment cap
AI_OCR_MAX_PAGES = 20                     # bounds worst-case per-document charge
DEFAULT_INLINE_CHAR_BUDGET = 8_000        # per-attachment auto-inlined text
INLINE_ENRICH_MAX_ATTACHMENTS = 3         # per-message auto-enrich cap

# Operators may replace this with any model supported by their LiteLLM setup.
AI_EXTRACTION_MODEL = os.environ.get("AI_EXTRACTION_MODEL", "openrouter/google/gemini-3.5-flash")

# Mimes/extensions the free CPU path can extract (delegates to document_ingest).
_DOCUMENT_MIME_HINTS = ("pdf", "wordprocessingml", "html", "json")
_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm")


def can_extract(mime_type: Optional[str], filename: Optional[str]) -> bool:
    """True if the free document path can handle this attachment type."""
    mime = (mime_type or "").lower()
    name = (filename or "").lower()
    return (
        mime.startswith("text/")
        or any(h in mime for h in _DOCUMENT_MIME_HINTS)
        or name.endswith(_DOCUMENT_EXTENSIONS)
    )


# ── Result / context types ───────────────────────────────────────────────────

@dataclass
class ExtractedContent:
    text: str
    method: str                      # 'document' | 'ai_ocr' (later: 'image_description', …)
    truncated: bool = False
    total_chars: int = 0             # pre-truncation length
    pages: Optional[int] = None      # PDFs only
    cost_charged: Optional[Decimal] = None  # set only when an AI method billed


@dataclass
class BillingContext:
    """Who pays for AI-assisted extraction. Raw runner + org — the usage
    tracker's organization attribution policy choke point resolves the billed pool."""
    user_id: str
    organization_id: Optional[str] = None
    workflow_id: Optional[str] = None
    node_id: Optional[str] = None
    sio: Any = None
    sid: Optional[str] = None


class ExtractionError(ValueError):
    """Unsupported type, oversize input, or an AI method failing. Message is
    user/agent-facing — callers surface it verbatim."""


# ── CPU placement ────────────────────────────────────────────────────────────

async def _extract_document_text(data: bytes, mime_type: str, filename: str) -> str:
    """Run CPU-bound document parsing outside the event loop."""
    from nodes.core.document_ingest import extract_text

    return await asyncio.to_thread(extract_text, data, mime_type, filename)


def _pdf_page_count(data: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


# ── AI OCR (first AI method; the registry pattern for image/video later) ─────

async def _ai_ocr_pdf(data: bytes, filename: str, billing: BillingContext) -> ExtractedContent:
    """OCR a scanned PDF with a vision model. Credit-gated, charged flat per page."""
    from billing.pricing import AI_EXTRACTION_PRICE_PER_PAGE
    from billing.schema import UsageEventData
    from billing.usage_tracker import usage_tracker

    pages = await asyncio.to_thread(_pdf_page_count, data)
    if pages > AI_OCR_MAX_PAGES:
        raise ExtractionError(
            f"'{filename}' has {pages} pages — AI OCR is capped at {AI_OCR_MAX_PAGES} pages per document."
        )

    # Pre-flight gate BEFORE any model spend; raises InsufficientBalanceError.
    await usage_tracker.enforce_credit_gate(
        billing.user_id,
        organization_id=billing.organization_id,
        sio=billing.sio,
        sid=billing.sid,
        surface="content_extraction",
    )

    import litellm

    b64 = base64.b64encode(data).decode()
    response = await litellm.acompletion(
        model=AI_EXTRACTION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Transcribe the full text content of this document. Output only the "
                    "document's text (tables as markdown), no commentary."
                )},
                {"type": "file", "file": {"file_data": f"data:application/pdf;base64,{b64}"}},
            ],
        }],
        temperature=0.0,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ExtractionError(f"AI OCR produced no text for '{filename}'.")

    cost = AI_EXTRACTION_PRICE_PER_PAGE * pages
    await usage_tracker.track_usage_event(
        UsageEventData(
            user_id=billing.user_id,
            total_cost=cost,
            usage_type="api_usage",
            usage_subtype="extraction/ai_ocr",
            quantity=Decimal(pages),  # pages billed as request units
            unit_type="requests",
            user_resource=False,
            organization_id=billing.organization_id,
            metadata={
                "filename": filename,
                "workflow_id": billing.workflow_id,
                "node_id": billing.node_id,
                "model": AI_EXTRACTION_MODEL,
            },
        ),
        sio=billing.sio,
        sid=billing.sid,
    )
    return ExtractedContent(text=text, method="ai_ocr", total_chars=len(text), pages=pages, cost_charged=cost)


# ── Public API ───────────────────────────────────────────────────────────────

def _budgeted(content: ExtractedContent, char_budget: Optional[int]) -> ExtractedContent:
    if char_budget is None or len(content.text) <= char_budget:
        return content
    note = (
        f"\n…[truncated — showing {char_budget:,} of {content.total_chars:,} characters; "
        f"fetch this attachment explicitly for the full text]"
    )
    content.text = content.text[:char_budget] + note
    content.truncated = True
    return content


async def extract_content(
    data: bytes,
    *,
    mime_type: str,
    filename: str,
    char_budget: Optional[int] = None,
    allow_ai: bool = False,
    billing: Optional[BillingContext] = None,
) -> ExtractedContent:
    """Extract readable text from attachment/document bytes.

    Free CPU path for text-layer documents. A PDF whose text layer is empty
    (scanned) raises ExtractionError unless ``allow_ai=True`` with a
    ``billing`` context, in which case it OCRs via the AI method — gated and
    charged. ``char_budget`` truncates with an explanatory note (used for
    inline auto-enrichment; explicit fetches pass None for full text).
    """
    if len(data) > MAX_EXTRACT_BYTES:
        raise ExtractionError(
            f"'{filename}' is {len(data) // (1024 * 1024)}MB — extraction is capped at "
            f"{MAX_EXTRACT_BYTES // (1024 * 1024)}MB."
        )
    if not can_extract(mime_type, filename):
        raise ExtractionError(
            f"Cannot extract '{filename}' ({mime_type}). Supported: PDF, DOCX, TXT, MD, CSV, JSON, HTML."
        )

    text = (await _extract_document_text(data, mime_type, filename)).strip()
    is_pdf = "pdf" in (mime_type or "").lower() or (filename or "").lower().endswith(".pdf")

    if text:
        return _budgeted(
            ExtractedContent(text=text, method="document", total_chars=len(text)), char_budget
        )

    if is_pdf and allow_ai:
        if billing is None:
            raise ExtractionError("AI OCR requires a billing context.")
        return _budgeted(await _ai_ocr_pdf(data, filename, billing), char_budget)

    raise ExtractionError(
        f"'{filename}' has no extractable text layer (likely a scanned document). "
        + ("" if not is_pdf else "Fetch it explicitly with AI extraction enabled to OCR it (billed per page).")
    )


# ── Shared attachment record + inline enrichment ─────────────────────────────

def attachment_record(
    *,
    filename: str,
    mime_type: str,
    size_bytes: Optional[int],
    source: str,
    attachment_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    download_url: Optional[str] = None,
) -> Dict[str, Any]:
    """The one attachment shape every email pathway emits (gmail/outlook/inbound)."""
    rec: Dict[str, Any] = {
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "source": source,
        "extractable": can_extract(mime_type, filename),
    }
    if attachment_id:
        rec["attachment_id"] = attachment_id
    if resource_id:
        rec["resource_id"] = resource_id
    if download_url:
        rec["download_url"] = download_url
    return rec


async def inline_enrich_attachments(
    records: List[Dict[str, Any]],
    fetch_bytes: Callable[[Dict[str, Any]], Awaitable[bytes]],
    *,
    char_budget: int = DEFAULT_INLINE_CHAR_BUDGET,
    max_attachments: int = INLINE_ENRICH_MAX_ATTACHMENTS,
) -> List[Dict[str, Any]]:
    """Natural surfacing: auto-extract small text-layer documents into the
    attachment records (``text`` / ``text_truncated`` keys) so agents read them
    without a tool call. Free CPU path only — never AI, never raises: an
    attachment that can't be enriched keeps its metadata plus a ``note``
    explaining how to get the content explicitly.
    """
    enriched = 0
    for rec in records:
        if enriched >= max_attachments:
            break
        if not rec.get("extractable"):
            continue
        size = rec.get("size_bytes") or 0
        if size > INLINE_BYTES_THRESHOLD * 4:  # 2MB inline-enrich cap
            rec["note"] = "Too large to inline — fetch this attachment explicitly for its content."
            continue
        try:
            data = await fetch_bytes(rec)
            content = await extract_content(
                data,
                mime_type=rec.get("mime_type") or "",
                filename=rec.get("filename") or "",
                char_budget=char_budget,
            )
            rec["text"] = content.text
            rec["text_truncated"] = content.truncated
            enriched += 1
        except Exception as e:  # metadata still stands; explain the escape hatch
            rec["note"] = str(e)
    return records
