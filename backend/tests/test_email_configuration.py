"""Self-hosted transactional email fails loudly on half-configuration."""

import os
from pathlib import Path
import subprocess
import sys


def test_resend_key_without_sender_stops_startup():
    backend = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "NOCLICK_LOCAL": "1",
        "FRONTEND_URL": "https://app.example.test",
        "RESEND_API_KEY": "re_test_key",
    }
    env.pop("FROM_EMAIL", None)
    result = subprocess.run(
        [sys.executable, "-c", "import utils.email"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "RESEND_API_KEY is set but FROM_EMAIL is not" in result.stderr
