"""Content-addressed store (CAS) for execution-log graph snapshots + node outputs.

See docs/design/execution-log-viewer.md. Modules:
- canonical: deterministic canonical bytes + sha256 content hashing (the CAS key).
- chunking:  decompose an output into a manifest + content-addressed chunks; reassemble.
"""
