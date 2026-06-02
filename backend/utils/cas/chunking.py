"""Decompose a node output into a per-run manifest + content-addressed chunks,
and reassemble it.

**Structural Merkle (Slice 2).** A subtree below the threshold is inlined into
the manifest verbatim; a container at or above it is recursively decomposed and
its reduced skeleton chunked only if still ≥ T (else inlined) — so identical
sub-structures across runs share one content-addressed chunk. ``decompose``
returns the FLAT transitive set of all chunks (incl. nested); the store refs the
whole set so GC never orphans a still-referenced nested chunk, and ``reassemble``
resolves nested placeholders recursively (the store fetches the transitive
closure; see ``utils/cas/store.py:_reassemble``).

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
    """Structural Merkle decomposition: factor large sub-structures into shared,
    content-addressed chunks so identical subtrees dedup across runs.

    Walk: a subtree whose canonical size < T is inlined verbatim. A container
    (dict/list) >= T is recursively decomposed; then its REDUCED form (children
    that were themselves chunked are now placeholders) is chunked ONLY if the
    reduced form is still >= T — otherwise the reduced skeleton is inlined into
    the parent / manifest.

    The "inline the reduced skeleton when it's < T" rule is the no-regression
    safeguard: a node is never split into a layout that costs more than storing
    it whole. In particular a single large compressible scalar stays exactly one
    chunk (== whole-blob), so chunking can't make a node's footprint worse.

    A scalar (string/number) >= T can't be subdivided structurally → one chunk.
    EXTENSION POINT: route such opaque scalars through content-defined chunking
    (a $cas pointer to a CDC sub-manifest) to dedup drifting binary/text — purely
    additive, since reassemble already resolves nested placeholders recursively.

    Returns ``(manifest, chunks)`` where ``chunks`` maps hash → canonical bytes
    for ALL chunks INCLUDING nested ones (the flat transitive set), so the store
    refs the complete set and GC never orphans a still-referenced nested chunk.
    The manifest is JSON-serializable (inlined value, reduced skeleton, or a
    single placeholder dict).
    """
    data = canonicalize(output)
    if len(data) < threshold:
        return output, {}

    chunks: Dict[str, bytes] = {}
    if isinstance(output, dict):
        reduced: Any = {}
        for key, value in output.items():
            child_manifest, child_chunks = decompose(value, threshold)
            reduced[key] = child_manifest
            chunks.update(child_chunks)
    elif isinstance(output, list):
        reduced = []
        for value in output:
            child_manifest, child_chunks = decompose(value, threshold)
            reduced.append(child_manifest)
            chunks.update(child_chunks)
    else:
        # Opaque scalar at or above T — can't subdivide (see EXTENSION POINT).
        digest = hash_bytes(data)
        return {_PLACEHOLDER_KEY: digest}, {digest: data}

    reduced_bytes = canonicalize(reduced)
    if len(reduced_bytes) < threshold:
        return reduced, chunks                 # inline the reduced skeleton
    digest = hash_bytes(reduced_bytes)
    chunks[digest] = reduced_bytes
    return {_PLACEHOLDER_KEY: digest}, chunks


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
