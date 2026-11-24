"""SavedOutput: a step's output a person saved under a name while building, to show again or pin as the step's
output."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class SavedOutput:
    """An output saved under a name, kept by step type: read beside every step of that type on any workflow your
    account opens, your account's own first (``mine``), then those made public or shared with it. Reading them takes
    what opening the workflow takes; saving, renaming and deleting take what changing it takes, and renaming or
    deleting one also takes being its owner or holding a share that may edit it. A key held to one of your users
    raises ``noclick.PermissionDenied``."""

    id: str
    workflow_id: str
    name: str
    step_type: str
    output: Dict[str, Any]
    visibility: str
    owner_id: Optional[str]
    mine: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, workflow_id: str, raw: Any) -> "SavedOutput":
        raw = raw if isinstance(raw, dict) else {}
        output = raw.get("output")
        return cls(str(raw.get("id")), workflow_id, str(raw.get("name") or ""), str(raw.get("step_type") or ""),
                   output if isinstance(output, dict) else {},
                   "public" if raw.get("visibility") == "public" else "user", raw.get("owner_id"),
                   raw.get("mine") is True, parse_time(raw.get("created_at")), parse_time(raw.get("updated_at")), raw)

    @staticmethod
    def _base(workflow_id: str) -> str:
        return f"/v1/workflows/{quote(workflow_id, safe='')}/saved_outputs"

    @synced
    @classmethod
    async def list(cls, workflow_id: str, step_type: str, *,
                   client: Optional[Client] = None) -> List["SavedOutput"]:
        """The outputs saved for steps of ``step_type``, read on the workflow ``workflow_id``: your account's own
        first, newest first, then those made public or shared with it.

        Returns:
            Each saved output, whole.

        Usage::

            for saved in noclick.SavedOutput.list(workflow_id, "automation-shopify"):
                print(saved.name)
        """
        raw = await resolve_client(client).request("GET", cls._base(workflow_id), params={"step_type": step_type},
                                                   user=None)
        return [cls._from(workflow_id, row) for row in (raw or {}).get("data") or []]

    @synced
    @classmethod
    async def create(cls, workflow_id: str, *, step_type: str, name: str, output: Dict[str, Any],
                     visibility: Optional[str] = None, client: Optional[Client] = None) -> "SavedOutput":
        """Save an output of a step of the workflow ``workflow_id`` under a name (``visibility`` ``user``, the
        default, or ``public``). Raises ``noclick.PlanRequired`` once the step type keeps as many as your plan
        allows.

        Returns:
            The saved output.

        Usage::

            noclick.SavedOutput.create(workflow_id, step_type="automation-shopify", name="A paid order", output=out)
        """
        body = {"step_type": step_type, "name": name, "output": output}
        if visibility is not None:
            body["visibility"] = visibility
        return cls._from(workflow_id, await resolve_client(client).request(
            "POST", cls._base(workflow_id), json=body, user=None))

    @synced
    async def update(self, *, name: Optional[str] = None, visibility: Optional[str] = None,
                     client: Optional[Client] = None) -> "SavedOutput":
        """Rename it, or make it ``public`` or your account's own (``user``) again.

        Returns:
            It, as it stands after the change.

        Usage::

            saved.update(visibility="public")
        """
        body = {k: v for k, v in (("name", name), ("visibility", visibility)) if v is not None}
        return type(self)._from(self.workflow_id, await resolve_client(client).request(
            "PATCH", f"{self._base(self.workflow_id)}/{quote(self.id, safe='')}", json=body, user=None))

    @synced
    async def delete(self, *, client: Optional[Client] = None) -> None:
        """Delete it, with its shares.

        Usage::

            saved.delete()
        """
        await resolve_client(client).request(
            "DELETE", f"{self._base(self.workflow_id)}/{quote(self.id, safe='')}", user=None)
