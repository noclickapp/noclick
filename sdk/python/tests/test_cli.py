"""The `noclick` command: argument parsing and the calls each command makes."""

import io
import json
import os
import stat
import subprocess
import sys
import time
import types

import httpx
import pytest

import noclick as nc
from noclick import cli
from platform_helpers import BASE, USER_ID, agent_row, body, listing, operation, user_row

SHA = "3f2a1c9e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39"


class FakeKeyring:
    """Stands in for the OS keychain (the real one is never touched in tests)."""

    class KeyringError(Exception):
        pass

    def __init__(self):
        self.saved = {}
        self.errors = types.SimpleNamespace(KeyringError=self.KeyringError)

    def get_password(self, service, user):
        return self.saved.get((service, user))

    def set_password(self, service, user, password):
        self.saved[(service, user)] = password

    def delete_password(self, service, user):
        del self.saved[(service, user)]


@pytest.fixture
def home(monkeypatch, tmp_path, client):
    """A signed-in shell (NOCLICK_API_KEY) with its own config dir, keychain and clock."""
    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_test")
    monkeypatch.setenv("NOCLICK_API_URL", BASE)
    monkeypatch.setenv("NOCLICK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("NOCLICK_PROFILE", raising=False)
    keychain = FakeKeyring()
    monkeypatch.setattr(cli, "_keyring", lambda: keychain)
    monkeypatch.setattr(cli, "POLL_S", 0)
    sleeps = []
    monkeypatch.setattr(cli, "_sleep", sleeps.append)
    return types.SimpleNamespace(keychain=keychain, sleeps=sleeps, config=tmp_path / "config")


def run(*argv):
    return cli.main(list(argv))


def stop_after(calls):
    """A ``_sleep`` that ends a follow loop (as Ctrl-C would) on its ``calls``-th call."""
    seen = []

    def sleep(delay):
        seen.append(delay)
        if len(seen) >= calls:
            raise KeyboardInterrupt

    return sleep


def signed_in_with_login(home, monkeypatch, *, store="keychain", key="nk_live_cli9f2c1a77"):
    monkeypatch.delenv("NOCLICK_API_KEY")
    config = {"profiles": {"default": {
        "api_url": BASE, "store": store, "key_id": "key_7", "key_name": "CLI on ana-mbp",
        "key_prefix": key[:12], "email": "ana@acme.test",
    }}}
    home.config.mkdir(parents=True, exist_ok=True)
    (home.config / "config.json").write_text(json.dumps(config))
    home.keychain.set_password("noclick", "default", key)


# --- parsing -------------------------------------------------------------------------


def test_help_lists_every_command_as_working(capsys):
    with pytest.raises(SystemExit) as done:
        run("--help")
    assert done.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for command in ("login Sign in", "logout Revoke", "whoami Show", "agents List", "users List", "bucket List",
                    "ops Wait", "webhooks Receive", "db Query", "deploy Push", "logs Print", "domains Search"):
        assert command in text, command
    assert "designed" not in text and "not_available" not in text


@pytest.mark.parametrize("argv, run_fn, expected", [
    (["whoami", "--json"], cli.cmd_whoami, {"json": True, "auth": False}),
    (["agents", "list", "--all-users", "--limit", "5"], cli.cmd_agents_list, {"all_users": True, "limit": 5}),
    (["agents", "chat", "support", "--user", "user_42", "-m", "hi"], cli.cmd_agents_chat,
     {"name": "support", "user": "user_42", "message": "hi", "conversation": None}),
    (["users", "create", "user_42", "--email", "ana@acme.test", "--spend-cap", "50"], cli.cmd_users_create,
     {"id": "user_42", "email": "ana@acme.test", "spend_cap": 50.0}),
    (["db", "query", "booking-db", "select ?", "-p", "2", "-p", "x", "--write"], cli.cmd_db_query,
     {"database": "booking-db", "sql": "select ?", "param": ["2", "x"], "write": True}),
    (["bucket", "cp", "-r", "./dist", "public-assets:"], cli.cmd_bucket_cp,
     {"src": "./dist", "dst": "public-assets:", "recursive": True}),
    (["deploy", "--branch", "new-form", "--no-wait"], cli.cmd_deploy,
     {"project": None, "app": None, "branch": "new-form", "no_wait": True, "create": False, "token": None}),
    (["deploy", "--app", "booking", "--create", "--token", "nk_mcp_t"], cli.cmd_deploy,
     {"project": None, "app": "booking", "create": True, "token": "nk_mcp_t", "auth": True}),
    (["logs", "booking", "-f", "--level", "error"], cli.cmd_logs, {"project": "booking", "follow": True, "level": "error"}),
    (["domains", "buy", "acmebooking.com", "--max-price", "15"], cli.cmd_domains_buy,
     {"name": "acmebooking.com", "max_price": 15.0, "years": None}),
    (["webhooks", "listen", "--forward-to", "http://localhost:3000/hooks", "--events", "operation.*,human.answered"],
     cli.cmd_webhooks_listen, {"events": ["operation.*", "human.answered"], "events_user": None}),
    (["--profile", "staging", "ops", "wait", "op_1", "--timeout", "30"], cli.cmd_ops_wait,
     {"operation_id": "op_1", "timeout": 30.0, "profile": "staging"}),
])
def test_parses_every_command(argv, run_fn, expected):
    args = cli.build_parser().parse_args(argv)
    assert args.run is run_fn
    for name, value in expected.items():
        assert getattr(args, name) == value, name


def test_money_needs_a_ceiling(capsys):
    with pytest.raises(SystemExit) as done:
        run("domains", "buy", "acmebooking.com")
    assert done.value.code == 2
    assert "--max-price" in capsys.readouterr().err


def test_module_runs_and_imports_without_a_key():
    env = {k: v for k, v in os.environ.items() if not k.startswith("NOCLICK_")}
    version = subprocess.run([sys.executable, "-m", "noclick", "--version"], capture_output=True, text=True, env=env)
    assert version.returncode == 0 and version.stdout.strip() == f"noclick {nc.__version__}"
    assert "cli" not in nc.__all__


# --- signing in ----------------------------------------------------------------------


def test_commands_need_a_key(home, monkeypatch, api, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY")
    route = api.get("/v1/agents").respond(json=listing())
    assert run("agents", "list") == 1
    err = capsys.readouterr().err
    assert "You're not signed in." in err and "Run noclick login, or set NOCLICK_API_KEY." in err
    assert route.call_count == 0


def test_login_runs_the_device_flow_and_keeps_the_key(home, monkeypatch, api, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY")
    start = api.post("/v1/cli/logins").respond(json={
        "object": "cli_login", "device_code": "dc_secret", "user_code": "WDJB-MJHT",
        "verification_url": "https://noclick.com/dashboard/developers/cli",
        "verification_url_complete": "https://noclick.com/dashboard/developers/cli?code=WDJB-MJHT",
        "expires_at": "2026-09-28T10:15:00Z", "interval_s": 5,
    })
    token = api.post("/v1/cli/logins/token").mock(side_effect=[
        httpx.Response(200, json={"object": "cli_login", "status": "pending", "interval_s": 10}),
        httpx.Response(200, json={
            "object": "cli_login", "status": "approved", "key": "nk_live_cli9f2c1a77", "key_id": "key_7",
            "key_name": "CLI on ana-mbp", "email": "ana@acme.test",
        }),
    ])
    assert run("login", "--no-browser") == 0
    out = capsys.readouterr()
    assert "Open https://noclick.com/dashboard/developers/cli and enter the code WDJB-MJHT" in out.out
    assert "Signed in as ana@acme.test." in out.out
    assert body(start.calls.last.request)["client"] == "noclick-cli"
    assert "authorization" not in start.calls.last.request.headers  # there is no key yet
    assert [body(call.request) for call in token.calls] == [{"device_code": "dc_secret"}] * 2
    assert home.sleeps == [5, 10]  # the server's interval, then the slower one it asked for
    assert home.keychain.get_password("noclick", "default") == "nk_live_cli9f2c1a77"
    saved = json.loads((home.config / "config.json").read_text())["profiles"]["default"]
    assert saved == {"api_url": BASE, "store": "keychain", "key_id": "key_7", "key_name": "CLI on ana-mbp",
                     "key_prefix": "nk_live_cli9", "email": "ana@acme.test"}
    assert "nk_live_cli9f2c1a77" not in (home.config / "config.json").read_text()


def test_login_denied_or_expired_is_an_error(home, monkeypatch, api, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY")
    api.post("/v1/cli/logins").respond(json={"device_code": "dc", "user_code": "A-B", "verification_url": "https://x.test"})
    api.post("/v1/cli/logins/token").respond(410, json={"error": {
        "type": "expired", "message": "The code expired.", "next_step": "Run noclick login again."}})
    assert run("login", "--no-browser") == 1
    assert "The code expired." in capsys.readouterr().err
    assert home.keychain.saved == {}


def test_login_without_a_keychain_keeps_the_key_in_a_private_file_and_says_where(home, monkeypatch, api, capsys):
    """``pip install noclick`` then ``noclick login`` failed for want of a keychain library (2026-11-25): with none,
    or a machine with no keychain behind it, or one that refuses, the key goes in the private file, said so. Asked
    for the keychain by name, a missing one refuses before the browser opens."""
    def missing():
        raise cli.CommandError("No OS keychain library is installed.", next_step="pip install keyring")

    monkeypatch.setattr(cli, "_keyring", missing)
    start = api.post("/v1/cli/logins").respond(json={"device_code": "dc", "user_code": "A-B",
                                                     "verification_url": "https://x.test"})
    api.post("/v1/cli/logins/token").respond(json={"status": "approved", "key": "nk_live_filekey123",
                                                   "key_name": "CLI on box"})
    assert run("login", "--store", "keychain") == 1
    assert "No OS keychain" in capsys.readouterr().err and start.call_count == 0

    monkeypatch.delenv("NOCLICK_API_KEY")
    assert run("login", "--no-browser") == 0
    path = home.config / "credentials.json"
    assert f'The key "CLI on box" is in {path} (only you can read it).' in capsys.readouterr().err
    assert cli.resolve_credentials("default").key == "nk_live_filekey123"
    assert json.loads((home.config / "config.json").read_text())["profiles"]["default"]["store"] == "file"

    refusing = FakeKeyring()
    refusing.set_password = lambda *a: (_ for _ in ()).throw(refusing.KeyringError("no Secret Service"))
    monkeypatch.setattr(cli, "_keyring", lambda: refusing)
    path.unlink()
    assert run("login", "--no-browser") == 0
    assert "The OS keychain refused: no Secret Service. Keeping the key in a file" in capsys.readouterr().err
    assert json.loads(path.read_text()) == {"default": "nk_live_filekey123"}


def test_login_can_keep_the_key_in_a_private_file(home, monkeypatch, api):
    monkeypatch.delenv("NOCLICK_API_KEY")
    api.post("/v1/cli/logins").respond(json={"device_code": "dc", "user_code": "A-B", "verification_url": "https://x.test"})
    api.post("/v1/cli/logins/token").respond(json={"status": "approved", "key": "nk_live_filekey123", "email": "a@b.test"})
    assert run("login", "--store", "file", "--no-browser") == 0
    path = home.config / "credentials.json"
    assert json.loads(path.read_text()) == {"default": "nk_live_filekey123"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert cli.resolve_credentials("default").key == "nk_live_filekey123"


ACCOUNT_ID = "6b3f1d2e-4a5c-4e7f-9a1b-2c3d4e5f6a7b"


def status_of(account):
    return {"object": "status", "account": account, "user_id": None}


def test_whoami_names_the_account_the_api_says_the_key_is_in(home, monkeypatch, api, capsys):
    """The account comes from the API, not from what login stored: a key kept for one account (or a
    NOCLICK_API_KEY set for another) names the one it really acts in."""
    status = api.get("/v1/status").respond(json=status_of(
        {"id": ACCOUNT_ID, "name": "Ana Lima", "email": "ana@acme.test", "acting_for": None}))
    assert run("whoami") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"Account  Ana Lima, ana@acme.test ({ACCOUNT_ID})"
    assert "nk_live_test…, from NOCLICK_API_KEY" in out and f"API      {BASE}" in out
    assert status.calls.last.request.headers["authorization"] == "Bearer nk_live_test"
    assert "noclick-user" not in status.calls.last.request.headers

    signed_in_with_login(home, monkeypatch)
    api.get("/v1/status").respond(json=status_of(
        {"id": ACCOUNT_ID, "name": None, "email": "ops@acme.test", "acting_for": None}))
    assert run("whoami") == 0
    out = capsys.readouterr().out
    assert f"Account  ops@acme.test ({ACCOUNT_ID})" in out and "ana@acme.test" not in out
    assert "Key      CLI on ana-mbp (nk_live_cli9…), in the OS keychain" in out
    assert status.calls.last.request.headers["authorization"] == "Bearer nk_live_cli9f2c1a77"

    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_ci00000000")
    assert run("whoami", "--json") == 0
    captured = capsys.readouterr()
    shown = json.loads(captured.out)
    assert shown["source"] == "env" and shown["account"]["email"] == "ops@acme.test"
    assert "overrides the login stored for this profile (ana@acme.test)" in captured.err


def test_whoami_names_the_user_a_key_acts_for_and_never_the_account(home, api, capsys):
    api.get("/v1/status").respond(json=status_of(
        {"id": None, "name": None, "email": None,
         "acting_for": {"id": USER_ID, "name": "Bo Diaz", "email": "bo@acme.test"}}))
    assert run("whoami") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"User     {USER_ID} (Bo Diaz, bo@acme.test): the key acts for this user, not the account"
    assert "Account" not in out


def test_whoami_says_which_key_the_api_refused(home, api, capsys):
    api.get("/v1/status").respond(401, json={"error": {
        "type": "unauthenticated", "message": "This API key was revoked.", "next_step": "Run noclick login."}})
    assert run("whoami") == 1
    captured = capsys.readouterr()
    assert "nk_live_test…, from NOCLICK_API_KEY" in captured.out and "Account" not in captured.out
    assert "This API key was revoked." in captured.err


def test_the_stored_key_signs_calls_on_its_own_api(home, monkeypatch, api):
    signed_in_with_login(home, monkeypatch)
    monkeypatch.delenv("NOCLICK_API_URL")
    route = api.get("/v1/users").respond(json=listing())
    assert run("users", "list") == 0
    assert route.calls.last.request.headers["authorization"] == "Bearer nk_live_cli9f2c1a77"


def test_logout_revokes_the_key_then_forgets_it(home, monkeypatch, api, capsys):
    signed_in_with_login(home, monkeypatch)
    revoke = api.delete("/v1/keys/current").respond(204)
    assert run("logout") == 0
    assert revoke.calls.last.request.headers["authorization"] == "Bearer nk_live_cli9f2c1a77"
    assert "Revoked the key \"CLI on ana-mbp\"." in capsys.readouterr().err
    assert home.keychain.saved == {}
    assert json.loads((home.config / "config.json").read_text()) == {"profiles": {}}


def test_logout_forgets_a_key_already_revoked_but_keeps_one_it_could_not_revoke(home, monkeypatch, api, capsys):
    signed_in_with_login(home, monkeypatch)
    api.delete("/v1/keys/current").respond(403, json={"error": {"type": "permission_denied", "message": "No."}})
    assert run("logout") == cli.exits.REFUSED
    assert home.keychain.saved  # kept, so you can retry
    api.delete("/v1/keys/current").respond(401, json={"error": {"type": "unauthenticated", "message": "Revoked."}})
    assert run("logout") == 0
    assert "already revoked" in capsys.readouterr().err and home.keychain.saved == {}


# --- agents, users, operations ------------------------------------------------------


def test_agents_list_prints_a_table_or_json(home, api, capsys):
    route = api.get("/v1/agents").respond(json=listing(agent_row(), agent_row(id="ag_2", name="concierge",
                                                                           user_id=USER_ID)))
    assert run("agents", "list") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["NAME", "MODEL", "USER", "CREATED", "ID"]
    assert out[1].split()[:3] == ["support", "openrouter/x", "account"]
    assert out[2].split()[:3] == ["concierge", "openrouter/x", USER_ID]
    assert "NoClick-User" not in route.calls.last.request.headers

    assert run("agents", "list", "--all-users", "--json") == 0
    assert route.calls.last.request.url.params["user_id"] == "all"
    assert [a["name"] for a in json.loads(capsys.readouterr().out)] == ["support", "concierge"]

    assert run("agents", "list", "--user", "user_42") == 0
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"


def _reply(text, conversation="conv_1", tools=()):
    return operation("op_m", kind="agent.message", status="succeeded", result={
        "text": text, "conversation": conversation, "tool_calls": [{"tool": t} for t in tools]})


def test_agents_chat_sends_one_message(home, api, capsys):
    api.get("/v1/agents").respond(json=listing(agent_row()))
    send = api.post("/v1/agents/ag_1/messages").respond(202, json=_reply("Lemon cake today.", tools=["search"]))
    assert run("agents", "chat", "support", "-m", "What's on?", "--user", "user_42") == 0
    out = capsys.readouterr()
    assert out.out == "Lemon cake today.\n"
    assert "(search)" in out.err and "continue it with --conversation conv_1" in out.err
    assert body(send.calls.last.request) == {"text": "What's on?"}
    assert send.calls.last.request.headers["NoClick-User"] == "user_42"


def test_agents_chat_as_a_user_prefers_their_own_agent_to_the_accounts(home, api, capsys):
    api.get("/v1/agents").respond(json=listing(agent_row(), agent_row(id="ag_2", user_id="user_42")))
    send = api.post("/v1/agents/ag_2/messages").respond(202, json=_reply("Yours."))
    assert run("agents", "chat", "support", "-m", "hi", "--user", "user_42") == 0
    assert send.call_count == 1 and capsys.readouterr().out == "Yours.\n"
    api.get("/v1/agents").respond(json=listing())
    assert run("agents", "chat", "ghost", "-m", "hi") == 1
    # An expired agent of the name takes no turns: the account's live one answers.
    api.get("/v1/agents").respond(json=listing(agent_row(id="ag_3", user_id="user_42", status="expired"), agent_row()))
    account = api.post("/v1/agents/ag_1/messages").respond(202, json=_reply("The account's."))
    assert run("agents", "chat", "support", "-m", "hi", "--user", "user_42") == 0
    assert account.call_count == 1


def test_agents_chat_keeps_the_thread_across_piped_lines(home, api, monkeypatch, capsys):
    api.get("/v1/agents").respond(json=listing(agent_row()))
    send = api.post("/v1/agents/ag_1/messages").mock(side_effect=[
        httpx.Response(202, json=_reply("Hi Ana.")), httpx.Response(202, json=_reply("Booked.")),
    ])
    monkeypatch.setattr(sys, "stdin", io.StringIO("hello\n\nbook Friday\n/exit\nnever sent\n"))
    assert run("agents", "chat", "support") == 0
    assert [body(c.request) for c in send.calls] == [
        {"text": "hello"}, {"text": "book Friday", "conversation": "conv_1"},
    ]
    assert capsys.readouterr().out == "Hi Ana.\nBooked.\n"


def test_users_list_and_create(home, api, capsys):
    listed = api.get("/v1/users").respond(json=listing(user_row(name="Ana Silva", email="ana@acme.test")))
    assert run("users", "list", "--q", "ana", "--limit", "5") == 0
    assert listed.calls.last.request.url.params["q"] == "ana"
    assert "user_42" in capsys.readouterr().out

    create = api.post("/v1/users").respond(201, json=user_row("globex"))
    assert run("users", "create", "globex", "--name", "Globex", "--spend-cap", "200") == 0
    assert body(create.calls.last.request) == {"id": "globex", "name": "Globex", "spend_cap_usd_per_month": 200.0}
    assert capsys.readouterr().out.strip() == "globex"


def test_ops_wait_prints_the_result(home, api, capsys):
    api.get("/v1/operations/op_1/wait").respond(json=operation(
        "op_1", kind="agent.message", status="succeeded", result={"text": "Done.", "conversation": "c"}))
    assert run("ops", "wait", "op_1") == 0
    out = capsys.readouterr()
    assert out.out == "Done.\n" and "agent.message succeeded" in out.err

    api.get("/v1/operations/op_2/wait").respond(json=operation("op_2", kind="x.y", status="succeeded", result={"n": 1}))
    assert run("ops", "wait", "op_2", "--json") == 0
    assert json.loads(capsys.readouterr().out)["result"] == {"n": 1}


def test_ops_wait_exit_codes(home, api, capsys):
    api.get("/v1/operations/op_f/wait").respond(json=operation(
        "op_f", status="failed", error={"type": "operation_failed", "message": "The build failed."}))
    assert run("ops", "wait", "op_f") == 1
    assert "error: The build failed." in capsys.readouterr().err

    api.get("/v1/operations/op_r").respond(json=operation("op_r", status="running"))
    assert run("ops", "wait", "op_r", "--timeout", "0") == cli.exits.TIMED_OUT


# --- databases and storage ------------------------------------------------------------

DB = {"object": "database", "id": "db_1", "name": "booking-db", "engine": "sqlite", "status": "ready",
      "size_bytes": 1_800_000_000, "table_count": 4, "user_id": None, "created_at": "2026-09-01T10:00:00Z"}


def test_db_query_reads_unless_told_to_write(home, api, capsys):
    lookup = api.get("/v1/databases").respond(json=listing(DB))
    query = api.post("/v1/databases/db_1/query").mock(side_effect=[
        httpx.Response(200, json={"columns": ["id", "guest"], "rows": [{"id": 42, "guest": "Ana"}],
                                  "rows_read": 1, "rows_written": 0, "duration_ms": 3.2}),
        httpx.Response(200, json={"columns": [], "rows": [], "rows_read": 0, "rows_written": 1, "duration_ms": 4}),
    ])
    assert run("db", "query", "booking-db", "select id, guest from bookings where id = ?", "-p", "42") == 0
    assert lookup.calls.last.request.url.params["name"] == "booking-db"
    assert body(query.calls.last.request) == {
        "sql": "select id, guest from bookings where id = ?", "params": [42], "read_only": True}
    out = capsys.readouterr()
    assert out.out.splitlines() == ["id  guest", "42  Ana"] and "1 row (3 ms)" in out.err

    assert run("db", "query", "booking-db", "update bookings set guest = ? where id = 42", "-p", "Bo", "--write") == 0
    assert body(query.calls.last.request) == {"sql": "update bookings set guest = ? where id = 42", "params": ["Bo"]}
    assert "1 row written (4 ms)" in capsys.readouterr().err


def test_db_shell_runs_statements_and_dot_commands(home, api, monkeypatch, capsys):
    api.get("/v1/databases").respond(json=listing(DB))
    api.get("/v1/databases/db_1/schema").respond(json={"data": [{"name": "bookings", "row_count": 18204, "columns": [
        {"name": "id", "type": "integer", "nullable": False, "primary_key": True},
        {"name": "guest", "type": "text", "nullable": True}]}]})
    query = api.post("/v1/databases/db_1/query").mock(side_effect=[
        httpx.Response(400, json={"error": {"type": "invalid_request", "message": "no such table: guests"}}),
        httpx.Response(200, json={"columns": ["n"], "rows": [{"n": 1}], "duration_ms": 1}),
    ])
    monkeypatch.setattr(sys, "stdin", io.StringIO(".tables\n.schema bookings\nselect * from guests;\nselect 1\n as n;\n.quit\n"))
    assert run("db", "shell", "booking-db") == 0
    out = capsys.readouterr()
    assert "bookings  18204" in out.out and "  id  integer primary key" in out.out and "  guest  text" in out.out
    assert "error: no such table: guests" in out.err  # the shell stays open after a SQL error
    assert body(query.calls.last.request) == {"sql": "select 1\n as n;", "read_only": True}


def test_a_service_not_enabled_yet_says_so(home, api, capsys):
    api.get("/v1/databases").respond(409, json={"error": {
        "type": "not_available", "message": "Databases aren't enabled on this deployment yet.",
        "next_step": "Try again once they are."}}, headers={"X-Request-Id": "req_9"})
    assert run("db", "query", "booking-db", "select 1") == 1
    err = capsys.readouterr().err
    assert "error: Databases aren't enabled on this deployment yet." in err and "request id: req_9" in err


BUCKET = {"object": "bucket", "id": "bkt_1", "name": "uploads", "public": False, "size_bytes": 42_100_000_000,
          "object_count": 18204, "user_id": None, "created_at": "2026-09-01T10:00:00Z"}


def _objects(request):
    """GET /objects lists without ``key`` and reads one file with it."""
    params = request.url.params
    if "key" in params:
        return httpx.Response(200, content=b"%PDF-0042")
    return httpx.Response(200, json=listing(
        {"key": "invoices/", "folder": True},
        {"key": "invoices/0042.pdf", "size": 9, "updated_at": "2026-09-27T08:00:00Z"},
    ))


def test_bucket_ls_lists_buckets_then_one_level(home, api, capsys):
    buckets = api.get("/v1/buckets").respond(json=listing(BUCKET))
    objects = api.get("/v1/buckets/bkt_1/objects").mock(side_effect=_objects)
    assert run("bucket", "ls") == 0
    assert "name" not in buckets.calls.last.request.url.params
    assert "uploads  no      42.1 GB  18204" in capsys.readouterr().out

    assert run("bucket", "ls", "uploads/invoices/") == 0
    params = objects.calls.last.request.url.params
    assert (params["prefix"], params["delimiter"]) == ("invoices/", "/")
    out = capsys.readouterr().out.splitlines()
    assert out[1].split() == ["-", "-", "invoices/"] and out[2].split()[-1] == "invoices/0042.pdf"

    assert run("bucket", "ls", "uploads:invoices/", "-r") == 0
    assert "delimiter" not in objects.calls.last.request.url.params


def test_bucket_cp_uploads_and_downloads(home, api, tmp_path, capsys):
    api.get("/v1/buckets").respond(json=listing(BUCKET))
    put = api.put("/v1/buckets/bkt_1/objects").respond(json={"key": "invoices/0042.pdf", "size": 9})
    read = api.get("/v1/buckets/bkt_1/objects").mock(side_effect=_objects)
    pdf = tmp_path / "0042.pdf"
    pdf.write_bytes(b"%PDF-0042")

    assert run("bucket", "cp", str(pdf), "uploads:invoices/") == 0
    params = put.calls.last.request.url.params
    assert (params["key"], params["content_type"]) == ("invoices/0042.pdf", "application/pdf")
    assert put.calls.last.request.content == b"%PDF-0042"

    site = tmp_path / "dist"
    (site / "css").mkdir(parents=True)
    (site / "index.html").write_text("<h1>hi</h1>")
    (site / "css" / "app.css").write_text("h1{}")
    assert run("bucket", "cp", "-r", str(site), "uploads:site") == 0
    assert [c.request.url.params["key"] for c in put.calls[-2:]] == ["site/css/app.css", "site/index.html"]

    out_dir = tmp_path / "down"
    out_dir.mkdir()
    assert run("bucket", "cp", "uploads:invoices/0042.pdf", str(out_dir)) == 0
    assert read.calls.last.request.url.params["key"] == "invoices/0042.pdf"
    assert (out_dir / "0042.pdf").read_bytes() == b"%PDF-0042"


def test_bucket_cp_needs_exactly_one_bucket_side(home, api, capsys):
    route = api.get("/v1/buckets").respond(json=listing(BUCKET))
    assert run("bucket", "cp", "a.txt", "b.txt") == 1
    assert "exactly one side is bucket:key" in capsys.readouterr().err and route.call_count == 0


# --- apps -----------------------------------------------------------------------------

PROJECT = {"object": "project", "id": "prj_1", "name": "booking", "url": "https://booking.noclick.site",
           "repo_id": "repo_1", "production_branch": "main", "user_id": None}
DEPLOYMENT = {"object": "deployment", "id": "dep_1", "project_id": "prj_1", "branch": "main", "commit": SHA,
              "status": "ready", "url": "https://booking.noclick.site", "production": True}


class FakeGit:
    def __init__(self, *, dirty="", branch="main", push_stderr=None):
        self.calls = []
        self.outputs = {"rev-parse --show-toplevel": "/work/booking", "status": dirty, "symbolic-ref": branch,
                        "rev-parse HEAD": SHA}
        self.push_stderr = push_stderr

    def __call__(self, *args, cwd=None, env=None):
        self.calls.append((args, env))
        if args[0] == "push" and self.push_stderr:
            raise cli.CommandError("push failed", details={"stderr": self.push_stderr})
        for prefix, output in self.outputs.items():
            if " ".join(args).startswith(prefix):
                return output
        return ""


def _deploy_routes(api, deploy_status="succeeded", **op):
    api.get("/v1/projects").respond(json=listing(PROJECT))
    clone = api.post("/v1/repos/repo_1/clone_url").respond(json={"url": "https://x:tok_9@git.noclick.test/booking.git"})
    deploy = api.post("/v1/projects/prj_1/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status=deploy_status, result=DEPLOYMENT if deploy_status == "succeeded" else None,
        **op))
    return clone, deploy


def test_deploy_pushes_the_commit_then_deploys_it(home, api, monkeypatch, capsys):
    git = FakeGit()
    monkeypatch.setattr(cli, "_git", git)
    clone, deploy = _deploy_routes(api)
    assert run("deploy") == 0  # the app named after the checkout's folder
    assert body(clone.calls.last.request) == {"write": True, "ttl_s": 600}
    [(push_args, push_env)] = [(a, e) for a, e in git.calls if a[0] == "push"]
    assert push_args == ("push", "noclick-deploy", "HEAD:refs/heads/main")
    assert push_env["GIT_CONFIG_VALUE_0"] == "https://x:tok_9@git.noclick.test/booking.git"  # never in argv
    assert body(deploy.calls.last.request) == {"branch": "main", "commit": SHA}
    out = capsys.readouterr()
    assert out.out == "https://booking.noclick.site\n"
    assert "Pushed 3f2a1c9 to main." in out.err and "Ready: production." in out.err


WARNED = {**DEPLOYMENT, "warning": "It's live, but https://booking.noclick.site/ answered 404: there's no home page.",
          "next_step": "Publish the folder holding index.html, then deploy again."}


def test_a_deploy_live_but_failing_its_check_prints_the_warning_and_exits_1(home, api, monkeypatch, capsys):
    """The CLI once printed the URL and "Ready" and exited 0 for a site whose / answered 404 (2026-11-19)."""
    monkeypatch.setattr(cli, "_git", FakeGit())
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.post("/v1/repos/repo_1/clone_url").respond(json={"url": "https://x:tok_9@git.noclick.test/booking.git"})
    deploy = api.post("/v1/projects/prj_1/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=WARNED))
    assert run("deploy") == 1
    out = capsys.readouterr()
    assert out.out == "https://booking.noclick.site\n"  # it's live: its URL still goes to stdout
    assert f"warning: {WARNED['warning']}" in out.err and f"next step: {WARNED['next_step']}" in out.err
    assert "Live, but not working: production stays deployed" in out.err and "Ready" not in out.err

    # Its code never ran: said, and not a failure.
    unchecked = {**DEPLOYMENT, "code_unchecked": "Static files answered every path asked."}
    deploy.respond(202, json=operation("op_e", kind="project.deploy", status="succeeded", result=unchecked))
    assert run("deploy") == 0
    err = capsys.readouterr().err
    assert "note: Static files answered every path asked." in err and "Ready: production." in err

    # Waited on later, the same.
    api.get("/v1/operations/op_d/wait").respond(json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=WARNED))
    assert run("ops", "wait", "op_d") == 1
    assert f"next step: {WARNED['next_step']}" in capsys.readouterr().err
    assert run("ops", "wait", "op_d", "--json") == 1
    assert json.loads(capsys.readouterr().out)["result"]["warning"] == WARNED["warning"]

    # A promote (a rollback too) is looked at as a deploy is, and a wait on one reads the same way.
    api.get("/v1/operations/op_p/wait").respond(json=operation(
        "op_p", kind="deployment.promote", status="succeeded", result=WARNED))
    assert run("ops", "wait", "op_p") == 1
    assert f"warning: {WARNED['warning']}" in capsys.readouterr().err


def test_deploy_with_a_deploy_token_signs_in_with_it_alone(home, api, monkeypatch, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY")  # an agent's shell: no key, no login
    monkeypatch.setattr(cli, "_git", FakeGit())
    clone, deploy = _deploy_routes(api)
    assert run("deploy", "--app", "booking", "--token", "nk_mcp_deploy") == 0
    for route in (clone, deploy):
        assert route.calls.last.request.headers["authorization"] == "Bearer nk_mcp_deploy"
    assert capsys.readouterr().out == "https://booking.noclick.site\n"
    assert run("deploy", "other", "--app", "booking", "--token", "nk_mcp_deploy") == 1
    assert "Two apps named" in capsys.readouterr().err


def test_deploy_sets_the_app_budget(home, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", FakeGit())
    _, deploy = _deploy_routes(api)
    patch = api.patch("/v1/projects/prj_1").respond(json={**PROJECT, "budget_usd_per_month": 25})
    assert run("deploy", "--budget", "25") == 0
    assert body(patch.calls.last.request) == {"budget_usd_per_month": 25.0}
    assert deploy.call_count == 1
    assert run("deploy") == 0 and patch.call_count == 1  # left out, the budget stays as it is


def test_deploy_refuses_a_dirty_checkout_or_a_detached_head(home, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", FakeGit(dirty=" M src/app.ts"))
    assert run("deploy") == 1
    assert "uncommitted changes" in capsys.readouterr().err

    detached = FakeGit()

    def no_branch(*args, cwd=None, env=None):
        if args[0] == "symbolic-ref":
            raise cli.CommandError("fatal: ref HEAD is not a symbolic ref", details={"stderr": "fatal: ..."})
        return detached(*args, cwd=cwd, env=env)

    monkeypatch.setattr(cli, "_git", no_branch)
    assert run("deploy") == 1
    assert "Pass --branch" in capsys.readouterr().err


def test_deploy_fetches_what_a_rejected_push_was_missing(home, api, monkeypatch, capsys):
    git = FakeGit(push_stderr=" ! [rejected]        HEAD -> main (fetch first)\n")
    monkeypatch.setattr(cli, "_git", git)
    _, deploy = _deploy_routes(api)
    assert run("deploy", "--branch", "main") == 1
    assert ("fetch", "noclick-deploy", "+refs/heads/main:refs/remotes/noclick/main") in [a for a, _ in git.calls]
    assert "git merge noclick/main" in capsys.readouterr().err
    assert deploy.call_count == 0


@pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="needs git")
def test_a_push_to_a_git_endpoint_that_sends_nothing_gives_up_saying_so(tmp_path, monkeypatch):
    """Real git against a socket that takes the request and never answers: the push ends, never waits on."""
    import socket
    import threading
    import time

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    held = []
    threading.Thread(target=lambda: held.append(listener.accept()), daemon=True).start()
    work = tmp_path / "app"
    work.mkdir()
    for args in (["init", "-q", "-b", "main"], ["-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-q",
                                                "--allow-empty", "-m", "start"]):
        subprocess.run(["git", *args], cwd=work, check=True)
    monkeypatch.setattr(cli, "GIT_GIVE_UP_S", 2)
    started = time.monotonic()
    try:
        with pytest.raises(cli.CommandError) as gave_up:
            cli._push(str(work), f"http://t:secret@127.0.0.1:{listener.getsockname()[1]}/app.git", "main")
    finally:
        listener.close()
    assert time.monotonic() - started < 30
    assert gave_up.value.message == "The repo's git endpoint sent nothing for 2 seconds, so the push gave up."
    assert gave_up.value.next_step == "Deploy again."


def test_deploy_names_a_missing_app_and_can_create_it(home, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", FakeGit(branch="new-form"))
    api.get("/v1/projects").respond(json=listing())
    assert run("deploy") == 1
    assert "Pass --create" in capsys.readouterr().err

    api.get("/v1/repos").respond(json=listing())
    make_repo = api.post("/v1/repos").respond(201, json={"object": "repo", "id": "repo_1", "name": "booking"})
    make_app = api.post("/v1/projects").respond(201, json=PROJECT)
    api.post("/v1/repos/repo_1/clone_url").respond(json={"url": "https://git.noclick.test/booking.git"})
    deploy = api.post("/v1/projects/prj_1/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded",
        result={**DEPLOYMENT, "branch": "new-form", "production": False, "url": "https://new-form--booking.noclick.site"}))
    assert run("deploy", "--create", "--budget", "10") == 0
    assert body(make_repo.calls.last.request)["name"] == "booking"
    assert body(make_app.calls.last.request) == {"name": "booking", "repo_id": "repo_1", "budget_usd_per_month": 10.0}
    assert body(deploy.calls.last.request) == {"branch": "new-form", "commit": SHA}
    out = capsys.readouterr()
    assert out.out == "https://new-form--booking.noclick.site\n" and "a preview of new-form" in out.err


def test_a_failed_deploy_shows_the_end_of_its_build_log(home, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", FakeGit())
    _deploy_routes(api, deploy_status="failed", error={
        "type": "operation_failed", "message": "The build failed.", "deployment_id": "dep_9"})
    build = api.get("/v1/deployments/dep_9/logs").respond(json=listing(
        {"at": "2026-09-28T10:00:00Z", "level": "info", "message": "npm run build"},
        {"at": "2026-09-28T10:00:04Z", "level": "error", "message": "Cannot find module './form'"}))
    assert run("deploy", "--no-wait") == 0 and capsys.readouterr().out == "op_d\n"
    assert run("deploy") == 1
    assert build.calls.last.request.url.params["kind"] == "build"
    err = capsys.readouterr().err
    assert "  Cannot find module './form'" in err and "error: The build failed." in err


def test_logs_follows_from_the_last_line(home, api, monkeypatch, capsys):
    api.get("/v1/projects").respond(json=listing(PROJECT))
    booking_failed = {"at": "2026-09-28T10:00:00Z", "level": "error", "message": "POST /book 500"}
    logs = api.get("/v1/projects/prj_1/logs").mock(side_effect=[
        httpx.Response(200, json=listing(booking_failed)),
        httpx.Response(200, json=listing(  # read from the last line's time, so it comes back once more
            booking_failed, {"at": "2026-09-28T10:00:02Z", "level": "error", "message": "POST /pay 502"})),
    ])
    monkeypatch.setattr(cli, "_sleep", stop_after(2))
    assert run("logs", "booking", "--follow", "--level", "error") == 0
    first, second = (c.request.url.params for c in logs.calls)
    assert "since" not in first and first["level"] == "error"
    assert second["since"].startswith("2026-09-28T10:00:00")
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["ERROR  POST /book 500", "ERROR  POST /pay 502"]


# --- domains --------------------------------------------------------------------------


def test_domains_search_prints_prices(home, api, capsys):
    search = api.get("/v1/domains/search").respond(json=listing(
        {"name": "acmebooking.com", "available": True, "price_usd": 11.25, "renewal_usd": 12.5, "premium": False},
        {"name": "acmebooking.app", "available": False}))
    assert run("domains", "search", "acmebooking", "--tld", "com", "--tld", "app") == 0
    assert search.calls.last.request.url.params["tlds"] == "com,app"
    out = capsys.readouterr().out.splitlines()
    assert out[1].split() == ["acmebooking.com", "yes", "$11.25", "$12.50", "no"]


def test_domains_buy_for_a_user_registers_it_to_them_and_waits_through_approval(home, api, capsys, tmp_path):
    ana = {"name": "Ana Silva", "email": "ana@example.com", "phone": "+14155550123", "address": "500 Market St",
           "city": "San Francisco", "region": "CA", "postal_code": "94105", "country": "US",
           "agreement_accepted_at": "2026-10-02T09:30:00+00:00"}
    (tmp_path / "ana.json").write_text(json.dumps(ana))
    buy = api.post("/v1/domains").respond(202, json=operation(
        "op_dom", kind="domain.buy", status="awaiting_human", price_usd=14))
    api.get("/v1/operations/op_dom").mock(side_effect=[
        httpx.Response(200, json=operation("op_dom", kind="domain.buy", status="awaiting_human")),
        httpx.Response(200, json=operation("op_dom", kind="domain.buy", status="succeeded", result={"domain": {
            "object": "domain", "id": "dom_1", "name": "anasilva.dev", "status": "active",
            "expires_at": "2027-09-28T10:00:00Z"}}, updated_at="2026-09-28T10:05:00Z")),
    ])
    assert run("domains", "buy", "anasilva.dev", "--max-price", "15", "--user", "user_42",
               "--registrant", str(tmp_path / "ana.json")) == 0
    request = buy.calls.last.request
    assert body(request) == {"name": "anasilva.dev", "max_price_usd": 15.0, "auto_renew": True, "registrant": ana}
    assert request.headers["NoClick-User"] == "user_42"
    out = capsys.readouterr()
    assert out.out == "anasilva.dev\n"
    assert "Waiting for someone to approve the purchase" in out.err and "/pay/" not in out.err
    assert "anasilva.dev is yours (active)" in out.err


def test_domains_buy_for_a_user_without_details_uses_their_registrant_profile(home, api, capsys):
    buy = api.post("/v1/domains").respond(202, json=operation("op_dom", kind="domain.buy", status="running"))
    assert run("domains", "buy", "anasilva.dev", "--max-price", "15", "--user", "user_42", "--no-wait") == 0
    request = buy.calls.last.request
    assert body(request) == {"name": "anasilva.dev", "max_price_usd": 15.0, "auto_renew": True}
    assert request.headers["NoClick-User"] == "user_42"


def test_domains_buy_for_the_account_uses_its_default_registrant(home, api, capsys):
    buy = api.post("/v1/domains").respond(202, json=operation("op_dom", kind="domain.buy", status="running"))
    assert run("domains", "buy", "acmebooking.com", "--max-price", "15", "--years", "2", "--no-wait") == 0
    assert body(buy.calls.last.request) == {"name": "acmebooking.com", "max_price_usd": 15.0, "years": 2,
                                            "auto_renew": True}
    assert capsys.readouterr().out == "op_dom\n"


def test_domains_buy_refused_above_the_ceiling(home, api, capsys):
    api.post("/v1/domains").respond(402, json={"error": {
        "type": "price_exceeded", "message": "acmebooking.com costs $89.00, above your $15.00 ceiling."}})
    assert run("domains", "buy", "acmebooking.com", "--max-price", "15") == cli.exits.REFUSED
    assert "above your $15.00 ceiling" in capsys.readouterr().err


# --- webhooks ----------------------------------------------------------------------


def test_webhooks_listen_forwards_each_event_signed(home, api, monkeypatch, capsys):
    event = {"object": "event", "id": "evt_1", "type": "operation.succeeded", "data": {"id": "op_1"},
             "user_id": None, "created_at": "2026-09-28T10:00:01Z"}
    events = api.get("/v1/events").mock(side_effect=[
        httpx.Response(200, json=listing(event)),
        httpx.Response(200, json=listing(event)),  # `since` is inclusive: the boundary event comes back once more
    ])
    local = api.post("http://localhost:3000/hooks").respond(204)
    monkeypatch.setattr(cli, "_sleep", stop_after(2))
    assert run("webhooks", "listen", "--forward-to", "http://localhost:3000/hooks", "--events", "operation.*",
               "--secret", "nk_whsec_test") == 0
    first, second = (c.request.url.params for c in events.calls)
    assert (first["type"], first["user_id"]) == ("operation.*", "all")
    assert second["since"].startswith("2026-09-28T10:00:01")
    assert local.call_count == 1
    delivered = local.calls.last.request
    got = nc.Webhook.verify(delivered.content, delivered.headers, "nk_whsec_test")
    assert (got.id, got.type) == ("evt_1", "operation.succeeded")
    [line] = capsys.readouterr().out.splitlines()
    assert line.split()[1:] == ["operation.succeeded", "evt_1", "->", "204", "No", "Content"]


def test_webhooks_listen_reports_an_unreachable_receiver(home, api, monkeypatch, capsys):
    events = api.get("/v1/events").respond(json=listing({"object": "event", "id": "evt_2", "type": "human.answered",
                                                         "data": {}, "created_at": "2026-09-28T10:00:01Z"}))
    api.post("http://localhost:3999/hooks").mock(side_effect=httpx.ConnectError("refused"))
    monkeypatch.setattr(cli, "_sleep", stop_after(1))
    assert run("webhooks", "listen", "--forward-to", "http://localhost:3999/hooks", "--user", "user_42") == 0
    assert events.calls.last.request.url.params["user_id"] == "user_42"
    out = capsys.readouterr()
    assert "evt_2  -> failed: ConnectError" in out.out
    assert "Signing secret for this session: nk_whsec_" in out.err


def test_push_and_rejection_with_real_git(tmp_path, monkeypatch):
    for name, value in {"GIT_AUTHOR_NAME": "Ana", "GIT_AUTHOR_EMAIL": "ana@acme.test", "GIT_COMMITTER_NAME": "Ana",
                        "GIT_COMMITTER_EMAIL": "ana@acme.test"}.items():
        monkeypatch.setenv(name, value)
    remote, work, other = tmp_path / "remote.git", tmp_path / "booking", tmp_path / "other"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "app.py").write_text("print('v1')\n")
    cli._git("add", ".", cwd=str(work))
    cli._git("commit", "-qm", "v1", cwd=str(work))

    cli._push(str(work), remote.as_uri(), "main")
    assert cli._git("rev-parse", "main", cwd=str(remote)) == cli._git("rev-parse", "HEAD", cwd=str(work))
    assert "remote.git" not in (work / ".git" / "config").read_text()  # the URL was never saved

    subprocess.run(["git", "clone", "-q", remote.as_uri(), str(other)], check=True)
    (other / "sign_in.py").write_text("# committed by an app service\n")
    cli._git("add", ".", cwd=str(other))
    cli._git("commit", "-qm", "Add sign-in", cwd=str(other))
    cli._push(str(other), remote.as_uri(), "main")  # the repo moves on without this checkout
    with pytest.raises(nc.Conflict) as refused:
        cli._push(str(work), remote.as_uri(), "main")
    assert "git merge noclick/main" in refused.value.next_step
    assert cli._git("log", "-1", "--format=%s", "noclick/main", cwd=str(work)) == "Add sign-in"


# --- machines ------------------------------------------------------------------

MACHINE_ID = "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b40"


class _Tty:
    """A terminal for the CLI's stdin: the slave end of a real PTY."""

    def __init__(self, fd):
        self._fd = fd

    def fileno(self):
        return self._fd

    def isatty(self):
        return True


def test_machines_ssh_opens_the_machines_shell_in_this_terminal(home, api, monkeypatch, capsys):
    import pty
    import threading

    from websockets.sync.server import serve

    seen = {}

    def shell(socket):
        seen["auth"] = json.loads(socket.recv())
        socket.send(json.dumps({"type": "ready", "state": "open", "cols": 100, "rows": 30}))
        seen["typed"] = socket.recv()
        socket.send(b"noclick@support-box:~$ " + seen["typed"])
        socket.send(json.dumps({"type": "state", "state": "exited", "reason": "exited", "exit_code": 3}))
        socket.close(4410, "The shell ended.")

    server = serve(shell, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.socket.getsockname()[1]
    api.get("/v1/machines").respond(json=listing({"object": "machine", "id": MACHINE_ID, "name": "support-box",
                                                  "kind": "noclick", "status": "running"}))
    opened = api.post(f"/v1/machines/{MACHINE_ID}/shell").respond(json={
        "object": "machine_shell", "machine_id": MACHINE_ID, "url": f"ws://127.0.0.1:{port}/v1/terminals/attach",
        "token": "tok_1", "token_expires_at": "2026-11-16T10:02:00Z", "idle_limit_s": 900})
    master, slave = pty.openpty()
    monkeypatch.setattr(sys, "stdin", _Tty(slave))
    os.write(master, b"df -h\r")

    def screen():  # the terminal emulator's side reads what the terminal echoes, so its output drains
        try:
            while os.read(master, 4096):
                pass
        except OSError:
            return
    threading.Thread(target=screen, daemon=True).start()
    try:
        assert run("machines", "ssh", "support-box") == 3
    finally:
        server.shutdown()
        os.write(master, b"x\n")  # wakes the CLI's reader (cooked again) on its closed socket, which then ends
        time.sleep(0.2)
        os.close(slave)
        os.close(master)
    assert opened.called and seen["auth"]["token"] == "tok_1" and seen["auth"]["type"] == "auth"
    assert seen["typed"].startswith(b"df -h")
    assert "noclick@support-box:~$ df -h" in capsys.readouterr().out


def test_machines_ssh_renews_its_shell_in_place_when_asked(home, api, monkeypatch, capsys):
    import pty
    import threading

    from websockets.sync.server import serve

    seen = {"other": []}

    def shell(socket):
        seen["auth"] = json.loads(socket.recv())
        socket.send(json.dumps({"type": "ready", "state": "open", "cols": 100, "rows": 30}))
        socket.send(json.dumps({"type": "renew"}))
        while "renew" not in seen:  # what's typed meanwhile still comes in; no answer within seconds fails the test
            message = socket.recv(timeout=5)
            said = json.loads(message) if isinstance(message, str) else {}
            if said.get("type") == "renew":
                seen["renew"] = said
            else:
                seen["other"].append(message)
        socket.send(json.dumps({"type": "renewed"}))
        socket.send(b"still here\r\n")
        socket.send(json.dumps({"type": "state", "state": "exited", "reason": "exited", "exit_code": 0}))
        socket.close(4410, "The shell ended.")

    server = serve(shell, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.socket.getsockname()[1]
    api.get("/v1/machines").respond(json=listing({"object": "machine", "id": MACHINE_ID, "name": "support-box",
                                                  "kind": "noclick", "status": "running"}))
    view = {"object": "machine_shell", "machine_id": MACHINE_ID, "url": f"ws://127.0.0.1:{port}/v1/terminals/attach",
            "token_expires_at": "2026-11-16T10:02:00Z", "idle_limit_s": 900}
    opened = api.post(f"/v1/machines/{MACHINE_ID}/shell").mock(side_effect=[
        httpx.Response(200, json={**view, "token": "tok_1"}), httpx.Response(200, json={**view, "token": "tok_2"})])
    master, slave = pty.openpty()
    monkeypatch.setattr(sys, "stdin", _Tty(slave))

    def screen():
        try:
            while os.read(master, 4096):
                pass
        except OSError:
            return
    threading.Thread(target=screen, daemon=True).start()
    try:
        assert run("machines", "ssh", "support-box") == 0
    finally:
        server.shutdown()
        os.write(master, b"x\n")
        time.sleep(0.2)
        os.close(slave)
        os.close(master)
    assert opened.call_count == 2 and seen["auth"]["token"] == "tok_1" and seen["auth"]["renew"] is True
    assert seen["renew"] == {"type": "renew", "token": "tok_2"}
    assert "still here" in capsys.readouterr().out


def test_machines_ssh_needs_a_terminal(home, api, monkeypatch, capsys):
    api.get("/v1/machines").respond(json=listing({"object": "machine", "id": MACHINE_ID, "name": "support-box"}))
    api.post(f"/v1/machines/{MACHINE_ID}/shell").respond(json={
        "object": "machine_shell", "machine_id": MACHINE_ID, "url": "ws://127.0.0.1:9/x", "token": "t",
        "token_expires_at": None, "idle_limit_s": 900})
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert run("machines", "ssh", "support-box") == 1
    assert "needs a terminal" in capsys.readouterr().err


# --- estimate --------------------------------------------------------------------------


_ESTIMATE_LINE = {"description": "d", "usage_fields": ["requests"]}
_ESTIMATE = {
    "object": "estimate", "estimated": True, "monthly_usd": 0.29,
    "plan": {"name": "free", "billing": "at_cost"}, "included_usd_per_month": 5.0,
    "items": [{"kind": "project", "label": "App on the edge", "name": "site", "options": {"runtime": "edge"},
               "usage": {"requests": 100000.0}, "assumed": ["framework", "releases"], "monthly_usd": 0.29,
               "lines": [{**_ESTIMATE_LINE, "charge": "front_door", "unit": "million requests", "unit_usd": 1.9,
                          "quantity": 0.1, "usd": 0.19, "assumed": False},
                         {**_ESTIMATE_LINE, "charge": "releases", "unit": "release-month", "unit_usd": 0.02,
                          "quantity": 5, "usd": 0.1, "assumed": True}],
               "not_included": ["The front door's CPU time."]}],
}


def test_estimate_prices_a_file_of_items_as_a_table_or_json(home, api, tmp_path, monkeypatch, capsys):
    route = api.post("/v1/estimates").respond(json=_ESTIMATE)
    items = [{"kind": "project", "name": "site", "usage": {"requests": 100000}}]
    path = tmp_path / "stack.json"
    path.write_text(json.dumps({"items": items}))
    assert run("estimate", str(path)) == 0
    assert body(route.calls.last.request) == {"items": items}
    captured = capsys.readouterr()
    out = captured.out.splitlines()
    assert out[0].split() == ["ITEM", "CHARGE", "QUANTITY", "UNIT", "UNIT", "PRICE", "A", "MONTH"]
    assert out[1].split() == ["site", "front_door", "0.1", "million", "requests", "$1.9", "$0.1900"]
    assert out[2].split() == ["site", "releases", "*", "5", "release-month", "$0.02", "$0.1000"]
    assert "Total: $0.29 a month" in captured.out and "cover" not in captured.out
    assert "Assumed (site): framework, releases" in captured.err
    assert "* a default decided it" in captured.err and "Not included (site)" in captured.err

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(items)))
    assert run("estimate", "-", "--json") == 0
    assert json.loads(capsys.readouterr().out)["monthly_usd"] == 0.29


def test_estimate_lists_the_kinds_or_says_what_it_needs(home, api, tmp_path, capsys):
    route = api.get("/v1/estimates/kinds").respond(json=listing({
        "object": "estimate_kind", "kind": "bucket", "label": "Bucket", "description": "d", "options": {},
        "usage": [{"name": "storage_gb", "unit": "GB", "description": "d", "default": 1.0, "most": None}],
        "prices": [{"charge": "storage", "description": "d", "unit": "GB-month", "unit_usd": 0.015,
                    "usage_fields": ["storage_gb"]}], "not_included": []}))
    assert run("estimate", "--kinds", "--region", "eu") == 0
    assert route.calls.last.request.url.params["region"] == "eu"
    assert capsys.readouterr().out.splitlines()[1].split() == ["bucket", "storage", "$0.015", "GB-month",
                                                               "storage_gb", "(1)"]
    assert run("estimate") == 1
    assert "Name a JSON file" in capsys.readouterr().err
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    assert run("estimate", str(path)) == 1
    assert "isn't JSON" in capsys.readouterr().err


# --- what a hands-on review found (2026-11-25) ------------------------------------------


class Piped(io.StringIO):
    """A pipe's stdout: what reaches it is only what was flushed, so a line printed and not flushed is held (and lost
    when the command is stopped)."""

    def __init__(self):
        super().__init__()
        self.reached = ""

    def flush(self):
        self.reached = self.getvalue()


def test_what_a_command_prints_as_it_goes_reaches_a_pipe_at_once(home, api, monkeypatch):
    """logs -f, webhooks listen and a piped agents chat printed nothing into a pipe until they ended, and a stopped
    command lost all of it."""
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.get("/v1/projects/prj_1/logs").respond(json=listing(
        {"at": "2026-09-28T10:00:00Z", "level": "error", "message": "POST /book 500"}))
    piped = Piped()
    monkeypatch.setattr(sys, "stdout", piped)
    monkeypatch.setattr(cli, "_sleep", stop_after(1))
    assert run("logs", "booking", "-f") == 0
    assert piped.reached.endswith("POST /book 500\n")

    event = {"object": "event", "id": "evt_1", "type": "operation.succeeded", "data": {}, "user_id": None,
             "created_at": "2026-09-28T10:00:01Z"}
    api.get("/v1/events").respond(json=listing(event))
    api.post("http://localhost:3000/hooks").respond(204)
    monkeypatch.setattr(cli, "_sleep", stop_after(1))
    assert run("webhooks", "listen", "--forward-to", "http://localhost:3000/hooks") == 0
    assert piped.reached.endswith("evt_1  -> 204 No Content\n")

    api.get("/v1/agents").respond(json=listing(agent_row()))
    api.post("/v1/agents/ag_1/messages").respond(202, json=_reply("Booked."))
    monkeypatch.setattr(sys, "stdin", io.StringIO("book Friday\n"))
    assert run("agents", "chat", "support") == 0
    assert piped.reached.endswith("Booked.\n")


def test_logs_say_how_late_a_line_can_be_and_follow_reads_on_past_a_full_read(home, api, monkeypatch, capsys):
    api.get("/v1/projects").respond(json=listing(PROJECT))
    line = lambda second: {"at": f"2026-09-28T10:00:0{second}Z", "level": "info", "message": f"GET /{second}"}
    logs = api.get("/v1/projects/prj_1/logs").mock(side_effect=[
        httpx.Response(200, json={**listing(), "delay_s": 60}),
        # Followed: a read that came back full is read on from its last line at once, never after a wait.
        httpx.Response(200, json=listing(line(1), line(2))),
        httpx.Response(200, json=listing(line(2), line(3))),
        httpx.Response(200, json=listing(line(3))),
    ])
    assert run("logs", "booking") == 0
    assert "No lines. A line takes up to 60s to show after its request" in capsys.readouterr().err
    monkeypatch.setattr(cli, "_sleep", stop_after(2))
    assert run("logs", "booking", "-f", "--limit", "2") == 0
    assert [c.request.url.params.get("since", "")[:19] for c in logs.calls[1:]] == [
        "", "2026-09-28T10:00:02", "2026-09-28T10:00:03"]
    assert [row.split("  ")[-1].strip() for row in capsys.readouterr().out.splitlines()] == ["GET /1", "GET /2", "GET /3"]


def test_logs_build_prints_a_build_log_and_a_missing_app_is_an_app(home, api, capsys):
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.get("/v1/projects/prj_1/deployments").respond(json=listing({**DEPLOYMENT, "status": "failed"}))
    api.get("/v1/deployments/dep_1/logs").respond(json=listing(
        {"at": "2026-09-28T10:00:00Z", "level": "warn", "message": 'Set it as one of the app\'s settings, which reach '
                                                                    'the build (app.settings.set("API_URL", "..."))'}))
    assert run("logs", "booking", "--build") == 0
    out = capsys.readouterr()
    assert "Build log of dep_1 (main, 3f2a1c9, failed)" in out.err
    assert out.out == 'WARN   Set it as one of the app\'s settings, which reach the build (noclick settings set ' \
                      'booking "API_URL" "...")\n'

    api.get("/v1/projects").respond(json=listing())
    assert run("logs", "nccli-worker") == 1
    err = capsys.readouterr().err
    assert "error: No app is named 'nccli-worker'." in err
    assert "next step: Create it with its first deploy: noclick deploy nccli-worker --create" in err


@pytest.mark.parametrize("argv, route, answer, said, code", [
    # A write through a read (the API refused the call's arguments: usage): the flag that allows it, not the SDK method.
    (["db", "query", "booking-db", "delete from bookings"], ("POST", "/v1/databases/db_1/query"),
     httpx.Response(400, json={"error": {"type": "invalid_request", "message": "query runs read-only.",
                                         "next_step": "Run statements that write with execute (or batch)."}}),
     "next step: Run it again with --write.", 2),
    (["db", "query", "nope", "select 1"], None, None, "next step: Create it with: noclick db create nope", 1),
    (["bucket", "cp", "uploads:missing.pdf", "."], ("GET", "/v1/buckets/bkt_1/objects"),
     httpx.Response(404, json={"error": {"type": "not_found", "message": "No file at 'missing.pdf'.",
                                         "next_step": "List the bucket's files with GET .../objects."}}),
     "next step: List its files with: noclick bucket ls uploads", 1),
    (["ops", "wait", "op_f"], ("GET", "/v1/operations/op_f/wait"),
     httpx.Response(200, json=operation("op_f", kind="project.deploy", status="failed", error={
         "type": "operation_failed", "message": "The build failed.",
         "next_step": "Read its build log: GET /v1/deployments/dep_9/logs?kind=build."})),
     "next step: Read its build log: noclick logs --build --deployment dep_9", 1),
])
def test_a_next_step_names_the_command_that_takes_it(home, api, capsys, argv, route, answer, said, code):
    api.get("/v1/databases").respond(json=listing(DB))
    api.get("/v1/databases", params={"name": "nope"}).respond(json=listing())
    api.get("/v1/buckets").respond(json=listing(BUCKET))
    if route:
        api.request(*route).mock(return_value=answer)
    assert run(*argv) == code
    assert said in capsys.readouterr().err


def test_db_and_bucket_create_and_a_statement_that_defines_reports_no_rows(home, api, capsys):
    made = api.post("/v1/databases").respond(201, json=DB)
    assert run("db", "create", "booking-db", "--engine", "postgres") == 0
    assert body(made.calls.last.request) == {"name": "booking-db", "engine": "postgres"}
    assert capsys.readouterr().out == "booking-db\n"
    bucket = api.post("/v1/buckets").respond(201, json=BUCKET)
    assert run("bucket", "create", "uploads", "--public") == 0
    assert body(bucket.calls.last.request) == {"name": "uploads", "public": True}

    api.get("/v1/databases").respond(json=listing(DB))
    api.post("/v1/databases/db_1/query").respond(json={"columns": [], "rows": [], "rows_written": 2,
                                                         "duration_ms": 5})
    assert run("db", "query", "booking-db", "create table notes (id integer)", "--write") == 0
    err = capsys.readouterr().err
    assert "Done (5 ms)." in err and "written" not in err


def test_settings_set_list_and_delete(home, api, capsys):
    api.get("/v1/projects").respond(json=listing(PROJECT))
    put = api.put("/v1/projects/prj_1/settings/API_URL").respond(json={})
    api.get("/v1/projects/prj_1/settings").respond(json=listing({"name": "API_URL", "value": "https://a.test"}))
    gone = api.delete("/v1/projects/prj_1/settings/API_URL").respond(204)
    assert run("settings", "set", "booking", "API_URL", "https://a.test") == 0
    assert body(put.calls.last.request) == {"value": "https://a.test"}
    assert "reaches booking at its next deploy" in capsys.readouterr().err
    assert run("settings", "list", "booking") == 0
    assert capsys.readouterr().out.splitlines()[1].split() == ["API_URL", "https://a.test"]
    assert run("settings", "delete", "booking", "API_URL") == 0 and gone.call_count == 1


def test_a_deploy_names_what_git_leaves_out_and_a_commit_already_live(home, api, monkeypatch, capsys):
    git = FakeGit()
    git.outputs["ls-files"] = "worker.js\nassets/logo.png"
    monkeypatch.setattr(cli, "_git", git)
    api.get("/v1/projects").respond(json=listing({**PROJECT, "production": DEPLOYMENT}))
    api.post("/v1/repos/repo_1/clone_url").respond(json={"url": "https://git.noclick.test/booking.git"})
    api.post("/v1/projects/prj_1/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=DEPLOYMENT))
    assert run("deploy") == 0
    err = capsys.readouterr().err
    assert "Not deployed, as git doesn't track them: worker.js, assets/logo.png. To include them: git add" in err
    assert "Production already serves 3f2a1c9: nothing changed since, so this builds it again." in err


def test_a_failed_deploy_says_its_error_once(home, api, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", FakeGit())
    _deploy_routes(api, deploy_status="failed", error={
        "type": "operation_failed", "message": "The build failed: no index.html.", "deployment_id": "dep_9"})
    api.get("/v1/deployments/dep_9/logs").respond(json=listing(
        {"at": "2026-09-28T10:00:00Z", "level": "info", "message": "npm run build"},
        {"at": "2026-09-28T10:00:04Z", "level": "error", "message": "The build failed: no index.html."}))
    assert run("deploy") == 1
    err = capsys.readouterr().err
    assert "  npm run build" in err and err.count("The build failed: no index.html.") == 1


def test_bucket_cp_of_a_checkout_leaves_its_git_history_out(home, api, tmp_path, capsys):
    api.get("/v1/buckets").respond(json=listing(BUCKET))
    put = api.put("/v1/buckets/bkt_1/objects").respond(json={"key": "k", "size": 1})
    site = tmp_path / "site"
    (site / ".git" / "objects").mkdir(parents=True)
    (site / ".git" / "objects" / "ab").write_text("blob")
    (site / "index.html").write_text("<h1>hi</h1>")
    assert run("bucket", "cp", "-r", str(site), "uploads:site/") == 0
    assert [c.request.url.params["key"] for c in put.calls] == ["site/index.html"]
    assert "Leaving out" in capsys.readouterr().err


def test_agents_list_shows_a_page_and_says_theres_more(home, api, capsys):
    route = api.get("/v1/agents").respond(json=listing(*(agent_row(id=f"ag_{i}", name=f"a{i}") for i in range(3))))
    assert run("agents", "list", "--limit", "2") == 0
    assert route.calls.last.request.url.params["limit"] == "3"
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 3 and "there are more" in captured.err
    assert run("agents", "list") == 0 and route.calls.last.request.url.params["limit"] == "51"


def test_domains_search_says_when_the_name_asked_for_isnt_offered(home, api, capsys):
    api.get("/v1/domains/search").respond(json=listing(
        {"name": "google.ai", "available": True, "price_usd": 199.98, "renewal_usd": 199.98, "premium": False}))
    assert run("domains", "search", "google.com") == 0
    assert "google.com isn't for sale here" in capsys.readouterr().err


def test_estimate_kinds_says_what_a_variant_is_in_a_few_words(home, api, capsys):
    api.get("/v1/estimates/kinds").respond(json=listing({
        "object": "estimate_kind", "kind": "project", "label": "App", "description": "d",
        "options": {"runtime": "container", "region": "us-east", "size": {"cpu": 1.0, "memory": 512}},
        "usage": [], "prices": [{"charge": "instance", "description": "d", "unit": "hour", "unit_usd": 0.05,
                                 "usage_fields": []}], "not_included": []}))
    assert run("estimate", "--kinds") == 0
    row = capsys.readouterr().out.splitlines()[1]
    assert "container, us-east" in row and "{" not in row


def test_an_exit_status_says_whether_it_failed_waits_on_a_person_or_was_refused(home, api, capsys):
    """An agent acts on the status without reading the words: 3 waiting on a person (with where), 4 refused by a
    limit, a price or a policy, 1 anything else that failed."""
    api.post("/v1/domains").respond(402, json={"error": {
        "type": "approval_required", "message": "The purchase waits for the account's owner.",
        "approve_url": "https://noclick.test/approve/ap_1"}})
    assert run("domains", "buy", "acmebooking.com", "--max-price", "15") == cli.exits.WAITING
    err = capsys.readouterr().err
    assert "waiting on a person: The purchase waits" in err and "open: https://noclick.test/approve/ap_1" in err
    api.post("/v1/domains").respond(402, json={"error": {"type": "spend_cap_exceeded", "message": "Cap used up."}})
    assert run("domains", "buy", "acmebooking.com", "--max-price", "15") == cli.exits.REFUSED
    api.post("/v1/domains").respond(500, json={"error": {"type": "server_error", "message": "Broke."}})
    assert run("domains", "buy", "acmebooking.com", "--max-price", "15") == cli.exits.FAILED
