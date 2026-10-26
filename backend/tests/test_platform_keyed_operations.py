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
    ("automation-reddit", "get_subreddit_posts", "DECODO_AUTH_TOKEN"),
    ("automation-exa", "search", "EXA_API_KEY"),
    ("automation-perplexity", "chat_completion", "PERPLEXITY_API_KEY"),
    ("automation-linkedin", "scrape_user_profiles", "APIFY_API_TOKEN"),
    ("automation-instagram", "scrape_profile_metadata", "APIFY_API_TOKEN"),
]

# Optional without any key at all: nothing to fund.
GENUINELY_FREE = {}


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
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
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


def _search_graph():
    return {"nodes": [{"id": "start", "type": "trigger-run", "config": {}},
                      {"id": "news", "type": "automation-exa",
                       "config": {"operation": "search", "label": "Find the news", "query": "OpenAI"}}],
            "edges": [{"source": "start", "target": "news"}]}


def test_the_builder_hears_which_keys_this_instance_lacks(self_hosted, monkeypatch):
    """A step on a key the instance doesn't hold tells the builder whose key, where the owner adds it, and that a
    step needing none is better, where it looks: the operations it lists and the step it added."""
    from coder.workflow.agentic.commands import execute_query_operations
    from coder.workflow.operation_catalog import credential_status_line
    from coder.workflow.workflow_xml import XmlOp

    line = credential_status_line("automation-exa", "search", {"operation": "search"}, "news")
    assert line.startswith("[credentials needed: exa] This operation runs on Exa, and this instance has no Exa key.")
    assert "Settings → Self-hosted (EXA_API_KEY)" in line and "Prefer a step that needs no key" in line
    assert '<ask node="news" field="credential" />' in line and "search_credentials" not in line
    scrape = credential_status_line("automation-linkedin", "scrape_user_profiles",
                                    {"operation": "scrape_user_profiles"}, "people")
    assert "no Apify key" in scrape and "your own" not in scrape

    [listed] = execute_query_operations([XmlOp(tag="query_operations", attrs={"type": "automation-exa"})])
    assert "On this instance:\n" in listed and "search" in listed.split("On this instance:\n")[1]
    assert "this instance has no Exa key" in listed

    monkeypatch.setenv("EXA_API_KEY", "instance-key")
    assert credential_status_line("automation-exa", "search", {"operation": "search"}, "news") == (
        "[credentials: not required for this operation]")
    [listed] = execute_query_operations([XmlOp(tag="query_operations", attrs={"type": "automation-exa"})])
    assert "On this instance" not in listed


def test_activation_names_the_missing_instance_key(self_hosted, monkeypatch):
    from utils.workflow_readiness import activation_issues

    [issue] = activation_issues(_search_graph(), "start")
    assert issue["code"] == "missing_credentials"
    assert issue["message"] == ("Find the news: This operation runs on Exa, and this instance has no Exa key. Add it "
                                "under Settings → Self-hosted (EXA_API_KEY), or connect your own Exa credential to "
                                "this node.")
    monkeypatch.setenv("EXA_API_KEY", "instance-key")
    assert activation_issues(_search_graph(), "start") == []


def test_hosted_says_nothing_of_instance_keys(hosted):
    from coder.workflow.agentic.commands import execute_query_operations
    from coder.workflow.operation_catalog import credential_status_line
    from coder.workflow.workflow_xml import XmlOp

    assert credential_status_line("automation-exa", "search", {"operation": "search"}, "news") == (
        "[credentials: not required for this operation]")
    [listed] = execute_query_operations([XmlOp(tag="query_operations", attrs={"type": "automation-exa"})])
    assert "On this instance" not in listed
