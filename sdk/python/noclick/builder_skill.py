"""BuilderSkill: the skills NoClick's workflow builder loads before it builds, apart from the Agent Skills an agent
attaches (``noclick.Skill``)."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import parse_time
from ._sync import synced

if TYPE_CHECKING:
    from .workflow import ExpressionPreview


def _fields(**given: Any) -> Dict[str, Any]:
    return {name: value for name, value in given.items() if value is not None}


@dataclass(frozen=True)
class BuilderSkill:
    """A skill NoClick's builder loads: a description the builder reads to decide whether it needs it, plus text and,
    optionally, a workflow to follow. ``scope`` says whose: ``owned`` (your account's, or a workspace it's in) or
    ``shared`` (shared with it to read). It loads while it's ``enabled`` and not ``muted`` for your account. They're
    what Settings → Skills in the NoClick app shows. Any of your account's own keys reads and changes them; one held to
    one of your users raises ``noclick.PermissionDenied``."""

    id: str
    name: str
    description: str
    scope: str
    owner_id: Optional[str]
    enabled: bool
    muted: bool
    has_text: bool
    has_workflow: bool
    body_text: Optional[str]
    body_workflow: Optional[Dict[str, Any]]
    workflow_version: Optional[int]
    display_metadata: Optional[Dict[str, Any]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "BuilderSkill":
        raw = raw if isinstance(raw, dict) else {}
        workflow = raw.get("body_workflow")
        version = raw.get("workflow_version")
        shown = raw.get("display_metadata")
        return cls(str(raw.get("id")), str(raw.get("name") or ""), str(raw.get("description") or ""),
                   "shared" if raw.get("scope") == "shared" else "owned", raw.get("owner_id"),
                   raw.get("enabled") is True, raw.get("muted") is True, raw.get("has_text") is True,
                   raw.get("has_workflow") is True, raw.get("body_text"),
                   workflow if isinstance(workflow, dict) else None,
                   version if isinstance(version, int) else None, shown if isinstance(shown, dict) else None,
                   parse_time(raw.get("created_at")), parse_time(raw.get("updated_at")), raw)

    @synced
    @classmethod
    async def list(cls, *, client: Optional[Client] = None) -> List["BuilderSkill"]:
        """Your account's builder skills (``owned``), newest first, then those shared with it (``shared``).

        Returns:
            Each skill, without its text and workflow (``get`` reads one whole).

        Usage::

            for skill in noclick.BuilderSkill.list():
                print(skill.name, skill.enabled and not skill.muted)
        """
        raw = await resolve_client(client).request("GET", "/v1/builder_skills", user=None)
        return [cls._from(row) for row in (raw or {}).get("data") or []]

    @synced
    @classmethod
    async def create(cls, name: str, *, description: Optional[str] = None, body_text: Optional[str] = None,
                     body_workflow: Optional[Dict[str, Any]] = None, enabled: Optional[bool] = None,
                     client: Optional[Client] = None) -> "BuilderSkill":
        """Make a builder skill in your account's active workspace: ``description`` is when the builder should use it,
        ``body_text`` what it tells the builder, ``body_workflow`` a workflow it may follow.

        Returns:
            The skill, whole.

        Usage::

            noclick.BuilderSkill.create("Brand voice", description="How we write.", body_text="Short sentences.")
        """
        body = _fields(name=name, description=description, body_text=body_text, body_workflow=body_workflow,
                       enabled=enabled)
        return cls._from(await resolve_client(client).request("POST", "/v1/builder_skills", json=body, user=None))

    @synced
    @classmethod
    async def get(cls, skill_id: str, *, client: Optional[Client] = None) -> "BuilderSkill":
        """One builder skill, with its text and workflow.

        Returns:
            The skill, whole.

        Usage::

            skill = noclick.BuilderSkill.get(skill_id)
            print(skill.body_text)
        """
        return cls._from(await resolve_client(client).request(
            "GET", f"/v1/builder_skills/{quote(skill_id, safe='')}", user=None))

    @synced
    async def update(self, *, name: Optional[str] = None, description: Optional[str] = None,
                     body_text: Optional[str] = None, body_workflow: Optional[Dict[str, Any]] = None,
                     enabled: Optional[bool] = None, muted: Optional[bool] = None,
                     client: Optional[Client] = None) -> "BuilderSkill":
        """Change it: what it says or whether it's enabled (its owner, or a share that may edit it; others raise
        ``noclick.PermissionDenied``), and whether it's ``muted`` for your account (anyone it reaches). Arguments left
        out stay as they are.

        Returns:
            It, as it stands after the change.

        Usage::

            skill.update(muted=True)
        """
        body = _fields(name=name, description=description, body_text=body_text, body_workflow=body_workflow,
                       enabled=enabled, muted=muted)
        return type(self)._from(await resolve_client(client).request(
            "PATCH", f"/v1/builder_skills/{quote(self.id, safe='')}", json=body, user=None))

    @synced
    @classmethod
    async def save_workflow(cls, skill_id: str, workflow: Dict[str, Any], *, if_version: Optional[int] = None,
                            display_metadata: Optional[Dict[str, Any]] = None,
                            deleted_steps: Optional[List[str]] = None, partial_steps: Optional[List[str]] = None,
                            changes: Optional[Dict[str, List[str]]] = None,
                            client: Optional[Client] = None) -> Dict[str, Any]:
        """Save a skill's workflow whole, as NoClick's canvas does (its owner, or a share that may edit it), on the
        version it was read at (``if_version``, its ``workflow_version``): a save on one the workflow has moved past
        raises ``noclick.Conflict``, whose ``details`` hold the ``workflow`` and ``version`` as they stand.
        ``deleted_steps``: steps removed since; ``partial_steps``: steps held only in part, kept as stored;
        ``changes`` (``steps``, ``edges_added``, ``edges_removed``): on a workflow that moved past ``if_version``,
        only these land. A save of the workflow as stored changes nothing.

        Returns:
            ``{"version", "changed"}``: the version it's at after, and whether the save changed it.

        Usage::

            skill = noclick.BuilderSkill.get(skill_id)
            noclick.BuilderSkill.save_workflow(skill.id, {"nodes": nodes, "edges": edges},
                                               if_version=skill.workflow_version)
        """
        body = _fields(workflow=workflow, if_version=if_version, display_metadata=display_metadata,
                       deleted_steps=deleted_steps or None, partial_steps=partial_steps or None, changes=changes)
        raw = await resolve_client(client).request(
            "PUT", f"/v1/builder_skills/{quote(skill_id, safe='')}/workflow", json=body, user=None)
        return {"version": int(raw["version"]), "changed": raw.get("changed") is True}

    @synced
    @classmethod
    async def preview_expression(cls, skill_id: str, expression: str, *, samples: Optional[Dict[str, Any]] = None,
                                 primary_input: Any = None, client: Optional[Client] = None) -> "ExpressionPreview":
        """What an expression in a setting of the skill's workflow gives, evaluated as a run evaluates it, against
        ``samples`` (each step's output by step id, ``vars`` the variables; a skill's workflow never runs), with
        ``primary_input`` as ``$json``. Changes nothing.

        Returns:
            The ``ExpressionPreview``; an expression that fails has ``ok`` False and its ``error``.

        Usage::

            noclick.BuilderSkill.preview_expression(skill_id, "$('Fetch').total", samples={"fetch": {"total": 2}})
        """
        from .workflow import ExpressionPreview

        raw = await resolve_client(client).request(
            "POST", f"/v1/builder_skills/{quote(skill_id, safe='')}/expression",
            json=_fields(expression=expression, samples=samples, primary_input=primary_input), user=None)
        return ExpressionPreview._from(raw)

    @synced
    async def delete(self, *, client: Optional[Client] = None) -> None:
        """Delete it for good: only the account that made it may.

        Usage::

            skill.delete()
        """
        await resolve_client(client).request("DELETE", f"/v1/builder_skills/{quote(self.id, safe='')}", user=None)
