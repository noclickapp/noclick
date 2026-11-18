"""Policy: which tools may run, which need a person's approval.

    noclick.Policy.set(deny=["*.delete_*"], require_approval=["gmail.send_email_message"])
    noclick.Policy.set(allow=["search", "gmail.*"], user="user_42")   # narrows the account policy

Patterns match dotted tool names (``gmail.*``, ``*.delete_*``, ``search``).
Deny wins; an empty ``allow`` allows everything the other rules don't stop.
Like every call, ``get``, ``set`` and ``evaluate`` follow ``as_user``: inside it they
address that user's policy, and ``user=None`` addresses the account's. A rule can
also be a ``noclick.Rule`` with a condition on the call's arguments and a person
who approves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Sequence, Union

from ._client import Client, resolve_client
from ._object import compact, paginate
from ._scope import AMBIENT, resolve_scope, user_ref
from ._sync import synced
from .human import Human

_LISTS = ("allow", "deny", "require_approval")


@dataclass(frozen=True)
class Rule:
    """A policy rule that says more than a pattern: ``tool`` is the pattern
    (``"stripe.create_refund"``, ``"gmail.*"``), ``when`` a CEL expression the call
    must satisfy for the rule to apply, over ``args`` (the call's final arguments,
    bound ones included) and ``user`` (the user it's made for: ``id``, ``email``,
    ``name``, ``metadata``), and ``approver`` who approves it in
    ``require_approval``: a ``Human`` (``user.human``, ``noclick.Human(email=...)``,
    or ``noclick.Human()`` for the user the call is made for) or an email; it's emailed
    the approval, and only it may answer. Without an ``approver`` the owner of what the
    call acts in approves, as for a pattern. A rule goes in any of the three lists; a
    dict with the same keys works too.

    ``message``, on a ``deny`` rule, is what the call's refusal says in your words, so the
    agent can tell the user what to do: "Web search comes with Pro:
    https://acme.com/upgrade". It may use ``{{user.id}}`` and the other ``user`` fields, as
    ``pause_spending`` does, filled in for whom the call is for; a field they lack leaves the
    refusal its usual words.

    A call ``when`` can't judge (an argument it lacks, values that don't compare) meets
    a ``deny`` or ``require_approval`` rule and misses an ``allow`` one, so a condition
    never opens what it was written to close; ``has(args.amount) && ...`` is precise.
    Numbers compare within their own type: write ``double(args.amount) > 99.5`` for an
    amount that may have a fraction.

    Usage:
        Refunds over $100 wait for finance; smaller ones run::

            noclick.Policy.add(
                noclick.Rule("stripe.create_refund", when="args.amount > 10000", approver="finance@acme.com"),
                to="require_approval",
            )

        A plan feature, refused with what to do about it::

            noclick.Policy.add(
                noclick.Rule("search", when='user.metadata.plan == "free"',
                             message="Web search comes with Pro: https://acme.com/upgrade?user={{user.id}}"),
                to="deny",
            )

        Never email a competitor, and let pro users' agents book without asking::

            noclick.Policy.set(
                deny=[noclick.Rule("gmail.send_email_message", when='args.to.exists(t, t.endsWith("@rival.com"))')],
                require_approval=[noclick.Rule("calendar.*", when='user.metadata.plan != "pro"')],
            )
    """

    tool: str
    when: Optional[str] = None
    approver: Any = None
    #: What a ``deny`` rule's refusal says, for the user.
    message: Optional[str] = None

    @classmethod
    def _parse(cls, entry: Any) -> Union[str, "Rule"]:
        """A list entry as your code gives it: a pattern, a ``Rule``, or a dict with its keys."""
        if isinstance(entry, (str, Rule)):
            return entry
        if isinstance(entry, dict):
            unknown = set(entry) - {"tool", "when", "approver", "message"}
            if unknown or "tool" not in entry:
                raise TypeError(
                    f"A rule dict has 'tool' and may have 'when', 'approver' and 'message', not {sorted(unknown) or entry}"
                )
            return cls(**entry)
        raise TypeError(f"A policy rule is a pattern, a noclick.Rule or a dict, not {entry!r}")

    @classmethod
    def _read(cls, raw: Any) -> Union[str, "Rule"]:
        """A list entry as the API returns it."""
        if not isinstance(raw, dict):
            return str(raw)
        approver = raw.get("approver") or {}
        who: Any = approver.get("email")
        if approver.get("user_id"):
            who = Human(user=approver["user_id"])
        elif approver.get("user"):
            who = Human()
        return cls(raw["tool"], raw.get("when"), who, raw.get("message"))

    async def _wire(self, list_name: str) -> Union[str, Dict[str, Any]]:
        if self.approver is not None and list_name != "require_approval":
            raise ValueError(f"Only a require_approval rule has an approver, not one in {list_name}")
        if self.message is not None and list_name != "deny":
            raise ValueError(f"Only a deny rule has a message, not one in {list_name}")
        if self.when is None and self.approver is None and self.message is None:
            return self.tool
        approver = None
        if isinstance(self.approver, str):
            approver = {"email": self.approver}
        elif isinstance(self.approver, Human):
            approver = await self.approver._address()
            if "phone" in approver and "email" not in approver:
                raise ValueError("An approver answers by email or on the approval page; give the Human an email")
            approver.pop("phone", None)
        elif self.approver is not None:
            raise TypeError(f"An approver is a noclick.Human or an email, not {self.approver!r}")
        return compact(tool=self.tool, when=self.when, approver=approver, message=self.message)


@dataclass(frozen=True)
class PolicyVerdict:
    """What a policy decides for one tool (``allow``, ``deny`` or ``approval``),
    and which rule (``matched_pattern`` in ``layer`` ``account``/``user``) decided it."""

    tool: str
    verdict: str
    matched_pattern: Optional[str]
    layer: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @property
    def rule(self) -> Union[None, str, Rule]:
        """The rule that decided, whole: a pattern, or a ``Rule`` with its condition and approver
        (None when nothing matched)."""
        rule = self.raw.get("rule")
        return None if rule is None else Rule._read(rule)


def _patterns(name: str, patterns: Sequence[Any]) -> List[Union[str, Rule]]:
    if isinstance(patterns, (str, Rule, dict)):
        raise TypeError(f"{name} takes a list of patterns and rules, not the one rule {patterns!r}")
    return [Rule._parse(entry) for entry in patterns]


async def _wire_rules(list_name: str, rules: Sequence[Union[str, Rule]]) -> List[Any]:
    return [entry if isinstance(entry, str) else await entry._wire(list_name) for entry in rules]


@dataclass(frozen=True)
class Policy:
    """The account's policy, or one user's (``user_id``). Each list holds patterns,
    and ``Rule``s where a rule has a condition or an approver."""

    allow: List[Union[str, Rule]]
    deny: List[Union[str, Rule]]
    require_approval: List[Union[str, Rule]]
    user_id: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any, user_id: Optional[str]) -> "Policy":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            allow=[Rule._read(entry) for entry in raw.get("allow") or []],
            deny=[Rule._read(entry) for entry in raw.get("deny") or []],
            require_approval=[Rule._read(entry) for entry in raw.get("require_approval") or []],
            user_id=raw.get("user_id", user_id),
            raw=raw,
        )

    @synced
    @classmethod
    async def list(cls, *, client: Optional[Client] = None) -> List["Policy"]:
        """List the account's policy and every user policy.

        Returns:
            The account's policy first (its ``user_id`` is ``None``), then each user that has a policy of
            its own, with your id for that user as its ``user_id``.

        Usage::

            for policy in noclick.Policy.list():
                print(policy.user_id or "account", policy.deny, policy.require_approval)
        """
        rows = await paginate(resolve_client(client), "/v1/policies", user=None)
        return [cls._from(row, None) for row in rows]

    @synced
    @classmethod
    async def evaluate(
        cls,
        tools: Union[str, Sequence[str]],
        *,
        arguments: Optional[Dict[str, Any]] = None,
        user: Any = AMBIENT,
        draft: Optional[Dict[str, Any]] = None,
        client: Optional[Client] = None,
    ) -> List[PolicyVerdict]:
        """Judge each of ``tools`` (dotted or wire names, at most
        500) against the policy for the account, or ``user=`` (inside ``as_user``, that user;
        ``user=None`` for the account). A ``draft``
        (``{"layer": "account"|"user", "allow", "deny", "require_approval"}``)
        is judged in place of its layer's saved rules. Nothing runs and no
        approval is requested. ``arguments`` judges one tool's call with those
        arguments, so rules with a ``when`` apply; without them a rule with a
        ``when`` never matches.

        Returns:
            One verdict per tool, in order: ``allow``, ``deny`` or ``approval``, with the ``matched_pattern``
            and ``layer`` that decided it, and the whole ``rule``. ``matched_pattern`` is ``None`` when no rule
            matched, or when an ``allow`` list left the tool out.

        Usage:
            See how a user's calls would be judged::

                for verdict in noclick.Policy.evaluate(["gmail.send_email_message", "search"], user="user_42"):
                    print(verdict.tool, verdict.verdict, verdict.matched_pattern)

            Try rules before you save them::

                verdicts = noclick.Policy.evaluate(
                    ["gmail.send_email_message", "gmail.fetch_emails_from_inbox"],
                    draft={"layer": "account", "deny": ["gmail.*"]},
                )

            See which rule a particular call meets::

                [verdict] = noclick.Policy.evaluate("stripe.create_refund", arguments={"amount": 25000}, user="user_42")
                print(verdict.verdict, verdict.rule)   # approval Rule(tool='stripe.create_refund', when='args.amount > 10000', ...)
        """
        user_id = await user_ref(resolve_scope(user))
        names = [tools] if isinstance(tools, str) else list(tools)
        if arguments is not None and len(names) != 1:
            raise ValueError("arguments= judges one call: pass one tool with it")
        wire_draft = None
        if draft is not None:
            wire_draft = {"layer": draft["layer"]}
            for name in _LISTS:
                wire_draft[name] = await _wire_rules(name, _patterns(f"draft[{name!r}]", draft.get(name) or ()))
        body = compact(tools=names, arguments=arguments, user_id=user_id, draft=wire_draft)
        raw = await resolve_client(client).request("POST", "/v1/policy/evaluate", json=body, user=None) or {}
        return [
            PolicyVerdict(row.get("tool"), row.get("verdict"), row.get("matched_pattern"), row.get("layer"), row)
            for row in raw.get("results") or []
        ]

    @synced
    @classmethod
    async def get(cls, user: Any = AMBIENT, *, client: Optional[Client] = None) -> "Policy":
        """Read the account policy, or with ``user=`` (a ``User`` or your id for
        one, and inside ``as_user`` that user) that user's own rules; ``user=None``
        reads the account's.

        Returns:
            The ``allow``, ``deny`` and ``require_approval`` lists, empty where nothing is set. A user's
            policy holds only its own rules, not the account's.

        Usage::

            policy = noclick.Policy.get()
            print(policy.allow, policy.deny, policy.require_approval)

            ana = noclick.Policy.get(user="user_42")
        """
        api = resolve_client(client)
        user_id = await user_ref(resolve_scope(user))
        raw = await api.request("GET", "/v1/policy", params={"user_id": user_id}, user=None)
        return cls._from(raw, user_id)

    @synced
    @classmethod
    async def set(
        cls,
        *,
        allow: Sequence[Any] = (),
        deny: Sequence[Any] = (),
        require_approval: Sequence[Any] = (),
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Policy":
        """Replace the account policy (or ``user=``'s, and inside ``as_user`` that user's;
        ``user=None`` is the account's) with these rules: patterns, and ``noclick.Rule``s
        (or dicts) with a condition or an approver.

        Returns:
            The saved policy, its patterns lowercased and deduplicated. A list you left out is now empty.

        Usage:
            Pass every rule you want to keep, since the call replaces the whole policy::

                noclick.Policy.set(deny=["*.delete_*"], require_approval=["gmail.send_email_message", "stripe.*"])

            A user's policy narrows the account's::

                noclick.Policy.set(allow=["search", "gmail.*"], user="user_42")
        """
        body: Dict[str, Any] = {}
        for name, rules in (("allow", allow), ("deny", deny), ("require_approval", require_approval)):
            body[name] = await _wire_rules(name, _patterns(f"Policy.set({name}=...)", rules))
        user_id = await user_ref(resolve_scope(user))
        if user_id is not None:
            body["user_id"] = user_id
        raw = await resolve_client(client).request("PUT", "/v1/policy", json=body, user=None)
        return cls._from(raw, user_id)

    @synced
    @classmethod
    async def add(
        cls, *rules: Any, to: str = "require_approval", user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Policy":
        """Add rules to one list of the account's policy (or ``user=``'s; inside ``as_user``
        that user's), leaving every other rule as it is, in one change on the server. A rule
        for a tool that list already has replaces it, so code that owns a rule can add it
        on every run. ``to`` is ``"require_approval"``, ``"deny"`` or ``"allow"``.

        Returns:
            The saved policy, with the rest of its rules.

        Usage:
            Own one rule from the code that needs it, safe to run on every deploy::

                noclick.Policy.add("quickbooks.create_bill")

            Deny an operation for one user::

                noclick.Policy.add("slack.*", to="deny", user="user_42")

            Hold only large bills, for finance to approve::

                noclick.Policy.add(
                    noclick.Rule("quickbooks.create_bill", when="args.total_amount > 2500", approver="finance@acme.com"),
                )
        """
        if to not in _LISTS:
            raise ValueError(f"to is one of {', '.join(_LISTS)}, not {to!r}")
        if not rules:
            raise ValueError("Policy.add() takes at least one rule")
        user_id = await user_ref(resolve_scope(user))
        body = compact(list=to, rules=await _wire_rules(to, [Rule._parse(r) for r in rules]), user_id=user_id)
        raw = await resolve_client(client).request("POST", "/v1/policy/add", json=body, user=None)
        return cls._from(raw, user_id)

    @synced
    @classmethod
    async def remove(cls, *tools: str, user: Any = AMBIENT, client: Optional[Client] = None) -> "Policy":
        """Remove the rules for these tools, as written (``"stripe.create_refund"``,
        ``"gmail.*"``), from every list of the account's policy (or ``user=``'s; inside
        ``as_user`` that user's), leaving the rest. A tool with no rule changes nothing.

        Returns:
            The saved policy, with the rules that are left.

        Usage::

            noclick.Policy.remove("quickbooks.create_bill")
        """
        if not tools or not all(isinstance(t, str) for t in tools):
            raise ValueError("Policy.remove() takes the tool patterns whose rules go, like 'stripe.create_refund'")
        user_id = await user_ref(resolve_scope(user))
        body = compact(tools=list(tools), user_id=user_id)
        raw = await resolve_client(client).request("POST", "/v1/policy/remove", json=body, user=None)
        return cls._from(raw, user_id)
