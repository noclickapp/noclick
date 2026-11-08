"""Bookeo declarations exercise staging's OAuth2 transport and refresh hooks."""
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from unittest.mock import AsyncMock
import httpx
from nodes.bookeo_node import BookeoNode
from nodes.oauth.bookeo_oauth import OAUTH_PROVIDER


def test_exchange_uses_basic_pkce_and_business_identity(monkeypatch):
    monkeypatch.setenv('BOOKEO_CLIENT_ID', 'client')
    monkeypatch.setenv('BOOKEO_CLIENT_SECRET', 'secret')
    redirect = 'https://app.example.test/api/auth/oauth/bookeo/callback'
    monkeypatch.setenv('BOOKEO_REDIRECT_URI', redirect)
    requests = []
    def respond(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(200, json={'access_token': 'access', 'refresh_token': 'refresh', 'expires_in': 3600, 'token_type': 'Bearer'})
        return httpx.Response(200, json={'name': 'Business'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    tokens, name = asyncio.run(OAUTH_PROVIDER.exchange('code', redirect, 'v'*43))
    token, identity = requests
    assert str(token.url) == 'https://oauth.bookeo.com/o2/token'
    assert token.headers['authorization'] == 'Basic Y2xpZW50OnNlY3JldA=='
    assert parse_qs(token.content.decode()) == {
        'grant_type': ['authorization_code'], 'code': ['code'],
        'redirect_uri': [redirect], 'code_verifier': ['v'*43]}
    assert str(identity.url) == 'https://api.bookeo.com/v2/settings/business'
    assert identity.headers['authorization'] == 'Bearer access'
    assert tokens.access_token == 'access' and name == 'Business'


def test_refresh_hook_uses_shared_refresh_manager(monkeypatch):
    from nodes.core import oauth_refresh
    credential = {'credential_type': 'bookeo_oauth', 'access_token': 'access', 'refresh_token': 'refresh',
                  'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    freshen = AsyncMock(return_value=credential)
    monkeypatch.setattr(oauth_refresh, 'freshen_oauth_credential', freshen)
    assert asyncio.run(BookeoNode.freshen_credential(credential, credential_id='saved', user_id='user')) == credential
    assert freshen.call_args.kwargs['provider'] == 'bookeo'
    assert freshen.call_args.kwargs['refresh'] == OAUTH_PROVIDER.refresh
