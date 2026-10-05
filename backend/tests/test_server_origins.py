"""CORS origins for local dev: a worktree served from its own host
(frontend/app/lib/devHost.ts) must reach the backend like plain localhost."""

import server


def test_dev_worktree_hosts_are_allowed_origins():
    assert "http://localhost:5180" in server.ORIGINS
    assert "http://wt5180.localhost:5180" in server.ORIGINS


def test_configured_loopback_origin_gains_its_worktree_host():
    assert server._origin_aliases("http://127.0.0.1:3100/") == [
        "http://127.0.0.1:3100", "http://localhost:3100", "http://wt3100.localhost:3100",
    ]
    assert server._origin_aliases("https://noclick.example.com") == ["https://noclick.example.com"]
