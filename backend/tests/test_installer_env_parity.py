"""The three installers must produce the same set of settings.

`docker compose up` fails loudly when a required variable is missing — the
compose file marks them `:?` — but only at the moment someone runs it, which is
the moment a first install is meant to succeed. There are three ways in
(`scripts/noclick-setup.sh`, `install.sh` which calls it, and `npx noclick`,
which generates the file itself so it can also run on Windows), and a setting
added to one and not the others is invisible until then.

Compares the KEYS, not the values: two installs must not share a secret.
"""

import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CLI = REPO / "sdk" / "typescript" / "bin" / "noclick.mjs"
SETUP = REPO / "scripts" / "noclick-setup.sh"


def _keys(text: str) -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    }


def _shell_env(tmp_path: pathlib.Path) -> set[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    env_file = tmp_path / "shell.env"
    subprocess.run(
        ["sh", str(SETUP)],
        cwd=REPO,
        env={"PATH": os.environ["PATH"], "NOCLICK_ENV_FILE": str(env_file)},
        check=True,
        capture_output=True,
    )
    return _keys(env_file.read_text())


def _cli_env(tmp_path: pathlib.Path) -> set[str]:
    """Drive the CLI's generator without Docker: `where` is a pure command, so
    the generator is exercised through a small harness that imports nothing."""
    workdir = tmp_path / "cli-install"
    workdir.mkdir(parents=True)
    # The CLI writes .env beside a checkout; a docker-compose.yml is all it
    # needs to consider the directory an install.
    (workdir / "docker-compose.yml").write_text("services: {}\n")
    (workdir / ".git").mkdir()
    # ensureEnv is not exported: run the real entry point with nothing on PATH,
    # which writes .env and then fails on the missing Docker — exactly the order
    # a first install depends on.
    subprocess.run(
        ["node", str(CLI), "start"],
        cwd=workdir,
        # node must be reachable; docker must not be, so the run stops right
        # after .env is written.
        env={
            "PATH": str(pathlib.Path(shutil.which("node")).parent),
            "NOCLICK_DIR": str(workdir),
            "HOME": str(tmp_path),
        },
        capture_output=True,
    )
    env_file = workdir / ".env"
    assert env_file.exists(), "the CLI did not write .env before needing Docker"
    return _keys(env_file.read_text())


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_shell_and_cli_installers_agree(tmp_path):
    shell = _shell_env(tmp_path / "a")
    cli = _cli_env(tmp_path / "b")
    assert shell == cli, (
        "the shell installer and `npx noclick` disagree about the settings:\n"
        f"  only in scripts/noclick-setup.sh: {sorted(shell - cli)}\n"
        f"  only in npx noclick:              {sorted(cli - shell)}"
    )


def test_every_required_compose_variable_is_generated(tmp_path):
    """`:?` in the compose file means "refuse to start without this"."""
    compose = (REPO / "docker-compose.yml").read_text()
    required = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?", compose))
    assert required, "no required variables found — has the compose file changed shape?"
    missing = required - _shell_env(tmp_path / "c")
    assert not missing, f"compose requires variables no installer generates: {sorted(missing)}"
