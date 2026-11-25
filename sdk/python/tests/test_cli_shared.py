"""The ``noclick`` command's shared pieces: the folder's linked app, ``--max-usd``, and the parts each adding their
commands."""

import types

import pytest

from noclick import cli
from noclick._cli import exits, kit, link, spend
from platform_helpers import BASE
from test_cli import home  # noqa: F401  (a signed-in shell with its own config dir)


def test_a_folder_is_linked_once_and_read_from_anywhere_inside_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(link.NotLinked) as unlinked:
        link.app_name(None)
    assert "noclick link <app>" in unlinked.value.next_step
    made = link.write("booking", app_id="prj_1", api_url=BASE)
    assert made.path == tmp_path / ".noclick" / "project.json"
    assert (tmp_path / ".noclick" / ".gitignore").read_text() == "*\n"  # this machine's, never committed
    inside = tmp_path / "src" / "pages"
    inside.mkdir(parents=True)
    found = link.find(inside)
    assert (found.app, found.app_id, found.api_url) == ("booking", "prj_1", BASE)
    assert link.app_name(None, start=inside) == "booking" and link.app_name("other") == "other"
    assert link.remove(inside).app == "booking" and link.find(inside) is None
    assert not (tmp_path / ".noclick").exists()


def test_max_usd_prices_first_and_refuses_above_the_ceiling(home, api, capsys):
    priced = api.post("/v1/estimates").respond(json={
        "object": "estimate", "monthly_usd": 0.42, "lines": [], "items": []})
    items = [{"kind": "live_editing", "usage": {"hours": 2}}]
    assert spend.check(items, 1.0, what="This session", per="at most").monthly_usd == 0.42
    assert "This session costs about $0.42 at most (under --max-usd $1.00)." in capsys.readouterr().err
    with pytest.raises(exits.OverLimit) as over:
        spend.check(items, 0.1, what="This session", per="at most")
    assert exits.code_for(over.value) == exits.REFUSED and "nothing was done" in over.value.message
    assert priced.call_count == 2


def test_a_part_adds_its_commands_to_the_command_line(home, monkeypatch, capsys):
    def register(built):
        hello = built.command(built.commands, "hello", lambda args: print(f"hi {args.name}") or 0, "Say hi.",
                              auth=False)
        hello.add_argument("name")
        built.command(built.groups["bucket"], "hello", lambda args: 0, "Say hi to a bucket.", auth=False)

    monkeypatch.setattr(kit, "parts", lambda: [types.SimpleNamespace(register=register)])
    assert cli.main(["hello", "Ana"]) == 0 and capsys.readouterr().out == "hi Ana\n"
    assert cli.main(["bucket", "hello"]) == 0
