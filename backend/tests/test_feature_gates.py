"""A feature is INTERNAL (staff) or EVERYONE — and, in between, open to the
accounts let in by name: a pilot customer is never put on the staff list."""

import pytest

from utils import feature_gates
from utils.feature_gates import FeatureNotAvailable, allow_accounts, is_feature_enabled, require_feature


@pytest.fixture(autouse=True)
def _own_rollout(monkeypatch):
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "pilot_feature", feature_gates.INTERNAL)
    monkeypatch.setitem(feature_gates.FEATURE_ALLOWLIST, "pilot_feature", set())
    monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: email == "staff@noclick.com")


def test_an_internal_feature_is_staff_only_until_an_account_is_let_in():
    assert is_feature_enabled("pilot_feature", email="staff@noclick.com")
    assert not is_feature_enabled("pilot_feature", email="customer@example.com")
    assert not is_feature_enabled("pilot_feature", email=None)
    with pytest.raises(FeatureNotAvailable):
        require_feature("pilot_feature", email="customer@example.com")

    allow_accounts("pilot_feature", ["  Customer@Example.com ", ""])
    assert is_feature_enabled("pilot_feature", email="customer@example.com")
    assert is_feature_enabled("pilot_feature", email="CUSTOMER@example.com")
    assert not is_feature_enabled("pilot_feature", email="other@example.com")  # one account, not everyone
    require_feature("pilot_feature", email="customer@example.com")


def test_a_pilot_list_for_an_unknown_feature_is_a_typo():
    with pytest.raises(KeyError):
        allow_accounts("phone_numbrs", ["customer@example.com"])
