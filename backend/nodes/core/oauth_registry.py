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


@lru_cache(maxsize=1)
def bespoke_exchange_providers() -> frozenset[str]:
    """Read literal client events without importing the socket/handler graph."""
    source = Path(__file__).resolve().parents[2] / "wss/receiver/client_events.py"
    suffix = ":oauth:exchange"
    return frozenset(
        node.value.value[: -len(suffix)]
        for cls in ast.parse(source.read_text()).body
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "event_name"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.endswith(suffix)
    )


def validate_oauth_credential_types(providers, node_classes) -> None:
    """A declared credential must belong to the provider its schema advertises."""
    by_type = {spec.credential_type: spec.provider for spec in providers.values()}
    if not by_type:
        return
    for cls in set(node_classes):
        schema = cls.get_config_schema() or {}
        for definition in schema.get("$defs", {}).values():
            field = definition.get("properties", {}).get("credential_type", {})
            credential_type = field.get("const") or field.get("default")
            provider = definition.get("x-oauth-provider")
            if (
                credential_type in by_type
                and provider
                and provider != by_type[credential_type]
            ):
                raise ValueError(
                    f"OAuth credential {credential_type} belongs to {provider}, not {by_type[credential_type]}"
                )


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
        if spec.provider in bespoke_exchange_providers():
            raise ValueError(
                f"OAuth provider already has a bespoke exchange event: {spec.provider}"
            )
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
