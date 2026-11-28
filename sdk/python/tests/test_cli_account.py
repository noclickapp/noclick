"""Where you work from: the logins this machine keeps and the one commands use, Tab completion read from the spec,
the console in a browser, the changelog, and the once-a-day update notice."""

import json
import os

import pytest

from noclick import cli
from noclick._cli import completion, updates
from noclick._cli.parts import account
from noclick._cli.spec import load
from platform_helpers import BASE, listing
from test_cli import home  # noqa: F401  (a signed-in shell with its own config dir)

PROJECT = {"object": "project", "id": "5c2e8a1f-3b7d-4e9a-a6c4-8d1f0e2b3a79", "name": "booking",
           "url": "https://booking.noclick.site", "repo_id": "repo_1", "production_branch": "main", "user_id": None}


@pytest.fixture
def logins(home, monkeypatch):
    """Two logins kept in a file, and no key in the environment."""
    monkeypatch.delenv("NOCLICK_API_KEY")
    home.config.mkdir(parents=True)
    (home.config / "config.json").write_text(json.dumps({"profiles": {
        "default": {"store": "file", "api_url": BASE, "email": "ana@example.com", "key_name": "Ana's laptop",
                    "key_prefix": "nk_live_aaaa"},
        "work": {"store": "file", "api_url": BASE, "email": "ana@acme.test", "key_name": "Acme CI",
                 "key_prefix": "nk_live_wwww"},
    }}))
    (home.config / "credentials.json").write_text(json.dumps({"default": "nk_live_aaaa_key", "work": "nk_live_wwww_key"}))
    return home


