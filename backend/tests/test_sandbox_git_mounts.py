"""Tests for the portable provider-requested Git workspace contract.

The self-hosted edition keeps provider configuration, mount-request
normalization, bootstrap-script generation, and AgentNode resolution. Runtime
provisioning belongs to the deployment-specific sandbox implementation and is
tested outside this public suite.
"""

from unittest.mock import AsyncMock, patch

import pytest

from nodes.agent.git_mounts import (
    assign_mount_dirs,
    build_gh_auth_script,
    build_git_mount_script,
    describe_git_mounts,
)
from nodes.agent.node_op_tools import build_provider_output, normalize_sandbox_repos
from nodes.core.base import WorkflowNode
from nodes.github_rest_node import GithubRestNode


def test_github_setup_from_oauth_credential():
    setup = GithubRestNode.get_sandbox_setup(
        repo="acme/widgets",
        branch="dev",
        credential_data={
            "access_token": "gho_x",
            "login": "example-user",
            "email": "developer@example.com",
        },
    )
    assert setup["clone_url"] == "https://github.com/acme/widgets.git"
    assert setup["token"] == "gho_x"
    assert setup["branch"] == "dev"
    assert setup["git_user"] == "example-user"
    assert setup["git_email"] == "developer@example.com"


def test_github_setup_from_pat_credential_uses_fallback_identity():
    setup = GithubRestNode.get_sandbox_setup(
        repo="acme/widgets",
        branch=None,
        credential_data={"personal_access_token": "ghp_y"},
    )
    assert setup["token"] == "ghp_y"
    assert setup["branch"] is None
    assert setup["git_user"] and setup["git_email"]


def test_github_setup_rejects_bad_repo_format():
    for bad in ("widgets", "acme/widgets/extra", "", "acme/wid gets"):
        with pytest.raises(ValueError, match="owner/name"):
            GithubRestNode.get_sandbox_setup(
                repo=bad,
                branch=None,
                credential_data={"access_token": "t"},
            )


def test_github_setup_rejects_tokenless_credential():
    with pytest.raises(ValueError, match="token"):
        GithubRestNode.get_sandbox_setup(
            repo="acme/widgets",
            branch=None,
            credential_data={},
        )


def test_base_hook_returns_none():
    assert (
        WorkflowNode.get_sandbox_setup(
            repo="a/b",
            branch=None,
            credential_data={"access_token": "t"},
        )
        is None
    )


def test_provider_output_includes_sandbox_mounts():
    output = build_provider_output(
        "automation-github-rest",
        {
            "agent_tool_operations": ["create_pull_request"],
            "agent_sandbox_repos": [
                {"repo": " acme/widgets ", "branch": "main"},
                "acme/docs",
            ],
            "credentialIds": {"github": "cred-1"},
        },
    )
    assert output["sandbox_repos"] == [
        {"repo": "acme/widgets", "branch": "main"},
        {"repo": "acme/docs", "branch": ""},
    ]


def test_provider_output_omits_empty_mounts():
    output = build_provider_output(
        "automation-github-rest",
        {"agent_tool_operations": []},
    )
    assert output["sandbox_repos"] == []


def test_normalize_accepts_strings_objects_and_json():
    repos, error = normalize_sandbox_repos(
        '["acme/widgets", {"repo": "acme/docs", "branch": "dev"}]'
    )
    assert error is None
    assert repos == [
        {"repo": "acme/widgets", "branch": ""},
        {"repo": "acme/docs", "branch": "dev"},
    ]
    repos, error = normalize_sandbox_repos("acme/widgets")
    assert error is None
    assert repos == [{"repo": "acme/widgets", "branch": ""}]


def test_normalize_skips_draft_rows_and_dedupes():
    repos, error = normalize_sandbox_repos(
        [
            {"repo": "", "branch": ""},
            {"repo": "acme/widgets", "branch": ""},
            {"repo": "acme/widgets", "branch": "x"},
        ]
    )
    assert error is None
    assert repos == [{"repo": "acme/widgets", "branch": ""}]
    assert normalize_sandbox_repos(None) == ([], None)
    assert normalize_sandbox_repos([]) == ([], None)


def test_normalize_rejects_malformed():
    for bad in (["not-a-repo"], [{"branch": "x"}], {"repo": 1}, 42):
        repos, error = normalize_sandbox_repos(bad)
        assert repos is None and error, bad


_SETUP = {
    "kind": "git_clone",
    "host": "github.com",
    "repo": "acme/widgets",
    "branch": None,
    "clone_url": "https://github.com/acme/widgets.git",
    "token": "tok_secret",
    "git_user": "example-user",
    "git_email": "developer@example.com",
}


def test_mount_script_authenticates_and_clones():
    setup = dict(_SETUP)
    assign_mount_dirs([setup])
    script = build_git_mount_script(setup, "/workspace")
    assert "credential.helper store" in script
    assert "credential.useHttpPath true" in script
    assert "x-access-token:tok_secret@github.com/acme/widgets.git" in script
    assert "git clone https://github.com/acme/widgets.git /workspace/widgets" in script
    assert "if [ ! -d /workspace/widgets/.git ]" in script
    assert "git -C /workspace/widgets config user.name example-user" in script
    assert "--global user.name" not in script
    assert script.startswith("set -e")


