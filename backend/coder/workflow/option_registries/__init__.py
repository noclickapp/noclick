"""
Queryable enum registries for schema fields with large option sets.

A schema field can declare ``x-queryable-enum: "<registry-name>"`` and the
field-write path will resolve loose user/brain input to the canonical option
id, surfacing close alternatives in the next-turn execution result. Used so
a 1000+ entry enum (e.g. LiteLLM model ids) doesn't have to be inlined into
``query_schema`` output, and so fuzzy input ("claude sonnet 4.6") gets
auto-corrected to a real id ("anthropic/claude-sonnet-4.6").
"""

from .base import Option, Resolution, OptionRegistry
from .models import MODELS_REGISTRY

REGISTRY: dict[str, OptionRegistry] = {
    "models": MODELS_REGISTRY,
}


def get_registry(name: str) -> OptionRegistry | None:
    return REGISTRY.get(name)


__all__ = ["Option", "Resolution", "OptionRegistry", "REGISTRY", "get_registry"]
