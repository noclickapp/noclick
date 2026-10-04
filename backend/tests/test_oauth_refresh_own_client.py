"""A credential minted on an OAuth app of its own (it holds ``client_id`` and
``client_secret``: a requester's app, or one typed into the connect form)
refreshes on that app, whichever name its provider's refresh gives the client;
any other credential refreshes on the instance's."""

from types import SimpleNamespace

import pytest

from nodes.core.oauth_refresh import ensure_fresh_oauth_token, own_client_kwargs

pytestmark = pytest.mark.asyncio

EXPIRED = "2000-01-01T00:00:00+00:00"


def _tokens():
    return SimpleNamespace(access_token="new", refresh_token="r2", expires_at="2099-01-01T00:00:00+00:00")


async def test_a_credential_on_its_own_app_refreshes_on_it():
    seen = []

    async def google_like(refresh_token, custom_client_id=None, custom_client_secret=None):
        seen.append((refresh_token, custom_client_id, custom_client_secret))
        return _tokens()

    async def box_like(refresh_token, client_id=None, client_secret=None):
        seen.append((refresh_token, client_id, client_secret))
        return _tokens()

    for refresh in (google_like, box_like):
        credential = {"access_token": "old", "refresh_token": "r1", "expires_at": EXPIRED,
                      "client_id": "acme-id", "client_secret": "acme-secret"}
        token = await ensure_fresh_oauth_token(credential_id=None, user_id=None, credential=credential,
                                               refresh=refresh, provider="test", caller_path="execute")
        assert token == "new"
    assert seen == [("r1", "acme-id", "acme-secret"), ("r1", "acme-id", "acme-secret")]


async def test_any_other_credential_refreshes_on_the_instances_app():
    seen = []

    async def google_like(refresh_token, custom_client_id=None, custom_client_secret=None):
        seen.append((custom_client_id, custom_client_secret))
        return _tokens()

    async def takes_no_client(refresh_token):
        seen.append("plain")
        return _tokens()

    await ensure_fresh_oauth_token(credential_id=None, user_id=None, refresh=google_like, provider="test",
                                   caller_path="execute",
                                   credential={"access_token": "old", "refresh_token": "r1", "expires_at": EXPIRED})
    await ensure_fresh_oauth_token(credential_id=None, user_id=None, refresh=takes_no_client, provider="test",
                                   caller_path="execute",
                                   credential={"access_token": "old", "refresh_token": "r1", "expires_at": EXPIRED,
                                               "client_id": "id", "client_secret": "secret"})
    assert seen == [(None, None), "plain"]
    assert own_client_kwargs(takes_no_client, {"client_id": "a", "client_secret": "b"}) is None
