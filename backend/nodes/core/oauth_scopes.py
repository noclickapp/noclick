"""Declarative OAuth scope requirements for integration nodes.

The bug this exists to prevent: ``x-oauth-scopes`` (what the app REQUESTS at
connect time) was a hand-written list, while the scopes an operation actually
NEEDS lived only in the provider's docs. Nothing linked the two, so operations
shipped that could never work — the Slack node had 131 of them, roughly 61% of
its surface, every one failing with ``missing_scope`` on first call.

A node declares a :class:`ScopeRegistry` mapping each unit of work — an API
endpoint for nodes with a central request helper, an operation name otherwise —
to the scopes that unit requires. Two things follow:

- :meth:`ScopeRegistry.declared_scopes` derives the connect-time request from
  the table, so the requested list cannot drift from the code that needs it.
- ``tests/test_oauth_scope_coverage.py`` asserts every operation is either
  mapped or explicitly declared unmapped, and that mapped requirements are a
  subset of what the node requests.

Two enforcement strengths, deliberately:

``STRICT``
    The requested scope list must equal the derived union. Used for nodes whose
    table has been verified against the provider's published docs.
``SUBSET``
    The derived union must be a subset of the requested list. Catches the bug
    class (a needed scope that is never requested) without letting an unverified
    table DELETE a scope that live credentials depend on — providers reject
    unknown or removed scopes at the authorize step, so a wrong derivation
    breaks connect for existing users.

New nodes start at ``SUBSET`` and ratchet to ``STRICT`` once verified.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Collection, Dict, Iterable, Iterator, Mapping, Optional, Sequence

__all__ = [
    "ANY_VARIANT",
    "DEFAULT_VARIANT",
    "STANDARD_TIER",
    "Enforcement",
    "ScopeRequirement",
    "ScopeRegistry",
    "UndeclaredScopeError",
    "CredentialTypeError",
]

#: Scope tier requested during the standard OAuth connect flow. Requirements in
#: any other tier are excluded from the request — a provider that rejects an
#: elevated scope on an ordinary workspace would otherwise break every install.
STANDARD_TIER = "standard"

#: Token variant for providers that mint a single token. Slack is the notable
#: exception: it returns a bot (``xoxb-``) and a user (``xoxp-``) token with
#: independently granted scope sets.
DEFAULT_VARIANT = "default"

#: Variant for calls whose token is chosen at runtime, so the scope must be
#: granted on every variant. Slack's write operations honor a per-operation
#: ``send_as``, so ``chat.postMessage`` needs ``chat:write`` on both tokens.
ANY_VARIANT = "any"


class Enforcement(enum.Enum):
    """How strictly a node's requested scopes must match its requirements."""

    STRICT = "strict"
    SUBSET = "subset"


class UndeclaredScopeError(LookupError):
    """Raised when code calls an endpoint/operation with no requirement entry.

    This is a programming error, not a user error: the node reached an API
    surface nobody declared scopes for, which is exactly how unusable
    operations shipped before. Fail loudly rather than let the provider
    return an opaque ``missing_scope``.
    """


class CredentialTypeError(ValueError):
    """Raised when an operation is run with a credential type it cannot use."""


@dataclass(frozen=True)
class ScopeRequirement:
    """What one endpoint (or operation) needs in order to run.

    ``scopes`` is a conjunction: every string listed must be held. Providers
    that accept ALTERNATIVES (Google publishes a set per method, any one of
    which suffices) cannot be expressed directly — name the single alternative
    the node's credential actually holds, and say so in a comment. Listing all
    the alternatives would demand scopes the call does not need and produce
    phantom missing-scope failures.

    Args:
        scopes: Provider scope strings required, ALL of them. Empty means the
            call needs no scope beyond authentication (e.g. Slack's
            ``auth.test``, or Google's public mobile-friendly test endpoint).
        variant: Which token the call is made with, for providers that mint
            more than one. Defaults to the provider's only token.
        tier: Scope tier. Anything other than ``standard`` is excluded from the
            connect-time request and must be satisfied by a credential the user
            supplies themselves.
        credential_types: If set, only these ``credential_type`` values can
            satisfy this requirement. Enforced at the node's request choke
            point, replacing per-handler ``if credential_type != ...`` checks.
        note: Free-text rationale, surfaced in error messages. Use it to say
            what the user must do, not what the code does.
    """

    scopes: tuple[str, ...] = ()
    variant: str = DEFAULT_VARIANT
    tier: str = STANDARD_TIER
    credential_types: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        # Normalize so callers can pass a bare string or any iterable and
        # equality/derivation stay predictable.
        object.__setattr__(self, "scopes", tuple(_as_tuple(self.scopes)))
        object.__setattr__(
            self, "credential_types", tuple(_as_tuple(self.credential_types))
        )

    @property
    def is_standard(self) -> bool:
        return self.tier == STANDARD_TIER

    def satisfied_by(self, credential_type: Optional[str]) -> bool:
        """Whether ``credential_type`` is allowed to run this requirement."""
        if not self.credential_types:
            return True
        return credential_type in self.credential_types


