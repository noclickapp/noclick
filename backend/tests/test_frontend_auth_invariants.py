"""Frontend auth invariants (docs/auth-refactor-spec.md §3.4), pinned as
source scans in the house style of test_no_raw_credential_blob_updates.py.

1. `document.cookie` is touched ONLY by @supabase/ssr's storage adapter
   (supabase-client.ts). Hand-rolled cookie reads fed the socket a raw cookie
   jar; hand-rolled deletes destroyed live refresh tokens (the 2026-07
   mid-session logout bug). Both classes are structurally banned.
2. `createServerSupabaseClient(request)` without a headers sink is only legal
   at explicitly allowlisted definition or machine-auth call sites — anywhere
   else a token rotation would be silently
   dropped, burning the single-use refresh token.
3. The socket auth payload never carries a `cookie` key — the contract is the
   access token.
"""

import re
from pathlib import Path

FRONTEND_APP = Path(__file__).parent.parent.parent / "frontend" / "app"

# The only file allowed to touch document.cookie: Supabase's own storage.
DOCUMENT_COOKIE_ALLOWLIST = {
    "lib/supabase-client.ts",
}

# Definition sites do not handle a request and therefore need no response-
# header sink. Runtime call sites must always provide one.
HEADERLESS_CLIENT_ALLOWLIST = {
    "lib/supabase.ts",
}


def _app_sources():
    for ext in ("*.ts", "*.tsx"):
        yield from FRONTEND_APP.rglob(ext)


def _rel(path: Path) -> str:
    """Stable allowlist key beneath the shipped application root."""
    return path.relative_to(FRONTEND_APP).as_posix()


def test_document_cookie_only_in_supabase_storage_adapter():
    offenders = []
    for path in _app_sources():
        rel = _rel(path)
        if rel in DOCUMENT_COOKIE_ALLOWLIST:
            continue
        text = path.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if "document.cookie" in line:
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "document.cookie outside the Supabase storage adapter — cookie "
        "lifecycle belongs to @supabase/ssr only:\n" + "\n".join(offenders)
    )


def test_server_supabase_client_always_gets_headers_sink():
    # Matches createServerSupabaseClient(<arg>) with exactly one argument —
    # i.e. no headers sink for rotated cookies.
    call_re = re.compile(r"createServerSupabaseClient\(\s*([A-Za-z_$][\w$]*)\s*\)")
    offenders = []
    for path in _app_sources():
        rel = _rel(path)
        if rel in HEADERLESS_CLIENT_ALLOWLIST:
            continue
        text = path.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if call_re.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "createServerSupabaseClient without a headers sink — a token rotation "
        "here would drop its Set-Cookie and burn the refresh token:\n"
        + "\n".join(offenders)
    )


def test_socket_auth_payload_carries_no_cookie_key():
    for rel in ("lib/socket/config.ts", "lib/socket-receiver.ts"):
        text = (FRONTEND_APP / rel).read_text(errors="ignore")
        assert not re.search(r"\bcookie\s*:", text), (
            f"{rel} builds an auth payload with a 'cookie' key — the socket "
            "auth contract is {{ token: access_token }}"
        )
