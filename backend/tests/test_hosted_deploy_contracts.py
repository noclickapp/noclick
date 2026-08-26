"""Static contracts for the public hosted-deployment entry points."""

from __future__ import annotations

import html
import re
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml


REPO = Path(__file__).resolve().parents[2]
SUPABASE_INPUTS = {
    "POSTGRES_URL",
    "POSTGRES_POOLER_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_JWK_URL",
}
INSTANCE_SECRETS = {
    "CREDENTIALS_ENCRYPTION_KEY",
    "WORKFLOW_JWT_SECRET",
    "CRON_SCHEDULER_SECRET",
    "SESSION_SECRET",
}
REQUIRED_INPUTS = SUPABASE_INPUTS | INSTANCE_SECRETS


def test_render_and_digitalocean_prompt_for_the_required_inputs() -> None:
    render = yaml.safe_load((REPO / "render.yaml").read_text())
    render_keys = {item["key"] for item in render["services"][0]["envVars"]}
    assert REQUIRED_INPUTS <= render_keys
    assert render["services"][0]["numInstances"] == 1
    assert render["services"][0]["preDeployCommand"].endswith("docker/bootstrap.py")

    digitalocean = yaml.safe_load((REPO / ".do" / "deploy.template.yaml").read_text())[
        "spec"
    ]["services"][0]
    digitalocean_keys = {item["key"] for item in digitalocean["envs"]}
    assert REQUIRED_INPUTS <= digitalocean_keys
    assert digitalocean["instance_count"] == 1
    assert digitalocean["health_check"]["http_path"] == "/health"
    assert digitalocean["dockerfile_path"] == "docker/single-origin.Dockerfile"


def test_fly_keeps_the_scheduler_alive_and_bootstraps_before_release() -> None:
    with (REPO / "fly.toml").open("rb") as stream:
        fly = tomllib.load(stream)
    assert fly["build"]["dockerfile"] == "docker/single-origin.Dockerfile"
    assert fly["deploy"]["release_command"].endswith("docker/bootstrap.py")
    assert fly["http_service"]["auto_stop_machines"] == "off"
    assert fly["http_service"]["checks"][0]["path"] == "/health"


def test_railway_button_uses_the_published_template() -> None:
    readme = (REPO / "README.md").read_text()
    match = re.search(r'<a href="([^"]+)"><img alt="Deploy on Railway"', readme)
    assert match, "README is missing its Deploy on Railway button"
    url = html.unescape(match.group(1))
    parsed = urlparse(url)
    assert parsed.netloc == "railway.com"
    assert parsed.path == "/new/template/noclick"
    assert parse_qs(parsed.query)["utm_campaign"] == ["noclick"]
