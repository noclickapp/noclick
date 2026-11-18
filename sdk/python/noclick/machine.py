"""Machines: an always-on computer for agents that should never sleep.

    box = noclick.Machine.from_name("support-box", create_if_missing=True, size="medium", region="eu",
                                    max_monthly_usd=120)
    support = noclick.Agent.from_name("support", create_if_missing=True, instructions="...",
                                      harness="claude_code", model_connection="claude", machine=box)
    print(box.exec("df -h /").stdout)

An agent on a machine runs its harness there instead of in a sandbox per
conversation: nothing is reaped when it goes quiet, and there's no per-minute
sandbox charge, only the machine's flat monthly price. Each conversation gets
its own container on the machine, so threads never see each other's files.
Model and tool calls go through NoClick's credential proxy with temporary keys:
your real keys are never on the machine. NoClick manages its image and updates,
restarts it if it fails (rebuilding it on a new host from its last backup if it
must), and attached volumes outlive it.

A Linux server you run can be one too, free (``Machine.add_own``): run the
command its ``pairing`` shows on the server as root, and your agents run there
in containers::

    home = noclick.Machine.add_own()
    print(home.pairing.command)
    # curl -fsSL https://api.noclick.com/machine-agent/v1/machine.sh | sudo sh -s -- --code nc_mach_...
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Mapping, Optional, Union, overload
from urllib.parse import quote

from ._client import Client, resolve_client
from ._designed import designed
from ._object import UNSET, Page, _Object, check_unchanged, compact, field, list_all, list_page, parse_time
from ._scope import AMBIENT, resolve_scope
from ._sync import synced
from .exceptions import Conflict, NotFound
from .operation import Operation, register_result
from .sandbox import ExecResult
from .volume import volume_ids, volume_refs


@designed
@dataclass(frozen=True)
class MachineHost:
    """A size on one host (``MachineSize.hosts``): where it runs, its disk there and its flat monthly price there."""

    #: What ``host=`` takes: ``hetzner`` or ``digitalocean``.
    host: str
    #: The regions it runs in on this host (``noclick.regions()``).
    regions: List[str]
    disk_gb: int
    #: Its price per month in US dollars on this host, whatever it runs and whether it's busy.
    monthly_usd: float

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MachineHost":
        return cls(raw["host"], list(raw["regions"]), int(raw["disk_gb"]), float(raw["monthly_usd"]))


@designed
@dataclass(frozen=True)
class MachineSizeRegion:
    """A region a size can be bought in now (``MachineSize.regions``, cheapest first): the host a new one would go
    on there, and its disk and flat monthly price there."""

    #: The region (``noclick.regions()``): what ``create`` takes as ``region=``.
    region: str
    #: The host a new one would go on there now, ``hetzner`` or ``digitalocean``: what ``create`` takes as ``host=``.
    host: str
    #: Its disk on that host.
    disk_gb: int
    #: Its price per month in US dollars on that host: what ``create`` takes as ``max_monthly_usd=``.
    monthly_usd: float
    #: A size that can be bought there now with at least its vCPUs and memory for no more, which makes this one no
    #: buy there (only listed with ``include_dominated=True``); ``None`` when there's none.
    dominated_by: Optional[str] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MachineSizeRegion":
        return cls(raw["region"], raw["host"], int(raw["disk_gb"]), float(raw["monthly_usd"]),
                   raw.get("dominated_by"))


@designed
@dataclass(frozen=True)
class MachineSize:
    """One of ``Machine.sizes()``: its processors and memory, and how it's bought now. ``region``, ``host``,
    ``disk_gb`` and ``monthly_usd`` are its cheapest offer anywhere (or, asked about a region, there); ``regions``
    lists every region it can be bought in now, cheapest first, and ``hosts`` each host that runs it. Stock is read at
    most a minute before; ``create`` checks again, so pass ``region``, ``host`` and ``monthly_usd`` (as
    ``max_monthly_usd``) to buy exactly this."""

    #: What ``size=`` takes: ``small``, ``medium``, ``large`` or ``xlarge`` (Hetzner's alone, so in ``eu`` only).
    name: str
    #: vCPUs (hardware threads), as hosts sell them.
    cpu: int
    memory_gb: int
    #: The machine's own disk on ``host`` (while it isn't available, on the first host that sells it).
    disk_gb: int
    #: Its price per month in US dollars on ``host`` in ``region`` (while it isn't available, the price it has once
    #: the first host that sells it has one again).
    monthly_usd: float
    #: About how many coding-agent conversations can work on it at the same moment.
    working_conversations: int
    #: Whether it can be bought now (only ``False`` with ``include_dominated=True``).
    available: bool = False
    #: Where it's cheapest now (the account's default region first at one price), or the region asked about;
    #: ``None`` when it can't be bought anywhere.
    region: Optional[str] = None
    #: The host a new one would go on there now; ``None`` while it can't be bought.
    host: Optional[str] = None
    #: A size that can be bought now with at least its vCPUs and memory for no more (only listed with
    #: ``include_dominated=True``); ``None`` when there's none.
    dominated_by: Optional[str] = None
    #: Each region it can be bought in now, cheapest first: the host, disk and price there.
    regions: List[MachineSizeRegion] = dc_field(default_factory=list)
    #: Each host that runs it, cheapest first: its regions, disk and price there.
    hosts: List[MachineHost] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MachineSize":
        return cls(raw["name"], int(raw["cpu"]), int(raw["memory_gb"]), int(raw["disk_gb"]),
                   float(raw["monthly_usd"]), int(raw["working_conversations"]), available=bool(raw["available"]),
                   region=raw.get("region"), host=raw.get("host"), dominated_by=raw.get("dominated_by"),
                   regions=[MachineSizeRegion._from(r) for r in raw.get("regions") or []],
                   hosts=[MachineHost._from(h) for h in raw.get("hosts") or []], raw=raw)


@designed
@dataclass(frozen=True)
class MachinePort:
    """A port a machine serves. ``url`` reaches it over HTTPS; a private port asks
    for an API key with the ``machines`` scope (``Authorization: Bearer``), a public
    one answers anyone."""

    port: int
    url: str
    public: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MachinePort":
        return cls(int(raw["port"]), raw["url"], bool(raw["public"]), raw)


@designed
@dataclass(frozen=True)
class MachineRefusal:
    """A server turned away with your own machine's code, newest first: by NoClick (its system, or the code
    expired) or by the installer itself. Cleared by a new code or a server that pairs."""

    system: Optional[str]
    arch: Optional[str]
    hostname: Optional[str]
    #: What the server's terminal printed, whole.
    message: str
    #: What to do, where NoClick knows it.
    next_step: Optional[str]
    at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["MachineRefusal"]:
        if not raw:
            return None
        return cls(raw.get("system"), raw.get("arch"), raw.get("hostname"), raw.get("message") or "",
                   raw.get("next_step"), parse_time(raw.get("at")), raw)


@designed
@dataclass(frozen=True)
class MachinePairing:
    """Your own machine until its server is set up: the one-time ``code`` and the
    ``command`` that carries it, which NoClick only shows as it makes them (a
    machine read again has both ``None``), when the code stops working, and the
    server being set up with it once its installer started."""

    code: Optional[str]
    #: What to run on the server as root (a Linux server's, or a Linux distro's in WSL on Windows).
    command: Optional[str]
    #: 30 minutes after the code was made; ``new_pairing_code()`` makes another.
    expires_at: Any
    installing_on: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    #: The last server turned away with the code, and why (None since the code was made, or once one pairs).
    refused: Optional[MachineRefusal] = None
    #: The command for each system: ``"linux"`` (``command``) and ``"mac"``, run in Terminal as you, never root; and
    #: each with ``--yes`` to install unattended (SSH, cloud-init, a script): ``"linux_unattended"``, ``"mac_unattended"``.
    commands: Optional[Dict[str, str]] = None

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["MachinePairing"]:
        if not raw:
            return None
        return cls(raw.get("code"), raw.get("command"), parse_time(raw.get("expires_at")), raw.get("installing_on"),
                   raw, MachineRefusal._from(raw.get("refused")), raw.get("commands"))


@designed
@dataclass(frozen=True)
class MachineHealth:
    """How hard a running machine works, from its last check-in (``machine.last_seen_at``)."""

    #: Its vCPUs (your own: the server's).
    cpus: Optional[int]
    #: Its one-minute load average, and that as a part of its vCPUs kept busy (at most 100).
    load_1m: float
    cpu_percent: Optional[int]
    #: Memory in use and in all (your own: the whole server's; its agents use ``agent_share`` of it).
    memory_used_gb: float
    memory_total_gb: float
    disk_used_gb: float
    disk_total_gb: float

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["MachineHealth"]:
        if not raw:
            return None
        return cls(raw.get("cpus"), float(raw["load_1m"]), raw.get("cpu_percent"), float(raw["memory_used_gb"]),
                   float(raw["memory_total_gb"]), float(raw["disk_used_gb"]), float(raw["disk_total_gb"]))


@designed
@dataclass(frozen=True)
class MachineFileEntry:
    """A file or folder on a machine's disk (``machine.files.list``)."""

    path: str
    #: ``file`` or ``directory``.
    type: str
    #: A file's bytes (``None`` for a folder).
    size: Optional[int]
    updated_at: Any

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MachineFileEntry":
        return cls(raw["path"], raw["type"], raw.get("size"), parse_time(raw.get("updated_at")))


