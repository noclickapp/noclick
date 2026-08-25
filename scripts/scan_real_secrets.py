#!/usr/bin/env python3
"""Fail the export if any blob in history holds a real-SHAPED credential.

gitleaks already runs, and it is useful, but it is a report rather than a gate
and it is tuned for recall. This narrower companion catches provider-shaped
credentials in places where broad heuristic findings can otherwise obscure the
one value that matters.

So this asks a narrower question with a yes/no answer: does any blob, in any
commit, contain a string matching the exact shape a real credential has? A
provider's token format is specific enough that shape alone is decisive —
`xoxb-` plus two long digit runs plus a 24-char secret is not something prose
produces by accident, whereas "phc_..." in a docstring is. A second,
assignment-aware rule covers high-entropy base64/hex values only when the
left-hand name contains SECRET, KEY, TOKEN or PASSWORD.

Placeholders are excluded by content, not by path: a test fixture with a real
token is exactly the case that got us, so exempting test files would reopen it.

Usage: scan_real_secrets.py <repo-root>   (exit 1 on any hit)
"""

import base64
import binascii
import hashlib
import math
import re
import subprocess
import sys

# Shapes specific enough that a match is a credential, not a mention of one.
PATTERNS = {
    "Slack bot token":        re.compile(rb"xoxb-\d{6,}-\d{6,}-[A-Za-z0-9]{20,}"),
    "Slack user token":       re.compile(rb"xoxp-\d{6,}-\d{6,}-\d{6,}-[A-Za-z0-9]{20,}"),
    "Slack app-level token":  re.compile(rb"xapp-\d-[A-Z0-9]{8,}-\d{6,}-[A-Za-z0-9]{20,}"),
    "PostHog project key":    re.compile(rb"phc_[A-Za-z0-9]{30,}"),
    "Stripe live key":        re.compile(rb"sk_live_[A-Za-z0-9]{20,}"),
    "Stripe restricted key":  re.compile(rb"rk_live_[A-Za-z0-9]{20,}"),
    "Anthropic key":          re.compile(rb"sk-ant-api03-[A-Za-z0-9_-]{40,}"),
    "OpenAI key":             re.compile(rb"sk-[A-Za-z0-9]{40,}"),
    "AWS access key id":      re.compile(rb"AKIA[0-9A-Z]{16}"),
    "GitHub token":           re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,}"),
    "Google API key":         re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "Signed JWT":             re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}"),
    "Fernet key":             re.compile(rb"gAAAAA[A-Za-z0-9_-]{60,}"),
}

# GitHub secret scanning also treats Twilio SIDs as sensitive identifiers.
# They are not sufficient to authenticate by themselves, but publishing a
# real-shaped identifier creates an alert and can disclose an account link.
# Unlike provider-token placeholders, do not exempt predictable-looking SIDs:
# test fixtures should be visibly synthetic instead of indistinguishable from
# production identifiers.
SENSITIVE_IDENTIFIER_PATTERNS = {
    "Twilio account SID": re.compile(rb"\bAC[0-9a-fA-F]{32}\b"),
    "Twilio API key SID": re.compile(rb"\bSK[0-9a-fA-F]{32}\b"),
}

# SHA-256 fingerprints of revoked credentials that must never reappear in any
# public object. Keeping only the one-way digest lets the scanner catch the
# exact historical value wherever it appears without retaining that value in
# the exporter or printing it into CI logs.
BLOCKED_SECRET_SHA256 = {
    bytes.fromhex("48731d5aa0bbd84bd1abae2f1fa251d790d08889eaf2c696633e8199eb0da730"),
}

OPAQUE_TOKEN = re.compile(
    rb"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{40,128}(?![A-Za-z0-9_+/=-])"
)

# Values that match a shape but are self-evidently not live.
PLACEHOLDER_MARKERS = (
    b"DEADBEEF", b"deadbeef", b"1234567890", b"xxxx", b"XXXX",
    b"REDACTED", b"EXAMPLE", b"example", b"your-", b"YOUR_", b"placeholder",
    b"abcdef", b"ABCDEF", b"000000",
)

# Human-readable test phrases can happen to be valid URL-safe base64. Limit
# these extra markers to the generic assignment rule: provider-prefixed tokens
# keep the stricter exclusions above, while values such as
# ``oauth-flow-test-secret-...`` are correctly recognized as fixtures.
ASSIGNED_PLACEHOLDER_MARKERS = (
    b"-test-", b"_test_", b"-fake-", b"_fake_", b"-dummy-", b"_dummy_",
)

# Generic signing/session secrets do not have a provider prefix. Restrict the
# entropy check to assignments whose name says the value is security-sensitive:
# this catches `JWT_SECRET = os.getenv("...", "<random fallback>")` without
# treating every content hash, fixture id, or generated schema token as a key.
ASSIGNED_SECRET = re.compile(
    rb"""(?imx)
    ^[ \t]*
    (?:(?:const|let|var)[ \t]+)?
    (?P<name>
        (?=[A-Za-z_][A-Za-z0-9_]*(?:secret|key|token|password))
        [A-Za-z_][A-Za-z0-9_]*
    )
    (?:[ \t]*:[^=\r\n]+)?
    [ \t]*=[ \t]*
    [^\r\n]{0,240}?
    (?P<quote>["'])
    (?P<value>[A-Za-z0-9_+/=-]{40,128})
    (?P=quote)
    """
)

