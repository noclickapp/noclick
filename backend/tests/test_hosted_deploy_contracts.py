"""Static contracts for the public hosted-deployment entry points.

The property under test is that there is nothing to fill in. A deploy button
that opens a form with an empty required field is a research task wearing a
button's clothes — which is what these were: ten values, six of them from a
Supabase project the operator had to create first.

The image needs one thing, a database, and every provider here creates it.
"""

from __future__ import annotations

import html
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml


REPO = Path(__file__).resolve().parents[2]

# Supplied by the platform, never by a person: a reference to the database it
# just created, or a value it generated.
def _is_supplied(variable: dict) -> bool:
    return bool(
        "value" in variable
        or variable.get("generateValue")
        or "fromDatabase" in variable
    )


def test_render_creates_its_own_database_and_generates_its_own_secrets() -> None:
    render = yaml.safe_load((REPO / "render.yaml").read_text())
    service = render["services"][0]

    assert render["databases"], "Render must provision the database itself"
    for variable in service["envVars"]:
        # `sync: false` is the prompt: Render asks for it at blueprint creation.
        assert variable.get("sync") is not False, f"{variable['key']} prompts"
        assert _is_supplied(variable), f"{variable['key']} has no value or generator"

    assert {"POSTGRES_URL", "CREDENTIALS_ENCRYPTION_KEY"} <= {
        item["key"] for item in service["envVars"]
    }
    # The scheduler and the realtime relay are in-process, so one instance, and
    # agent workspaces need somewhere to live across deploys.
    assert service["numInstances"] == 1
    assert service["healthCheckPath"] == "/health"
    assert service["disk"]["mountPath"] == "/var/lib/noclick"
    # The auth server that migrates first runs inside the image, so there is
    # nothing a release phase could usefully run ahead of it.
    assert "preDeployCommand" not in service


def test_digitalocean_binds_a_database_and_asks_for_nothing_else() -> None:
    spec = yaml.safe_load((REPO / ".do" / "deploy.template.yaml").read_text())["spec"]
    service = spec["services"][0]

    assert spec["databases"], "App Platform must provision the database itself"
    # It can neither generate a secret nor mount a disk, so the database binding
    # is the whole configuration and the instance mints its own keys on boot.
    assert [env["key"] for env in service["envs"]] == ["POSTGRES_URL"]
    assert service["envs"][0]["value"] == "${db.DATABASE_URL}"
    assert "REPLACE_WITH" not in (REPO / ".do" / "deploy.template.yaml").read_text()

    assert service["instance_count"] == 1
    assert service["health_check"]["http_path"] == "/health"
    assert service["image"]["repository"] == "noclick"


def test_the_railway_template_fills_in_every_field_it_shows() -> None:
    template = json.loads((REPO / "railway.template.json").read_text())
    services = list(template["services"].values())

    assert any(service["name"] == "Postgres" for service in services), (
        "the template must bring its own database"
    )
    for service in services:
        for name, variable in service["variables"].items():
            assert variable.get("defaultValue"), (
                f"{service['name']}.{name} renders as an empty required field"
            )
            assert variable.get("description"), f"{service['name']}.{name} is unexplained"

    application = next(service for service in services if service["name"] == "noclick")
    assert (
        application["variables"]["POSTGRES_URL"]["defaultValue"]
        == "${{Postgres.DATABASE_URL}}"
    )
    # The one value worth keeping a copy of says so where the operator sees it.
    assert "somewhere safe" in (
        application["variables"]["CREDENTIALS_ENCRYPTION_KEY"]["description"]
    )
    assert list(application["volumeMounts"].values())[0]["mountPath"] == "/var/lib/noclick"


def test_fly_needs_only_a_database_and_keeps_the_scheduler_alive() -> None:
    with (REPO / "fly.toml").open("rb") as stream:
        fly = tomllib.load(stream)

    assert fly["build"]["dockerfile"] == "docker/single-origin.Dockerfile"
    # No release command: the auth server that has to migrate first runs inside
    # the image, so the instance prepares its own database as it starts.
    assert "deploy" not in fly
    assert fly["http_service"]["auto_stop_machines"] == "off"
    assert fly["http_service"]["checks"][0]["path"] == "/health"


def test_the_image_serves_the_auth_api_it_no_longer_asks_for() -> None:
    """The embedded auth stack is what removed the Supabase project from the
    deploy forms: GoTrue and PostgREST ship in the image, and nginx serves them
    on the paths supabase-js addresses."""
    dockerfile = (REPO / "docker" / "single-origin.Dockerfile").read_text()
    entrypoint = (REPO / "docker" / "single-origin-entrypoint.sh").read_text()
    upstreams = (REPO / "docker" / "gateway" / "supabase-upstreams.conf").read_text()
    template = (REPO / "docker" / "gateway" / "single-origin.conf.template").read_text()

    assert "COPY --from=supabase/gotrue" in dockerfile
    assert "COPY --from=postgrest/postgrest" in dockerfile
    assert "include /etc/nginx/supabase/*.conf;" in template
    assert "^/auth/v1/" in upstreams and "^/rest/v1/" in upstreams

    # Ordering is the correctness argument: roles and schemas, then GoTrue's own
    # migrations, then ours — which carry foreign keys onto auth.users.
    steps = [
        entrypoint.index("bootstrap.py prepare"),
        entrypoint.index("gotrue migrate"),
        entrypoint.index("python /app/docker/bootstrap.py\n"),
    ]
    assert steps == sorted(steps), "the database is prepared out of order"

    # Pointing at a real Supabase project stays supported and unchanged.
    assert 'if [ -z "${SUPABASE_URL:-}" ]; then' in entrypoint


def test_railway_button_uses_the_published_template() -> None:
    readme = (REPO / "README.md").read_text()
    match = re.search(r'<a href="([^"]+)"><img alt="Deploy on Railway"', readme)
    assert match, "README is missing its Deploy on Railway button"
    url = html.unescape(match.group(1))
    parsed = urlparse(url)
    assert parsed.netloc == "railway.com"
    assert parsed.path == "/new/template/noclick"
    assert parse_qs(parsed.query)["utm_campaign"] == ["noclick"]
