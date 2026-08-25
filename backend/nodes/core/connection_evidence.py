"""Connection evidence: proving to a user that a credential really works.

A green tick proves nothing to a human. "#sales, #gtm, #incident" proves
everything — only a genuinely connected credential could know that, and the user
verifies it from memory in a second. This module is the one seam that produces
that proof, so every node answers "are you actually connected?" the same way.

Two failure classes this exists to catch, both from real incidents:

* **Dead credential.** A Slack bot token stayed attached, passed
  ``validate_workflow`` with ``config_valid: true``, and returned ``invalid_auth``
  on every call. Nothing surfaced it until a run silently delivered nothing.
* **Insufficient scope.** A fresh Slack OAuth landed without ``channels:write``
  and hit ``missing_scope`` 54 seconds into the first run. The credential was
  live; it just could not do the job.

Evidence catches the first and is the persuasive half. It does NOT catch the
second — listing channels proves ``channels:read`` and says nothing about
``chat:write`` — so :func:`verify_operation_scopes` runs alongside it. Evidence
earns belief; the scope check earns correctness. Belief without correctness is
exactly how that Slack token stayed green for weeks.

Declaring it
------------
A node declares what to show, never how to fetch it::

    connection_evidence = ConnectionEvidence(
        field="channel",                     # preferred: the existing picker
        operation="list_channels_in_workspace",  # fallback: a read-only op
        noun="channels",
        identity_operation="test_authentication",
    )

Resolution order is deliberate:

1. ``field`` — if the node implements ``load_field_options`` for it, that call
   IS the evidence. It is already authenticated, already refreshes the token at
   load, and already returns the exact nouns the user recognises. Preferring it
   means the dropdown and the proof are one request, not two.
2. ``operation`` — run one of the node's own read-only operations through
   ``run_node_operation``. No bespoke API code per node: the node's own request
   helper, auth and error handling are reused as-is.
3. ``identity_operation`` — for accounts with nothing to list (a brand-new
   Airtable has no bases) and for genuinely stateless providers. Falls back to
   naming the account rather than showing an empty panel to the people who most
   need reassurance.

Coverage is a ratchet: ``tests/test_connection_evidence_coverage.py`` fails for
any credentialed node that declares neither this nor an entry on its shrinking
allowlist — the same mechanism that took OAuth scope coverage to zero
unverified nodes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Connecting an account is a deliberate act the user is watching, so the budget
# is generous rather than tight: Gmail fetches messages one round-trip each and
# lost the race at 8s often enough to report "cannot judge" on a healthy inbox,
# which is the least useful answer this module can give. A provider that cannot
# answer in this long is still treated as "cannot judge", never as broken.
EVIDENCE_TIMEOUT_S = 15.0

# How many recognisable items to surface. Enough to be convincing, few enough to
# read at a glance and to keep an inbox-shaped provider from dumping its contents
# onto a screen someone may be sharing.
EVIDENCE_SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class ConnectionEvidence:
    """What a node shows to prove a credential is genuinely connected.

    Declarative on purpose: nodes say *what* is recognisable, never *how* to
    fetch it, so the fetching stays in one place and new nodes get the whole
    layer by adding a few lines.
    """

    #: Human noun for what will be listed — "channels", "bases", "pipelines".
    #: Shown to the user, so write it as they would say it.
    noun: str

    #: Config field whose ``load_field_options`` result is the evidence.
    #: Preferred when present: the picker and the proof become one call.
    field: Optional[str] = None

    #: Read-only operation to run when there is no field loader. Must be
    #: genuinely non-mutating — it runs the moment someone connects an account.
    operation: Optional[str] = None

    #: Arguments the operation needs beyond defaults (rare; keep empty).
    operation_arguments: Dict[str, Any] = dc_field(default_factory=dict)

    #: Keys to try, in order, when pulling a human label out of a raw result row.
    label_keys: Tuple[str, ...] = ("name", "label", "title", "display_name", "id")

    #: Operation naming the account itself, used when the list comes back empty
    #: (new accounts) or when a provider has nothing user-owned to list.
    identity_operation: Optional[str] = None

    #: What a successful probe actually demonstrates.
    #:
    #: ``"account"`` (default) — the samples are data unique to THIS account, so
    #: they are real evidence: two different accounts would show different
    #: things. That is the whole point, and the bar every declaration should try
    #: to clear.
    #:
    #: ``"reachability"`` — the probe only proves the credential is accepted.
    #: Some providers genuinely have nothing per-account to list (Translate's
    #: language list is byte-identical for every API key on earth). Marking it
    #: honestly is required: the UI then says the key was accepted instead of
    #: parading a static catalogue as proof, which is worse than saying nothing.
    proves: str = "account"

    #: Keys to try when pulling the account's name out of the identity result.
    identity_keys: Tuple[str, ...] = (
        "name",
        "display_name",
        "email",
        "team",
        "workspace",
        "account",
        "login",
        "handle",
        "url",
    )

    def __post_init__(self) -> None:
        if not (self.field or self.operation or self.identity_operation):
            raise ValueError(
                "ConnectionEvidence needs at least one of field / operation / "
                "identity_operation — otherwise it can prove nothing."
            )


@dataclass(frozen=True)
class EvidenceSample:
    """One recognisable item, and — when it can be — the answer to a question.

    ``value`` is set only when the sample came from a config field's own options
    loader, which means it is directly settable into that field. The proof and
    the answer are then the same object, so picking a resource costs no step of
    its own.
    """

    label: str
    value: Optional[str] = None


@dataclass
class EvidenceResult:
    """Outcome of asking a provider to prove itself.

    ``reachable is None`` means "cannot judge" and must never render as broken —
    the same non-definitive-signal doctrine credential health and webhook
    teardown already follow.
    """

    #: True = provider answered, False = provider rejected us, None = unknown.
    reachable: Optional[bool] = None
    #: Recognisable items, e.g. #sales / #gtm.
    samples: List[EvidenceSample] = dc_field(default_factory=list)
    #: Config field these samples can fill, when they can fill one.
    #:
    #: Set ONLY when the probe went through that field's own options loader, so
    #: the things shown really are the things choosable. Evidence fetched from a
    #: read operation proves the account works but answers no question — Gmail's
    #: recent senders cannot populate a label picker — and leaves this None.
    answers_field: Optional[str] = None
    #: Total the provider reported, when it exceeds what we sampled.
    total: Optional[int] = None
    #: Human noun for the samples.
    noun: str = "items"
    #: The account itself, when known — the fallback for an empty list.
    account_label: Optional[str] = None
    #: Verbatim provider error when reachable is False. Never paraphrased: the
    #: provider's own words are what makes a failure diagnosable.
    error: Optional[str] = None

    @property
    def is_empty_but_working(self) -> bool:
        """Connected, but the account has nothing to show yet.

        The common case for new signups, and the reason identity fallback is
        mandatory rather than optional.
        """
        return self.reachable is True and not self.samples


def _tidy(text: str) -> str:
    """Human-readable form of one label.

    Mail headers arrive as ``Casey Example <casey@sender.example>``; the name is the
    recognisable half and the address is noise on a screen someone may be
    sharing. A bare address stays as-is — it is all there is.
    """
    text = text.strip().strip('"')
    if text.endswith(">") and "<" in text:
        name = text[: text.rindex("<")].strip().strip('"')
        if name:
            return name
        return text[text.rindex("<") + 1 : -1].strip()
    return text


def _label_from(row: Any, keys: Sequence[str]) -> Optional[str]:
    """Best human label for one result row, or None if nothing readable."""
    if isinstance(row, str):
        return _tidy(row) or None
    if not isinstance(row, dict):
        return None
    for k in keys:
        v = row.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return _tidy(str(v))
    return None


def _rows_from_options(payload: Dict[str, Any]) -> List[Any]:
    """Rows out of a ``load_field_options`` payload."""
    opts = payload.get("options")
    return opts if isinstance(opts, list) else []


class _ProviderRefused(Exception):
    """A node reported failure in its RESULT rather than by raising.

    Most nodes return ``{"status": "error", "error": ..., "status_code": 403}``
    instead of throwing, so treating "the call returned" as "the credential
    works" reports a dead account as connected — the precise false green this
    whole layer exists to remove. Raised so both the operation and identity paths
    funnel into the one place that classifies provider failures.
    """


def _raise_if_error_envelope(payload: Any) -> None:
    """Turn a node's error-shaped result into a real failure."""
    if not isinstance(payload, dict):
        return
    failed = payload.get("status") == "error" or payload.get("success") is False
    err = payload.get("error") or payload.get("message")
    if not (failed and err):
        return
    code = payload.get("status_code")
    raise _ProviderRefused(f"{err}{f' (HTTP {code})' if code else ''}")