def test_mount_script_branch_and_quoting():
    setup = {**_SETUP, "branch": "feat/x", "git_user": "a b'c"}
    assign_mount_dirs([setup])
    script = build_git_mount_script(setup, "/workspace")
    assert "--branch feat/x" in script
    assert "'a b'\"'\"'c'" in script


def test_assign_mount_dirs_dedupes_collisions():
    setups = [
        {**_SETUP, "repo": "acme/widgets"},
        {**_SETUP, "repo": "other/widgets"},
        {**_SETUP, "repo": "acme/widgets"},
    ]
    assign_mount_dirs(setups)
    assert [setup["dir"] for setup in setups] == [
        "widgets",
        "other-widgets",
        "acme-widgets",
    ]


def test_gh_auth_script_writes_hosts_yml():
    script = build_gh_auth_script([dict(_SETUP)])
    assert "mkdir -p ~/.config/gh" in script
    assert "github.com:" in script
    assert "'    oauth_token: tok_secret'" in script
    assert "'    user: example-user'" in script
    assert "> ~/.config/gh/hosts.yml" in script


def test_gh_auth_first_credential_per_host_wins():
    setups = [
        dict(_SETUP),
        {
            **_SETUP,
            "repo": "other/thing",
            "token": "tok_other",
            "git_user": "other",
        },
    ]
    script = build_gh_auth_script(setups)
    assert "tok_secret" in script and "tok_other" not in script
    assert script.count("github.com:") == 1


def test_describe_git_mounts_states_push_contract():
    note = describe_git_mounts([dict(_SETUP)], "/workspace")
    assert "acme/widgets" in note and "/workspace/widgets" in note
    assert "push" in note and "github__create_pull_request" in note
    assert "gh pr create" in note
    assert describe_git_mounts([], "/workspace") == ""


def test_describe_git_mounts_lists_multiple_repos():
    setups = [
        {**_SETUP, "repo": "acme/widgets"},
        {**_SETUP, "repo": "other/widgets"},
    ]
    note = describe_git_mounts(setups, "/workspace")
    assert "/workspace/widgets" in note
    assert "/workspace/other-widgets" in note


def _bare_agent():
    agent_class = __import__("nodes.agent_node", fromlist=["AgentNode"]).AgentNode
    agent = object.__new__(agent_class)
    agent.user_id = "user-1"
    agent.organization_id = None
    agent.workflow_id = "wf-1"
    agent.node_id = "agent_1"
    return agent


@pytest.mark.asyncio
async def test_resolve_sandbox_mounts_resolves_and_freshens():
    agent = _bare_agent()
    mounts = [
        {
            "node_id": "gh_1",
            "node_type": "automation-github-rest",
            "repo": "acme/widgets",
            "branch": None,
            "credential_id": "cred-1",
        }
    ]
    credential = {
        "access_token": "tok",
        "login": "example-user",
        "email": "developer@example.com",
    }

    with (
        patch(
            "nodes.core.run_op.resolve_operation_credential",
            new=AsyncMock(return_value=credential),
        ) as resolve,
        patch.object(
            GithubRestNode,
            "freshen_credential",
            new=AsyncMock(return_value=credential),
        ) as freshen,
    ):
        setups = await agent._resolve_sandbox_mounts(mounts, "user-1")

    assert len(setups) == 1
    assert setups[0]["repo"] == "acme/widgets"
    assert setups[0]["token"] == "tok"
    assert setups[0]["provider_node_id"] == "gh_1"
    resolve.assert_awaited_once()
    freshen.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_sandbox_mounts_fails_loudly_without_credential():
    agent = _bare_agent()
    mounts = [
        {
            "node_id": "gh_1",
            "node_type": "automation-github-rest",
            "repo": "acme/widgets",
            "branch": None,
            "credential_id": None,
        }
    ]
    with pytest.raises(ValueError, match="credential"):
        await agent._resolve_sandbox_mounts(mounts, "user-1")


@pytest.mark.asyncio
async def test_resolve_sandbox_mounts_rejects_non_mount_provider():
    agent = _bare_agent()
    mounts = [
        {
            "node_id": "lin_1",
            "node_type": "automation-linear",
            "repo": "acme/widgets",
            "branch": None,
            "credential_id": "cred-1",
        }
    ]
    with patch(
        "nodes.core.run_op.resolve_operation_credential",
        new=AsyncMock(return_value={"access_token": "t"}),
    ):
        with pytest.raises(ValueError, match="does not support sandbox mounts"):
            await agent._resolve_sandbox_mounts(mounts, "user-1")


@pytest.mark.asyncio
async def test_resolve_sandbox_mounts_empty_is_noop():
    agent = _bare_agent()
    assert await agent._resolve_sandbox_mounts([], "user-1") == []
