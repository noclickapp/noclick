"""The CLI installer authenticates its GitHub clone without exposing the token.

Anonymous git-over-HTTPS from shared runners gets HTTP 429 (2026-09-08, both
native-agent-protocols jobs on the open repo, twice). The token must lift that
without ever reaching argv, since a failed clone prints its command.
"""
import base64
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

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


def test_cached_checkout_is_reused_without_a_clone(tmp_path: Path):
    dest = tmp_path / "hermes"
    (dest / ".git").mkdir(parents=True)
    with patch("tests.fixtures.install_clis.subprocess.run") as run:
        clone_hermes("v1.2.3", dest, None)
    run.assert_not_called()


def test_cold_clone_retries_with_backoff_then_succeeds(tmp_path: Path):
    dest = tmp_path / "hermes"
    calls = []

    def flaky(args, **kwargs):
        calls.append(args)
        if len(calls) < 3:
            dest.mkdir(exist_ok=True)  # a partial checkout git left behind
            raise subprocess.CalledProcessError(128, args)

    waits = []
    with patch("tests.fixtures.install_clis.subprocess.run", side_effect=flaky):
        clone_hermes("v1.2.3", dest, None, attempts=3, sleep=waits.append)
    assert len(calls) == 3
    assert waits == [20, 40]
    assert not dest.exists()  # the partial dir never survives into the next attempt


def test_cold_clone_gives_up_after_the_last_attempt(tmp_path: Path):
    failing = subprocess.CalledProcessError(128, ["git"])
    with patch("tests.fixtures.install_clis.subprocess.run", side_effect=failing) as run:
        with pytest.raises(subprocess.CalledProcessError):
            clone_hermes("v1.2.3", tmp_path / "hermes", None, attempts=3, sleep=lambda s: None)
    assert run.call_count == 3


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
