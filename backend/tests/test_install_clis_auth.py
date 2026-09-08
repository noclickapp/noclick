"""The CLI installer authenticates its GitHub clone without exposing the token.

Anonymous git-over-HTTPS from shared runners gets HTTP 429 (2026-09-08, both
native-agent-protocols jobs on the open repo, twice). The token must lift that
without ever reaching argv, since a failed clone prints its command.
"""
import base64
from pathlib import Path
from unittest.mock import patch

from tests.fixtures.install_clis import HERMES_REPO, clone_hermes, github_git_env


def test_no_token_means_plain_environment():
    assert github_git_env(None) == {}
    assert github_git_env("") == {}


def test_token_becomes_a_basic_auth_header_for_github_only():
    env = github_git_env("ghs_secret")
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    scheme, encoded = env["GIT_CONFIG_VALUE_0"].split(" ", 2)[1:]
    assert scheme == "basic"
    assert base64.b64decode(encoded) == b"x-access-token:ghs_secret"
    assert "ghs_secret" not in " ".join(env.values())


def test_clone_keeps_the_token_out_of_argv(tmp_path: Path):
    with patch("tests.fixtures.install_clis.subprocess.run") as run:
        clone_hermes("v1.2.3", tmp_path / "hermes", "ghs_secret")
    (args,), kwargs = run.call_args
    assert args[:2] == ["git", "clone"]
    assert "v1.2.3" in args and HERMES_REPO in args
    assert "ghs_secret" not in " ".join(args)
    assert kwargs["check"] is True
    assert kwargs["env"]["GIT_CONFIG_COUNT"] == "1"
    assert "ghs_secret" not in " ".join(kwargs["env"].values())
