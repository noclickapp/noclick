"""A connect link that brings an OAuth app of its requester's (``OAUTH_APPS``) signs in on it through the app's own
sign-in: for every provider ``oauth_app_providers()`` says takes one, the exchange event the link builds names the
app, the provider's exchange is called with it, and the credential keeps it so its refreshes run on it too."""

import inspect
import typing

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.credential_request_routes import oauth_app_providers
from utils.encryption import get_encryption
from utils.link_sign_in import client_fields, exchange_request, sign_in

CLIENT = {"client_id": "own-client", "client_secret": "own-secret"}
OWNER_ID = "00000000-0000-4000-8000-0000000000a1"
# What each provider's connect form may send beside the code; a sign-in takes only the fields its event declares.
INPUTS = {"code": "code-1", "redirect_uri": "https://noclick.test/oauth/callback",
          "code_verifier": "verifier", "credential_name": "Mine", "shop": "acme.myshopify.com", "subdomain": "acme",
          "realm_id": "1", "region": "us", "jira_site": "acme"}


class _Answer:
    """A provider's tokens and account, any field a handler reads present (an id, a domain, a token)."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return "1"


def _exchange_name(module):
    """The name the provider's sign-in calls its exchange by, in the module that calls it."""
    return next(name for name, value in vars(module).items()
                if getattr(value, "__name__", None) == "exchange_code_for_tokens")


@pytest.mark.parametrize("provider", sorted(oauth_app_providers()))
async def test_a_sign_in_on_the_requesters_app_exchanges_and_keeps_it(provider, real_database, monkeypatch):
    import importlib

    module = importlib.import_module(f"nodes.oauth.{provider}_oauth")
    returns_pair = len(typing.get_args(typing.get_type_hints(module.exchange_code_for_tokens).get("return"))) == 2
    seen = {}

    async def exchange(**kwargs):
        seen.update(kwargs)
        return (_Answer(), _Answer()) if returns_pair else _Answer()

    # The handler (or the module it delegates to) calls the exchange by the name it imported.
    for caller in (f"wss.handlers.oauth.{provider}_oauth_handler", "utils.pipedrive_connection"):
        caller_module = importlib.import_module(caller)
        if any(getattr(v, "__name__", None) == "exchange_code_for_tokens" for v in vars(caller_module).values()):
            monkeypatch.setattr(caller_module, _exchange_name(caller_module), exchange)
    stored = {}

    async def store(credential_type, name, encrypted, metadata):
        stored.update(get_encryption().decrypt_credential(encrypted))
        return {"id": "00000000-0000-4000-8000-0000000000c1", "name": name}, None

    named = client_fields(provider, CLIENT)
    assert named is not None
    # Scopes in the shape the provider's form sends them: a list, or Shopify's one comma-joined string.
    scopes = "" if exchange_request(provider).model_fields["scopes"].annotation in (str, typing.Optional[str]) else []
    await sign_in(provider, {**INPUTS, "scopes": scopes, **named}, user_id=OWNER_ID, tier="free", store=store)

    sent = set(inspect.signature(module.exchange_code_for_tokens).parameters) & set(named)
    assert {k: seen[k] for k in sent} == named
    # Kept under the names the provider's refresh reads (client_id/client_secret; Shopify's own pair).
    assert {CLIENT["client_id"], CLIENT["client_secret"]} <= set(stored.values())