MIN_SECRET_BYTES = 32
MIN_ENTROPY_BITS_PER_BYTE = 4.0


def is_placeholder(value: bytes) -> bool:
    return any(m in value for m in PLACEHOLDER_MARKERS)


def _decoded_secret(value: bytes) -> bytes | None:
    """Decode a hex/base64 candidate, returning None for non-secret shapes."""
    if len(value) % 2 == 0 and re.fullmatch(rb"[0-9a-fA-F]+", value):
        try:
            raw = bytes.fromhex(value.decode("ascii"))
        except ValueError:
            return None
    else:
        # Accept standard and URL-safe base64 with or without padding. Validation
        # happens after translating the URL-safe alphabet, so prose-like strings
        # cannot become candidates merely because Python's decoder ignores them.
        normalized = value.replace(b"-", b"+").replace(b"_", b"/")
        normalized += b"=" * (-len(normalized) % 4)
        try:
            raw = base64.b64decode(normalized, validate=True)
        except (binascii.Error, ValueError):
            return None
    return raw if len(raw) >= MIN_SECRET_BYTES else None


def _entropy(raw: bytes) -> float:
    if not raw:
        return 0.0
    counts = {byte: raw.count(byte) for byte in set(raw)}
    size = len(raw)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def high_entropy_assignments(data: bytes) -> set[bytes]:
    """Random-looking values assigned to a SECRET/KEY/TOKEN/PASSWORD name."""
    found = set()
    for match in ASSIGNED_SECRET.finditer(data):
        value = match.group("value")
        if is_placeholder(value) or any(
            marker in value for marker in ASSIGNED_PLACEHOLDER_MARKERS
        ):
            continue
        raw = _decoded_secret(value)
        if raw is None or _entropy(raw) < MIN_ENTROPY_BITS_PER_BYTE:
            continue
        found.add(value)
    return found


def blocked_fingerprint_values(data: bytes) -> set[bytes]:
    """Return opaque tokens whose SHA-256 matches a revoked credential."""
    return {
        value
        for value in OPAQUE_TOKEN.findall(data)
        if hashlib.sha256(value).digest() in BLOCKED_SECRET_SHA256
    }


def find_secrets(data: bytes) -> dict[str, set[bytes]]:
    findings: dict[str, set[bytes]] = {}
    for name, rx in PATTERNS.items():
        for match in rx.finditer(data):
            value = match.group(0)
            if not is_placeholder(value):
                findings.setdefault(name, set()).add(value)
    for name, rx in SENSITIVE_IDENTIFIER_PATTERNS.items():
        for match in rx.finditer(data):
            findings.setdefault(name, set()).add(match.group(0))
    assigned = high_entropy_assignments(data)
    if assigned:
        findings["High-entropy assigned secret"] = assigned
    blocked = blocked_fingerprint_values(data)
    if blocked:
        findings["Known revoked credential"] = blocked
    return findings


def main(root: str) -> int:
    object_result = subprocess.run(
        ["git", "-C", root, "rev-list", "--objects", "--all"],
        capture_output=True,
    )
    if object_result.returncode != 0:
        print(
            "    SECRET SCAN FAILED — could not enumerate the repository history",
            file=sys.stderr,
        )
        return 2
    objects = object_result.stdout.decode(errors="ignore").splitlines()

    shas, paths = [], {}
    for line in objects:
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        shas.append(parts[0])
        if len(parts) > 1:
            paths[parts[0]] = parts[1]

    # A bad path used to look exactly like a clean scan: git failed, stdout was
    # empty, and the script proudly reported zero objects. Fail closed both for
    # that case and for an initialized repository with no history to inspect.
    if not shas:
        print(
            "    SECRET SCAN FAILED — repository history contained no objects",
            file=sys.stderr,
        )
        return 2

    # One batch call: 70k objects individually would take minutes.
    batch_result = subprocess.run(
        ["git", "-C", root, "cat-file", "--batch"],
        input="\n".join(shas).encode(),
        capture_output=True,
    )
    if batch_result.returncode != 0:
        print(
            "    SECRET SCAN FAILED — could not read the repository objects",
            file=sys.stderr,
        )
        return 2
    batch = batch_result.stdout

    findings = find_secrets(batch)

    if not findings:
        print(f"    no real-shaped credentials in history ({len(shas)} objects)")
        return 0

    print("    SECRET SCAN FAILED — history contains real-shaped credentials:", file=sys.stderr)
    for name, values in sorted(findings.items()):
        for v in sorted(values):
            # A fingerprint is enough to correlate a finding without printing
            # usable credential material into CI logs.
            fingerprint = hashlib.sha256(v).hexdigest()[:12]
            print(f"      {name}: sha256:{fingerprint} ({len(v)} chars)", file=sys.stderr)
    print(
        "\n    Fix the source, add a targeted shape rewrite to the export, and add a\n"
        "    SHA-256 deny fingerprint here. Never copy credential plaintext into\n"
        "    rule files; removing it at HEAD alone is not enough.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
