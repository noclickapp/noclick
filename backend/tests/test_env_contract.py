"""Every environment variable the setup surfaces name must be one something reads.

`backend/.env.example`, `docs/self-hosting.md` and `scripts/run_local.py` all
documented `WEBHOOK_URL_BASE`. Nothing read it — the code reads
`PUBLIC_WEBHOOK_URL`, falling back to `PUBLIC_API_URL`. So `make local` composed
an environment in which minting a webhook URL raised, and with it every webhook,
form and schedule trigger, since registering a schedule needs the URL the
scheduler will call. The tests missed it because conftest sets `PUBLIC_API_URL`
itself.

A variable named in a setup surface and read nowhere is not a documentation
slip; it is a promise the install does not keep.

"Reads it" spans three consumers, because the install does: the backend, the
compose file that composes the backend's environment, and the frontend that
gets its own half of the configuration.
"""

import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# Documented for the operator's benefit and consumed by neither: the database
# container reads these itself.
NOT_READ_ANYWHERE = {"POSTGRES_URL"}


def _documented_vars() -> set[str]:
    names: set[str] = set()
    for line in (BACKEND / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            names.add(line.split("=", 1)[0].strip())
    doc = (REPO / "docs" / "self-hosting.md").read_text()
    names.update(m.group(1) for m in re.finditer(r"^\|\s*`([A-Z][A-Z0-9_]+)`", doc, re.M))
    return names


def _consumer_text() -> str:
    parts = []
    for path in BACKEND.rglob("*.py"):
        if any(p in {"__pycache__", "tests", ".venv"} for p in path.parts):
            continue
        parts.append(path.read_text(errors="ignore"))
    for path in (REPO / "frontend" / "app").rglob("*.ts*"):
        parts.append(path.read_text(errors="ignore"))
    for extra in ("docker-compose.yml", "scripts/noclick-setup.sh"):
        candidate = REPO / extra
        if candidate.exists():
            parts.append(candidate.read_text(errors="ignore"))
    return "\n".join(parts)


_CONSUMERS = _consumer_text()


def _side_text(root: pathlib.Path, patterns: tuple[str, ...]) -> str:
    parts = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if any(p in {"__pycache__", "tests", ".venv", "node_modules", "build"}
                   for p in path.parts):
                continue
            parts.append(path.read_text(errors="ignore"))
    return "\n".join(parts)


def _compose_service_env(service: str) -> set[str]:
    """Read mapping keys under one service's ``environment:`` block.

    A tiny indentation parser is enough here and avoids making PyYAML a test
    dependency solely to validate Compose's operator-facing contract.
    """
    compose = (REPO / "docker-compose.yml").read_text().splitlines()
    in_service = False
    in_environment = False
    names: set[str] = set()
    for line in compose:
        if re.match(rf"^  {re.escape(service)}:\s*$", line):
            in_service = True
            continue
        if in_service and re.match(r"^  [a-zA-Z0-9_-]+:\s*$", line):
            break
        if in_service and line == "    environment:":
            in_environment = True
            continue
        if in_environment:
            match = re.match(r"^      ([A-Z][A-Z0-9_]+):", line)
            if match:
                names.add(match.group(1))
            elif line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= 4:
                break
    return names


_BACKEND_TEXT = _side_text(BACKEND, ("*.py", "*.sh"))
_FRONTEND_TEXT = _side_text(REPO / "frontend", ("*.ts", "*.tsx", "*.js", "*.sh"))


@pytest.mark.parametrize("name", sorted(_documented_vars() - NOT_READ_ANYWHERE))
def test_documented_env_var_is_read_somewhere(name: str):
    assert re.search(rf"\b{re.escape(name)}\b", _CONSUMERS), (
        f"{name} is named in .env.example or the self-hosting guide, and nothing "
        f"in the backend, the frontend or the compose file reads it. Either the "
        f"code reads a different name — the operator then sets something inert — "
        f"or the variable is obsolete and the surface should stop asking for it."
    )


@pytest.mark.parametrize(
    "name",
    sorted(_compose_service_env("backend")),
)
def test_compose_backend_env_is_read_by_backend(name: str):
    assert re.search(rf"\b{re.escape(name)}\b", _BACKEND_TEXT), (
        f"docker-compose passes {name} to the backend, but backend code does not "
        "read it; remove the inert knob or implement it"
    )


@pytest.mark.parametrize(
    "name",
    sorted(_compose_service_env("frontend") - {"PORT", "NODE_ENV"}),
)
def test_compose_frontend_env_is_read_by_frontend(name: str):
    assert re.search(rf"\b{re.escape(name)}\b", _FRONTEND_TEXT), (
        f"docker-compose passes {name} to the frontend, but frontend code does "
        "not read it; remove the inert knob or implement it"
    )
