"""Sharing your resources with people, as the app's Share dialog does.

    intake = noclick.Workflow.from_name("Order intake")
    share = noclick.Share.create(intake, email="sam@example.com", access="edit")
    print([(s.name, s.access) for s in noclick.Share.list(intake)])
    share.delete()

A workflow, a workflow folder, a database, a connection, a saved output or a skill is shared with a person by email
(who's told, and gets it once they have an account), a team workspace of the NoClick app, or, for a workflow, anyone
with the link. Whoever manages the resource's shares (its owner, or a team workspace's admin for the workspace's own)
reads and changes them. Sharing is between people: a call acting for one of your users has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import parse_time, ref_id
from ._sync import synced


def _resource(resource: Any, resource_type: Optional[str]) -> Dict[str, Any]:
    from .workflow import Workflow

    kind = resource_type or ("workflow" if isinstance(resource, Workflow) else None)
    if kind is None:
        raise ValueError("Name the resource_type of anything but a Workflow: workflow, workflow_folder, database, "
                         "credential, saved_output or skill.")
    return {"resource_type": kind}


@dataclass(frozen=True)
class ShareInviteLink:
    """A personal workflow's invite link: whoever opens it signed in joins the workflow with its ``access``."""

    workflow_id: str
    url: str
    token: str
    access: str


@dataclass(frozen=True)
class Share:
    """Who one of your resources is shared with, and what they may do with it."""

    id: str
    resource_type: str
    resource_id: str
    #: ``user`` (a person, by ``email``), ``organization`` (a team workspace) or ``public`` (anyone with ``url``).
    with_: str
    #: ``view`` or ``edit``.
    access: str
    #: Who it's with, as the app names them.
    name: Optional[str]
    email: Optional[str]
    user_id: Optional[str]
    organization_id: Optional[str]
    #: A person without an account yet: they get it once they make one.
    pending: bool
    #: A public share's page.
    url: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Share":
        return cls(raw["id"], raw["resource_type"], raw["resource_id"], raw["with"], raw["access"], raw.get("name"),
                   raw.get("email"), raw.get("user_id"), raw.get("organization_id"), bool(raw.get("pending")),
                   raw.get("url"), parse_time(raw.get("created_at")), raw)

    @synced
    @staticmethod
    async def list(resource: Any, *, resource_type: Optional[str] = None,
                   client: Optional[Client] = None) -> List["Share"]:
        """Who ``resource`` (a ``Workflow``, or any resource's id with its ``resource_type``) is shared with. Only someone who manages its shares reads them.

        Returns:
            Each share, with whom (``with_``, ``name``) and what it allows (``access``).

        Usage::

            for share in noclick.Share.list(noclick.Workflow.from_name("Order intake")):
                print(share.name, share.access, share.pending)
        """
        params = {**_resource(resource, resource_type), "resource_id": await ref_id(resource)}
        page = await resolve_client(client).request("GET", "/v1/shares", params=params, user=None) or {}
        return [Share._from(row) for row in page.get("data") or []]

    @synced
    @staticmethod
    async def create(resource: Any, *, email: Optional[str] = None, organization_id: Optional[str] = None,
                     public: bool = False, access: str = "view", resource_type: Optional[str] = None,
                     client: Optional[Client] = None) -> "Share":
        """Share ``resource`` with a person by ``email`` (they're told; someone without an account gets it once they
        make one), a team workspace (``organization_id``), or, for a workflow, anyone with the link (``public``,
        always to view). Sharing again with the same one changes its ``access`` (``view`` or ``edit``).

        Returns:
            The share.

        Usage::

            noclick.Share.create(noclick.Workflow.from_name("Order intake"), email="sam@example.com", access="edit")
        """
        body = {**_resource(resource, resource_type), "resource_id": await ref_id(resource), "access": access,
                "with": "public" if public else "organization" if organization_id else "user"}
        if email is not None:
            body["email"] = email
        if organization_id is not None:
            body["organization_id"] = organization_id
        return Share._from(await resolve_client(client).request("POST", "/v1/shares", json=body, user=None))

    @synced
    async def update(self, access: str, *, client: Optional[Client] = None) -> "Share":
        """Change what it allows (``view`` or ``edit``).

        Returns:
            The share as it is now.

        Usage::

            [share] = noclick.Share.list(noclick.Workflow.from_name("Order intake"))
            share.update("view")
        """
        return Share._from(await resolve_client(client).request(
            "PATCH", f"/v1/shares/{quote(self.id, safe='')}", json={"access": access}, user=None))

    @synced
    async def delete(self, *, client: Optional[Client] = None) -> None:
        """End it: whoever it was with stops seeing the resource (sharing it again gives it back).

        Usage::

            for share in noclick.Share.list(noclick.Workflow.from_name("Order intake")):
                if share.pending:
                    share.delete()
        """
        await resolve_client(client).request("DELETE", f"/v1/shares/{quote(self.id, safe='')}", user=None)

    @synced
    @staticmethod
    async def leave(resource: Any, *, resource_type: Optional[str] = None, client: Optional[Client] = None) -> bool:
        """Stop seeing something shared with you: your own share of it goes.

        Returns:
            False when there was none to drop (it reaches you through a team workspace or a shared folder).

        Usage::

            noclick.Share.leave("6f1c…", resource_type="workflow")
        """
        body = {**_resource(resource, resource_type), "resource_id": await ref_id(resource)}
        answer = await resolve_client(client).request("POST", "/v1/shares/leave", json=body, user=None) or {}
        return bool(answer.get("left"))

    @synced
    @staticmethod
    async def invite_link(workflow: Any, *, client: Optional[Client] = None) -> ShareInviteLink:
        """A personal workflow's invite link: whoever opens it signed in joins the workflow as a collaborator. Its
        owner makes it the first time; anyone it's shared with reads the one that's on.

        Returns:
            The link's ``url`` and the ``access`` it gives.

        Usage::

            print(noclick.Share.invite_link(noclick.Workflow.from_name("Order intake")).url)
        """
        workflow_id = await ref_id(workflow)
        raw = await resolve_client(client).request("POST", "/v1/shares/invite_links",
                                                   json={"workflow_id": workflow_id}, user=None)
        return ShareInviteLink(raw["workflow_id"], raw["url"], raw["token"], raw["access"])