def test_profile_use_makes_a_login_the_default_and_whoami_says_which_is_active_and_why(logins, api, capsys,
                                                                                         monkeypatch):
    assert cli.main(["profile", "list"]) == 0
    listed = capsys.readouterr()
    assert "*  default  ana@example.com  Ana's laptop" in listed.out and "work     ana@acme.test" in listed.out
    assert "* is active (the default)" in listed.err

    assert cli.main(["profile", "use", "work"]) == 0
    assert capsys.readouterr().out == "Commands now use the profile work (ana@acme.test).\n"
    status = api.get("/v1/status").respond(json={"account": {"id": "acct_2", "name": "Acme", "email": "ana@acme.test"}})
    assert cli.main(["whoami"]) == 0
    assert "Profile  work (set by noclick profile use)" in capsys.readouterr().out
    assert status.calls.last.request.headers["authorization"] == "Bearer nk_live_wwww_key"

    # --profile, then NOCLICK_PROFILE, still win over it.
    assert cli.main(["--profile", "default", "whoami", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert (said["profile"], said["profile_source"]) == ("default", "flag")
    monkeypatch.setenv("NOCLICK_PROFILE", "default")
    assert cli.main(["profile", "show", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["active_source"] == "env"
    monkeypatch.delenv("NOCLICK_PROFILE")

    assert cli.main(["profile", "use", "nope"]) == 1
    refused = capsys.readouterr().err
    assert "No stored login is called nope (stored: default, work)." in refused
    assert "run: noclick login --profile nope" in refused


def test_logging_out_of_the_active_profile_leaves_no_default_naming_it(logins, api, capsys):
    assert cli.main(["profile", "use", "work"]) == 0
    api.delete("/v1/keys/current").respond(204)
    assert cli.main(["logout"]) == 0
    config = json.loads((logins.config / "config.json").read_text())
    assert "work" not in config["profiles"] and cli.DEFAULT_PROFILE_KEY not in config
    assert cli.active_profile() == ("default", "default")


def complete(*words):
    return completion.candidates(list(words), profiles=lambda: ["default", "work"], apps=lambda: ["booking", "blog"])


def test_tab_completes_commands_flags_choices_profiles_and_apps_from_the_spec(home):
    spec = load()
    names = [value for value, _ in complete("")]
    assert {"deploy", "profile", "completion"} <= set(names)
    assert set(spec.areas()) <= set(names)  # every area of the API, as the spec has it now
    assert [value for value, _ in complete("profile", "u")] == ["use"]
    assert ("--level", "Only warnings and errors, or only errors") in complete("logs", "--le")
    assert [value for value, _ in complete("logs", "--level", "")] == ["warn", "error"]
    assert [value for value, _ in complete("profile", "use", "")] == ["default", "work"]
    assert [value for value, _ in complete("--profile", "w")] == ["work"]
    assert [value for value, _ in complete("logs", "b")] == ["booking", "blog"]
    assert [value for value, _ in complete("deploy", "--app", "bo")] == ["booking"]
    assert complete("no-such-command", "") == []
    # An operation's commands and its fields' flags, whatever names the spec gives them.
    area, ops = next((a, o) for a, o in sorted(spec.areas().items()) if any(
        p["in"] != "path" for op in o for p in op["params"]))
    op = next(op for op in ops if any(p["in"] != "path" for p in op["params"]))
    assert op["command"] in [value for value, _ in complete(area, "")]
    field = next(p for p in op["params"] if p["in"] != "path")
    flags = [value for value, _ in complete(area, op["command"], "--")]
    assert completion._flag_of(field["name"]) in flags and "--no-wait" in flags


def test_app_names_come_from_a_cache_read_again_in_the_background_when_stale(home):
    started = []
    assert completion.app_names("default", now=1000.0, refresh=started.append) == []
    assert started == ["default"]
    completion._write_apps("default", {"at": 1000.0, "names": ["booking"]})
    assert completion.app_names("default", now=1100.0, refresh=started.append) == ["booking"]
    assert started == ["default"]  # fresh: no read
    assert completion.app_names("default", now=1000.0 + completion.APPS_FRESH_S, refresh=started.append) == ["booking"]
    assert started == ["default", "default"]


def test_the_hidden_command_answers_one_line_a_candidate(home, capsys):
    assert cli.main(["__complete", "--", "profile", ""]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split("\t")[0] == "list" and all("\t" in line for line in lines)
    assert cli.main(["__complete", "--space", "--", "completion"]) == 0
    assert capsys.readouterr().out == "bash\t\nzsh\t\nfish\t\npowershell\t\n"


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_completion_install_puts_the_script_in_place_once(home, tmp_path, monkeypatch, capsys, shell):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "ZDOTDIR"):
        monkeypatch.delenv(var, raising=False)
    assert cli.main(["completion", shell]) == 0
    printed = capsys.readouterr().out
    assert printed == completion.SCRIPTS[shell] and "noclick __complete" in printed
    assert cli.main(["completion", shell, "--install"]) == 0
    first = capsys.readouterr().out
    script, rc, _ = completion.places(shell)
    assert script.read_text() == completion.SCRIPTS[shell] and str(script) in first
    assert cli.main(["completion", shell, "--install"]) == 0
    again = capsys.readouterr().out
    if rc is None:
        assert "fish loads it by itself." in again
    else:
        assert f"{rc} loads it (added a line)." in first and f"{rc} already loads it." in again
        assert rc.read_text().count(completion.MARK) == 1


def test_dashboard_opens_the_console_at_a_terminal_and_prints_its_url_otherwise(home, api, capsys, monkeypatch):
    monkeypatch.setenv("NOCLICK_CONSOLE_URL", "https://console.test/developers")
    opened = []
    monkeypatch.setattr(account, "_open", lambda url: opened.append(url) or True)
    assert cli.main(["dashboard"]) == 0  # piped: printed, not opened
    assert capsys.readouterr().out == "https://console.test/developers\n" and opened == []
    monkeypatch.setattr(account, "_can_open", lambda: True)
    api.get("/v1/projects").respond(json=listing(PROJECT))
    assert cli.main(["dashboard", "booking"]) == 0
    said = capsys.readouterr()
    page = f"https://console.test/developers/resources/apps/{PROJECT['id']}"
    assert said.out == f"{page}\n" and opened == [page] and "Opened it in your browser." in said.err
    monkeypatch.delenv("NOCLICK_CONSOLE_URL")
    assert cli.main(["dashboard"]) == 1  # the fake API's console isn't known
    assert "NOCLICK_CONSOLE_URL" in capsys.readouterr().err


CHANGELOG_MD = """# Changelog

> What changed in NoClick, newest first.

## November 28, 2026

### Profiles switch from the CLI

New · SDK · Next SDK release

`noclick profile use` makes a login the default.

### Improvements and fixes

- Fixed: a typo.

## November 20, 2026

### Older change

Improved · API

It changed.

### Improvements and fixes

- Fixed: another typo.

## Earlier

- [September 2026](https://docs.test/changelog/2026-09.md): 86 changes
"""


@pytest.fixture
def docs_site(monkeypatch):
    """A fake docs site serving changelog.md, as NOCLICK_DOCS_URL names it."""
    import http.server
    import threading

    asked = []

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            found = self.path == "/docs/changelog.md"
            self.send_response(200 if found else 404)
            self.send_header("content-type", "text/markdown; charset=utf-8")
            self.end_headers()
            self.wfile.write(CHANGELOG_MD.encode() if found else b"no")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NOCLICK_DOCS_URL", f"http://127.0.0.1:{server.server_port}/docs/")
    yield asked
    server.shutdown()


def test_changelog_lists_the_newest_changes_first_from_the_docs_page(home, docs_site, capsys):
    assert cli.main(["changelog", "--limit", "3"]) == 0
    said = capsys.readouterr()
    assert said.out.splitlines() == ["DATE        CHANGE", "2026-11-28  Profiles switch from the CLI",
                                     "2026-11-28  Improvements and fixes", "2026-11-20  Older change"]
    assert "Read one whole: noclick changelog profiles-switch-from-the-cli" in said.err
    assert docs_site == ["/docs/changelog.md"]
    assert cli.main(["changelog", "--json", "--limit", "1"]) == 0
    first = json.loads(capsys.readouterr().out)["data"][0]
    assert first == {"date": "2026-11-28", "title": "Profiles switch from the CLI", "slug": "profiles-switch-from-the-cli",
                     "url": f"{os.environ['NOCLICK_DOCS_URL'].rstrip('/')}/changelog/2026-11#2026-11-28-profiles-switch-"
                            "from-the-cli", "kind": "new", "areas": "SDK · Next SDK release",
                     "body": "`noclick profile use` makes a login the default."}


def test_changelog_prints_one_change_whole_by_its_title_or_slug(home, docs_site, capsys):
    assert cli.main(["changelog", "Profiles switch from the CLI"]) == 0
    said = capsys.readouterr()
    assert said.out == ("## Profiles switch from the CLI\n2026-11-28 · New · SDK · Next SDK release\n\n"
                        "`noclick profile use` makes a login the default.\n")
    assert "#2026-11-28-profiles-switch-from-the-cli" in said.err
    # A slug two days share names each by its date too.
    assert cli.main(["changelog", "improvements-and-fixes"]) == 2
    refused = capsys.readouterr().err
    assert "improvements-and-fixes-2026-11-28, improvements-and-fixes-2026-11-20" in refused
    assert cli.main(["changelog", "improvements-and-fixes-2026-11-20"]) == 0
    assert "another typo" in capsys.readouterr().out
    assert cli.main(["changelog", "older"]) == 0  # a word of its title, when only one holds it
    assert capsys.readouterr().out.startswith("## Older change\n2026-11-20 · Improved · API")
    assert cli.main(["changelog", "nothing-like-this"]) == 1


def test_changelog_says_where_it_couldnt_read_the_page(home, docs_site, capsys, monkeypatch):
    monkeypatch.setenv("NOCLICK_DOCS_URL", os.environ["NOCLICK_DOCS_URL"] + "missing")
    assert cli.main(["changelog"]) == 1
    said = capsys.readouterr().err
    assert "missing/changelog.md: it answered 404" in said and "NOCLICK_DOCS_URL" in said


def test_the_update_notice_is_said_at_most_once_a_day_and_never_where_it_would_get_in_the_way(home):
    asked = []
    say = dict(current="0.2.5", how=updates.PIP, env={}, terminals=True, ask=asked.append)
    assert updates.notice([], now=0.0, **say) is None and len(asked) == 1  # nothing heard yet: the registry is asked
    path = home.config / updates.FILE
    path.write_text(json.dumps({**json.loads(path.read_text()), "latest": "0.3.0"}))
    assert updates.notice([], now=60.0, **say) == (
        "A newer noclick is out: 0.3.0 (you have 0.2.5). Update: pip install -U noclick")
    assert updates.notice([], now=120.0, **say) is None and len(asked) == 1  # once a day, asked once a day
    later = updates.DAY_S + 61.0
    assert updates.notice([], now=later, **say) is not None and len(asked) == 2
    for quiet in ({"argv": ["--json"]}, {"env": {"CI": "1"}}, {"env": {"NOCLICK_NO_UPDATE_CHECK": "1"}},
                  {"terminals": False}):
        assert updates.notice(**{"argv": [], **say, "now": later * 3, **quiet}) is None
    assert not updates.newer("0.3.0rc1", "0.2.5") and not updates.newer("0.2.5", "0.2.5")
    assert updates.newer("0.10.0", "0.9.9")
