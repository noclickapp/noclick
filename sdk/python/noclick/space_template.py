"""Adding a space template: its channels, agents (with their instructions, skills and memories), automations, data
stores and app, made in your account as a new space (``Workspace.from_template``) or beside what a space of yours
already holds (``workspace.add_template``). All of it is made, or none of it.

    plan = Workspace.from_template("https://api.noclick.com/v1/public/git/pub_123.git", dry_run=True)
    print(plan.summary, plan.estimate["monthly_usd"], [a.label for a in plan.connections if not a.connected])
    added = Workspace.from_template("https://api.noclick.com/v1/public/git/pub_123.git").wait()
    print(added.workspace_id, added.channel_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ._object import compact, field
from .operation import Operation, register_result


@dataclass(frozen=True)
class TemplatePart:
    """One part of a template: ``kind`` (agent, channel, skill, memory, automation, store, app), its ``name`` in the
    template, the name it'll have (``named``: a space you have carries the template's word), a line on it, the
    integrations it needs, and whether it comes (``included``)."""

    kind: str
    name: str
    named: str
    line: Optional[str]
    needs: List[str]
    #: A channel's agents, by the names they'll have.
    members: List[str]
    #: A channel's schedules' messages.
    schedules: List[str]
    included: bool
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class TemplateAccount:
    """An account a template's parts use: its ``integration`` and ``label``, who uses it, and the connection of yours
    it'll use (``connected``: ``{ref, name, id}``), or None while it waits for you to connect one."""

    integration: str
    label: str
    node_type: Optional[str]
    used_by: List[str]
    connected: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class TemplatePlan:
    """What adding a template would make and ask, with nothing made (a dry run): where it goes, each part under the
    name it'll have, the month's ``estimate`` (its app and data stores; its agents said as the cap they stop at), the
    ``cap`` shared out as its agents' budgets, each account (one you have is used, never asked again), each secret it
    asks for, its app's deploy, whether your account can pay (``funds``), and why it can't be added (``refused``)."""

    template: Dict[str, Any]
    target: Dict[str, Any]
    parts: List[TemplatePart]
    short: List[str]
    connections: List[TemplateAccount]
    secrets: List[Dict[str, Any]]
    cap: Dict[str, Any]
    app: Optional[Dict[str, Any]]
    estimate: Dict[str, Any]
    funds: Dict[str, Any]
    refused: Optional[Dict[str, Any]]
    summary: str
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "TemplatePlan":
        parts = [TemplatePart(p["kind"], p["name"], p.get("as") or p["name"], p.get("line"), list(p.get("needs") or []),
                              [str(m) for m in p.get("members") or []],
                              [s for s in p.get("schedules") or [] if isinstance(s, str)],
                              bool(p.get("included")), p) for p in raw.get("parts") or []]
        accounts = [TemplateAccount(c["integration"], c.get("label") or c["integration"], c.get("node_type"),
                                    list(c.get("for") or []), c.get("connected"), c)
                    for c in raw.get("connections") or []]
        return cls(dict(raw.get("template") or {}), dict(raw.get("target") or {}), parts, list(raw.get("short") or []),
                   accounts, list(raw.get("secrets") or []), dict(raw.get("cap") or {}), raw.get("app"),
                   dict(raw.get("estimate") or {}), dict(raw.get("funds") or {}), raw.get("refused"),
                   raw.get("summary") or "", raw)


@dataclass(frozen=True)
class TemplateAdded:
    """A template that arrived: its space, the ``#noclick`` channel its welcome post is in, and every part made, by
    kind (each ``{id, name}``), its app (``{project_id, name, url, to_reveal}``), and the accounts still waiting for
    you (``waiting``)."""

    workspace_id: str
    workspace_name: str
    channel_id: Optional[str]
    message_id: Optional[str]
    agents: List[Dict[str, Any]]
    channels: List[Dict[str, Any]]
    app: Optional[Dict[str, Any]]
    waiting: List[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "TemplateAdded":
        space, home = raw.get("workspace") or {}, raw.get("channel") or {}
        return cls(space.get("id"), space.get("name") or "", home.get("id"), raw.get("message_id"),
                   list(raw.get("agents") or []), list(raw.get("channels") or []), raw.get("app"),
                   list(raw.get("waiting") or []), raw)


def _read_added(result: Any, op: Operation) -> TemplateAdded:
    return TemplateAdded._from(result)


register_result("workspace.template_add", _read_added)


class TemplateAdd(Operation):
    """A template being added: ``wait()`` gives a ``TemplateAdded`` once all of it is made; ``progress`` shows each
    stage (copying its code, deploying its app, making its parts, saying what arrived). One that fails makes
    nothing: what it had made goes with it."""

    workspace_id: Optional[str] = field("workspace_id", doc="The space it's added to, once it's there.")
    channel_id: Optional[str] = field("channel_id", doc="The space's #noclick, its welcome post's channel.")


def template_source(source: Any) -> Dict[str, Any]:
    """A template's address (a URL), or one of your repos holding a space.json (a ``Repo``, its id or its name)."""
    repo_id = getattr(source, "id", None) if not isinstance(source, str) else None
    if repo_id is not None:
        return {"repo": repo_id}
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is a template's address, or one of your repos (a Repo, its id or its name)")
    source = source.strip()
    return {"url": source} if "://" in source or "/" in source else {"repo": source}


def template_body(source: Any, *, leave_out: Optional[Sequence[Mapping[str, Any]]] = None,
                  cap_usd_per_month: Optional[float] = None, connections: Optional[Mapping[str, str]] = None,
                  secrets: Optional[Mapping[str, Mapping[str, str]]] = None,
                  app_secrets: Optional[Mapping[str, str]] = None, dry_run: bool = False,
                  **more: Any) -> Dict[str, Any]:
    return compact(source=template_source(source), leave_out=[dict(p) for p in leave_out] if leave_out else None,
                   cap_usd_per_month=cap_usd_per_month, connections=dict(connections) if connections else None,
                   secrets={k: dict(v) for k, v in secrets.items()} if secrets else None,
                   app_secrets=dict(app_secrets) if app_secrets else None, dry_run=True if dry_run else None, **more)


def template_answer(raw: Dict[str, Any], *, client: Any, user: Any) -> Any:
    """A dry run's ``TemplatePlan``, else the ``TemplateAdd`` doing it."""
    if raw.get("object") == "space_template_plan":
        return TemplatePlan._from(raw)
    return TemplateAdd._from_payload(raw.get("operation"), client=client, user=user, kind="workspace.template_add",
                                     reader=_read_added)
