"""A reference to ``"module:attribute"`` that imports it when first used.

Registering a capability or a hook used to import its implementation, and with it
whatever that module imports: the start-up of a process that never used it paid
for the model client, the socket handlers and the builder. A ``Lazy`` registers
nothing heavier than its name. ``utils.capabilities`` resolves one at the
capability's first lookup; called as a hook, it imports its target and calls it.
"""
import importlib
from typing import Any


class Lazy:
    __slots__ = ("ref", "_target")

    def __init__(self, ref: str):
        module, colon, attribute = ref.partition(":")
        if not (module and colon and attribute):
            raise ValueError(f"Lazy references are 'module:attribute', not {ref!r}")
        self.ref = ref
        self._target: Any = None

    def resolve(self) -> Any:
        if self._target is None:
            module, _, attribute = self.ref.partition(":")
            self._target = getattr(importlib.import_module(module), attribute)
        return self._target

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.resolve()(*args, **kwargs)

    def __repr__(self) -> str:
        return f"Lazy({self.ref!r})"
