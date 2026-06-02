"""Decompose a node output into a per-run manifest + content-addressed chunks,
and reassemble it.

**Slice 1 (this file) stores each output whole — no Merkle.** An output whose
canonical size is below the threshold is inlined into the manifest verbatim; at
or above the threshold the whole output becomes one chunk and the manifest is a
single ``{"$cas": <hash>}`` pointer.

**Slice 2** replaces ``decompose`` with the size-thresholded structural Merkle
walk (chunk a child when its own canonical size ≥ T, inline smaller children,
recurse into a chunk's own ≥T children). ``reassemble`` already resolves nested
placeholders, so it is forward-compatible and does not change in Slice 2.

Chunk values are *canonical bytes* (uncompressed). The store layer applies zstd
before R2 and decompresses on read, so this module stays pure (no I/O, no
compression) and is exhaustively unit-testable.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional, Tuple

from utils.cas.canonical import canonicalize, hash_bytes

# T — outputs/subtrees at or above this canonical size are content-addressed.
DEFAULT_CHUNK_THRESHOLD_BYTES = 4 * 1024

_PLACEHOLDER_KEY = "$cas"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# Substituted for a chunk that is no longer in the store (GC'd / race casualty).
# The read path renders this as an explicit "output no longer retained" state.
PRUNED_PLACEHOLDER: Dict[str, Any] = {"$cas_pruned": True}


def _is_placeholder(node: Any) -> bool:
    """A node is a CAS pointer iff it is exactly ``{"$cas": <64-hex sha256>}``.

    Validating the hash shape makes a real output that happens to contain a
    ``$cas`` key (without a 64-hex value) impossible to misread as a pointer.
    The astronomically-unlikely exact collision degrades benignly (a fetch miss
    → "not retained"), never to corruption.
    """
    return (
        isinstance(node, dict)
        and len(node) == 1
        and isinstance(node.get(_PLACEHOLDER_KEY), str)
        and bool(_HASH_RE.match(node[_PLACEHOLDER_KEY]))
    )


def decompose(
    output: Any, threshold: int = DEFAULT_CHUNK_THRESHOLD_BYTES
) -> Tuple[Any, Dict[str, bytes]]:
    """Return ``(manifest, chunks)`` where ``chunks`` maps hash → canonical bytes.

    Slice 1: whole-output. Inline below the threshold (zero chunks); one chunk at
    or above it. The returned manifest is JSON-serializable (it IS the inlined
    output, or a single placeholder dict).
    """
    data = canonicalize(output)
    if len(data) < threshold:
        return output, {}
    digest = hash_bytes(data)
    return {_PLACEHOLDER_KEY: digest}, {digest: data}


def reassemble(
    manifest: Any,
    fetch_chunk: Callable[[str], Optional[bytes]],
    *,
    on_missing: Any = PRUNED_PLACEHOLDER,
) -> Any:
    """Rebuild the output from a manifest, resolving ``$cas`` placeholders.

    ``fetch_chunk(hash)`` returns the chunk's canonical bytes, or ``None`` if the
    chunk is no longer stored — in which case ``on_missing`` is substituted at
    that position (never raises). Chunks may themselves contain nested
    placeholders (Slice 2), which are resolved recursively.
    """

    def walk(node: Any) -> Any:
        if _is_placeholder(node):
            data = fetch_chunk(node[_PLACEHOLDER_KEY])
            if data is None:
                return on_missing
            return walk(json.loads(data))
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(manifest)


def referenced_hashes(manifest: Any) -> set:
    """Every chunk hash a manifest points at (recursively through inline structure).

    Slice-1 manifests reference at most one hash; provided now so the store's
    ref-reconcile and GC accounting are correct when Slice 2 nests placeholders.
    """
    found: set = set()

    def walk(node: Any) -> None:
        if _is_placeholder(node):
            found.add(node[_PLACEHOLDER_KEY])
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(manifest)
    return found
