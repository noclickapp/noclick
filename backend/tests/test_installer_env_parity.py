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


def _values(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in text.splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    )


def _shell_env(tmp_path: pathlib.Path, existing: str = "") -> dict[str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    env_file = tmp_path / "shell.env"
    env_file.write_text(existing)
    subprocess.run(
        ["sh", str(SETUP)],
        cwd=REPO,
        env={"PATH": os.environ["PATH"], "NOCLICK_ENV_FILE": str(env_file)},
        check=True,
        capture_output=True,
    )
    return _values(env_file.read_text())


def test_every_required_compose_variable_is_generated(tmp_path):
    """`:?` in the compose file means "refuse to start without this"."""
    compose = (REPO / "docker-compose.yml").read_text()
    required = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?", compose))
    assert required, "no required variables found — has the compose file changed shape?"
    missing = required - _shell_env(tmp_path / "c").keys()
    assert not missing, f"compose requires variables no installer generates: {sorted(missing)}"


MINIO_KEYS = {"OBJECT_STORAGE_ACCESS_KEY_ID", "OBJECT_STORAGE_SECRET_ACCESS_KEY", "NOCLICK_STORAGE_PORT"}


def test_an_upgraded_install_keeps_minio_credentials_and_a_fresh_one_gets_none(tmp_path):
    """Releases up to v0.4.1 ran MinIO, and on upgrade bootstrap copies its
    files onto the backend's volume through MinIO's credentials. The script
    rewrites .env whole, so it must carry them over, and never mint them for a
    fresh install, which has no MinIO."""
    assert not MINIO_KEYS & _shell_env(tmp_path / "fresh").keys()

    upgraded = _shell_env(
        tmp_path / "upgraded",
        "OBJECT_STORAGE_ACCESS_KEY_ID=noclick-old\n"
        "OBJECT_STORAGE_SECRET_ACCESS_KEY=old-secret\n"
        "NOCLICK_STORAGE_PORT=9100\n"
        "NOCLICK_STORAGE_URL=http://storage.localhost:9100\n",
    )
    assert {key: upgraded[key] for key in MINIO_KEYS} == {
        "OBJECT_STORAGE_ACCESS_KEY_ID": "noclick-old",
        "OBJECT_STORAGE_SECRET_ACCESS_KEY": "old-secret",
        "NOCLICK_STORAGE_PORT": "9100",
    }
    assert "NOCLICK_STORAGE_URL" not in upgraded

    compose = (REPO / "docker-compose.yml").read_text()
    for wiring in (
        "LEGACY_MINIO_URL: http://storage:${NOCLICK_STORAGE_PORT:-9000}",
        "LEGACY_MINIO_ACCESS_KEY_ID: ${OBJECT_STORAGE_ACCESS_KEY_ID:-}",
        "LEGACY_MINIO_SECRET_ACCESS_KEY: ${OBJECT_STORAGE_SECRET_ACCESS_KEY:-}",
    ):
        assert wiring in compose
