"""
Lazy, TTL-refreshed option registry.

Wraps StaticOptionRegistry's matching machinery and rebuilds the underlying
Option list on demand via a build callback. Used by the models registry to
pull live OpenRouter + LiteLLM data instead of a hand-curated tuple.

Design notes:
- Cache miss after TTL expiry triggers a rebuild on the next ``match``/``get``
  call. Build is synchronous (the OpenRouter fetch already is).
- A failed rebuild keeps the previous in-memory snapshot in service. The
  build callback is expected to log its own errors.
- Cold start with no successful build ever falls back to ``static_fallback``
  so the resolver never returns "registry empty" — for the models registry
  that means CLI agents and Kling are always matchable even if both upstreams
  are down.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, Optional

from .base import Option, Resolution, StaticOptionRegistry

logger = logging.getLogger(__name__)


class LazyOptionRegistry:
    """An OptionRegistry whose options refresh on a TTL.

    Matches the OptionRegistry protocol — ``match``, ``get``, ``hint`` — by
    delegating to a wrapped StaticOptionRegistry that gets rebuilt on demand.
    """

    def __init__(
        self,
        name: str,
        build: Callable[[], Iterable[Option]],
        hint: str,
        ttl_seconds: float = 600.0,
        static_fallback: Iterable[Option] = (),
    ) -> None:
        self.name = name
        self._build = build
        self._hint = hint
        self._ttl = ttl_seconds
        self._fallback: tuple[Option, ...] = tuple(static_fallback)
        self._inner: StaticOptionRegistry = StaticOptionRegistry(
            name=name, options=self._fallback, hint=hint,
        )
        self._loaded_at: float = 0.0
        self._has_succeeded: bool = False

    def hint(self) -> str:
        return self._hint

    def get(self, option_id: str) -> Optional[Option]:
        self._maybe_refresh()
        return self._inner.get(option_id)

    def match(self, query: str, limit: int = 8) -> Resolution:
        self._maybe_refresh()
        return self._inner.match(query, limit=limit)

    def _maybe_refresh(self) -> None:
        now = time.monotonic()
        if self._has_succeeded and (now - self._loaded_at) < self._ttl:
            return
        try:
            options = tuple(self._build())
        except Exception as e:
            logger.warning(
                f"[LazyOptionRegistry:{self.name}] build failed: {e!r}; "
                f"keeping previous snapshot ({len(self._inner._options)} entries)"
            )
            # Reset the timer anyway so we don't hammer a failing source on
            # every match() call. Retry one TTL window from now.
            self._loaded_at = now
            return
        if not options:
            logger.warning(
                f"[LazyOptionRegistry:{self.name}] build returned 0 options; "
                f"keeping previous snapshot ({len(self._inner._options)} entries)"
            )
            self._loaded_at = now
            return
        self._inner = StaticOptionRegistry(
            name=self.name, options=options, hint=self._hint,
        )
        self._loaded_at = now
        self._has_succeeded = True
        logger.info(
            f"[LazyOptionRegistry:{self.name}] rebuilt with {len(options)} options"
        )
