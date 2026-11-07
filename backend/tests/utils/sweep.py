"""Check many cases in one test, naming every case that fails.

A sweep parametrized over every operation or every node class pays pytest's
per-test cost (an event loop, the autouse fixtures, a report line) once per
case, which on CI came to far more than the checks themselves. One test that
runs each case and collects every failure checks the same things and still
says which cases broke.
"""

import inspect
from typing import Any, Callable, Iterable


async def check_each(cases: Iterable[Any], check: Callable[[Any], Any], *, name: Callable[[Any], str] = str) -> None:
    """Run ``check`` on every case (awaiting it when it is async); fail naming each case that raised."""
    cases = list(cases)
    failures = []
    for case in cases:
        try:
            result = check(case)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # every failing case, not only the first
            failures.append(f"{name(case)}: {type(error).__name__}: {error}")
    assert not failures, f"{len(failures)} of {len(cases)} cases failed:\n" + "\n".join(failures)
