"""``@designed``: marks a class or method whose API is designed but not built yet.

It changes nothing at runtime. The reference generator reads it (by name, from
the source) and tags the class or method as an invite-only beta; without access, such
a call answers 404 (``NotFound``), or ``not_available`` (``NotAvailable``) where
NoClick has built it and waits on a vendor going live. Put it outermost, above
``@synced`` and ``@classmethod``.

``@designed_params("timezone", "shell")`` marks parameters of a built call the
same way: the call works, and passing one of them answers 404 (or
``not_available``) until it ships.
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def designed(obj: T) -> T:
    return obj


def designed_params(*names: str) -> Callable[[T], T]:
    def mark(obj: T) -> T:
        return obj

    return mark
