"""The installer must generate every setting the compose file requires.

`docker compose up` fails loudly when a required variable is missing — the
compose file marks them `:?` — but only at the moment someone runs it, which is
the moment a first install is meant to succeed. `scripts/noclick-setup.sh`
(which `install.sh` calls) writes the `.env`, so a variable the compose file
starts requiring and the script does not generate is invisible until then.
"""

import os
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
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


def test_every_required_compose_variable_is_generated(tmp_path):
    """`:?` in the compose file means "refuse to start without this"."""
    compose = (REPO / "docker-compose.yml").read_text()
    required = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?", compose))
    assert required, "no required variables found — has the compose file changed shape?"
    missing = required - _shell_env(tmp_path / "c")
    assert not missing, f"compose requires variables no installer generates: {sorted(missing)}"
