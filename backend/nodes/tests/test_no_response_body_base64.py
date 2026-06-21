"""
Regression guard: a node must never base64-encode a downloaded HTTP response body
into its output. Doing so produces the unusable "wall of characters" media shape.
Hand the bytes back as a ``nodes.core.binary_output.BinaryOutput`` marker instead;
``WorkflowNode.run`` resolves it to a {url, mime_type, name, size_bytes} reference.

This scans node source for ``b64encode(<...response...>.content)`` — encoding a
*response* body. Encoding config/input data to send to an API is fine and not matched.
"""
import re
from pathlib import Path

# b64encode( <var containing 'response'> .content )  — the download-to-base64 antipattern
_PATTERN = re.compile(r"b64encode\(\s*[\w.]*response[\w.]*\.content\b", re.IGNORECASE)

_NODES_DIR = Path(__file__).resolve().parent.parent

# http_request_node is the canonical binary handler: it stores to R2 and returns a
# {url, ...} ref whenever there's workflow context, and base64-encodes ONLY as the
# no-context fallback (the same thing the central resolver does) — not the antipattern.
_ALLOWLIST = {"http_request_node.py"}


def test_no_node_base64_encodes_a_response_body():
    violations = []
    for path in sorted(_NODES_DIR.glob("*.py")):
        if path.name in _ALLOWLIST:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if _PATTERN.search(line):
                violations.append(f"{path.name}:{i}: {line.strip()}")
    assert not violations, (
        "These nodes base64-encode a response body into their output (unusable media). "
        "Return BinaryOutput(data=..., content_type=..., filename=...) instead:\n"
        + "\n".join(violations)
    )
