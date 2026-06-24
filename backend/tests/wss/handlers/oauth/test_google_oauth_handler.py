from unittest.mock import AsyncMock

from wss.handlers.oauth.google_oauth_handler import GoogleOAuthHandler


def test_get_credential_type_maps_firestore_scope():
    handler = GoogleOAuthHandler(AsyncMock())

    credential_type = handler._get_credential_type_from_scopes(
        ["https://www.googleapis.com/auth/datastore"]
    )

    assert credential_type == "firestore_oauth"
