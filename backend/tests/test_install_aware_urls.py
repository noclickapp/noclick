import json
import os
import subprocess
import sys

import pytest


WEBHOOK_ID = "1b1f56d7-9463-42ce-83e6-f599eb57c623"






def test_self_host_webhook_url_never_falls_back_to_hosted_relay(monkeypatch):
    from utils import webhook_tunnel

    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    for name in (
        "PUBLIC_WEBHOOK_URL",
        "WEBHOOK_URL_BASE",
        "APP_WEBHOOK_BASE_URL",
        "PUBLIC_API_URL",
        "WEBHOOK_DOMAIN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="PUBLIC_WEBHOOK_URL"):
        webhook_tunnel.get_webhook_url(WEBHOOK_ID)


def test_email_urls_use_install_frontend():
    env = os.environ.copy()
    env.update({
        "NOCLICK_LOCAL": "1",
        "FRONTEND_URL": "https://automation.example.test/",
        "RESEND_API_KEY": "",
    })
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from utils.email import FRONTEND_URL; "
            "from utils.email_unsubscribe import DISABLE_LINK_BASE; "
            "print(json.dumps([FRONTEND_URL, DISABLE_LINK_BASE]))",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [
        "https://automation.example.test",
        "https://automation.example.test",
    ]


