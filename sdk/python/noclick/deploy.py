"""Deploy a repository as a new app in one call: a public one on any git host, or one of your own repos.

``noclick.deploy`` copies the repository (or takes your repo as it is), makes the app, sets the secrets it reads,
gives it the key to your account it asks for (or has the deploy ask the account's owner), and deploys production.
Ask with ``dry_run=True`` first to see what it would do, what it would cost a month and what it asks of you, with
nothing made.

    plan = noclick.deploy("https://github.com/acme/console", dry_run=True)
    print(plan.runtime, f"${plan.estimate.monthly_usd:.2f} a month", plan.missing_secrets)

    app = noclick.deploy("https://github.com/acme/console", secrets={"STRIPE_SECRET_KEY": "sk_live_..."}).wait()
    print(app.url)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Union, overload

from ._client import Client, resolve_client
from ._object import compact, field
from ._scope import AMBIENT, resolve_scope
from ._sync import synced
from .estimate import Estimate
from .operation import Operation, register_result


@dataclass(frozen=True)
class DeploySecret:
    """A secret the repository's noclick.json says its code reads."""

    name: str
    #: What NoClick makes for it (``secret`` or ``password``); None for one you set.
    generate: Optional[str]
    #: What it is, in the repository's words.
    description: Optional[str]
    #: For one you set: whether a deploy without it is refused. One NoClick makes is always there.
    required: bool
    #: For one you set: whether the call brought its value.
    given: bool
    #: For one NoClick makes: whether it's a password you read once (``app.secrets.reveal``).
    shown_once: bool


@dataclass(frozen=True)
class DeployKeyAsk:
    """The key to your account the repository asks for, as you're shown it before you agree."""

    scopes: List[str]
    #: What the key can do, a line per scope (``scope``, ``can``, ``reads_secrets``).
    can: List[Dict[str, Any]]
    #: What no app's key can do, whatever it holds.
    cannot: List[str]
    #: That whoever can change the app's code acts with the key.
    note: str
    #: ``you``: you give it in the call (send ``account_key`` with these scopes); ``deploy``: the deploy asks for it.
    given_by: str
    #: When the deploy asks: ``asks_owner`` (the account's owner approves it from a link), ``given`` or ``denied``,
    #: as the account's ``app_key`` approval setting decides.
    at_deploy: Optional[str]

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["DeployKeyAsk"]:
        if not raw:
            return None
        return cls(list(raw["scopes"]), list(raw.get("can") or []), list(raw.get("cannot") or []),
                   raw.get("note") or "", raw["given_by"], raw.get("at_deploy"))


def _secrets(raw: Mapping[str, Any]) -> List[DeploySecret]:
    made = [DeploySecret(s["name"], s.get("kind"), s.get("description"), True, False, bool(s.get("shown_once")))
            for s in raw.get("generated") or []]
    asked = [DeploySecret(s["name"], None, s.get("description"), bool(s.get("required")), bool(s.get("given")),
                          False) for s in raw.get("asked") or []]
    return made + asked


@dataclass(frozen=True)
class DeployPlan:
    """What a deploy would do, with nothing made: ``noclick.deploy(..., dry_run=True)``."""

    #: What it read: ``kind`` (``url`` or ``repo``), the ``url`` or ``repo_id``, and the ``commit`` and ``branch``;
    #: ``forked_from`` (``{"address": ...}``) names public work on NoClick the deploy copies.
    source: Dict[str, Any]
    #: The app's name (and its copy's): the one you gave, or the first free one from the repository's.
    name: str
    #: Where the app would run (``edge`` or ``container``), and why; None when it won't run as it stands.
    runtime: Optional[str]
    framework: Optional[str]
    reason: Optional[str]
    #: Whether the repository has a noclick.json.
    noclick_json: bool
    account_key: Optional[DeployKeyAsk]
    secrets: List[DeploySecret]
    #: The secrets you set that the call would have to bring: a deploy without them is refused.
    missing_secrets: List[str]
    #: Why it won't deploy as it stands (``message``, ``next_step``); None when it will.
    refused: Optional[Dict[str, str]]
    #: What it would cost a month, priced for your account (usage-based: what's charged is what's used).
    estimate: Estimate
    #: Whether your account can pay to run it now (``ok``); if not, the ``refusal`` a deploy would meet.
    funds: Dict[str, Any]
    #: What it makes: ``repo`` (a copy) and ``project`` (the app).
    makes: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "DeployPlan":
        return cls(dict(raw["source"]), raw["name"], raw.get("runtime"), raw.get("framework"), raw.get("reason"),
                   bool(raw.get("noclick_json")), DeployKeyAsk._from(raw.get("account_key")),
                   _secrets(raw.get("secrets") or {}), list(raw.get("missing_secrets") or []), raw.get("refused"),
                   Estimate._from(raw["estimate"]), dict(raw.get("funds") or {}), list(raw.get("makes") or []), raw)


@dataclass(frozen=True)
class DeployResult:
    """A deploy that ended live: what ``RepoDeploy.wait()`` gives."""

    project_id: str
    name: str
    #: Where production serves it.
    url: Optional[str]
    repo_id: Optional[str]
    deployment_id: Optional[str]
    commit: Optional[str]
    #: Where its key to the account stands (``status``: ``granted``, ``waiting`` for the owner, ``declined``...),
    #: None when the repository asks for none.
    account_key: Optional[Dict[str, Any]]
    #: The passwords NoClick made that nobody has read yet: read each once with ``app.secrets.reveal(name)``.
    to_reveal: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "DeployResult":
        waiting = ((raw.get("secrets") or {}).get("to_reveal")) or []
        return cls(raw["project_id"], raw["name"], raw.get("url"), raw.get("repo_id"), raw.get("deployment_id"),
                   raw.get("commit"), raw.get("account_key"), [w["name"] for w in waiting], raw)


