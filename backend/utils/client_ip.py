"""The address a request came from: what per-visitor limits and records of a caller key on.

Kept apart from any route module so code that only needs the address doesn't import one.
"""


def client_ip(request) -> str:
    # Cloudflare fronts prod; the header is stripped/overwritten at the edge.
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
