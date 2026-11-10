"""Google Docs → OAuth scope requirements (Google's shared scope notes are in google.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google import DRIVE, _table


DOCUMENTS = "https://www.googleapis.com/auth/documents"


# ---------------------------------------------------------------------------
# Docs — docs/v1, except the document picker which lists via Drive.
# ---------------------------------------------------------------------------
GOOGLE_DOCS_SCOPES = ScopeRegistry(
    provider="google-docs",
    requirements=_table(
        {
            DOCUMENTS: (
                "fetch_document_content",
                "create_new_document",
                "append_text_to_document",
                "insert_text_in_document",
                "replace_document_text",
            ),
            # Drive `files.list` filtered to the Docs mime type.
            DRIVE: ("list_google_drive_documents",),
        }
    ),
)
