"""What ``make local`` hands the backend for storage and email.

Uploads are presigned against Supabase Storage's S3 endpoint, which checks the region a URL was signed for: the CLI
serves region "local", and URLs signed for us-east-1 were refused, so every upload failed. The Send Email node and
the run-failure alerts sign their one-click disable links with EMAIL_RELAY_SECRET, which make local never set, so
the first email failed.
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_local.py"
SUPABASE = {"API_URL": "http://127.0.0.1:54321", "DB_URL": "postgresql://local", "JWT_SECRET": "jwt",
            "ANON_KEY": "anon", "SERVICE_ROLE_KEY": "service", "S3_PROTOCOL_ACCESS_KEY_ID": "key",
            "S3_PROTOCOL_ACCESS_KEY_SECRET": "secret", "S3_PROTOCOL_REGION": "local"}


def _run_local(monkeypatch, tmp_path):
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    for name in ("NOCLICK_APP_URL", "NOCLICK_API_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("run_local_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uploads_are_signed_for_the_region_the_cli_serves(monkeypatch, tmp_path):
    module = _run_local(monkeypatch, tmp_path)
    env = module.compose_backend_env(SUPABASE, module.local_secrets())
    assert env["OBJECT_STORAGE_ENDPOINT"] == "http://127.0.0.1:54321/storage/v1/s3"
    assert env["OBJECT_STORAGE_REGION"] == "local"
    assert module.compose_backend_env({**SUPABASE, "S3_PROTOCOL_REGION": "eu-west-2"},
                                      module.local_secrets())["OBJECT_STORAGE_REGION"] == "eu-west-2"


def test_email_links_are_signed_with_a_secret_kept_beside_the_others(monkeypatch, tmp_path):
    module = _run_local(monkeypatch, tmp_path)
    first = module.local_secrets()
    assert len(first["EMAIL_RELAY_SECRET"]) >= 32
    assert module.compose_backend_env(SUPABASE, first)["EMAIL_RELAY_SECRET"] == first["EMAIL_RELAY_SECRET"]
    # Generated once: an old email's disable link keeps working after a restart.
    assert module.local_secrets()["EMAIL_RELAY_SECRET"] == first["EMAIL_RELAY_SECRET"]
    assert f"EMAIL_RELAY_SECRET={first['EMAIL_RELAY_SECRET']}" in (tmp_path / "local.env").read_text()
