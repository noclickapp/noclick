"""Instance OAuth apps: precedence, secrecy, and the env bookkeeping.

The subtle one is `_TAG_PREFIX`. Values applied from the database are tagged with
an env var named `_NC_INSTANCE_OAUTH_<PROVIDER>_CLIENT_ID` — which itself ends in
`_CLIENT_ID`, so the scan for environment-configured providers matched its own
bookkeeping and reported a provider called "_nc_instance_oauth_linear" in the UI.
"""

import os

import pytest

from utils import instance_oauth


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(os.environ):
        if name.endswith(("_CLIENT_ID", "_CLIENT_SECRET")) or name.startswith(instance_oauth._TAG_PREFIX):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NOCLICK_LOCAL", "1")


class FakePool:
    """Just enough asyncpg surface for these functions."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    async def fetch(self, *_args, **_kwargs):
        return self.rows


def test_env_report_ignores_its_own_bookkeeping(monkeypatch):
    monkeypatch.setenv("LINEAR_CLIENT_ID", "from-db")
    monkeypatch.setenv(f"{instance_oauth._TAG_PREFIX}LINEAR_CLIENT_ID", "1")

    assert instance_oauth.env_configured_providers() == [], (
        "a database-applied value must not be reported as environment-configured, "
        "and the tag variable must never be read as a provider of its own"
    )


def test_env_report_names_real_environment_providers(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "really-from-the-environment")
    assert instance_oauth.env_configured_providers() == ["slack"]


@pytest.mark.asyncio
async def test_apply_never_overwrites_a_real_env_var(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "from-the-environment")
    pool = FakePool([{"provider": "slack", "client_id": "from-db", "client_secret_encrypted": None}])

    await instance_oauth.apply_to_environment(pool)

    assert os.environ["SLACK_CLIENT_ID"] == "from-the-environment"
    assert f"{instance_oauth._TAG_PREFIX}SLACK_CLIENT_ID" not in os.environ


@pytest.mark.asyncio
async def test_apply_sets_and_tags_an_unset_var(monkeypatch):
    pool = FakePool([{"provider": "linear", "client_id": "lin-123", "client_secret_encrypted": None}])

    applied = await instance_oauth.apply_to_environment(pool)

    assert applied == 1
    assert os.environ["LINEAR_CLIENT_ID"] == "lin-123"
    assert os.environ[f"{instance_oauth._TAG_PREFIX}LINEAR_CLIENT_ID"] == "1"


@pytest.mark.asyncio
async def test_delete_reclaims_only_what_it_applied(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "from-the-environment")
    monkeypatch.setenv("LINEAR_CLIENT_ID", "lin-123")
    monkeypatch.setenv(f"{instance_oauth._TAG_PREFIX}LINEAR_CLIENT_ID", "1")

    class Deleter(FakePool):
        async def execute(self, *_a, **_k):
            return "DELETE 1"

    await instance_oauth.delete_app(Deleter(), "linear")
    await instance_oauth.delete_app(Deleter(), "slack")

    assert "LINEAR_CLIENT_ID" not in os.environ, "a value we applied should be reclaimed"
    assert os.environ["SLACK_CLIENT_ID"] == "from-the-environment", (
        "an operator's own environment variable must survive deleting the stored row"
    )


@pytest.mark.asyncio
async def test_apply_is_inert_on_hosted(monkeypatch):
    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
    pool = FakePool([{"provider": "linear", "client_id": "lin-123", "client_secret_encrypted": None}])

    assert await instance_oauth.apply_to_environment(pool) == 0
    assert "LINEAR_CLIENT_ID" not in os.environ
