"""``make local`` takes the addresses people off the machine reach the app and the API at (NOCLICK_APP_URL and
NOCLICK_API_URL, as the Compose stack names them). It used to set the app's address to the dev server's own, over
whatever was configured, so a link the assistant texted to a phone read http://127.0.0.1:…/credential/provide/…"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_local.py"
SUPABASE = {"API_URL": "http://127.0.0.1:54321", "DB_URL": "postgresql://local", "JWT_SECRET": "jwt",
            "ANON_KEY": "anon", "SERVICE_ROLE_KEY": "service"}
SECRETS = {"WORKFLOW_JWT_SECRET": "w", "CRON_SCHEDULER_SECRET": "c", "SESSION_SECRET": "s",
           "CREDENTIALS_ENCRYPTION_KEY": "k"}


def _run_local(monkeypatch, **env):
    for name in ("NOCLICK_APP_URL", "NOCLICK_API_URL", "NOCLICK_BACKEND_PORT", "NOCLICK_FRONTEND_PORT",
                 "SOCKET_CORS_ORIGINS", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("run_local_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compose_backend_env(SUPABASE, SECRETS), module.compose_frontend_env(SUPABASE, SECRETS)


def test_the_public_addresses_build_every_link_and_the_browser_reaches_the_api_there(monkeypatch):
    backend, frontend = _run_local(monkeypatch, NOCLICK_APP_URL="https://app.example.org/",
                                   NOCLICK_API_URL="https://api.example.org", NOCLICK_FRONTEND_PORT="3000")
    assert backend["FRONTEND_URL"] == "https://app.example.org"
    assert backend["PUBLIC_API_URL"] == backend["WEBHOOK_URL_BASE"] == backend["MCP_BASE_URL"] == "https://api.example.org"
    # The dev server's own origin still passes CORS, beside the public one FRONTEND_URL adds.
    assert backend["SOCKET_CORS_ORIGINS"] == "http://127.0.0.1:3000"
    # A page opened from a texted link calls the API from that phone.
    assert frontend["VITE_PUBLIC_URL"] == frontend["PUBLIC_URL"] == "https://app.example.org"
    assert frontend["VITE_API_URL"] == "https://api.example.org"
    assert frontend["VITE_RELAY_URL"] == "wss://api.example.org/relay"


def test_unset_they_are_this_machines_own_and_other_cors_origins_stay(monkeypatch):
    backend, frontend = _run_local(monkeypatch, SOCKET_CORS_ORIGINS="https://extra.example.org")
    assert backend["FRONTEND_URL"] == frontend["VITE_PUBLIC_URL"] == "http://127.0.0.1:5173"
    assert backend["PUBLIC_API_URL"] == frontend["VITE_API_URL"] == "http://127.0.0.1:8000"
    assert frontend["VITE_RELAY_URL"] == "ws://127.0.0.1:8000/relay"
    assert backend["SOCKET_CORS_ORIGINS"] == "https://extra.example.org,http://127.0.0.1:5173"
