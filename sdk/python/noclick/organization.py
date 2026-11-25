"""The team workspaces of the NoClick app you're in, as its workspace settings show them.

    acme = noclick.Organization.create("Acme Ops")
    noclick.Organization.invite(acme, "sam@example.com", role="admin")
    for member in noclick.Organization.members(acme):
        print(member["email"], member["role"])

A team workspace's members are people, so every call is a signed-in person's own: a client holding a person's
session token (never a key, which refuses them all). Not ``noclick.Workspace``, which is one of Work's spaces.
Members, invites and single sign-on come back as the API answers them (dicts).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._sync import synced


def _id(organization: Any) -> str:
    return quote(str(organization.id if isinstance(organization, Organization) else organization), safe="")


async def _call(client: Optional[Client], method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    return await resolve_client(client).request(
        method, path, json={k: v for k, v in (body or {}).items() if v is not None} if body is not None else None,
        user=None)


@dataclass(frozen=True)
class Organization:
    """A team workspace you're in."""

    id: str
    name: str
    slug: str
    #: Your role in it: ``owner``, ``admin`` or ``member``.
    role: Optional[str]
    icon_url: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Organization":
        return cls(str(raw["id"]), raw.get("name") or "", raw.get("slug") or "", raw.get("role") or raw.get("user_role"),
                   raw.get("icon_url"), raw)

    @synced
    @staticmethod
    async def list(*, client: Optional[Client] = None) -> List["Organization"]:
        """The team workspaces you're in, each with your ``role``.

        Returns:
            Each team workspace you're in, as an ``Organization``.

        Usage::

            for workspace in noclick.Organization.list():
                print(workspace.name, workspace.role)
        """
        page = await _call(client, "GET", "/v1/organizations") or {}
        return [Organization._from(row) for row in page.get("data") or []]

    @synced
    @staticmethod
    async def get(organization: Any, *, client: Optional[Client] = None) -> "Organization":
        """One you're in, by id.

        Returns:
            The ``Organization``.

        Usage::

            print(noclick.Organization.get("8c1f…").name)
        """
        return Organization._from((await _call(client, "GET", f"/v1/organizations/{_id(organization)}"))["organization"])

    @synced
    @staticmethod
    async def create(name: str, *, slug: Optional[str] = None, client: Optional[Client] = None) -> "Organization":
        """Make a team workspace with you as its owner (``slug`` made from the name when left out); your session acts
        in it from then on. How many you may own is your plan's.

        Returns:
            The new ``Organization``.

        Usage::

            acme = noclick.Organization.create("Acme Ops")
        """
        made = await _call(client, "POST", "/v1/organizations", {"name": name, "slug": slug})
        return Organization._from({**made["organization"], "role": "owner"})

    @synced
    @staticmethod
    async def update(organization: Any, *, name: Optional[str] = None, settings: Optional[Dict[str, Any]] = None,
                     client: Optional[Client] = None) -> Dict[str, Any]:
        """Rename it or change its settings (its owner or an admin).

        Returns:
            The team workspace as it now stands.

        Usage::

            noclick.Organization.update(acme, name="Acme Operations")
        """
        return await _call(client, "PATCH", f"/v1/organizations/{_id(organization)}",
                           {"name": name, "settings": settings})

    @synced
    @staticmethod
    async def delete(organization: Any, *, client: Optional[Client] = None) -> None:
        """Delete it for good, its members and invites with it (its owner only).

        Usage::

            noclick.Organization.delete(acme)
        """
        await _call(client, "DELETE", f"/v1/organizations/{_id(organization)}")

    @synced
    @staticmethod
    async def slug_available(slug: str, *, client: Optional[Client] = None) -> bool:
        """Whether a new team workspace could take ``slug``.

        Returns:
            ``True`` when no team workspace has it.

        Usage::

            print(noclick.Organization.slug_available("acme-ops"))
        """
        return bool((await _call(client, "GET", f"/v1/organizations/slugs/{quote(slug, safe='')}")).get("available"))

    @synced
    @staticmethod
    async def members(organization: Any, *, client: Optional[Client] = None) -> List[Dict[str, Any]]:
        """Its members, each with their ``user_id``, ``email`` and ``role``.

        Returns:
            Each member, with their ``user_id``, ``email``, ``full_name`` and ``role``.

        Usage::

            print([m["email"] for m in noclick.Organization.members(acme)])
        """
        return (await _call(client, "GET", f"/v1/organizations/{_id(organization)}/members")).get("data") or []

    @synced
    @staticmethod
    async def spend_cap(organization: Any, *, client: Optional[Client] = None) -> Dict[str, Any]:
        """The monthly spending cap of the account that pays for its work, and what that account's billing period
        has spent. Only the person who pays changes it, as their own account's cap (``PATCH /v1/account``).

        Returns:
            ``cap_usd`` (``None`` for none), ``spent_usd``, ``period_start``, ``resets_at``, ``reached``, and
            ``payer``: ``{"self": True}`` when it's you, else ``{"self": False, "name": ...}``.

        Usage::

            cap = noclick.Organization.spend_cap(acme)
            print(cap["cap_usd"], cap["payer"])
        """
        return await _call(client, "GET", f"/v1/organizations/{_id(organization)}/spend_cap")

    @synced
    @staticmethod
    async def invite(organization: Any, email: str, *, role: str = "member",
                     client: Optional[Client] = None) -> Dict[str, Any]:
        """Invite someone by email (its owner or an admin): they're emailed a link that joins them as ``role``
        (``admin`` or ``member``). How many people it holds is its plan's.

        Returns:
            The invite, with ``email_sent``: ``False`` when its email couldn't go (``email_error`` says why), and the
            invite stands all the same, so share its link yourself.

        Usage::

            noclick.Organization.invite(acme, "sam@example.com", role="admin")
        """
        made = await _call(client, "POST", f"/v1/organizations/{_id(organization)}/members",
                           {"email": email, "role": role})
        return {**made["invite"], **{k: made[k] for k in ("email_sent", "email_error") if k in made}}

    @synced
    @staticmethod
    async def set_role(organization: Any, user_id: str, role: str, *, client: Optional[Client] = None) -> None:
        """Change a member's role (its owner or an admin; never the owner's).

        Usage::

            noclick.Organization.set_role(acme, "6a0b…", "admin")
        """
        await _call(client, "PATCH", f"/v1/organizations/{_id(organization)}/members/{quote(user_id, safe='')}",
                    {"role": role})

    @synced
    @staticmethod
    async def remove_member(organization: Any, user_id: str, *, client: Optional[Client] = None) -> None:
        """Take a member out (its owner or an admin; never the owner).

        Usage::

            noclick.Organization.remove_member(acme, "6a0b…")
        """
        await _call(client, "DELETE", f"/v1/organizations/{_id(organization)}/members/{quote(user_id, safe='')}")

    @synced
    @staticmethod
    async def transfer(organization: Any, user_id: str, *, client: Optional[Client] = None) -> None:
        """Hand it to another of its members (its owner only): they become its owner, you an admin.

        Usage::

            noclick.Organization.transfer(acme, "6a0b…")
        """
        await _call(client, "POST", f"/v1/organizations/{_id(organization)}/transfer", {"user_id": user_id})

    @synced
    @staticmethod
    async def invites(organization: Any, *, client: Optional[Client] = None) -> List[Dict[str, Any]]:
        """Its invites still waiting to be accepted.

        Returns:
            Each invite still waiting, with its ``email``, ``role`` and when it expires.

        Usage::

            print([i["email"] for i in noclick.Organization.invites(acme)])
        """
        return (await _call(client, "GET", f"/v1/organizations/{_id(organization)}/invites")).get("data") or []

    @synced
    @staticmethod
    async def revoke_invite(organization: Any, invite_id: str, *, client: Optional[Client] = None) -> None:
        """Call an invite off: its link stops working.

        Usage::

            noclick.Organization.revoke_invite(acme, "c3d4…")
        """
        await _call(client, "DELETE", f"/v1/organizations/{_id(organization)}/invites/{quote(invite_id, safe='')}")

    @synced
    @staticmethod
    async def accept_invite(token: str, *, client: Optional[Client] = None) -> Dict[str, Any]:
        """Join the team workspace an invite to your email asks you to.

        Returns:
            The ``organization_id`` and ``organization_name`` of the team workspace you joined.

        Usage::

            noclick.Organization.accept_invite(token)
        """
        return await _call(client, "POST", f"/v1/organizations/invites/{quote(token, safe='')}/accept")

    @synced
    @staticmethod
    async def invitation(token: str, *, client: Optional[Client] = None) -> Dict[str, Any]:
        """An invite to a team workspace by its token, before accepting it.

        Returns:
            Which workspace (``organization_name``), from whom, and as what ``role``.

        Usage::

            invite = noclick.Organization.invitation(token)
            print(invite["organization_name"], invite["role"])
        """
        return await _call(client, "GET", f"/v1/organizations/invites/{quote(token, safe='')}")

    @synced
    @staticmethod
    async def upload_icon(organization: Any, image_data: str, *, content_type: str = "image/png",
                          client: Optional[Client] = None) -> Dict[str, Any]:
        """Set its picture (its owner or an admin): ``image_data`` base64, at most 2 MB; ``content_type`` image/png,
        image/jpeg, image/gif or image/webp.

        Returns:
            Its ``icon_url``.

        Usage::

            import base64

            noclick.Organization.upload_icon(acme, base64.b64encode(open("logo.png", "rb").read()).decode())
        """
        return await _call(client, "PUT", f"/v1/organizations/{_id(organization)}/icon",
                           {"image_data": image_data, "content_type": content_type})

    @synced
    @staticmethod
    async def sso(organization: Any, *, client: Optional[Client] = None) -> Dict[str, Any]:
        """Its SAML single sign-on, as it's set up.

        Returns:
            Its domain, its identity provider's metadata URL and whether it's on.

        Usage::

            print(noclick.Organization.sso(acme))
        """
        return await _call(client, "GET", f"/v1/organizations/{_id(organization)}/sso")

    @synced
    @staticmethod
    async def configure_sso(organization: Any, *, domain: str, metadata_url: str,
                            attribute_mapping: Optional[Dict[str, Any]] = None,
                            client: Optional[Client] = None) -> Dict[str, Any]:
        """Set up SAML single sign-on for its email domain (its owner only), from the identity provider's metadata.

        Returns:
            The single sign-on as it's now set up.

        Usage::

            noclick.Organization.configure_sso(acme, domain="acme.com", metadata_url="https://idp.acme.com/metadata")
        """
        return await _call(client, "PUT", f"/v1/organizations/{_id(organization)}/sso",
                           {"domain": domain, "metadata_url": metadata_url, "attribute_mapping": attribute_mapping})

    @synced
    @staticmethod
    async def disable_sso(organization: Any, *, client: Optional[Client] = None) -> None:
        """Turn its single sign-on off (its owner only).

        Usage::

            noclick.Organization.disable_sso(acme)
        """
        await _call(client, "DELETE", f"/v1/organizations/{_id(organization)}/sso")

    @synced
    @staticmethod
    async def switch_to(organization: Any, *, client: Optional[Client] = None) -> None:
        """Make the workspace your session acts in a team one you're in, or your own (``None``).

        Usage::

            noclick.Organization.switch_to(None)
        """
        ref = organization.id if isinstance(organization, Organization) else organization
        await _call(client, "POST", "/v1/me/organization", {"organization_id": ref})