@designed
@dataclass(frozen=True)
class MachineShell:
    """A shell on a machine NoClick runs (``machine.shell()``): ``url`` is a websocket, opened once with ``token``
    within two minutes. Its first message is ``{"type": "auth", "token": ..., "cols": ..., "rows": ...}``; then binary
    messages carry what you type and what it prints, a text ``{"type": "resize", "cols", "rows"}`` sizes it, and it
    sends ``{"type": "ready"}`` once and ``{"type": "state", "state": "exited", "reason"}`` as it closes (code 4410):
    bash exited, ``idle_limit_s`` passed with nothing typed, or the socket closed."""

    machine_id: str
    url: str
    token: str
    token_expires_at: Any
    idle_limit_s: int

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "MachineShell":
        return cls(raw["machine_id"], raw["url"], raw["token"], parse_time(raw.get("token_expires_at")),
                   int(raw["idle_limit_s"]))


def _read_exec(result: Any, op: Operation) -> ExecResult:
    return ExecResult._from(result)


def _read_machine(result: Any, op: Operation) -> "Machine":
    return Machine._new(raw=result, client=op._client, user=op._scope)


register_result("machine.exec", _read_exec)
register_result("machine.restart", _read_machine)


@designed
class MachineFiles:
    """``machine.files``: read and write files on the machine's own disk."""

    def __init__(self, machine: "Machine") -> None:
        self._machine = machine

    @synced
    async def write(self, path: str, data: Union[bytes, str]) -> None:
        """Write ``data`` (bytes, or text as UTF-8) to ``path`` (relative paths are under ``/home/noclick``).

        Usage::

            box = noclick.Machine.from_name("support-box")
            box.files.write("/etc/noclick/notes.md", "Restart the worker after deploys.")
        """
        content = data.encode() if isinstance(data, str) else bytes(data)
        await self._machine._request(
            "PUT", f"{await self._machine._path()}/files", params={"path": path}, content=content,
        )

    @synced
    async def read(self, path: str) -> bytes:
        """Read the file at ``path``; a missing file raises ``noclick.NotFound``.

        Returns:
            The file's bytes, exactly as stored.

        Usage::

            box = noclick.Machine.from_name("support-box")
            print(box.files.read("/var/log/worker.log").decode()[-2000:])
        """
        return await self._machine._request(
            "GET", f"{await self._machine._path()}/files", params={"path": path}, binary=True,
        )

    @synced
    async def list(self, path: str = "/home/noclick") -> List[MachineFileEntry]:
        """The files and folders in the folder at ``path`` (relative paths are under ``/home/noclick``, the
        machine user's home), by name.

        Returns:
            Each entry's ``path``, ``type`` (``file`` or ``directory``), ``size`` and ``updated_at``.

        Usage::

            box = noclick.Machine.from_name("support-box")
            for entry in box.files.list("logs"):
                print(entry.type, entry.path, entry.size)
        """
        found: List[MachineFileEntry] = []
        cursor: Optional[str] = None
        while True:
            page = await self._machine._request("GET", f"{await self._machine._path()}/files",
                                                params=compact(path=path, view="list", cursor=cursor))
            found += [MachineFileEntry._from(e) for e in page["data"]]
            cursor = page.get("next_cursor")
            if not cursor:
                return found


