from urllib.parse import parse_qs, urlparse

from nodes.oauth.zoom_oauth import get_zoom_auth_url


def test_zoom_authorization_url_uses_marketplace_configured_scopes_only():
    """Zoom rejects a caller-provided scope parameter during Marketplace auth."""
    url = get_zoom_auth_url(
        ["meeting:read:meeting", "webinar:write:webinar"],
        state="csrf-state",
        redirect_uri="https://app.example.test/api/auth/zoom/callback",
        client_id="zoom-client-id",
    )

    query = parse_qs(urlparse(url).query)
    assert query == {
        "client_id": ["zoom-client-id"],
        "redirect_uri": ["https://app.example.test/api/auth/zoom/callback"],
        "response_type": ["code"],
        "state": ["csrf-state"],
    }
