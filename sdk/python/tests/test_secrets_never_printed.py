"""Errors and clients never show the client's key: not in a repr, a traceback (even one that shows
each frame's locals, as Sentry and ``pytest -l`` do), a log line or an uncaught error's output.
Run against a real local server, so httpx and httpcore log and raise as they do in production."""

import http.server
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import httpx
import pytest

import noclick as nc

KEY = "nk_live_FAKEKEY4c9e2f7a"
HEADER_SECRET = "hdr_FAKE8d1b3e"
ROOT = Path(__file__).resolve().parents[1]
REFUSALS = {
    402: {"error": {"type": "payment_required", "message": "Your account can't pay for this.", "offers": [
        {"kind": "funds", "label": "$10 of funds", "price_usd": 10, "url": "https://noclick.com/pay/j_1", "operation_id": "op_pay"},
    ]}},
    500: {"error": {"type": "internal_error", "message": "Something broke."}},
}
PAID = {"object": "operation", "id": "op_pay", "kind": "payment", "status": "succeeded", "result": {}}


@pytest.fixture
def server():
    """A local API: ``GET /v1/users/<status>`` and ``POST /v1/ai/chat/completions`` refuse; the offer's operation is paid."""
    seen = []

    class Api(http.server.BaseHTTPRequestHandler):
        def _answer(self, status, body):
            seen.append(self.headers.get("Authorization") == f"Bearer {KEY}")  # not the header: the test's locals are shown too
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path.startswith("/v1/operations/op_pay/wait"):
                return self._answer(200, PAID)
            status = int(self.path.rsplit("/", 1)[-1])
            self._answer(status, REFUSALS[status])

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._answer(402, REFUSALS[402])

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", seen
    httpd.shutdown()
    httpd.server_close()


def _client(base_url):
    client = nc.Client(api_key=KEY, base_url=base_url, max_retries=1, headers={"X-Proxy-Token": HEADER_SECRET})

    async def no_wait(delay):
        pass

    client._sleep = no_wait
    return client


def _shown(err, client, logs):
    return {
        "repr": repr(err), "str": str(err), "vars": repr(vars(err)),
        "traceback": "".join(traceback.format_exception(err)),
        "traceback with locals": "".join(traceback.TracebackException.from_exception(err, capture_locals=True).format()),
        "logs": logs, "client": repr(client), "client vars": repr(vars(client)),
    }


def _assert_no_secret(shown):
    for what, text in shown.items():
        assert KEY not in text, f"{what} shows the key:\n{text}"
        assert HEADER_SECRET not in text, f"{what} shows a header:\n{text}"


@pytest.mark.parametrize("call,status,cls", [
    ("request", 402, nc.PaymentRequired), ("request", 500, nc.ServerError), ("stream", 402, nc.PaymentRequired),
])
def test_an_error_shows_no_key_and_its_follow_ups_still_use_it(server, caplog, call, status, cls):
    base_url, seen = server
    client = _client(base_url)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(cls) as info:
        if call == "stream":
            nc.AI.chat("hi", client=client)
        else:
            nc.User.get(str(status), client=client)
    err = info.value
    if call == "request" and status == 402:
        assert err.offers[0].operation.wait() == PAID["result"]
    logging.getLogger("app").exception("the call failed", exc_info=err)
    assert all(seen) and len(seen) == (1 if call == "stream" else 2)  # every call sent the key
    assert "HTTP Request" in caplog.text and "the call failed" in caplog.text  # the logs checked are real ones
    _assert_no_secret(_shown(err, client, caplog.text))
    assert client.api_key == KEY


def test_a_lost_connection_shows_no_key_and_keeps_its_cause():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{probe.getsockname()[1]}"
    client = _client(closed)
    with pytest.raises(nc.APIConnectionError) as info:
        nc.User.get("user_42", client=client)
    assert isinstance(info.value.__cause__, httpx.ConnectError)
    _assert_no_secret(_shown(info.value, client, ""))


@pytest.mark.parametrize("status,name", [(402, "PaymentRequired"), (500, "ServerError")])
def test_an_uncaught_error_shows_no_key(server, status, name):
    base_url, _ = server
    script = (
        "import logging, os, noclick as nc\n"
        "logging.basicConfig(level=logging.DEBUG)\n"
        "client = nc.Client(api_key=os.environ['NC_KEY'], base_url=os.environ['NC_URL'], max_retries=0,"
        " headers={'X-Proxy-Token': os.environ['NC_HEADER']})\n"
        "nc.User.get(os.environ['NC_STATUS'], client=client)\n"
    )
    run = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": str(ROOT), "NC_KEY": KEY, "NC_HEADER": HEADER_SECRET, "NC_URL": base_url,
             "NC_STATUS": str(status)},
    )
    assert run.returncode == 1
    assert f"noclick.exceptions.{name}: " in run.stderr and "HTTP Request" in run.stderr
    _assert_no_secret({"stderr": run.stderr, "stdout": run.stdout})
