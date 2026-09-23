"""Edition-neutral authenticated scheduler delivery contract."""
import hashlib
import hmac
import time


def delivery_headers(body: bytes, secret: str, *, timestamp=None):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Scheduler-Timestamp": stamp, "X-Scheduler-Signature": signature}


def verify_delivery(body: bytes, headers, secret: str, *, max_age=300):
    try:
        stamp = headers.get("x-scheduler-timestamp", "")
        age = abs(time.time() - int(stamp))
        if not secret or (max_age is not None and age > max_age):
            return False
        expected = delivery_headers(body, secret, timestamp=stamp)["X-Scheduler-Signature"]
        return hmac.compare_digest(expected, headers.get("x-scheduler-signature", ""))
    except (ValueError, TypeError):
        return False
