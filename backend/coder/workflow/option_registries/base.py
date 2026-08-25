"""
Shared types and the OptionRegistry protocol for queryable-enum fields.

A registry exposes a single ``match(query)`` entry point that returns the
canonical option id for a fuzzy input plus a small list of nearby
alternatives. The field-write path stores the canonical id; the next-turn
execution summary renders the alternatives so the brain (or node drafting) can
correct itself in the same turn loop without a separate query verb.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Protocol


@dataclass(frozen=True)
class Option:
    """A single entry in a queryable-enum registry."""
    id: str                          # canonical id stored in config
    label: str                       # human-readable name
    description: str = ""            # short context (provider, modality, tier)
    tags: tuple[str, ...] = ()       # facets for filtering / variant inference
    aliases: tuple[str, ...] = ()    # alternate names users might type
    preferred: bool = False          # boost this option when fuzzy scores are close


@dataclass
class Resolution:
    """Outcome of registry.match(input) for one field write."""
    field_name: str
    original: str                    # raw value the brain/node drafting wrote
    matched_id: Optional[str]        # canonical id stored, or None if unresolved
    matched_label: str = ""          # label of the matched option
    score: float = 0.0               # match confidence in [0, 1]
    alternatives: List[Option] = field(default_factory=list)
    exact: bool = False              # True when the input was already a canonical id

    @property
    def resolved(self) -> bool:
        return self.matched_id is not None


# Threshold below which we don't claim a match — we still return alternatives
# but leave the original value in place and flag it as unresolved.
DEFAULT_MIN_SCORE = 0.45

# A "preferred" option (e.g. an openrouter/* mirror) gets this additive bonus
# on its raw fuzzy score so it wins ties against equally-good direct-provider
# entries. Bonus is intentionally large enough to flip near-ties (anthropic/...
# at 0.88 vs openrouter/anthropic/... at 0.84) but capped at 1.0 and only
# applies when the raw score already cleared PREFERRED_FLOOR — so a weak
# fuzzy match never gets boosted into a confident-looking pick. Exact-id
# input bypasses scoring entirely, so direct ids the brain types verbatim
# stay verbatim.
PREFERRED_BONUS = 0.10
PREFERRED_FLOOR = 0.60


def _normalize(text: str) -> str:
    """Lowercase + strip non-alphanumeric for fuzzy comparison."""
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != " ":
            out.append(" ")
    return "".join(out).strip()


def _score(query_norm: str, candidate_norm: str) -> float:
    """Simple fuzzy similarity. Substring containment scores high; otherwise
    use SequenceMatcher ratio. Both inputs must already be normalized."""
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0
    if query_norm in candidate_norm:
        # Reward containment proportional to how much of the candidate matches
        return 0.7 + 0.3 * (len(query_norm) / max(len(candidate_norm), 1))
    if candidate_norm in query_norm:
        return 0.7 + 0.3 * (len(candidate_norm) / max(len(query_norm), 1))
    return SequenceMatcher(None, query_norm, candidate_norm).ratio()


class OptionRegistry(Protocol):
    """A queryable-enum backing store."""

    name: str

    def hint(self) -> str:
        """One-line guidance shown to node drafting / the brain in query_schema."""
        ...

    def get(self, option_id: str) -> Optional[Option]:
        """Return the option for an exact canonical id, or None."""
        ...

    def match(self, query: str, limit: int = 8) -> Resolution:
        """Resolve fuzzy input to a canonical id + alternatives.

        Implementations should:
          - Treat exact-id matches as score 1.0 with no alternatives.
          - Score against id, label, aliases, and description tokens.
          - Cap the alternatives list at *limit* (default keeps prompts small).
        """
        ...


class StaticOptionRegistry:
    """Default implementation backed by an in-memory tuple of Options."""

    def __init__(
        self,
        name: str,
        options: Iterable[Option],
        hint: str,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        self.name = name
        self._options: tuple[Option, ...] = tuple(options)
        self._by_id = {o.id: o for o in self._options}
        self._hint = hint
        self._min_score = min_score

    def hint(self) -> str:
        return self._hint

    def get(self, option_id: str) -> Optional[Option]:
        return self._by_id.get(option_id)

    def match(self, query: str, limit: int = 8) -> Resolution:
        raw = (query or "").strip()
        if not raw:
            return Resolution(field_name="", original=raw, matched_id=None)

        # Exact-id fast path.
        if raw in self._by_id:
            opt = self._by_id[raw]
            return Resolution(
                field_name="",
                original=raw,
                matched_id=opt.id,
                matched_label=opt.label,
                score=1.0,
                alternatives=[],
                exact=True,
            )

        q_norm = _normalize(raw)
        scored: list[tuple[float, Option]] = []
        for opt in self._options:
            best = max(
                _score(q_norm, _normalize(opt.id)),
                _score(q_norm, _normalize(opt.label)),
                *(_score(q_norm, _normalize(a)) for a in opt.aliases) if opt.aliases else (0.0,),
                _score(q_norm, _normalize(opt.description)) * 0.6 if opt.description else 0.0,
            )
            if best <= 0:
                continue
            if opt.preferred and best >= PREFERRED_FLOOR:
                best = min(1.0, best + PREFERRED_BONUS)
            scored.append((best, opt))

        scored.sort(key=lambda x: (-x[0], x[1].id))
        if not scored:
            return Resolution(field_name="", original=raw, matched_id=None)

        top_score, top_opt = scored[0]
        alternatives = [o for _, o in scored[1:1 + limit]]

        if top_score < self._min_score:
            # Weak match — leave the original in place but still surface neighbors
            # so the brain can correct.
            return Resolution(
                field_name="",
                original=raw,
                matched_id=None,
                matched_label="",
                score=top_score,
                alternatives=[top_opt, *alternatives][:limit],
            )

        return Resolution(
            field_name="",
            original=raw,
            matched_id=top_opt.id,
            matched_label=top_opt.label,
            score=top_score,
            alternatives=alternatives,
        )