def _rows_from_operation(payload: Any) -> List[Any]:
    """Rows out of an arbitrary operation result.

    Node outputs are not uniform — some return a bare list, most wrap it under
    ``data``/``results``/``items``, and a few nest one level deeper. Rather than
    make every node declare a path, probe the handful of shapes that actually
    occur and give up quietly if none match; a missing sample degrades to the
    identity fallback rather than to an error.
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("options", "results", "items", "records", "values", "data"):
        v = payload.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for inner in ("results", "items", "records", "values"):
                iv = v.get(inner)
                if isinstance(iv, list):
                    return iv

    # Nodes name their collection after the thing (`emails`, `zones`, `boards`),
    # so a fixed key list is endless whack-a-mole — Gmail returned its rows under
    # `emails` and the probe reported "connected, nothing to show". Fall back to
    # the largest list of rows anywhere in the envelope, which is what any of
    # those names points at anyway.
    best: List[Any] = []
    for v in payload.values():
        if not isinstance(v, list) or len(v) <= len(best):
            continue
        if all(isinstance(x, (dict, str)) for x in v):
            best = v
    return best


def verify_operation_scopes(
    node_cls: Any,
    operations: Sequence[str],
    granted_scopes: Optional[Sequence[str]],
) -> Dict[str, List[str]]:
    """Operations whose required scopes are not covered by what was granted.

    Pure computation against data already held — no provider round-trip — which
    is why this runs on every connect rather than on demand. It is the half that
    catches "signed in but cannot post", the failure evidence is blind to.

    ``granted_scopes`` of None means the credential records no scopes at all
    (bot tokens, plain API keys). That is "cannot judge", not "missing": the
    caller shows an unverified state rather than a false alarm.
    """
    registry = getattr(node_cls, "scope_registry", None)
    if registry is None or granted_scopes is None:
        return {}

    granted = {s.strip() for s in granted_scopes if s and s.strip()}
    missing: Dict[str, List[str]] = {}
    for op in operations:
        # Registries are keyed by ENDPOINT for nodes with a central request
        # helper (Slack maps `chat.postMessage`, not `send_message_to_channel`)
        # and by OPERATION for everything else. Only the latter can be resolved
        # from an operation name alone; endpoint-keyed nodes fall through to no
        # verdict, which is "cannot judge" and must never render as missing.
        # Mapping the former needs the node's own operation→endpoint table —
        # tests/test_oauth_scope_coverage.py does it by AST at build time,
        # which is not available here.
        requirement = registry.get(op)
        if requirement is None:
            continue
        required = getattr(requirement, "scopes", ()) or ()
        if not required:
            continue
        # A scope is satisfied by an exact grant or by a granted scope that
        # contains it — providers express the same permission at different
        # granularities (Google's full URLs vs Slack's bare `chat:write`).
        unmet = [
            r
            for r in required
            if not any(r == g or r in g for g in granted)
        ]
        if unmet:
            missing[op] = unmet
    return missing


async def collect_evidence(
    *,
    node_type: str,
    credential_id: str,
    user_id: str,
    pool=None,
    organization_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
) -> EvidenceResult:
    """Ask a provider to prove itself, and shape the answer for a human.

    Never raises: a connect flow must not break because a provider was slow or
    returned a shape we did not expect. Anything unexpected degrades to
    ``reachable=None`` ("cannot judge"), which the UI renders as unverified
    rather than broken.
    """
    import asyncio

    from nodes.core.registry import NODE_REGISTRY

    node_cls = NODE_REGISTRY.get(node_type)
    spec: Optional[ConnectionEvidence] = getattr(node_cls, "connection_evidence", None)
    if node_cls is None or spec is None:
        return EvidenceResult(reachable=None, noun="items")

    result = EvidenceResult(noun=spec.noun)

    async def _run() -> None:
        rows: List[Any] = []

        # 1. The field picker, when the node has one. Already authenticated,
        #    already refreshes the token at load, and already returns the exact
        #    nouns the user recognises — so the dropdown and the proof are one
        #    request rather than two.
        if spec.field and hasattr(node_cls, "load_field_options"):
            from utils.credentials import resolve_credential_with_owner_fallback

            credential_data = await resolve_credential_with_owner_fallback(
                credential_id,
                user_id,
                pool,
                org_id=organization_id,
                workflow_id=workflow_id,
            )
            if credential_data is None:
                raise ValueError(f"credential {credential_id} is unresolvable")
            # Freshen at load, exactly as the dropdown path does. Without this the
            # probe can hit the provider with an expired access token and report
            # a perfectly healthy credential as REJECTED — telling someone to
            # reconnect a working account, the one outcome worse than saying
            # nothing. (Caught trashing a test file: the same credential 401'd
            # here and answered fine after a refresh.)
            from nodes.core.oauth_audit import caller_path_scope

            with caller_path_scope("connection_evidence"):
                credential_data = await node_cls.freshen_credential(
                    credential_data,
                    pool=pool,
                    user_id=user_id,
                    credential_id=credential_id,
                )
            payload = await node_cls.load_field_options(
                field_name=spec.field, credential_data=credential_data
            )
            _raise_if_error_envelope(payload)
            rows = _rows_from_options(payload or {})
            result.reachable = True
            # These rows came from this field's own loader, so each one is a
            # legal value for it: the proof doubles as the picker.
            result.answers_field = spec.field

        # 2. Otherwise one of the node's own read-only operations, through the
        #    same seam agent tool calls use — the node's request helper, auth
        #    and error handling are reused as-is rather than reimplemented here.
        elif spec.operation:
            from nodes.core.run_op import run_node_operation

            payload = await run_node_operation(
                node_type=node_type,
                operation=spec.operation,
                arguments=dict(spec.operation_arguments),
                user_id=user_id,
                pool=pool,
                credential_id=credential_id,
                organization_id=organization_id,
                workflow_id=workflow_id,
            )
            _raise_if_error_envelope(payload)
            rows = _rows_from_operation(payload)
            result.reachable = True

        if rows:
            # Deduplicate: five rows from one busy sender is not five pieces of
            # evidence, it is one repeated until it looks like filler.
            seen: set = set()
            distinct: List[EvidenceSample] = []
            for row in rows:
                label = _label_from(row, spec.label_keys)
                if not label or label.casefold() in seen:
                    continue
                seen.add(label.casefold())
                value = row.get("value") if isinstance(row, dict) else None
                distinct.append(
                    EvidenceSample(
                        label=label,
                        value=str(value) if value not in (None, "") else None,
                    )
                )
            result.samples = distinct[:EVIDENCE_SAMPLE_LIMIT]
            if len(distinct) > len(result.samples):
                result.total = len(distinct)

        # 3. Name the account when there is nothing to list. A brand-new
        #    Airtable has no bases, and showing the people who most need
        #    reassurance an empty panel is the worst possible outcome.
        if not result.samples and spec.identity_operation:
            from nodes.core.run_op import run_node_operation

            ident = await run_node_operation(
                node_type=node_type,
                operation=spec.identity_operation,
                arguments={},
                user_id=user_id,
                pool=pool,
                credential_id=credential_id,
                organization_id=organization_id,
                workflow_id=workflow_id,
            )
            _raise_if_error_envelope(ident)
            result.reachable = True
            if isinstance(ident, dict):
                inner = ident.get("data") if isinstance(ident.get("data"), dict) else ident
                result.account_label = _label_from(inner, spec.identity_keys)

    try:
        await asyncio.wait_for(_run(), timeout=EVIDENCE_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.info("[evidence] %s timed out after %ss", node_type, EVIDENCE_TIMEOUT_S)
        return EvidenceResult(reachable=None, noun=spec.noun)
    except _BROKEN_DECLARATION as e:
        # OUR bug, not the provider's: a field or operation that does not resolve,
        # or a seam whose signature moved. Degrading these to "cannot judge" is
        # how a typo'd declaration goes unnoticed for months while every user is
        # quietly told nothing — so it is logged loudly and alertably even though
        # the connect flow itself still survives.
        logger.error(
            "[evidence] %s declaration is broken: %s", node_type, e, exc_info=True
        )
        return EvidenceResult(reachable=None, noun=spec.noun)
    except Exception as e:
        # A provider REJECTING us is a real, reportable verdict; anything else
        # (shape surprises, transport blips) is not something to accuse a user's
        # credential over.
        text = str(e)
        if _looks_like_auth_rejection(text):
            return EvidenceResult(reachable=False, noun=spec.noun, error=text[:300])
        logger.info("[evidence] %s could not be judged: %s", node_type, text[:200])
        return EvidenceResult(reachable=None, noun=spec.noun)

    return result


# Signals a declaration or a seam is wrong rather than a provider being unhappy.
# Kept separate so a mistake of ours is never filed as a mystery about the user's
# account — the distinction this module exists to make.
_BROKEN_DECLARATION = (ImportError, AttributeError, TypeError, NameError)


# Provider phrasing for "your credential is no good". Deliberately narrow: a
# false positive here tells someone to reconnect a working account, which is
# worse than showing nothing.
_AUTH_REJECTION_MARKERS = (
    "invalid_auth",
    "not_authed",
    "token_revoked",
    "account_inactive",
    "missing_scope",
    "unauthorized",
    "401",
    "403",
    "invalid_grant",
    "invalid credentials",
    # Google's phrasing. NOT covered by "invalid credentials" above — the word
    # "authentication" sits between the two, so the substring never matched and
    # every dead Google credential reported "cannot judge" instead of asking the
    # user to reconnect.
    "invalid authentication",
    "invalid_token",
    "token has been expired or revoked",
    "unauthenticated",
    "authentication failed",
    "permission denied",
    "forbidden",
)


def _looks_like_auth_rejection(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _AUTH_REJECTION_MARKERS)
