"""Discover only OAuth modules declaring an OAUTH_PROVIDER spec.

The cheap source/AST prefilter leaves all bespoke OAuth utilities unimported.
Invalid declarations and duplicate ids/types fail startup deterministically.
"""
from __future__ import annotations

import ast
import importlib
from functools import lru_cache
from pathlib import Path

from nodes.core.oauth_provider import OAuthProviderSpec


def discover_oauth_providers(
    directory: Path, package: str = "nodes.oauth"
) -> dict[str, OAuthProviderSpec]:
    providers = {}
    credential_types = set()
    for path in sorted(directory.glob("*_oauth.py")):
        source = path.read_text()
        if "OAUTH_PROVIDER" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        if not any(
            isinstance(stmt, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "OAUTH_PROVIDER"
                for target in (
                    stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                )
            )
            for stmt in tree.body
        ):
            continue
        module = importlib.import_module(f"{package}.{path.stem}")
        spec = module.OAUTH_PROVIDER
        if not isinstance(spec, OAuthProviderSpec):
            raise ValueError(f"Invalid OAUTH_PROVIDER in {module.__name__}")
        if spec.provider in providers or spec.credential_type in credential_types:
            raise ValueError(
                f"Duplicate OAuth provider or credential type: {spec.provider}"
            )
        providers[spec.provider] = spec
        credential_types.add(spec.credential_type)
    return providers


@lru_cache(maxsize=1)
def oauth_providers() -> dict[str, OAuthProviderSpec]:
    return discover_oauth_providers(Path(__file__).resolve().parents[1] / "oauth")


def get_oauth_provider(provider: str) -> OAuthProviderSpec:
    try:
        return oauth_providers()[provider]
    except KeyError:
        raise ValueError(f"Unknown OAuth provider: {provider}") from None
