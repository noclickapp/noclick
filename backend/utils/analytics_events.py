"""Compatibility labels for analytics call sites that are no-ops in this edition.

Keeping labels mechanical avoids publishing the hosted product-event catalogue.
"""


class _EventLabels(type):
    def __getattr__(cls, name: str) -> str:
        return name.lower()


class Events(metaclass=_EventLabels):
    pass