def _as_tuple(value: object) -> Sequence[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class _Grant:
    """A resolved requirement plus the key it was registered under."""

    key: str
    requirement: ScopeRequirement


class ScopeRegistry:
    """A node's endpoint/operation → scope requirement table.

    Keys are whatever unit the node dispatches on. Nodes with a central request
    helper (``_make_request(method, endpoint, ...)``) key on the endpoint, which
    gives runtime enforcement for free. Nodes without one key on the operation
    name.
    """

    def __init__(
        self,
        provider: str,
        requirements: Mapping[str, ScopeRequirement],
        *,
        enforcement: Enforcement = Enforcement.SUBSET,
        unmapped: Collection[str] = (),
        extra_scopes: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        """
        Args:
            provider: Node/provider identifier, used in error messages.
            requirements: The table itself.
            enforcement: How strictly requested scopes must match (see module
                docstring).
            unmapped: Operations knowingly without a requirement entry. Listing
                one is an explicit admission of a gap — the coverage test allows
                it but counts it, so the number ratchets down instead of hiding.
            extra_scopes: Scopes the app must request that no single endpoint
                implies — event subscriptions being the main case (Slack's
                ``app_mentions:read`` is needed to RECEIVE ``app_mention``
                events; no endpoint call requires it). Keyed by variant.
        """
        self.provider = provider
        self.enforcement = enforcement
        self._requirements: Dict[str, ScopeRequirement] = dict(requirements)
        self._unmapped = frozenset(unmapped)
        self._extra: Dict[str, tuple[str, ...]] = {
            variant: tuple(scopes) for variant, scopes in (extra_scopes or {}).items()
        }

    # -- lookup ---------------------------------------------------------

    def __contains__(self, key: object) -> bool:
        return key in self._requirements

    def __iter__(self) -> Iterator[str]:
        return iter(self._requirements)

    def __len__(self) -> int:
        return len(self._requirements)

    def get(self, key: str) -> Optional[ScopeRequirement]:
        return self._requirements.get(key)

    def require(self, key: str) -> ScopeRequirement:
        """Look up ``key``, raising if it was never declared."""
        try:
            return self._requirements[key]
        except KeyError:
            raise UndeclaredScopeError(
                f"{self.provider}: no OAuth scope requirement declared for "
                f"'{key}'. Add an entry to the node's ScopeRegistry — an "
                f"undeclared call is how unusable operations ship."
            ) from None

    @property
    def keys_declared(self) -> frozenset[str]:
        return frozenset(self._requirements)

    @property
    def unmapped(self) -> frozenset[str]:
        return self._unmapped

    # -- derivation -----------------------------------------------------

    def declared_scopes(
        self,
        *,
        variant: str = DEFAULT_VARIANT,
        tier: str = STANDARD_TIER,
    ) -> list[str]:
        """The scope list to request at connect time, derived from the table.

        Sorted for a stable diff — the requested list is user-visible on the
        provider's consent screen and churn there is confusing.
        """
        scopes: set[str] = set()
        for req in self._requirements.values():
            if req.tier != tier:
                continue
            if req.variant not in (variant, ANY_VARIANT):
                continue
            scopes.update(req.scopes)
        if tier == STANDARD_TIER:
            scopes.update(self._extra.get(variant, ()))
        return sorted(scopes)

    def variants(self) -> frozenset[str]:
        """The concrete token variants this provider mints.

        ``ANY_VARIANT`` is a marker meaning "whichever token the call uses", not
        a token of its own, so it never appears here — its scopes are folded
        into every concrete variant by :meth:`declared_scopes`.
        """
        concrete = {
            req.variant
            for req in self._requirements.values()
            if req.variant != ANY_VARIANT
        }
        return frozenset(concrete | set(self._extra)) or frozenset({DEFAULT_VARIANT})

    def tiers(self) -> frozenset[str]:
        return frozenset(req.tier for req in self._requirements.values())

    def elevated(self) -> Dict[str, ScopeRequirement]:
        """Requirements outside the standard tier, keyed by endpoint/operation."""
        return {
            key: req
            for key, req in self._requirements.items()
            if not req.is_standard
        }

    # -- enforcement ----------------------------------------------------

    def enforce_credential_type(
        self, key: str, credential_type: Optional[str]
    ) -> ScopeRequirement:
        """Look up ``key`` and verify the credential may run it.

        Called from the node's request choke point so the check lives in one
        place instead of being re-implemented per handler.
        """
        req = self.require(key)
        if req.satisfied_by(credential_type):
            return req
        allowed = ", ".join(req.credential_types)
        detail = f" {req.note}" if req.note else ""
        raise CredentialTypeError(
            f"This operation requires a {allowed} credential, but the node is "
            f"connected with {credential_type or 'no'} credential.{detail}"
        )
