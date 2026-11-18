"""Brand: how your product appears on the pages and emails NoClick sends for you, and the
OAuth apps your users connect with."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, Mapping, Optional

from ._client import Client, resolve_client
from ._object import UNSET, compact
from ._sync import synced
from .domain import domain_name
from .secret import secret_ids, secret_refs


@dataclass(frozen=True)
class Brand:
    """One per account; rendered on ``/h/`` pages and human emails. ``oauth_apps`` names your
    own OAuth app per provider, as ``{provider: secret id}``. ``oauth_redirect_urls`` has the
    redirect URI to register with your app at every provider you can bring one for, as
    ``{provider: url}``: you need it to create the app, before it is named here."""

    name: Optional[str]
    logo_url: Optional[str]
    color: Optional[str]
    support_url: Optional[str]
    email_from_name: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    # True while nothing is set (the defaults are shown).
    is_default: bool = False
    # The host your approval, question and hand-off pages are served from; None: NoClick's.
    domain: Optional[str] = None
    oauth_apps: Dict[str, str] = dc_field(default_factory=dict)
    oauth_redirect_urls: Dict[str, str] = dc_field(default_factory=dict)

    @classmethod
    def _from(cls, raw: Any) -> "Brand":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("name"), raw.get("logo_url"), raw.get("color"),
            raw.get("support_url"), raw.get("email_from_name"), raw, raw.get("is_default") is True,
            raw.get("domain"), dict(raw.get("oauth_apps") or {}), dict(raw.get("oauth_redirect_urls") or {}),
        )

    @synced
    @classmethod
    async def reset(cls, *, client: Optional[Client] = None) -> "Brand":
        """Remove the account's brand: pages and emails go back to the defaults.

        Returns:
            NoClick's default brand, with ``is_default`` ``True``.

        Usage::

            brand = noclick.Brand.reset()
            print(brand.is_default)   # True
        """
        return cls._from(await resolve_client(client).request("DELETE", "/v1/brand", user=None))

    @synced
    @classmethod
    async def get(cls, *, client: Optional[Client] = None) -> "Brand":
        """Read the account's brand.

        Returns:
            The brand your pages and emails show now; ``is_default`` is ``True`` while you haven't set one.

        Usage::

            brand = noclick.Brand.get()
            print(brand.name, brand.color, brand.is_default)
        """
        return cls._from(await resolve_client(client).request("GET", "/v1/brand", user=None))

    @synced
    @classmethod
    async def set(
        cls,
        *,
        name: Optional[str] = None,
        logo_url: Optional[str] = None,
        color: Optional[str] = None,
        support_url: Optional[str] = None,
        email_from_name: Optional[str] = None,
        domain: Any = None,
        oauth_apps: Optional[Mapping[str, Any]] = None,
        client: Optional[Client] = None,
    ) -> "Brand":
        """Replace the account's brand with these fields (``color`` as ``"#RRGGBB"``, or ``"#RGB"``);
        a field left out is cleared. To change one field and keep the rest, use ``update``.

        ``oauth_apps`` maps a provider (``google``, ``slack``, ``box``, ...) to an account
        ``Secret`` (or its id or name) holding ``CLIENT_ID`` and ``CLIENT_SECRET`` of your own
        OAuth app there, so the consent screen your users see names you; register the
        provider's ``oauth_redirect_urls`` entry as the app's redirect URI. Connect links made
        after it is set sign in with that app, and each connection keeps the app it was made
        with, refreshing on it too: connections made before keep NoClick's until they're
        reconnected. A provider NoClick can't sign in to with your own app yet raises
        ``noclick.InvalidRequest`` naming those it can.

        ``domain`` (a ``Domain`` your account holds, or its name, such as ``connect.acme.com``)
        serves the approval, question and hand-off pages NoClick shows your users from your own
        host, and the emails that bring people there link to it and name only your brand (they come
        from NoClick's address under ``email_from_name``; connect links stay on NoClick's host for
        now). A bought domain gets its CNAME at once; a connected one lists the records to add in
        its ``records``: the CNAME, and a TXT that proves the name is yours. The domain's
        ``serves`` then includes ``brand``. ``None`` moves the pages back to NoClick's host.

        Returns:
            The saved brand, with ``color`` lowercased and ``is_default`` ``False``. A field you left out is now empty.

        Usage:
            Show your name, logo and colour::

                noclick.Brand.set(
                    name="Acme",
                    logo_url="https://acme.com/logo.png",
                    color="#FF5500",
                    support_url="https://acme.com/help",
                    email_from_name="Acme Support",
                )

            Ask for Google access with your own app. Create it with the redirect URI from
            ``Brand.get().oauth_redirect_urls["google"]``, put its client id and secret in a
            secret, then name it::

                noclick.Brand.set(
                    name="Acme",
                    logo_url="https://acme.com/logo.png",
                    oauth_apps={"google": noclick.Secret.from_name("google-oauth-app")},
                )

            Serve the pages from your own host::

                noclick.Brand.set(name="Acme", domain="connect.acme.com")
        """
        body = await _body(dict(name=name, logo_url=logo_url, color=color, support_url=support_url,
                                email_from_name=email_from_name, domain=domain, oauth_apps=oauth_apps), client)
        return cls._from(await resolve_client(client).request("PUT", "/v1/brand", json=body, user=None))

    @synced
    @classmethod
    async def update(
        cls,
        *,
        name: Any = UNSET,
        logo_url: Any = UNSET,
        color: Any = UNSET,
        support_url: Any = UNSET,
        email_from_name: Any = UNSET,
        domain: Any = UNSET,
        oauth_apps: Any = UNSET,
        client: Optional[Client] = None,
    ) -> "Brand":
        """Change only the fields you pass; the rest stay as they are. ``None`` clears a field.
        ``set`` replaces the whole brand instead. ``oauth_apps`` changes only the providers it
        names (links made after for a provider mapped to ``None`` sign in with NoClick's app), and
        ``oauth_apps=None`` removes them all. ``domain`` is as in ``set``.
        Before you've set a brand, it changes NoClick's default one: the name stays ``NoClick``
        until you give it yours.

        Returns:
            The saved brand. A field you left out is unchanged.

        Usage::

            noclick.Brand.update(color="#FF5500")    # the name, logo and the rest are kept
            noclick.Brand.update(support_url=None)   # no support link from now on
            noclick.Brand.update(oauth_apps={"slack": noclick.Secret.from_name("slack-oauth-app")})   # Google's stays
            noclick.Brand.update(oauth_apps={"google": None})   # new Google links use NoClick's app
        """
        fields = dict(name=name, logo_url=logo_url, color=color, support_url=support_url,
                      email_from_name=email_from_name, domain=domain, oauth_apps=oauth_apps)
        body = await _body({k: v for k, v in fields.items() if v is not UNSET}, client, keep_none=True)
        return cls._from(await resolve_client(client).request("PATCH", "/v1/brand", json=body, user=None))


async def _body(fields: Dict[str, Any], client: Optional[Client], *, keep_none: bool = False) -> Dict[str, Any]:
    """The wire body: ``oauth_apps`` secrets as ids (``None`` kept: a provider going back to
    NoClick's app) and ``domain`` as a name. ``keep_none`` sends ``None`` (a clear) instead of dropping it."""
    if fields.get("oauth_apps") is not None:
        apps = fields["oauth_apps"]
        named = {provider: secret for provider, secret in apps.items() if secret is not None}
        ids = dict(zip(named, await secret_ids(secret_refs(list(named.values()), user=None, client=client) or [])))
        fields["oauth_apps"] = {provider: ids.get(provider) for provider in apps}
    if fields.get("domain") is not None:
        fields["domain"] = await domain_name(fields["domain"])
    return fields if keep_none else compact(**fields)
