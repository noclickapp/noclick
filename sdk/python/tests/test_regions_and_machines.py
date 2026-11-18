"""Regions (built for sandboxes and agents, designed on the data and hosting
resources) and machines (designed, not built yet): the routes, bodies and
parsed results the client sends and reads, against the mocked transport."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation

REGIONS = [
    {"object": "region", "name": name, "label": label, "location": location, "kinds": ["sandbox", "agent"],
     "default": name == "eu"}
    for name, label, location in [
        ("us-east", "US East", "The eastern United States"), ("us-west", "US West", "The western United States"),
        ("eu", "Europe", "The European Economic Area"), ("ap", "Asia-Pacific", "Asia and the Pacific"),
    ]
]
SANDBOX = {"object": "sandbox", "id": "sb_1", "status": "running", "image": "python", "region": "eu", "user_id": None,
           "created_at": "2026-10-01T10:00:00Z", "expires_at": "2026-10-01T10:10:00Z"}
MACHINE_ID = "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b40"
MACHINE = {"object": "machine", "id": MACHINE_ID, "name": "support-box", "size": "medium", "cpu": 4, "memory_gb": 8,
           "disk_gb": 160, "region": "eu", "status": "running", "status_reason": None, "monthly_usd": 78.0,
           "max_monthly_usd": 120.0, "network": True, "volumes": {},
           "ports": [{"port": 8080, "url": "https://m-8080.example", "public": False}],
           "agent_count": 1, "image": "noclick-machine:2026.10", "restarts": 0, "last_restart_at": None,
           "user_id": None, "created_at": "2026-10-01T10:00:00Z"}


# --- regions ----------------------------------------------------------------------

def test_regions_list_the_catalog_for_the_account(api, client):
    route = api.get("/v1/regions").respond(json=listing(*REGIONS))
    with nc.as_user("user_42"):
        regions = nc.regions(kind="sandbox")
    request = route.calls.last.request
    assert request.url.params["kind"] == "sandbox" and "NoClick-User" not in request.headers
    assert [r.name for r in regions] == ["us-east", "us-west", "eu", "ap"]
    eu = regions[2]
    assert (eu.label, eu.location, eu.kinds, eu.default) == ("Europe", "The European Economic Area",
                                                             ["sandbox", "agent"], True)
    assert [r.name for r in regions if r.default] == ["eu"]
    nc.regions()
    assert "kind" not in route.calls.last.request.url.params


def test_a_sandbox_is_created_in_a_region_and_reads_it_back(api, client):
    create = api.post("/v1/sandboxes").respond(json=SANDBOX)
    sb = nc.Sandbox.create(image="python", region="eu")
    assert body(create.calls.last.request) == {"image": "python", "region": "eu"}
    assert sb.region == "eu"
    nc.Sandbox.create()
    assert "region" not in body(create.calls.last.request)


def test_an_agent_takes_a_region_and_from_name_holds_it_fixed(api, client):
    create = api.post("/v1/agents").respond(json=agent_row(region="eu"))
    agent = nc.Agent.create("support", instructions="hi", region="eu")
    assert body(create.calls.last.request)["region"] == "eu" and agent.region == "eu"

    # An existing agent elsewhere: the definition sends its region, and the API's conflict surfaces.
    api.get("/v1/agents").respond(json=listing(agent_row(region="us-east")))
    patch = api.patch("/v1/agents/ag_1").respond(409, json={"error": {
        "type": "conflict", "message": "The agent runs in us-east, and an agent's region is fixed when it's created.",
        "region": "us-east"}})
    lazy = nc.Agent.from_name("support", create_if_missing=True, instructions="hi", region="eu")
    with pytest.raises(nc.Conflict):
        lazy.hydrate()
    assert body(patch.calls.last.request) == {"region": "eu"}

    # Without a region the definition leaves it alone.
    nc.Agent.from_name("support", create_if_missing=True, instructions="hi").hydrate()
    assert patch.call_count == 1


def test_data_and_hosting_resources_take_a_region_designed(api, client):
    routes = {kind: api.post(f"/v1/{kind}").respond(json={"object": kind[:-1], "id": "x_1", "name": "n", "region": "eu"})
              for kind in ("volumes", "buckets", "queues", "dicts", "databases", "projects")}
    nc.Volume.create("datasets", region="eu")
    nc.Bucket.create("records", region="eu")
    nc.Queue.create("jobs", region="eu")
    nc.Dict.create("seen", region="eu")
    db = nc.Database.create("orders", engine="postgres", region="eu")
    nc.Project.create("booking", repo="repo_1", region="eu")
    for route in routes.values():
        assert body(route.calls.last.request)["region"] == "eu"
    assert db.region == "eu"
    # Omitted, nothing is sent: the account's default (else us-east) applies.
    nc.Volume.create("cache")
    assert body(routes["volumes"].calls.last.request) == {"name": "cache"}
    # from_name creates in the region it names.
    api.get("/v1/dicts").respond(json=listing())
    nc.Dict.from_name("flags", create_if_missing=True, region="ap").hydrate()
    assert body(routes["dicts"].calls.last.request) == {"name": "flags", "region": "ap"}


# --- machines (designed) -------------------------------------------------------------

def test_machine_sizes_create_and_read(api, client):
    sizes = api.get("/v1/machines/sizes").respond(json=listing(
        {"object": "machine_size", "name": "small", "cpu": 2, "memory_gb": 4, "disk_gb": 80, "monthly_usd": 39,
         "working_conversations": 2, "available": True, "region": "us-east", "host": "digitalocean"}))
    create = api.post("/v1/machines").respond(json=MACHINE)
    [small] = nc.Machine.sizes()
    assert (small.name, small.cpu, small.monthly_usd, small.working_conversations) == ("small", 2, 39.0, 2)
    assert "NoClick-User" not in sizes.calls.last.request.headers

    vol = nc.Volume.from_id("vol_1")
    box = nc.Machine.create("support-box", size="medium", region="eu", max_monthly_usd=120, volumes={"/shared": vol})
    assert body(create.calls.last.request) == {"name": "support-box", "size": "medium", "region": "eu",
                                               "max_monthly_usd": 120, "volumes": {"/shared": "vol_1"}}
    assert (box.status, box.region, box.monthly_usd, box.agent_count) == ("running", "eu", 78.0, 1)
    assert box.ports == [nc.MachinePort(8080, "https://m-8080.example", False, MACHINE["ports"][0])]
    assert (box.network, box.status_reason) == (True, None)
    # A limited network is sent as given.
    nc.Machine.create("locked-box", max_monthly_usd=60, network=["pypi.org"])
    assert body(create.calls.last.request) == {"name": "locked-box", "size": "small", "network": ["pypi.org"],
                                               "max_monthly_usd": 60}


def test_machine_sizes_list_each_hosts_disk_and_price_and_create_can_name_a_host(api, client):
    api.get("/v1/machines/sizes").respond(json=listing(
        {"object": "machine_size", "name": "small", "cpu": 2, "memory_gb": 4, "disk_gb": 40, "monthly_usd": 8.39,
         "working_conversations": 2, "region": "eu", "available": True, "host": "hetzner", "hosts": [
             {"host": "hetzner", "regions": ["eu"], "disk_gb": 40, "monthly_usd": 8.39},
             {"host": "digitalocean", "regions": ["us-east", "us-west", "eu", "ap"], "disk_gb": 80,
              "monthly_usd": 31.2}]}))
    [small] = nc.Machine.sizes()
    assert (small.disk_gb, small.monthly_usd) == (40, 8.39)
    assert small.hosts == [nc.MachineHost("hetzner", ["eu"], 40, 8.39),
                           nc.MachineHost("digitalocean", ["us-east", "us-west", "eu", "ap"], 80, 31.2)]
    create = api.post("/v1/machines").respond(json={**MACHINE, "host": "digitalocean"})
    box = nc.Machine.create("support-box", region="eu", host="digitalocean", max_monthly_usd=40)
    assert body(create.calls.last.request) == {"name": "support-box", "size": "small", "region": "eu",
                                               "host": "digitalocean", "max_monthly_usd": 40}
    assert box.host == "digitalocean"


def test_machine_sizes_are_size_first_each_at_its_cheapest_with_where_else_it_can_be_bought(api, client):
    listed = api.get("/v1/machines/sizes").respond(json=listing(
        {"object": "machine_size", "name": "small", "cpu": 2, "memory_gb": 4, "working_conversations": 2,
         "available": True, "region": "eu", "host": "hetzner", "disk_gb": 40, "monthly_usd": 8.39,
         "dominated_by": None,
         "regions": [{"region": "eu", "host": "hetzner", "disk_gb": 40, "monthly_usd": 8.39, "dominated_by": None},
                     {"region": "us-east", "host": "digitalocean", "disk_gb": 80, "monthly_usd": 31.2,
                      "dominated_by": None}],
         "hosts": [{"host": "hetzner", "regions": ["eu"], "disk_gb": 40, "monthly_usd": 8.39},
                   {"host": "digitalocean", "regions": ["us-east", "eu"], "disk_gb": 80, "monthly_usd": 31.2}]}))
    [small] = nc.Machine.sizes()
    params = listed.calls.last.request.url.params
    assert "region" not in params and "include_dominated" not in params
    assert (small.available, small.region, small.host, small.disk_gb, small.monthly_usd, small.dominated_by) == (
        True, "eu", "hetzner", 40, 8.39, None)
    assert small.regions == [nc.MachineSizeRegion("eu", "hetzner", 40, 8.39),
                             nc.MachineSizeRegion("us-east", "digitalocean", 80, 31.2)]
    # Bought exactly as offered: its region, host and price pinned.
    create = api.post("/v1/machines").respond(json={**MACHINE, "host": "hetzner"})
    nc.Machine.create("support-box", size=small.name, region=small.region, host=small.host,
                      max_monthly_usd=small.monthly_usd)
    assert body(create.calls.last.request) == {"name": "support-box", "size": "small", "region": "eu",
                                               "host": "hetzner", "max_monthly_usd": 8.39}
    nc.Machine.sizes(region="us-east")
    assert listed.calls.last.request.url.params["region"] == "us-east"


def test_machine_sizes_can_include_what_another_size_beats_and_what_cant_be_bought(api, client):
    listed = api.get("/v1/machines/sizes").respond(json=listing(
        {"object": "machine_size", "name": "medium", "cpu": 4, "memory_gb": 8, "working_conversations": 4,
         "available": True, "region": "eu", "host": "digitalocean", "disk_gb": 160, "monthly_usd": 62.4,
         "dominated_by": "large", "regions": [{"region": "eu", "host": "digitalocean", "disk_gb": 160,
                                               "monthly_usd": 62.4, "dominated_by": "large"}], "hosts": []},
        {"object": "machine_size", "name": "xlarge", "cpu": 16, "memory_gb": 32, "working_conversations": 16,
         "available": False, "region": "eu", "host": None, "disk_gb": 320, "monthly_usd": 42.59,
         "dominated_by": None, "regions": [], "hosts": []}))
    medium, xlarge = nc.Machine.sizes(region="eu", include_dominated=True)
    assert listed.calls.last.request.url.params["include_dominated"] == "true"
    assert (medium.available, medium.monthly_usd, medium.dominated_by) == (True, 62.4, "large")
    assert medium.regions == [nc.MachineSizeRegion("eu", "digitalocean", 160, 62.4, "large")]
    assert (xlarge.available, xlarge.host, xlarge.regions) == (False, None, [])


def test_machine_from_name_holds_its_host_fixed(api, client):
    api.get("/v1/machines").respond(json=listing({**MACHINE, "host": "hetzner"}))
    with pytest.raises(nc.Conflict):
        nc.Machine.from_name("support-box", create_if_missing=True, host="digitalocean", max_monthly_usd=120).hydrate()


def test_machine_from_name_needs_a_ceiling_and_converges_size(api, client):
    with pytest.raises(ValueError):
        nc.Machine.from_name("support-box", create_if_missing=True)
    api.get("/v1/machines").respond(json=listing({**MACHINE, "size": "small"}))
    patch = api.patch(f"/v1/machines/{MACHINE_ID}").respond(json=MACHINE)
    box = nc.Machine.from_name("support-box", create_if_missing=True, size="medium", max_monthly_usd=120)
    assert box.size == "medium" and body(patch.calls.last.request) == {"size": "medium"}
    # A definition without a size leaves an existing machine's alone.
    nc.Machine.from_name("support-box", create_if_missing=True, max_monthly_usd=120).hydrate()
    assert patch.call_count == 1
    # A network that differs is changed to match.
    nc.Machine.from_name("support-box", create_if_missing=True, network=["pypi.org"], max_monthly_usd=120).hydrate()
    assert body(patch.calls.last.request) == {"network": ["pypi.org"]}


def test_machine_exec_files_ports_agents_and_lifecycle(api, client):
    path = f"/v1/machines/{MACHINE_ID}"
    api.get(path).respond(json=MACHINE)
    run = api.post(f"{path}/exec").mock(side_effect=[
        httpx.Response(200, json={"stdout": "ok\n", "stderr": "", "exit_code": 0}),
        httpx.Response(202, json=operation("op_x", kind="machine.exec", status="running")),
    ])
    write = api.put(f"{path}/files").respond(json={})
    api.get(f"{path}/files").respond(content=b"log")
    expose = api.post(f"{path}/ports").respond(json={"port": 3000, "url": "https://m-3000.example", "public": True})
    close = api.delete(f"{path}/ports/3000").respond(json={})
    api.get(f"{path}/agents").respond(json=listing(agent_row(machine_id=MACHINE_ID)))
    restart = api.post(f"{path}/restart").respond(json=operation("op_r", kind="machine.restart", status="running"))
    stop = api.post(f"{path}/stop").respond(json={**MACHINE, "status": "stopped"})
    update = api.patch(path).respond(json={**MACHINE, "size": "large"})
    delete = api.delete(path).respond(json={})

    box = nc.Machine.from_id(MACHINE_ID)
    assert box.exec("df -h").stdout == "ok\n"
    background = box.exec("tar czf x.tgz /home", background=True, timeout_s=1800)
    assert isinstance(background, nc.Operation) and background.kind == "machine.exec"
    assert body(run.calls.last.request) == {"command": "tar czf x.tgz /home", "background": True, "timeout_s": 1800}
    box.files.write("notes.md", "hi")
    assert write.calls.last.request.url.params["path"] == "notes.md" and box.files.read("/var/log/w.log") == b"log"
    port = box.expose(3000, public=True)
    assert (port.url, port.public) == ("https://m-3000.example", True)
    assert body(expose.calls.last.request) == {"port": 3000, "public": True}
    box.close_port(3000)
    assert close.called
    [agent] = box.agents()
    assert agent.machine_id == MACHINE_ID
    assert box.restart().kind == "machine.restart" and restart.called
    assert box.stop().status == "stopped" and stop.called
    box.update(size="large", max_monthly_usd=240)
    assert body(update.calls.last.request) == {"size": "large", "max_monthly_usd": 240}
    box.delete()
    assert delete.called


def test_a_machines_page_reads_its_month_who_works_and_how_hard(api, client):
    path = f"/v1/machines/{MACHINE_ID}"
    api.get(path).respond(json={
        **MACHINE, "spent_usd_this_month": 16.64, "started_at": "2026-11-04T09:00:00Z", "working_count": 1,
        "agent_states": [{"agent_id": "ag_1", "working": True}, {"agent_id": "ag_2", "working": False}],
        "health": {"cpus": 2, "load_1m": 0.76, "cpu_percent": 38, "memory_used_gb": 2.6, "memory_total_gb": 4.0,
                   "disk_used_gb": 31.0, "disk_total_gb": 80.0},
        "pending": None})
    box = nc.Machine.from_id(MACHINE_ID)
    assert (box.spent_usd_this_month, box.working_count, box.pending) == (16.64, 1, None)
    assert box.started_at.day == 4 and [a["working"] for a in box.agent_states] == [True, False]
    assert (box.health.cpu_percent, box.health.memory_total_gb, box.health.disk_used_gb) == (38, 4.0, 31.0)


def test_a_machines_folders_list_a_page_at_a_time_and_its_shell_opens(api, client):
    path = f"/v1/machines/{MACHINE_ID}"
    api.get(path).respond(json=MACHINE)
    listed = api.get(f"{path}/files").mock(side_effect=[
        httpx.Response(200, json={"object": "list", "path": "/home/noclick/logs", "next_cursor": "/home/noclick/logs/a",
                                  "data": [{"object": "machine_entry", "path": "/home/noclick/logs/a",
                                            "type": "directory", "size": None, "updated_at": None}]}),
        httpx.Response(200, json={"object": "list", "path": "/home/noclick/logs", "next_cursor": None,
                                  "data": [{"object": "machine_entry", "path": "/home/noclick/logs/b.log",
                                            "type": "file", "size": 12, "updated_at": "2026-11-16T10:00:00Z"}]}),
    ])
    opened = api.post(f"{path}/shell").respond(json={
        "object": "machine_shell", "machine_id": MACHINE_ID, "url": "wss://api.noclick.test/v1/terminals/attach",
        "token": "tok_1", "token_expires_at": "2026-11-16T10:02:00Z", "idle_limit_s": 900})
    box = nc.Machine.from_id(MACHINE_ID)
    entries = box.files.list("logs")
    assert [(e.path, e.type, e.size) for e in entries] == [("/home/noclick/logs/a", "directory", None),
                                                          ("/home/noclick/logs/b.log", "file", 12)]
    assert dict(listed.calls[0].request.url.params) == {"path": "logs", "view": "list"}
    assert listed.calls[1].request.url.params["cursor"] == "/home/noclick/logs/a"
    shell = box.shell()
    assert (shell.url, shell.token, shell.idle_limit_s) == ("wss://api.noclick.test/v1/terminals/attach", "tok_1", 900)
    assert opened.called


def test_an_agent_runs_on_a_machine_designed(api, client):
    create = api.post("/v1/agents").respond(json=agent_row(machine_id=MACHINE_ID))
    update = api.patch("/v1/agents/ag_1").respond(json=agent_row(machine_id=None))
    box = nc.Machine.from_id(MACHINE_ID)
    agent = nc.Agent.create("support", instructions="hi", harness="claude_code", model_connection="claude", machine=box)
    assert body(create.calls.last.request)["machine_id"] == MACHINE_ID and agent.machine_id == MACHINE_ID
    agent.update(machine=None)
    assert body(update.calls.last.request) == {"machine_id": None}
    with nc.as_user("user_42"):
        nc.Agent.create("mine", instructions="hi", machine=MACHINE_ID)
    assert body(create.calls.last.request)["machine_id"] == MACHINE_ID
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID


# --- your own machine ----------------------------------------------------------------

OWN_ID = "7c1d9a20-2b6f-4e0a-9d51-3f8e6a4b2c10"
PAIRING = {"code": "nc_mach_4Hq9xY", "command": "curl -fsSL https://noclick.com/machine.sh | sudo sh -s -- --code "
                                                "nc_mach_4Hq9xY",
           "commands": {"linux": "curl -fsSL https://noclick.com/machine.sh | sudo sh -s -- --code nc_mach_4Hq9xY",
                        "mac": "curl -fsSL https://noclick.com/machine.sh | sh -s -- --code nc_mach_4Hq9xY",
                        "linux_unattended": "curl -fsSL https://noclick.com/machine.sh | sudo sh -s -- --code "
                                            "nc_mach_4Hq9xY --yes",
                        "mac_unattended": "curl -fsSL https://noclick.com/machine.sh | sh -s -- --code "
                                          "nc_mach_4Hq9xY --yes"},
           "expires_at": "2026-11-10T14:32:00Z", "installing_on": None, "refused": None}
REFUSED = {"system": "Darwin", "arch": "x86_64", "hostname": "imac", "at": "2026-11-10T14:12:03Z",
           "message": "This is macOS on x86_64: NoClick runs agents on Linux servers on x86-64 or ARM64, and Macs "
                      "with Apple silicon.", "next_step": "Run the command on a Linux server ..."}
OWN = {**MACHINE, "id": OWN_ID, "kind": "own", "name": "machine-3f2a1c", "size": None, "cpu": None, "memory_gb": None,
       "disk_gb": None, "os": None, "hostname": None, "status": "provisioning", "monthly_usd": 0.0,
       "max_monthly_usd": None, "ports": [], "agent_count": 0, "image": None, "last_seen_at": None,
       "max_conversations": None, "conversations_at_once": None, "agent_share": 0.75, "agent_share_fixed": False,
       "pairing": PAIRING, "docker": True, "app_testing": "ask_first"}
ONLINE = {**OWN, "name": "office-mini", "status": "running", "cpu": 8, "memory_gb": 32, "disk_gb": 450,
          "os": "Ubuntu 24.04.1 LTS", "hostname": "office-mini", "last_seen_at": "2026-11-10T14:02:00Z",
          "conversations_at_once": 6, "pairing": None}


def test_your_own_machine_is_added_with_a_code_and_set_up_on_the_server(api, client):
    add = api.post("/v1/machines/own").respond(json=OWN)
    fresh = {**PAIRING, "code": "nc_mach_newer", "command": "curl ... --code nc_mach_newer"}
    renew = api.post(f"/v1/machines/{OWN_ID}/pairing_code").respond(json={**OWN, "pairing": fresh})
    with nc.as_user("user_42"):
        home = nc.Machine.add_own()
    request = add.calls.last.request
    assert body(request) == {} and "NoClick-User" not in request.headers
    assert (home.kind, home.status, home.size, home.monthly_usd, home.max_monthly_usd) == (
        "own", "provisioning", None, 0.0, None)
    pairing = home.pairing
    assert (pairing.code, pairing.command, pairing.installing_on) == (
        "nc_mach_4Hq9xY", PAIRING["command"], None)
    assert pairing.expires_at.isoformat() == "2026-11-10T14:32:00+00:00"
    # A Mac's form runs as its person: no sudo.
    assert pairing.commands == PAIRING["commands"] and "sudo" not in pairing.commands["mac"]
    assert pairing.commands["linux_unattended"] == pairing.commands["linux"] + " --yes"
    nc.Machine.add_own(name="build-box", max_conversations=3, agent_share=1, docker=True)
    assert body(add.calls.last.request) == {"name": "build-box", "max_conversations": 3, "agent_share": 1,
                                            "docker": True}
    assert (home.agent_share, home.agent_share_fixed, home.docker, home.app_testing) == (0.75, False, True, "ask_first")
    nc.Machine.add_own(app_testing="never")
    assert body(add.calls.last.request) == {"app_testing": "never"}
    assert home.new_pairing_code().pairing.code == "nc_mach_newer" and renew.called
    assert pairing.refused is None


def test_a_box_turned_away_reads_on_the_machines_pairing(api, client):
    api.get(f"/v1/machines/{OWN_ID}").respond(json={**OWN, "pairing": {**PAIRING, "code": None, "command": None,
                                                                        "refused": REFUSED}})
    refused = nc.Machine.get(OWN_ID).pairing.refused
    assert (refused.system, refused.arch, refused.hostname, refused.message, refused.next_step) == (
        "Darwin", "x86_64", "imac", REFUSED["message"], REFUSED["next_step"])
    assert refused.at.isoformat() == "2026-11-10T14:12:03+00:00"


def test_your_own_machine_lists_by_kind_and_takes_a_cap(api, client):
    listed = api.get("/v1/machines").respond(json=listing(ONLINE))
    patch = api.patch(f"/v1/machines/{OWN_ID}").respond(json={**ONLINE, "max_conversations": 2,
                                                              "conversations_at_once": 2})
    [box] = nc.Machine.list(kind="own")
    assert listed.calls.last.request.url.params["kind"] == "own"
    assert (box.status, box.os, box.hostname, box.cpu, box.conversations_at_once, box.pairing) == (
        "running", "Ubuntu 24.04.1 LTS", "office-mini", 8, 6, None)
    assert box.last_seen_at.isoformat() == "2026-11-10T14:02:00+00:00"
    nc.Machine.list()
    assert "kind" not in listed.calls.last.request.url.params
    box.update(max_conversations=2)
    assert body(patch.calls.last.request) == {"max_conversations": 2}
    assert (box.max_conversations, box.conversations_at_once) == (2, 2)
    box.update(max_conversations=None)
    assert body(patch.calls.last.request) == {"max_conversations": None}
    box.update(agent_share=0.5)
    assert body(patch.calls.last.request) == {"agent_share": 0.5}
    box.update(docker=True)
    assert body(patch.calls.last.request) == {"docker": True}


def test_whether_agents_run_on_machines_here(api, client):
    route = api.get("/v1/machines").respond(json={**listing({**MACHINE, "agents_enabled": False}),
                                                  "agents_enabled": False})
    assert nc.Machine.agents_enabled_here() is False
    request = route.calls.last.request
    assert request.url.params["limit"] == "1" and "NoClick-User" not in request.headers
    [box] = nc.Machine.list()
    assert box.agents_enabled is False