# What ``from_name`` sets on an existing machine (a new size is judged against the ceiling sent with it).
_CONVERGED = ("size", "volumes", "network", "max_monthly_usd")


@designed
class Machine(_Object):
    """An always-on computer of a fixed ``size`` in one ``region``, billed a flat
    monthly price. Agents created with ``machine=`` run their harness on it, each
    conversation in a container of its own; ``exec``, ``files`` and ``expose`` reach
    the machine itself. ``status`` is ``provisioning``, ``running``, ``restarting``,
    ``updating``, ``stopped`` or ``failed`` (``status_reason`` says why), or
    ``awaiting_approval``: rented while NoClick reviews your company, nothing made
    or charged yet, it starts once that's approved.

    ``kind`` ``own`` is a server you added (``Machine.add_own``): free, the size
    the server is, its ``shell`` and ``files`` as any machine's, its agents in
    containers only (no ``exec``, ports, ``restart``, ``stop`` or ``start``), and
    ``offline`` while it's silent."""

    _repr_keys = ("id", "name", "kind", "size", "status")

    id: str = field("id")
    name: str = field("name")
    kind: Optional[str] = field("kind", doc="``noclick``: a machine NoClick runs; ``own``: a server you added.")
    size: Optional[str] = field("size", doc="``small``, ``medium``, ``large`` or ``xlarge`` (``Machine.sizes()``); "
                                            "``None`` on your own, which is the size its server is.")
    host: Optional[str] = field("host", doc="The host it runs on, ``hetzner`` or ``digitalocean``, for its life "
                                            "(``None`` on your own).")
    cpu: Optional[int] = field("cpu", doc="vCPUs (hardware threads).")
    memory_gb: Optional[int] = field("memory_gb")
    disk_gb: Optional[int] = field("disk_gb", doc="Its disk. A larger size on Hetzner keeps the disk it had, so a "
                                                  "move back down stays a resize.")
    os: Optional[str] = field("os", doc="The server's system, as it reports it (``Ubuntu 24.04.1 LTS``).")
    hostname: Optional[str] = field("hostname")
    last_seen_at: Any = field("last_seen_at", parse_time,
                              doc="When it last answered NoClick: on your own machine ``offline``, since when.")
    max_conversations: Optional[int] = field("max_conversations",
                                             doc="Your own machine: the most of its agents' conversations you let "
                                                 "work at once (``None``: what the server takes).")
    conversations_at_once: Optional[int] = field("conversations_at_once",
                                                 doc="How many of its agents' conversations work at once.")
    agent_share: Optional[float] = field("agent_share", doc="Your own machine: the part of its CPUs and memory its "
                                                            "agents use (0.75 by default); the rest stays yours.")
    agent_share_fixed: Optional[bool] = field("agent_share_fixed",
                                              doc="True on a Mac once NoClick's VM is made: a VM keeps its size.")
    docker: bool = field("docker", bool, doc="Your own machine: whether its agents' containers run Docker (any "
                                             "``app_testing`` but ``never``).")
    app_testing: Optional[str] = field(
        "app_testing", doc="Your own machine: whether its agents run apps and test databases: ``by_itself``, "
        "``ask_first`` (the default: each agent asks its owner first) or ``never``; an agent on it gets the stricter of "
        "this and its own ``app_testing``. ``never`` on a machine NoClick runs.")
    agents_enabled: Optional[bool] = field("agents_enabled", doc="Whether agents run on machines on this API yet "
                                                                 "(``Machine.agents_enabled_here()``).")
    region: Optional[str] = field("region", doc="The region it runs in (``noclick.regions()``), fixed when it was created.")
    status: Optional[str] = field("status")
    status_reason: Optional[str] = field("status_reason", doc="Why it's stopped or failed, or why it restarted.")
    monthly_usd: Optional[float] = field("monthly_usd", doc="What it costs a month on its host, in US dollars, running "
                                                            "or stopped (0 for your own).")
    max_monthly_usd: Optional[float] = field("max_monthly_usd", doc="The most you agreed it may cost a month.")
    network: Any = field("network", doc="What its own commands may reach: ``True`` (anywhere the machines usage "
                                        "policy allows) or the hosts.")
    volumes: Optional[Dict[str, str]] = field("volumes", doc="The volumes it mounts, by path: ``{path: volume id}``.")
    agent_count: Optional[int] = field("agent_count", doc="How many agents run on it.")
    working_count: Optional[int] = field("working_count", doc="How many of its agents are working now, from its "
                                                              "last check-in.")
    agent_states: List[Dict[str, Any]] = field(
        "agent_states", lambda v: list(v or []),
        doc="Each agent on it, ``{agent_id, working}``: working while one of its conversations there is.")
    spent_usd_this_month: Optional[float] = field("spent_usd_this_month",
                                                  doc="What it was charged this month (UTC) so far, in US dollars.")
    started_at: Any = field("started_at", parse_time, doc="When it last booted, while it runs: its uptime.")
    pending: Optional[Dict[str, Any]] = field(
        "pending", doc="While ``updating``: ``{size, move}``, the size it becomes and whether it moves to a new host.")
    image: Optional[str] = field("image", doc="The NoClick-managed image it runs, with its harness versions.")
    restarts: Optional[int] = field("restarts", doc="How many times it restarted after failing, ever.")
    last_restart_at: Any = field("last_restart_at", parse_time)
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def files(self) -> MachineFiles:
        return MachineFiles(self)

    @property
    def health(self) -> Optional[MachineHealth]:
        """How hard it works, from its last check-in while it runs; ``None`` otherwise."""
        return MachineHealth._from(self._sync_raw().get("health"))

    @property
    def ports(self) -> List[MachinePort]:
        """The ports it serves."""
        return [MachinePort._from(p) for p in self._sync_raw().get("ports") or []]

    @property
    def pairing(self) -> Optional[MachinePairing]:
        """Your own machine until its server is set up; ``None`` after, and on a machine NoClick runs."""
        return MachinePairing._from(self._sync_raw().get("pairing"))

    @property
    def console_url(self) -> Optional[str]:
        """This machine in the developer console (None off the hosted API)."""
        base = self._api.console_url("resources", "machines")
        return f"{base}?machine={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    # --- construction ----------------------------------------------------

    @staticmethod
    def _body(name: str, size: Optional[str], region: Optional[str], volumes: Any, network: Any,
              max_monthly_usd: Optional[float], *, user: Any, client: Optional[Client],
              host: Optional[str] = None) -> Dict[str, Any]:
        # ``volumes`` may still hold lazy refs here; ``_wire`` resolves them.
        return compact(name=name, size=size, region=region, network=network, max_monthly_usd=max_monthly_usd,
                       volumes=volume_refs(volumes, user=user, client=client), host=host)

    @staticmethod
    async def _wire(body: Dict[str, Any]) -> Dict[str, Any]:
        return {**body, "volumes": await volume_ids(body["volumes"])} if "volumes" in body else body

    @synced
    @classmethod
    async def sizes(cls, *, region: Optional[str] = None, include_dominated: bool = False,
                    client: Optional[Client] = None) -> List[MachineSize]:
        """The sizes worth buying now, smallest first: size first, each at its cheapest anywhere, or as
        bought in ``region`` (``noclick.regions()``). A size that can't be bought now is left out, as is
        one where another that can be bought has at least its vCPUs and memory for no more (judged
        across every region, or in ``region``; a larger disk alone doesn't count).
        ``include_dominated=True`` lists every size, each with ``available`` and ``dominated_by``.

        Returns:
            Each size's ``name`` (what ``size=`` takes), its processors and memory, about how many
            conversations can work on it at once, and its cheapest offer now: the ``region``, the
            ``host`` it would go on and its ``disk_gb`` and ``monthly_usd`` there. ``regions`` lists every
            region it can be bought in now, cheapest first, and ``hosts`` each host that runs it here.
            Stock is read at most a minute before; ``create`` checks again.

        Usage::

            size = noclick.Machine.sizes()[0]
            print(size.name, size.region, size.host, size.monthly_usd)   # small eu hetzner 8.39
            box = noclick.Machine.create("support-box", size=size.name, region=size.region, host=size.host,
                                         max_monthly_usd=size.monthly_usd)
        """
        params = compact(region=region, include_dominated="true" if include_dominated else None)
        page = await resolve_client(client).request("GET", "/v1/machines/sizes", params=params, user=None)
        return [MachineSize._from(row) for row in page["data"]]

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        size: str = "small",
        region: Optional[str] = None,
        volumes: Optional[Mapping[str, Any]] = None,
        network: Union[bool, List[str], None] = None,
        max_monthly_usd: float,
        host: Optional[Literal["hetzner", "digitalocean"]] = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Machine":
        """Start an always-on machine called ``name`` (unique to its user; a taken
        name raises ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True``
        returns the machine already there, as it is: nothing about it changes). ``size`` is one of
        ``Machine.sizes()``; ``region`` (``noclick.regions()``) is where it runs, for
        good, else your account's default region, else ``us-east``. ``volumes``
        attaches ``Volume``s (or their ids or names) at absolute paths: each
        conversation sees a volume as it was when its turn started and saves its
        writes when the turn ends. ``network`` is what the machine's own commands may
        reach: ``True`` (the default: anywhere the machines usage policy allows, so no
        mail ports, mining pools or private addresses) or a list of hosts (HTTPS to them,
        ``"*.github.com"`` for subdomains, and name lookups). It's charged to your
        account from the day it first runs, a thirtieth of its monthly price a day
        while it exists, running or stopped, and refused (``noclick.PriceExceeded``,
        nothing started) if its size costs more than ``max_monthly_usd`` on the host it goes on. It goes
        on the cheapest host that runs the size in the region and has stock for it (Hetzner in
        ``eu``, DigitalOcean everywhere; ``Machine.sizes()`` lists each host's price and disk),
        never one costing more than ``max_monthly_usd``: when only a dearer host has stock, that
        raises ``noclick.PriceExceeded`` naming the host and its price. ``host`` names one instead
        (only it is tried). A machine stays on its host for its life. An account's
        first machine needs its company vetted by NoClick: its owner asks in the
        developer console (Resources, Machines), saying what its machines will run,
        and until NoClick approves it this raises ``noclick.ActionRequired``, whose
        ``next_step`` links that page.

        Returns:
            The machine, ``provisioning`` until it's ready (``running``).

        Usage:
            A machine in Europe for a team of agents, with their shared files::

                box = noclick.Machine.create(
                    "support-box", size="medium", region="eu", max_monthly_usd=120,
                    volumes={"/shared": noclick.Volume.from_name("support-kb", create_if_missing=True)},
                )
                print(box.status, box.monthly_usd)
        """
        scope = resolve_scope(user)
        body = await cls._wire(cls._body(name, size, region, volumes, network, max_monthly_usd, user=scope,
                                         client=client, host=host))
        raw = await cls._create_named("/v1/machines", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @synced
    @classmethod
    async def add_own(
        cls, *, name: Optional[str] = None, max_conversations: Optional[int] = None,
        agent_share: Optional[float] = None, docker: Optional[bool] = None, app_testing: Optional[str] = None,
        client: Optional[Client] = None,
    ) -> "Machine":
        """Add a Linux server you run (x86-64 or ARM64, with sudo) as a machine your
        account's agents run on, in containers: free, its agents' model calls at
        cost. Its containers can't reach its network, and on the server itself
        NoClick only opens the account owner's ``shell`` and ``files``, as its
        ``noclick`` user. Run ``pairing.command`` on it as root within 30
        minutes. Without ``name`` it takes the server's hostname;
        ``max_conversations`` caps how many
        of its agents' conversations work at once; ``agent_share`` is the part of
        the server they use (0.1 to 1; 0.75 by default, 1 for a server just for
        NoClick; on a Mac, NoClick's VM is made that size); ``app_testing`` is whether
        its agents run apps and test databases (``"ask_first"`` unless it says: each
        agent asks its owner in the chat first; ``"by_itself"``; ``"never"``), each
        conversation's container then running its own Docker inside its gVisor sandbox
        (no host socket, nothing privileged on the server; a container whose agent's
        network is limited runs without it); ``docker`` alone chooses ``"by_itself"``
        (true) or ``"never"`` (false). Called again before a
        server pairs, it returns that same machine, with its code while the code is
        good and a new one once it expired: add one per server, after the last one
        paired. The account's own, never a user's (``as_user`` doesn't apply).

        Returns:
            The machine, ``provisioning`` until the server answers, then ``running``
            (``offline`` while it's silent: its agents' turns fail then), with its
            ``pairing``.

        Usage::

            home = noclick.Machine.add_own()
            print(home.pairing.command)
            # On the server: curl -fsSL https://api.noclick.com/machine-agent/v1/machine.sh | sudo sh -s -- \\
            #     --code nc_mach_...
        """
        raw = await resolve_client(client).request(
            "POST", "/v1/machines/own",
            json=compact(name=name, max_conversations=max_conversations, agent_share=agent_share, docker=docker,
                         app_testing=app_testing),
            user=None)
        return cls._new(raw=raw, client=client, user=None)

    @synced
    @classmethod
    async def agents_enabled_here(cls, *, client: Optional[Client] = None) -> bool:
        """Whether agents run on machines on this API yet. Until they do, an agent
        isn't put on a machine and your own server isn't added
        (``noclick.NotAvailable``), and each machine reads ``agents_enabled`` False.

        Returns:
            True once agents run on machines here.

        Usage::

            if noclick.Machine.agents_enabled_here():
                home = noclick.Machine.add_own()
        """
        page = await resolve_client(client).request("GET", "/v1/machines", params={"limit": 1}, user=None)
        return page.get("agents_enabled") is True

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        size: Optional[str] = None,
        region: Optional[str] = None,
        volumes: Optional[Mapping[str, Any]] = None,
        network: Union[bool, List[str], None] = None,
        max_monthly_usd: Optional[float] = None,
        host: Optional[Literal["hetzner", "digitalocean"]] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Machine":
        """A lazy reference to the machine called ``name`` in the current (or given)
        user. Given fields, it gets the machine and sets the ``size``, ``volumes``, ``network`` and
        ``max_monthly_usd`` you pass, on every run (a new size restarts it, judged against the
        ``max_monthly_usd`` set with it). Fields you leave out are never changed. Its ``region`` and
        ``host`` are fixed: an existing machine in another raises ``noclick.Conflict`` naming it.
        ``create_if_missing=True`` starts it with the fields ``create`` takes when there's none
        (``max_monthly_usd`` is required then); without it, a missing machine raises
        ``noclick.NotFound``.

        Returns:
            A machine that loads (or is started, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage::

            box = noclick.Machine.from_name("support-box", create_if_missing=True, size="medium", max_monthly_usd=120)
            print(box.status)
        """
        machine = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing and max_monthly_usd is None:
            raise ValueError("Machine.from_name(create_if_missing=True) needs max_monthly_usd=")
        machine._define(cls._body(name, size, region, volumes, network, max_monthly_usd, user=user, client=client,
                                  host=host), create_if_missing=create_if_missing)
        return machine

    @classmethod
    def from_id(cls, machine_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Machine":
        """A lazy reference to a machine by id.

        Returns:
            A machine that loads the first time you read a field. Nothing is sent yet.

        Usage::

            box = noclick.Machine.from_id("3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b40")
            print(box.exec("uptime").stdout)
        """
        return cls._new(hints={"id": machine_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, machine_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Machine":
        """Load a machine by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The machine, loaded.

        Usage::

            box = noclick.Machine.get("3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b40")
            print(box.name, box.status, box.agent_count)
        """
        machine = cls.from_id(machine_id, client=client, user=user)
        await machine._ensure()
        return machine

    @synced
    @classmethod
    async def list(
        cls, *, kind: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Machine"]:
        """The current user's machines (the account's own outside ``as_user``, or those ``user_filter`` covers);
        ``kind`` (``noclick`` or ``own``) narrows them.

        Returns:
            Every matching machine, newest first, fetched page by page.

        Usage::

            for box in noclick.Machine.list(user_filter=noclick.ALL_USERS):
                print(box.name, box.region, box.status, box.monthly_usd)
            print([box.name for box in noclick.Machine.list(kind="own") if box.status == "offline"])
        """
        return await list_all(
            "/v1/machines", lambda raw, scope: cls._new(raw=raw, client=client, user=scope), params={"kind": kind},
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, kind: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of machines; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the machines and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Machine.list_page(limit=50)
            print([box.name for box in page.data], page.next_cursor)
        """
        return await list_page(
            "/v1/machines", lambda raw, scope: cls._new(raw=raw, client=client, user=scope), params={"kind": kind},
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        machine_id = self._known("id")
        if machine_id:
            return await self._request("GET", f"/v1/machines/{machine_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/machines", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No machine is named {name!r}.",
                next_step="Create it with noclick.Machine.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/machines", json=await self._wire(self._create_with))
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/machines/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing machine, after checking the ones it can't set."""
        if self._create_with is None:
            return raw
        definition = self._create_with
        check_unchanged("machine", raw, {k: definition[k] for k in ("region", "host") if k in definition})
        wanted = await self._wire({k: v for k, v in definition.items() if k in _CONVERGED})
        changes = {k: v for k, v in wanted.items() if raw.get(k) != v}
        if not changes:
            return raw
        return await self._request("PATCH", f"/v1/machines/{raw['id']}", json=changes)

    async def _path(self) -> str:
        return f"/v1/machines/{(await self._ensure())['id']}"

    # --- the machine itself ----------------------------------------------

    @overload
    async def exec(self, command: str, *, background: Literal[False] = False,
                   timeout_s: Optional[int] = None) -> ExecResult: ...

    @overload
    async def exec(self, command: str, *, background: Literal[True], timeout_s: Optional[int] = None) -> Operation: ...

    @synced
    async def exec(
        self, command: str, *, background: bool = False, timeout_s: Optional[int] = None,
    ) -> Union[ExecResult, Operation]:
        """Run a shell command on the machine itself (not in a conversation's
        container) and wait for it: ``timeout_s`` is 60 by default, at most 90.
        ``background=True`` runs it as an operation, up to an hour.

        Returns:
            What the command printed and how it exited, or with ``background=True`` an ``Operation``
            whose ``wait()`` gives that result.

        Usage::

            box = noclick.Machine.from_name("support-box")
            print(box.exec("df -h /").stdout)
            backup = box.exec("tar czf /shared/backup.tgz /home/noclick", background=True, timeout_s=1800)
            print(backup.wait().exit_code)
        """
        body = compact(command=command, background=background or None, timeout_s=timeout_s)
        payload = await self._request("POST", f"{await self._path()}/exec", json=body)
        if background:
            return Operation._from_payload(payload, client=self._client, user=self._call_scope(), kind="machine.exec",
                                           reader=_read_exec)
        return ExecResult._from(payload)

    @synced
    async def expose(self, port: int, *, public: bool = False) -> MachinePort:
        """Serve ``port`` at an HTTPS URL on NoClick's domain: a dashboard or a webhook
        receiver your agents run. A private port asks for an API key with the
        ``machines`` scope, which the app never sees; ``public=True`` answers anyone.

        Returns:
            The port's ``url``.

        Usage::

            box = noclick.Machine.from_name("support-box")
            dashboard = box.expose(8080)
            print(dashboard.url)
        """
        raw = await self._request("POST", f"{await self._path()}/ports", json={"port": port, "public": public})
        self._raw = await self._load()
        return MachinePort._from(raw)

    @synced
    async def close_port(self, port: int) -> None:
        """Stop serving ``port``; its URL stops answering.

        Usage::

            noclick.Machine.from_name("support-box").close_port(8080)
        """
        await self._request("DELETE", f"{await self._path()}/ports/{int(port)}")
        self._raw = await self._load()

    @synced
    async def agents(self) -> List[Any]:
        """The agents that run on it.

        Returns:
            Each ``Agent``, loaded.

        Usage::

            box = noclick.Machine.from_name("support-box")
            print([agent.name for agent in box.agents()])
        """
        from .agent import Agent

        page = await self._request("GET", f"{await self._path()}/agents") or {}
        return [Agent._new(raw=row, client=self._client, user=self._call_scope()) for row in page.get("data") or []]

    # --- management ------------------------------------------------------

    @synced
    async def update(
        self, *, name: Any = UNSET, size: Any = UNSET, volumes: Any = UNSET, network: Any = UNSET,
        max_monthly_usd: Any = UNSET, max_conversations: Any = UNSET, agent_share: Any = UNSET,
        docker: Any = UNSET,
        app_testing: Any = UNSET,
    ) -> "Machine":
        """Rename it, change its size, volumes, network or price ceiling. New volumes and
        network apply without a restart (each conversation's from its next turn). A larger
        size restarts it once running turns finish (``updating``); the new price applies
        from the next day. A smaller size moves a running machine to a new host, since no
        host shrinks a disk in place: its user's home is copied over and each conversation
        loads its files from where they're saved, a longer restart (what's on its disk
        must fit the smaller one; a move that fails leaves it on its old host).
        Your own machine takes ``max_conversations`` (``None``: what its server takes)
        ``agent_share`` (``None``: 0.75), ``app_testing`` and ``docker`` (as in ``add_own``) instead of a
        size or a price; its server takes them within seconds, each conversation's
        container at its next start.

        Returns:
            This machine, updated.

        Usage::

            box = noclick.Machine.from_name("support-box")
            box.update(size="large", max_monthly_usd=240)
        """
        changes = compact(name=None if name is UNSET else name, size=None if size is UNSET else size,
                          network=None if network is UNSET else network,
                          max_monthly_usd=None if max_monthly_usd is UNSET else max_monthly_usd)
        for key, value in (("max_conversations", max_conversations), ("agent_share", agent_share), ("docker", docker),
                           ("app_testing", app_testing)):
            if value is not UNSET:
                changes[key] = value
        if volumes is not UNSET:
            changes["volumes"] = await volume_ids(volume_refs(volumes, user=self._call_scope(), client=self._client))
        self._raw = await self._request("PATCH", await self._path(), json=changes)
        return self

    @synced
    async def new_pairing_code(self) -> "Machine":
        """Your own machine, until its server is set up: a new one-time code (and
        command) in place of the last one, which stops working.

        Returns:
            This machine, with the new ``pairing``.

        Usage::

            home = noclick.Machine.get("7c1d9a20-2b6f-4e0a-9d51-3f8e6a4b2c10")
            print(home.new_pairing_code().pairing.command)
        """
        self._raw = await self._request("POST", f"{await self._path()}/pairing_code")
        return self

    @synced
    async def restart(self) -> Operation:
        """Restart it now, without waiting for running turns (they fail as interrupted).
        Its disk and volumes are kept; a ``machine.restarted`` event follows.

        Returns:
            An ``Operation`` whose ``wait()`` gives the machine, ``running`` again.

        Usage::

            box = noclick.Machine.from_name("support-box")
            print(box.restart().wait().status)   # running
        """
        payload = await self._request("POST", f"{await self._path()}/restart")
        return Operation._from_payload(payload, client=self._client, user=self._call_scope(), kind="machine.restart",
                                       reader=_read_machine)

    @synced
    async def stop(self) -> "Machine":
        """Stop it: its agents take no turns (a message raises ``noclick.NotAvailable``)
        until ``start()``. It's still charged, since it stays yours.

        Returns:
            This machine, ``stopped``.

        Usage::

            noclick.Machine.from_name("support-box").stop()
        """
        self._raw = await self._request("POST", f"{await self._path()}/stop")
        return self

    @synced
    async def start(self) -> "Machine":
        """Start a stopped machine. One stopped because the balance couldn't pay it
        is charged what it owes first (``noclick.PaymentRequired`` while it can't).

        Returns:
            This machine, ``provisioning`` until it's ``running``.

        Usage::

            noclick.Machine.from_name("support-box").start()
        """
        self._raw = await self._request("POST", f"{await self._path()}/start")
        return self

    @synced
    async def shell(self) -> MachineShell:
        """Open a shell (``bash -l``) on this machine, as its user, in its home: for the account's owner, with
        its secret key or signed in, while it's running. Your own machine's too (on a Mac, in NoClick's VM
        there). ``noclick machines ssh <name>`` opens one in your own terminal.

        Returns:
            The websocket's ``url`` and its single-use ``token`` (good for two minutes): hand them to a browser
            terminal (xterm.js) from your server.

        Usage::

            box = noclick.Machine.from_name("support-box")
            opened = box.shell()
            send_to_browser(opened.url, opened.token)
        """
        return MachineShell._from(await self._request("POST", f"{await self._path()}/shell"))

    @synced
    async def delete(self) -> None:
        """Delete it, with its disk; attached volumes stay. The agents on it go
        back to their own cloud sandboxes first, each from its next turn. The
        charge stops that day. Your own machine is removed from NoClick, which
        uninstalls itself from the server when it next answers.

        Usage::

            box = noclick.Machine.from_name("support-box")
            moving = box.agents()   # what goes back to sandboxes
            box.delete()
        """
        await self._request("DELETE", await self._path())
