"""Credential-optional operations mean two things, and only one of them holds
on a self-hosted instance.

In the cloud, ``x-credentials-optional`` on Exa search or a LinkedIn scrape
means NoClick's own key pays. A self-hosted instance holds no such key, so the
same marker made the credential panel, the builder and the validation badge
all say "ready" for operations that failed on their first run. The verdict now
comes from one seam (nodes/core/platform_billing.py) that every consumer asks.
"""

import os

import pytest

from coder.workflow.operation_catalog import is_operation_credentials_optional
from nodes.agent.node_op_tools import _iter_operation_defs, allowlist_requires_credentials
from nodes.core.platform_billing import PLATFORM_KEY_MARKER, require_platform_key
from nodes.core.registry import NODE_REGISTRY

PLATFORM_KEYED = [
    ("automation-exa", "search", "EXA_API_KEY"),
    ("automation-perplexity", "chat_completion", "PERPLEXITY_API_KEY"),
    ("automation-linkedin", "scrape_user_profiles", "APIFY_API_TOKEN"),
    ("automation-instagram", "scrape_profile_metadata", "APIFY_API_TOKEN"),
]

# Optional without any key at all: nothing to fund.
GENUINELY_FREE = {"automation-reddit": {"get_subreddit_posts"}}


@pytest.fixture
def no_platform_keys(monkeypatch):
    for _, _, env in PLATFORM_KEYED:
        monkeypatch.delenv(env, raising=False)


@pytest.fixture
def self_hosted(monkeypatch, no_platform_keys):
    monkeypatch.setenv("NOCLICK_LOCAL", "1")


@pytest.fixture
def hosted(monkeypatch, no_platform_keys):
    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)


@pytest.mark.parametrize("node_type,operation,env", PLATFORM_KEYED)
def test_hosted_runs_platform_keyed_operations_without_a_credential(hosted, node_type, operation, env):
    assert is_operation_credentials_optional(node_type, operation) is True
    assert allowlist_requires_credentials(node_type, [operation]) is False


@pytest.mark.parametrize("node_type,operation,env", PLATFORM_KEYED)
def test_self_hosted_requires_a_credential_until_the_instance_holds_the_key(self_hosted, monkeypatch, node_type, operation, env):
    assert is_operation_credentials_optional(node_type, operation) is False
    assert allowlist_requires_credentials(node_type, [operation]) is True
    monkeypatch.setenv(env, "instance-key")
    assert is_operation_credentials_optional(node_type, operation) is True
    assert allowlist_requires_credentials(node_type, [operation]) is False


def test_a_genuinely_free_operation_stays_optional_everywhere(self_hosted):
    assert is_operation_credentials_optional("automation-reddit", "get_subreddit_posts") is True
    assert allowlist_requires_credentials("automation-reddit", ["get_subreddit_posts"]) is False


def test_every_credential_optional_operation_declares_who_pays():
    """Ratchet: a new platform-funded operation cannot ship unmarked."""
    unmarked = []
    for node_type, node_class in NODE_REGISTRY.items():
        for entry in _iter_operation_defs(node_class):
            member = entry["member"]
            if member.get("x-credentials-optional") is not True:
                continue
            if PLATFORM_KEY_MARKER in member or entry["operation"] in GENUINELY_FREE.get(node_type, set()):
                continue
            unmarked.append((node_type, entry["operation"]))
    assert unmarked == [], (
        "credential-optional operations must declare the platform key that pays "
        "(platform_keyed_operation) or be listed as genuinely free: " + repr(unmarked)
    )


def test_a_missing_key_names_the_fix_for_each_edition(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    with pytest.raises(RuntimeError) as local:
        require_platform_key("EXA_API_KEY", "Exa", byok=True)
    assert "Settings → Self-hosted (EXA_API_KEY)" in str(local.value)
    assert "connect your own Exa credential" in str(local.value)
    with pytest.raises(RuntimeError) as local_only:
        require_platform_key("APIFY_API_TOKEN", "Apify", byok=False)
    assert "credential" not in str(local_only.value)

    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
    with pytest.raises(RuntimeError) as hosted:
        require_platform_key("EXA_API_KEY", "Exa", byok=True)
    assert str(hosted.value) == "EXA_API_KEY is not configured on the server. Add your own Exa API key to run this operation."

    monkeypatch.setenv("EXA_API_KEY", "k")
    assert require_platform_key("EXA_API_KEY", "Exa", byok=True) == "k"
