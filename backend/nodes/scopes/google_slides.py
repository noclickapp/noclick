"""Google Slides → OAuth scope requirements (Google's shared scope notes are in google.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google import DRIVE, _table


PRESENTATIONS = "https://www.googleapis.com/auth/presentations"


# ---------------------------------------------------------------------------
# Slides — slides/v1, except the presentation picker which lists via Drive.
# ---------------------------------------------------------------------------
GOOGLE_SLIDES_SCOPES = ScopeRegistry(
    provider="google-slides",
    requirements=_table(
        {
            PRESENTATIONS: (
                "get_presentation_metadata",
                "create_new_presentation",
                "add_presentation_slide",
                "delete_presentation_slide",
                "get_slide_page",
                "get_slide_thumbnail",
            ),
            # Drive `files.list` filtered to the Slides mime type.
            DRIVE: ("list_google_drive_presentations",),
        }
    ),
)