def _read_deploy(result: Any, op: Operation) -> DeployResult:
    return DeployResult._from(result)


register_result("repo.deploy", _read_deploy)


class RepoDeploy(Operation):
    """A repository being deployed as a new app: the operation ``noclick.deploy`` returns. ``wait()`` gives a
    ``DeployResult`` once it's live; ``progress`` shows each stage (copying, making the app, setting its secrets and
    key, building and deploying). A deploy that fails after the copy keeps the app and its repo, and its error says
    how to go on."""

    project_id: Optional[str] = field("project_id", doc="The new app's id, once it's made.")
    repo_id: Optional[str] = field("repo_id", doc="The repo it deploys: the copy, or yours.")
    deployment_id: Optional[str] = field("deployment_id", doc="The production deployment, once it's started.")


def _source(source: Any, ref: Optional[str]) -> Dict[str, Any]:
    """A URL, or one of your repos (a ``Repo``, its id or its name)."""
    repo_id = getattr(source, "id", None) if not isinstance(source, str) else None
    if repo_id is not None:
        return compact(repo=repo_id, ref=ref)
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is a repository's URL, or one of your repos (a Repo, its id or its name)")
    is_url = "://" in source or "@" in source
    return compact(url=source.strip(), ref=ref) if is_url else compact(repo=source.strip(), ref=ref)


@overload
async def deploy(source: Any, *, dry_run: Literal[True], ref: Optional[str] = None, name: Optional[str] = None,
                 secrets: Optional[Mapping[str, str]] = None, account_key: Optional[Sequence[str]] = None,
                 key_spend_cap_usd_per_month: Optional[float] = None, user: Any = AMBIENT,
                 client: Optional[Client] = None) -> DeployPlan: ...


@overload
async def deploy(source: Any, *, dry_run: Literal[False] = False, ref: Optional[str] = None,
                 name: Optional[str] = None, secrets: Optional[Mapping[str, str]] = None,
                 account_key: Optional[Sequence[str]] = None, key_spend_cap_usd_per_month: Optional[float] = None,
                 user: Any = AMBIENT, client: Optional[Client] = None) -> RepoDeploy: ...


@synced
async def deploy(source: Any, *, dry_run: bool = False, ref: Optional[str] = None, name: Optional[str] = None,
                 secrets: Optional[Mapping[str, str]] = None, account_key: Optional[Sequence[str]] = None,
                 key_spend_cap_usd_per_month: Optional[float] = None, user: Any = AMBIENT,
                 client: Optional[Client] = None) -> Union[DeployPlan, RepoDeploy]:
    """Deploy ``source`` as a new app of yours: a public git repository's https URL, on any host (copied into a new
    repo of yours, the one branch it deploys), public work on NoClick by its https address
    (``"https://pilot-hub.noclick.site"``: a copy of the code its owner made public), or one of your own repos (a
    ``Repo``, its id or its name, deployed as it is). ``ref`` names a branch, tag or full commit sha (the default
    branch otherwise).

    It makes the app (``name``, or the repository's own name, or the first of name-2, name-3... free), sets the
    secrets its noclick.json says its code reads (NoClick makes the ones marked ``generate``; ``secrets`` brings
    the rest, by name), gives the app the key to your account it asks for when ``account_key`` names exactly its
    scopes (only you signed in, or a key holding ``keys:create``; otherwise the deploy asks the account's owner, as
    every deploy does), and deploys production.

    Never a private repository, a URL with a login, an ``ssh://`` or ``git@`` address, or another account's repo:
    push a private one to a repo of yours with git and deploy that. What can't deploy is refused before anything is
    made. Needs the ``apps`` and ``repos`` scopes.

    Returns:
        A ``RepoDeploy`` operation whose ``wait()`` gives a ``DeployResult`` (the app's ``url``, where its key
        stands, the passwords to read once); with ``dry_run=True``, a ``DeployPlan`` of what it would do, what it
        would cost a month and what it asks of you, with nothing made.

    Usage:
        See what it would do first::

            plan = noclick.deploy("https://github.com/acme/console", dry_run=True)
            print(plan.runtime, f"${plan.estimate.monthly_usd:.2f} a month")
            if plan.account_key:
                for line in plan.account_key.can:
                    print("its key can", line["can"])
            print("you set:", plan.missing_secrets)

        Then deploy it, bringing the secrets you set, and read the password NoClick made once::

            done = noclick.deploy("https://github.com/acme/console",
                                  secrets={"STRIPE_SECRET_KEY": "sk_live_..."}).wait()
            print(done.url)
            app = noclick.Project.from_id(done.project_id)
            for name in done.to_reveal:
                print(name, app.secrets.reveal(name))

        One of your own repos, as it is::

            done = noclick.deploy("console", name="console-live").wait()
    """
    scope = resolve_scope(user)
    body: Dict[str, Any] = compact(source=_source(source, ref), name=name, secrets=dict(secrets) if secrets else None)
    if account_key is not None:
        body["account_key"] = compact(scopes=list(account_key), spend_cap_usd_per_month=key_spend_cap_usd_per_month)
    if dry_run:
        body["dry_run"] = True
    raw = await resolve_client(client).request("POST", "/v1/deploys", json=body, user=scope)
    if dry_run:
        return DeployPlan._from(raw)
    return RepoDeploy._from_payload(raw.get("operation"), client=client, user=scope, kind="repo.deploy",
                                    reader=_read_deploy)

