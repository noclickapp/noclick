"""NoClick-managed hostnames are limited to reviewed public surfaces.

Community backend and frontend code must use operator configuration. The
managed API SDK default is scoped to exact SDK implementation and documentation
paths; the public website and documentation hosts are deliberate global links.
Every other managed hostname fails closed without publishing an inventory of
private infrastructure.
"""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_DOMAIN = "noclick" + ".io"
PUBLIC_DOMAIN = "noclick" + ".com"
APPROVED_API_HOST = "api." + MANAGED_DOMAIN
APPROVED_PUBLIC_HOSTS = frozenset(
    {"www." + PUBLIC_DOMAIN, "docs." + PUBLIC_DOMAIN}
)
MANAGED_DOMAIN_RE = "|".join(
    re.escape(domain) for domain in (MANAGED_DOMAIN, PUBLIC_DOMAIN)
)
MANAGED_HOST_RE = re.compile(
    rf"(?<![A-Za-z0-9.-])(?P<host>(?:[A-Za-z0-9-]+[.])+(?:{MANAGED_DOMAIN_RE}))(?![A-Za-z0-9.-])",
    re.IGNORECASE,
)
APPROVED_API_PATHS = frozenset(
    {
        "docs/edition-boundary.md",
        "docs/public/sdk/external-apps.mdx",
        "frontend/public/noclick-sdk/sdk.esm.js",
        "sdk/python/README.md",
        "sdk/python/noclick/client.py",
        "sdk/typescript/README.md",
        "sdk/typescript/src/index.ts",
        "sdk/typescript/src/transports/websocket.ts",
    }
)
SEARCH_ROOTS = ("backend", "frontend", "sdk", "docs", "scripts")
SKIP_DIR_NAMES = {
    "node_modules", ".git", "build", "dist", ".venv", "__pycache__",
    ".noclick", ".noclick-home", "logs", ".pnpm", "coverage",
}
SCANNED_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml",
    ".md", ".mdx", ".sh", ".yaml", ".yml",
}
PUBLIC_ENDPOINT_ENV_VARS = (
    "EVENT_RELAY_URL",
    "ASSETS_BASE_URL",
    "MCP_SERVER_URL",
    "FRONTEND_URL",
    "PUBLIC_API_URL",
    "SUPABASE_URL",
    "MCP_BASE_URL",
)


def _iter_public_files():
    for root in SEARCH_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            yield path


def test_managed_hostnames_only_in_reviewed_sdk_defaults():
    violations = []
    for path in _iter_public_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            for match in MANAGED_HOST_RE.finditer(line):
                host = match.group("host").lower()
                if host in APPROVED_PUBLIC_HOSTS:
                    continue
                if host == APPROVED_API_HOST and relative in APPROVED_API_PATHS:
                    continue
                violations.append(f"{relative}:{lineno}: unapproved managed hostname")

    assert not violations, (
        "Managed-service hostnames are restricted to the reviewed SDK default "
        "locations; self-hosted traffic must use operator configuration:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize(
    ("resolver", "env_var"),
    (
        ("relay_base_url", "EVENT_RELAY_URL"),
        ("assets_base_url", "ASSETS_BASE_URL"),
        ("mcp_server_url", "MCP_SERVER_URL"),
        ("frontend_url", "FRONTEND_URL"),
        ("api_base_url", "PUBLIC_API_URL"),
    ),
)
def test_self_hosted_resolvers_require_explicit_configuration(
    monkeypatch, resolver, env_var
):
    """A community install must fail closed instead of choosing any service."""
    import utils.hosted_defaults as hosted_defaults

    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    for variable in PUBLIC_ENDPOINT_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(hosted_defaults.HostedEndpointNotConfigured):
        getattr(hosted_defaults, resolver)()

    configured = "https://operator.example"
    monkeypatch.setenv(env_var, configured)
    assert getattr(hosted_defaults, resolver)() == configured


def test_self_hosted_assets_do_not_derive_a_public_storage_bucket(monkeypatch):
    """A database URL is not implicit consent to expose an asset bucket."""
    import utils.hosted_defaults as hosted_defaults

    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    monkeypatch.setenv("SUPABASE_URL", "https://storage.example.test")
    monkeypatch.delenv("ASSETS_BASE_URL", raising=False)

    with pytest.raises(hosted_defaults.HostedEndpointNotConfigured):
        hosted_defaults.assets_base_url()
