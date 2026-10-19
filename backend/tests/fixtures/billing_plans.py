"""Which plans a test's accounts bill on.

Every account bills on Free/Member: usage at its vendor's cost, one dollar
balance and the plan's fee on funds added (the ``free_member`` and
``auto_topup`` rollouts are open to everyone). The old plans' code (Plus/Pro,
credits, markup, count caps, top-up offers) stays for an account those rollouts
are closed to again. A test of either names the plans it means, so it never
depends on what utils/feature_gates.py ships with: ``on_the_old_plans`` closes
both rollouts (only staff, and accounts a test lets in by name, are in),
``on_free_member`` opens them. Import the fixture into the test module.
"""

import pytest

from utils import feature_gates

ROLLOUTS = ("free_member", "auto_topup")


def bill_on_the_old_plans(monkeypatch) -> None:
    """Close Free/Member and auto top-up again, as they were before they opened to everyone."""
    for feature in ROLLOUTS:
        monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, feature, feature_gates.INTERNAL)
        monkeypatch.setitem(feature_gates.FEATURE_ALLOWLIST, feature, set())


def bill_on_free_member(monkeypatch) -> None:
    """Open Free/Member and auto top-up to every account."""
    for feature in ROLLOUTS:
        monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, feature, feature_gates.EVERYONE)


@pytest.fixture
def on_the_old_plans(monkeypatch):
    bill_on_the_old_plans(monkeypatch)


@pytest.fixture
def on_free_member(monkeypatch):
    bill_on_free_member(monkeypatch)
