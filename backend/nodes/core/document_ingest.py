"""
Shared document-ingest pipeline for the external vector-database nodes.

One place owns "upload a file → indexable chunks": resolve the uploaded file
(reusing the existing `media_upload` widget + `resolve_media_input`), extract
text (native pypdf / python-docx / bs4 / decode — no third-party parser),
chunk it, and (for providers without server-side embedding) embed the chunks
with NoClick's model and CHARGE the embedding to the running user/org via the
usage-tracker choke point.

Each vector-DB node's ``upload_and_index`` operation is a thin wrapper: call
``ingest_document`` (→ records with vectors) or ``ingest_document_text`` (→
text records, for providers that embed server-side), then map the records into
that provider's upsert body. The pipeline — including billing — lives here, not
duplicated per node.
"""

import io
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Accept string for the media_upload widget on every node's upload field.
DOCUMENT_ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.csv,.json,.html,.htm"

# Deterministic chunk ids (uuid5) so re-indexing the same source overwrites
# rather than duplicating — and they're valid for ID-strict stores like Qdrant.
_ID_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def chunk_id(source: str, index: int, prefix: Optional[str] = None) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{prefix or source}#{index}"))


def _decode(data: bytes) -> str:
    try:
        import chardet

        enc = chardet.detect(data).get("encoding") or "utf-8"
    except Exception:
        enc = "utf-8"
    return data.decode(enc, errors="replace")


def extract_text(data: bytes, mime_type: str, filename: str) -> str:
    """Extract plain text from an uploaded document's bytes.

    Routes by file extension first, then MIME. Raises ValueError for a type we
    can't extract (never returns garbage silently).
    """
    name = (filename or "").lower()
    mime = (mime_type or "").lower()

    if name.endswith(".pdf") or "pdf" in mime:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()

    if name.endswith((".docx",)) or "wordprocessingml" in mime:
        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs).strip()

    if name.endswith((".html", ".htm")) or "html" in mime:
        from bs4 import BeautifulSoup

        return BeautifulSoup(data, "html.parser").get_text("\n").strip()

    if name.endswith((".txt", ".md", ".markdown", ".csv", ".json")) or mime.startswith("text/") or "json" in mime:
        return _decode(data).strip()

    # Old .doc (binary) and everything else we don't have a native parser for.
    raise ValueError(
        f"Unsupported document type '{filename or mime_type}'. Supported: PDF, DOCX, TXT, MD, CSV, JSON, HTML."
    )


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks, preferring natural boundaries
    (paragraph → line → sentence → word) near the chunk edge."""
    text = (text or "").strip()
    if not text:
        return []
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 5
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            for sep in ("\n\n", "\n", ". ", " "):
                boundary = text.rfind(sep, start + chunk_size // 2, end)
                if boundary != -1:
                    end = boundary + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


async def load_and_chunk(
    document_value: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> Tuple[List[str], Dict[str, Any]]:
    """Resolve an uploaded file / URL → text → chunks. Returns (chunks, info)."""
    from nodes.core.media_resolver import resolve_media_input

    resolved = await resolve_media_input(document_value, default_mime="application/octet-stream")
    text = extract_text(resolved.data, resolved.mime_type, resolved.filename)
    chunks = chunk_text(text, chunk_size, chunk_overlap)
    return chunks, {"filename": resolved.filename, "mime_type": resolved.mime_type, "char_count": len(text)}


async def embed_texts(texts: List[str]) -> Tuple[List[List[float]], int]:
    """Embed texts with NoClick's model. Returns (embeddings, total_tokens)."""
    import litellm

    embeddings: List[List[float]] = []
    total_tokens = 0
    for i in range(0, len(texts), 96):  # batch (the model caps inputs per call)
        batch = texts[i : i + 96]
        resp = await litellm.aembedding(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend(item["embedding"] for item in resp.data)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        elif isinstance(resp, dict) and resp.get("usage"):
            total_tokens += int(resp["usage"].get("total_tokens", 0) or 0)
    return embeddings, total_tokens


async def _embed_and_charge(node, chunks: List[str]) -> List[List[float]]:
    """Gate the runner's credit balance, embed the chunks with NoClick's model,
    then charge the real embedding cost through the organization-attribution choke point.
    Mirrors the send-email node's gate+charge pattern."""
    import asyncio
    from decimal import Decimal

    from billing.usage_tracker import usage_tracker

    if not getattr(node, "user_id", None):
        raise ValueError("Document embedding requires a user context")

    await asyncio.to_thread(
        usage_tracker.enforce_credit_gate,
        node.user_id,
        organization_id=node.organization_id,
        sio=node.sio,
        sid=node.sid,
        user_resource=False,
        surface="document_embedding",
        loop=asyncio.get_running_loop(),
    )

    embeddings, tokens = await embed_texts(chunks)

    from billing.pricing import get_embedding_cost
    from billing.schema import UsageEventData

    await asyncio.to_thread(
        usage_tracker.track_usage_event,
        UsageEventData(
            user_id=node.user_id,
            total_cost=get_embedding_cost(tokens),
            usage_type="api_usage",
            usage_subtype=f"embedding/{EMBEDDING_MODEL}",
            quantity=Decimal(tokens),
            unit_type="tokens",
            user_resource=False,
            organization_id=node.organization_id,
            metadata={
                "chunks": len(chunks),
                "node_id": getattr(node, "node_id", None),
                "workflow_id": str(node.workflow_id) if getattr(node, "workflow_id", None) else None,
            },
        ),
    )
    return embeddings


async def ingest_document(
    node,
    document_value: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    id_prefix: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Full pipeline for providers that need client-supplied vectors: resolve →
    extract → chunk → embed (charged) → records.

    Returns (records, info) where each record is
    ``{id, values: [float], metadata: {text, source, chunk_index}}``.
    """
    chunks, info = await load_and_chunk(document_value, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        return [], info
    embeddings = await _embed_and_charge(node, chunks)
    source = info.get("filename") or "document"
    records = [
        {
            "id": chunk_id(source, i, id_prefix),
            "values": vector,
            "metadata": {"text": chunk, "source": source, "chunk_index": i},
        }
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings))
    ]
    return records, info


async def ingest_document_text(
    document_value: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    id_prefix: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Pipeline for providers that embed server-side (no NoClick embedding /
    charge): resolve → extract → chunk → text records.

    Returns (records, info) where each record is
    ``{id, text, metadata: {source, chunk_index}}``.
    """
    chunks, info = await load_and_chunk(document_value, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    source = info.get("filename") or "document"
    records = [
        {"id": chunk_id(source, i, id_prefix), "text": chunk, "metadata": {"source": source, "chunk_index": i}}
        for i, chunk in enumerate(chunks)
    ]
    return records, info
