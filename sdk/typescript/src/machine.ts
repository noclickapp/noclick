/**
 * Machines: an always-on computer for agents that should never sleep.
 *
 *     const box = Machine.fromName("support-box", { createIfMissing: true, size: "medium", region: "eu", maxMonthlyUsd: 120 });
 *     await Agent.create("support", { instructions: "...", harness: "claude_code", modelConnection: "claude", machine: box });
 *
 * An agent on a machine runs its harness there instead of in a sandbox of its own: nothing
 * is reaped when it goes quiet, and there's no per-minute sandbox charge, only the machine's flat
 * monthly price. Each agent gets its own container on the machine. Model and tool calls go
 * through NoClick's credential proxy with temporary keys, so your real keys are never on it.
 * NoClick manages its image and updates, restarts it if it fails (rebuilding it on a new host from its last
 * backup if it must), and attached volumes outlive it.
 *
 * A Linux server you run can be one too, free (`Machine.addOwn`): run the command its `pairing` shows on the
 * server as root, and your agents run there in containers.
 *
 *     const home = await Machine.addOwn();
 *     console.log(home.pairing?.command);
 *     // curl -fsSL https://api.noclick.com/machine-agent/v1/machine.sh | sudo sh -s -- --code nc_mach_...
 */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL, resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Conflict, NotFound } from "./errors.ts";
import {
  ApiObject, asList, asObject, checkUnchanged, compact, createNamed, defined, givesFields, listAll, listPage, num, parseTime, str,
} from "./object.ts";
import type { AppTesting } from "./agent.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import type { RegionName } from "./region.ts";
import type { ExecOptions, ExecResult } from "./sandbox.ts";
import { resolveScope } from "./scope.ts";
import { volumeMountIds } from "./volume.ts";
import type { VolumeRef } from "./volume.ts";

/** `xlarge` is Hetzner's alone, so it runs only in `eu`. */
export type MachineSizeName = "small" | "medium" | "large" | "xlarge";
/** The host a machine runs on, for its life. */
export type MachineHostName = "hetzner" | "digitalocean";
/** `awaiting_approval`: rented while NoClick reviews the account's company; it starts once that's approved. */
export type MachineStatus =
  | "awaiting_approval" | "provisioning" | "running" | "offline" | "restarting" | "updating" | "stopped" | "failed";
/** `noclick`: a machine NoClick runs, at a monthly price. `own`: a server you added, free. */
export type MachineKind = "noclick" | "own";
/**
 * Where each conversation's workspace (`/workspace`) lives: `local` (your own machine's default: on its disk alone,
 * never saved, so a turn ends without waiting on a save; a conversation that starts elsewhere, or whose agent leaves,
 * starts with an empty one) or `saved` (in NoClick's volumes, saved after every turn; always on a machine NoClick
 * runs).
 */
export type MachineWorkspaces = "local" | "saved";

/**
 * Your own machine until its server is set up: the one-time code (and the command carrying it), which NoClick
 * only shows as it makes it, so a machine read again has `code` and `command` null.
 */
export interface MachinePairing {
  code: string | null;
  /** What to run on the server as root (a Linux server's, or a Linux distro's in WSL on Windows). */
  command: string | null;
  /**
   * The command for each system: `linux` (`command`) and `mac`, run in Terminal as you, never root; and each with
   * `--yes` to install unattended (SSH, cloud-init, a script): `linuxUnattended`, `macUnattended`.
   */
  commands: { linux: string; mac: string; linuxUnattended: string; macUnattended: string } | null;
  /** When the code stops working (30 minutes after it was made); `newPairingCode()` makes another. */
  expiresAt: Date | null;
  /** The server being set up with the code, once its installer started. */
  installingOn: string | null;
  /** The last server turned away with the code, and why (null since the code was made, or once one pairs). */
  refused: MachineRefusal | null;
  raw: JsonObject;
}

/** A server turned away with your own machine's code: by NoClick (its system, or the code expired) or by the
 * installer itself. Cleared by a new code or a server that pairs. */
export interface MachineRefusal {
  system: string | null;
  arch: string | null;
  hostname: string | null;
  /** What the server's terminal printed, whole. */
  message: string;
  /** What to do, where NoClick knows it. */
  nextStep: string | null;
  at: Date | null;
  raw: JsonObject;
}

/** Invite-only beta. A size on one host (`MachineSize.hosts`): where it runs, its disk there and its price there. */
export interface MachineHost {
  host: MachineHostName;
  /** The regions it runs in on this host (`regions()`). */
  regions: RegionName[];
  diskGb: number;
  /** Its price per month in US dollars on this host, whatever it runs and whether it's busy. */
  monthlyUsd: number;
}

/**
 * Invite-only beta. A region a size can be bought in now (`MachineSize.regions`, cheapest first): the host a new one
 * would go on there, and its disk and flat monthly price there.
 */
export interface MachineSizeRegion {
  /** What `create` takes as `region`. */
  region: RegionName;
  /** The host a new one would go on there now: what `create` takes as `host`. */
  host: MachineHostName;
  diskGb: number;
  /** Its price per month in US dollars on that host: what `create` takes as `maxMonthlyUsd`. */
  monthlyUsd: number;
  /**
   * A size that can be bought there now with at least its vCPUs and memory for no more, which makes this one no buy
   * there (only listed with `includeDominated`).
   */
  dominatedBy: MachineSizeName | null;
}

/**
 * Invite-only beta. One of `Machine.sizes()`: its processors and memory, and how it's bought now. `region`, `host`,
 * `diskGb` and `monthlyUsd` are its cheapest offer anywhere (or, asked about a region, there); `regions` lists every
 * region it can be bought in now, cheapest first, and `hosts` each host that runs it. Stock is read at most a minute
 * before; `create` checks again, so pass `region`, `host` and `monthlyUsd` (as `maxMonthlyUsd`) to buy exactly this.
 */
export interface MachineSize {
  name: MachineSizeName;
  /** vCPUs (hardware threads), as hosts sell them. */
  cpu: number;
  memoryGb: number;
  /** The machine's own disk on `host` (while it isn't available, on the first host that sells it). */
  diskGb: number;
  /**
   * Its price per month in US dollars on `host` in `region` (while it isn't available, the price it has once the first
   * host that sells it has one again).
   */
  monthlyUsd: number;
  /** About how many coding-agent conversations can work on it at the same moment. */
  workingConversations: number;
  /** Whether it can be bought now (only false with `includeDominated`). */
  available: boolean;
  /**
   * Where it's cheapest now (your account's default region first at one price), or the region asked about; null when
   * it can't be bought anywhere.
   */
  region: RegionName | null;
  /** The host a new one would go on there now; null while it can't be bought. */
  host: MachineHostName | null;
  /** A size that can be bought now with at least its vCPUs and memory for no more (only listed with `includeDominated`). */
  dominatedBy: MachineSizeName | null;
  /** Each region it can be bought in now, cheapest first: the host, disk and price there. */
  regions: MachineSizeRegion[];
  /** Each host that runs it, cheapest first: its regions, disk and price there. */
  hosts: MachineHost[];
  raw: JsonObject;
}

/**
 * Invite-only beta. A port a machine serves; a private one asks for an API key with the `machines`
 * scope, a public one answers anyone.
 */
export interface MachinePort {
  port: number;
  url: string;
  public: boolean;
  raw: JsonObject;
}

function toPort(value: unknown): MachinePort {
  const raw = asObject(value);
  return { port: num(raw.port) ?? 0, url: str(raw.url) ?? "", public: raw.public === true, raw };
}

function toExec(result: unknown): ExecResult {
  const raw = asObject(result);
  const exitCode = typeof raw.exit_code === "number" ? raw.exit_code : null;
  return { stdout: str(raw.stdout) ?? "", stderr: str(raw.stderr) ?? "", exitCode, ok: exitCode === 0, raw };
}

registerResult("machine.exec", toExec);

function toPairing(value: unknown): MachinePairing | null {
  if (!value) return null;
  const raw = asObject(value);
  return {
    code: str(raw.code), command: str(raw.command), commands: toCommands(raw.commands),
    expiresAt: parseTime(raw.expires_at), installingOn: str(raw.installing_on), refused: toRefusal(raw.refused), raw,
  };
}

function toCommands(value: unknown): MachinePairing["commands"] {
  if (!value) return null;
  const raw = asObject(value);
  return {
    linux: str(raw.linux) ?? "", mac: str(raw.mac) ?? "",
    linuxUnattended: str(raw.linux_unattended) ?? "", macUnattended: str(raw.mac_unattended) ?? "",
  };
}

function toRefusal(value: unknown): MachineRefusal | null {
  if (!value) return null;
  const raw = asObject(value);
  return {
    system: str(raw.system), arch: str(raw.arch), hostname: str(raw.hostname), message: str(raw.message) ?? "",
    nextStep: str(raw.next_step), at: parseTime(raw.at), raw,
  };
}

/** `Machine.addOwn` options. */
export interface MachineAddOwnOptions extends CallOptions {
  /** Omitted, it takes the server's hostname when its installer runs. */
  name?: string;
  /** How many of its agents' conversations may work at once, at most what the server takes. */
  maxConversations?: number;
  /**
   * The part of the server its agents use, 0.1 to 1: 0.75 by default, 1 for a server just for NoClick. On a Mac,
   * NoClick's VM is made that size.
   */
  agentShare?: number;
  /**
   * Whether its agents run apps and test databases (`AppTesting`): `ask_first` unless it says (each agent asks its
   * owner in the chat first). Each conversation's container then runs its own Docker, inside the container's gVisor
   * sandbox (no host socket, nothing privileged on the server); a container whose agent's network is limited runs
   * without it. An agent on it gets the stricter of this and its own `appTesting`.
   */
  appTesting?: AppTesting;
  /** Sent alone, `true` chooses `appTesting: "by_itself"` and `false` `"never"`. */
  docker?: boolean;
  /**
   * Where each conversation's workspace lives (`MachineWorkspaces`): `local` unless it says. Either way, a checkout
   * kept on the server borrows from its repo cache, package managers share their caches, and its volumes are mounted
   * read-only.
   */
  workspaces?: MachineWorkspaces;
}

export interface MachineCreateOptions extends CallOptions {
  /** One of `Machine.sizes()`; `small` by default. */
  size?: MachineSizeName;
  /** Where it runs (`regions()`), for good; omitted, your account's default region, else `us-east`. */
  region?: RegionName;
  /**
   * Volumes it attaches, by absolute path: each conversation sees a volume as it was when its turn started
   * and saves its writes when the turn ends.
   */
  volumes?: Record<string, VolumeRef>;
  /**
   * What the machine's own commands may reach: `true` (anywhere the machines usage policy allows: no mail
   * ports, mining pools or private addresses) or a list of hosts (HTTPS to them, `"*.github.com"` for
   * subdomains, and name lookups).
   */
  network?: boolean | string[];
  /**
   * The most its size may cost a month on the host it goes on; above it nothing starts (`PriceExceeded`, naming the
   * host and its price when only a dearer host has stock).
   */
  maxMonthlyUsd: number;
  /**
   * The host to put it on, for its life. Omitted, the cheapest host that runs the size in the region and has stock
   * (Hetzner in `eu`, DigitalOcean everywhere: `Machine.sizes()`), never one costing more than `maxMonthlyUsd`.
   */
  host?: MachineHostName;
}

/** How hard a running machine works, from its last check-in (`machine.lastSeenAt`). */
export interface MachineHealth {
  /** Its vCPUs (your own: the server's). */
  cpus: number | null;
  /** Its one-minute load average, and that as a part of its vCPUs kept busy (at most 100). */
  load1m: number;
  cpuPercent: number | null;
  /** Memory in use and in all (your own: the whole server's; its agents use `agentShare` of it). */
  memoryUsedGb: number;
  memoryTotalGb: number;
  diskUsedGb: number;
  diskTotalGb: number;
}

/** Each agent on a machine: working while one of its conversations there is. */
export interface MachineAgentState {
  agentId: string;
  working: boolean;
}

/** A file or folder on a machine's disk (`machine.files.list`). */
export interface MachineFileEntry {
  path: string;
  type: "file" | "directory";
  /** A file's bytes (null for a folder). */
  size: number | null;
  updatedAt: Date | null;
}

/**
 * A shell on a machine NoClick runs (`machine.shell()`): `url` is a websocket, opened once with `token` within two
 * minutes, whose first message is `{"type": "auth", token, cols, rows}`; then binary messages carry what you type and
 * what it prints, a text `{"type": "resize", cols, rows}` sizes it, and it closes (code 4410) once bash exits, after
 * `idleLimitS` with nothing typed, or when the socket closes.
 */
export interface MachineShell {
  machineId: string;
  url: string;
  token: string;
  tokenExpiresAt: Date | null;
  idleLimitS: number;
}

/** Invite-only beta. `machine.files`: read and write files on the machine's own disk. */
export class MachineFiles {
  private readonly machine: Machine;

  constructor(machine: Machine) {
    this.machine = machine;
  }

  async write(path: string, data: string | Uint8Array | ArrayBuffer | Blob): Promise<void> {
    await this.machine._request("PUT", `${await this.machine._path()}/files`, { query: { path }, body: data });
  }

  async read(path: string): Promise<Uint8Array> {
    return await this.machine._request<Uint8Array>("GET", `${await this.machine._path()}/files`, {
      query: { path }, responseType: "bytes",
    });
  }

  /** The files and folders in the folder at `path` (relative paths are under `/home/noclick`), by name. */
  async list(path = "/home/noclick"): Promise<MachineFileEntry[]> {
    const found: MachineFileEntry[] = [];
    let cursor: string | undefined;
    do {
      const page = asObject(await this.machine._request("GET", `${await this.machine._path()}/files`, {
        query: cursor ? { path, view: "list", cursor } : { path, view: "list" },
      }));
      for (const raw of asList(page.data)) {
        const entry = asObject(raw);
        found.push({ path: str(entry.path) ?? "", type: entry.type === "directory" ? "directory" : "file",
          size: num(entry.size), updatedAt: parseTime(entry.updated_at) });
      }
      cursor = str(page.next_cursor) ?? undefined;
    } while (cursor);
    return found;
  }
}

/**
 * Invite-only beta.
 *
 * An always-on computer of a fixed `size` in one `region`, billed a flat monthly price (a thirtieth
 * of it a day while it exists, running or stopped). Agents created with `machine` run their harness
 * on it, each conversation in a container of its own; `exec`, `files` and `expose` reach the
 * machine itself.
 */
export class Machine extends ApiObject {
  private _createWith: JsonObject | null = null;
  private _createVolumes: Record<string, VolumeRef> | undefined;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * The sizes worth buying now, smallest first: size first, each at its cheapest anywhere (its `region`, `host`,
   * `diskGb` and `monthlyUsd`), or as bought in `region` (`regions()`), with every region it can be bought in now,
   * cheapest first (`regions`). A size that can't be bought now is left out, as is one where another that can be
   * bought has at least its vCPUs and memory for no more (judged across every region, or in `region`; a larger disk
   * alone doesn't count); `includeDominated` lists every size, each with `available` and `dominatedBy`.
   *
   *     const [size] = await Machine.sizes();
   *     await Machine.create("support-box", { size: size.name, region: size.region!, host: size.host!, maxMonthlyUsd: size.monthlyUsd });
   */
  static async sizes(options: { region?: RegionName; includeDominated?: boolean; client?: NoClick } = {}): Promise<MachineSize[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/machines/sizes", {
      query: { region: options.region, include_dominated: options.includeDominated ? "true" : undefined }, user: null,
    });
    return asList(page).map((value) => {
      const raw = asObject(value);
      return {
        name: str(raw.name) as MachineSizeName, cpu: num(raw.cpu) ?? 0, memoryGb: num(raw.memory_gb) ?? 0,
        diskGb: num(raw.disk_gb) ?? 0, monthlyUsd: num(raw.monthly_usd) ?? 0,
        workingConversations: num(raw.working_conversations) ?? 0,
        available: raw.available === true, region: str(raw.region) as RegionName | null,
        host: str(raw.host) as MachineHostName | null, dominatedBy: str(raw.dominated_by) as MachineSizeName | null,
        regions: asList(raw.regions ?? []).map((entry) => {
          const where = asObject(entry);
          return {
            region: str(where.region) as RegionName, host: str(where.host) as MachineHostName,
            diskGb: num(where.disk_gb) ?? 0, monthlyUsd: num(where.monthly_usd) ?? 0,
            dominatedBy: str(where.dominated_by) as MachineSizeName | null,
          };
        }),
        hosts: asList(raw.hosts ?? []).map((offer) => {
          const host = asObject(offer);
          return {
            host: str(host.host) as MachineHostName, regions: asList(host.regions).map((r) => str(r) as RegionName),
            diskGb: num(host.disk_gb) ?? 0, monthlyUsd: num(host.monthly_usd) ?? 0,
          };
        }),
        raw,
      };
    });
  }

  /**
   * Whether NoClick vetted the account's company for machines (`status`: `not_submitted`, `pending`, `approved` or
   * `rejected`, with its `reason`), which an account's first machine needs.
   *
   *     const access = await Machine.access();
   *     if (access.status !== "approved") console.log(access.status, access.reason);
   */
  static async access(options: { client?: NoClick; signal?: AbortSignal } = {}): Promise<MachineAccess> {
    return toMachineAccess(asObject(await resolveClient(options.client).request("GET", "/v1/machines/vetting", {
      user: null, signal: options.signal,
    })));
  }

  /**
   * Ask NoClick for machines: the company, its website and country (ISO 3166-1 alpha-2), what its machines will run,
   * and the machines usage policy accepted. Signed in, the owner accepts it themselves; from your server, a key holding
   * `machines:vetting` also says who accepted it and when (`acceptedBy`, `acceptedAt`). NoClick reviews it before the
   * account's first machine; an approved account gets `Conflict`.
   *
   *     await Machine.requestAccess({ companyName: "Acme", website: "https://acme.com", country: "US",
   *       useCase: "Support agents that never sleep", acceptUsagePolicy: true });
   */
  static async requestAccess(request: MachineAccessRequest, options: { client?: NoClick } = {}): Promise<MachineAccess> {
    const json = compact({
      company_name: request.companyName, website: request.website, country: request.country, use_case: request.useCase,
      accept_usage_policy: request.acceptUsagePolicy, accepted_by: request.acceptedBy,
      accepted_at: request.acceptedAt?.toISOString(),
    });
    return toMachineAccess(asObject(await resolveClient(options.client).request("POST", "/v1/machines/vetting", { json, user: null })));
  }

  /**
   * Start an always-on machine called `name` (unique to its user; a taken name throws `Conflict`
   * with `existingId`, or with `allowExisting: true` returns the machine already there, as it is: nothing
   * about it changes), refused with `PriceExceeded` if its size costs more than `maxMonthlyUsd` on the host it goes
   * on: the cheapest host with stock for it in its region, or `host` when one is named. An
   * account's first machine needs its company vetted by NoClick: its owner asks in the developer console
   * (Resources, Machines), saying what its machines will run, and until NoClick approves it this throws
   * `ActionRequired`, whose `nextStep` links that page.
   */
  static async create(name: string, options: MachineCreateOptions & AllowExisting): Promise<Machine> {
    const scope = resolveScope(options.user);
    const json = compact({
      name, size: options.size ?? "small", region: options.region, network: options.network,
      max_monthly_usd: options.maxMonthlyUsd, volumes: await volumeMountIds(options.volumes, { ...options, user: scope }),
      host: options.host,
    });
    const raw = await createNamed("/v1/machines", json, { allowExisting: options.allowExisting, user: scope, client: options.client });
    return new Machine({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the machine called `name`. Given fields, it gets the machine and sets the `size`,
   * `volumes`, `network` and `maxMonthlyUsd` you pass, on every run (a new size restarts it, judged
   * against the `maxMonthlyUsd` set with it). Fields left out are never changed. Its `region` and `host` are
   * fixed: an existing machine in another throws `Conflict` naming it. `createIfMissing` (with `maxMonthlyUsd`)
   * starts it when there's none; without it, a missing machine throws `NotFound`.
   */
  static fromName(
    name: string,
    options: CallOptions & Partial<MachineCreateOptions> & { createIfMissing?: boolean } = {},
  ): Machine {
    const machine = new Machine({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing && options.maxMonthlyUsd === undefined) {
      throw new TypeError("Machine.fromName(..., { createIfMissing: true }) needs maxMonthlyUsd");
    }
    machine._creates = Boolean(options.createIfMissing);
    if (machine._creates || givesFields(options)) {
      machine._createWith = compact({
        name, size: options.size, region: options.region, network: options.network, max_monthly_usd: options.maxMonthlyUsd,
        host: options.host,
      });
      machine._createVolumes = options.volumes;
    }
    return machine;
  }

  static fromId(machineId: string, options: CallOptions = {}): Machine {
    return new Machine({ hints: { id: machineId }, client: options.client, user: options.user });
  }

  static async get(machineId: string, options: CallOptions = {}): Promise<Machine> {
    return await Machine.fromId(machineId, options).hydrate();
  }

  /**
   * Add a Linux server you run (x86-64 or ARM64, with sudo) as a machine your account's agents run on, in containers:
   * free, its agents' model calls at cost. Its containers can't reach its network, and on the server itself NoClick
   * only opens the account owner's `shell` and `files`, as its `noclick` user.
   * Run `pairing.command` on it as root within 30 minutes; it's `provisioning` until the server answers, then
   * `running`, and `offline` while it's silent (its agents' turns fail then). Called again before a server pairs,
   * it returns that same machine, with its code while the code is good and a new one once it expired: add one per
   * server, after the last one paired. The account's only: not for `asUser`.
   */
  static async addOwn(options: MachineAddOwnOptions = {}): Promise<Machine> {
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/machines/own", {
      json: compact({
        name: options.name, max_conversations: options.maxConversations, agent_share: options.agentShare,
        docker: options.docker,
        app_testing: options.appTesting, workspaces: options.workspaces,
      }),
      user: null,
    });
    return new Machine({ raw, client: options.client, user: null });
  }

  /**
   * Whether agents run on machines on this API yet. Until they do, an agent isn't put on a machine and your own
   * server isn't added (`NotAvailable`), and each machine reads `agentsEnabled` false.
   */
  static async agentsEnabledHere(options: { client?: NoClick } = {}): Promise<boolean> {
    const page = await resolveClient(options.client).request<JsonObject>("GET", "/v1/machines", {
      query: { limit: 1 }, user: null,
    });
    return page.agents_enabled === true;
  }

  /** The current user's machines (the account's own outside `asUser`, or those `userFilter` covers); `kind` narrows them. */
  static async list(options: ReadOptions & { limit?: number; kind?: MachineKind } = {}): Promise<Machine[]> {
    return await listAll({ ...options, path: "/v1/machines", query: { kind: options.kind } },
      (raw, user) => new Machine({ raw, client: options.client, user }));
  }

  /** One page of machines; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions & { kind?: MachineKind } = {}): Promise<Page<Machine>> {
    return await listPage({ ...options, path: "/v1/machines", query: { kind: options.kind } },
      (raw, user) => new Machine({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get kind(): MachineKind {
    return this._field("kind");
  }
  /** Null on your own machine, which is the size its server is. */
  get size(): MachineSizeName | null {
    return this._field("size");
  }
  /** vCPUs (hardware threads). */
  get cpu(): number | null {
    return this._field("cpu");
  }
  get memoryGb(): number | null {
    return this._field("memory_gb");
  }
  /** The host it runs on, for its life; null on your own. */
  get host(): MachineHostName | null {
    return this._field("host");
  }
  /** Its disk. A larger size on Hetzner keeps the disk it had, so a move back down stays a resize. */
  get diskGb(): number | null {
    return this._field("disk_gb");
  }
  /** The server's system, as it reports it (`Ubuntu 24.04.1 LTS`). */
  get os(): string | null {
    return this._field("os");
  }
  get hostname(): string | null {
    return this._field("hostname");
  }
  /** When it last answered NoClick: on your own machine `offline`, since when. */
  get lastSeenAt(): Date | null {
    return parseTime(this._field("last_seen_at"));
  }
  /** Your own machine: the most of its agents' conversations you let work at once (null: what the server takes). */
  get maxConversations(): number | null {
    return this._field("max_conversations");
  }
  /** How many of its agents' conversations work at once. */
  get conversationsAtOnce(): number | null {
    return this._field("conversations_at_once");
  }
  /** Your own machine: the part of its CPUs and memory its agents use (0.75 by default); the rest stays yours. */
  get agentShare(): number | null {
    return this._field("agent_share");
  }
  /** True on a Mac once NoClick's VM is made: a VM keeps its size. */
  get agentShareFixed(): boolean | null {
    return this._field("agent_share_fixed");
  }
  /** Your own machine: whether its agents' containers run Docker (any `appTesting` but `never`). */
  get docker(): boolean {
    return Boolean(this._field("docker"));
  }
  /** Your own machine: whether its agents run apps and test databases (`AppTesting`); `never` on one NoClick runs. */
  get appTesting(): AppTesting {
    return this._field<AppTesting | null>("app_testing") ?? "never";
  }
  /** Where each conversation's workspace lives (`MachineWorkspaces`): `saved` on a machine NoClick runs. */
  get workspaces(): MachineWorkspaces {
    return this._field<MachineWorkspaces | null>("workspaces") ?? "saved";
  }
  /** Whether agents run on machines on this API yet (`Machine.agentsEnabledHere()`). */
  get agentsEnabled(): boolean | null {
    return this._field("agents_enabled");
  }
  /** Your own machine until its server is set up; null after, and on a machine NoClick runs. */
  get pairing(): MachinePairing | null {
    return toPairing(this._field("pairing"));
  }
  /** The region it runs in, fixed when it was created. */
  get region(): RegionName | null {
    return this._field("region");
  }
  get status(): MachineStatus {
    return this._field("status");
  }
  /** Why it's stopped or failed, or why it restarted. */
  get statusReason(): string | null {
    return this._field("status_reason");
  }
  /** What its own commands may reach: `true` (anywhere the machines usage policy allows) or the hosts. */
  get network(): boolean | string[] | null {
    return this._field("network");
  }
  /** What it costs a month, in US dollars, running or stopped (0 for your own). */
  get monthlyUsd(): number | null {
    return this._field("monthly_usd");
  }
  get maxMonthlyUsd(): number | null {
    return this._field("max_monthly_usd");
  }
  /** The volumes it mounts: `{ path: volume id }`. */
  get volumes(): Record<string, string> {
    return this._field<Record<string, string> | null>("volumes") ?? {};
  }
  get ports(): MachinePort[] {
    return asList(this._field("ports")).map(toPort);
  }
  get agentCount(): number | null {
    return this._field("agent_count");
  }
  /** How many of its agents are working now, from its last check-in. */
  get workingCount(): number | null {
    return this._field("working_count");
  }
  get agentStates(): MachineAgentState[] {
    return asList(this._field("agent_states")).map((raw) => {
      const state = asObject(raw);
      return { agentId: str(state.agent_id) ?? "", working: state.working === true };
    });
  }
  /** What it was charged this month (UTC) so far, in US dollars. */
  get spentUsdThisMonth(): number | null {
    return this._field("spent_usd_this_month");
  }
  /** When it last booted, while it runs: its uptime. */
  get startedAt(): Date | null {
    return parseTime(this._field("started_at"));
  }
  /** How hard it works, from its last check-in while it runs; null otherwise. */
  get health(): MachineHealth | null {
    const raw = this._field<JsonObject | null>("health");
    if (!raw) return null;
    return {
      cpus: num(raw.cpus), load1m: num(raw.load_1m) ?? 0, cpuPercent: num(raw.cpu_percent),
      memoryUsedGb: num(raw.memory_used_gb) ?? 0, memoryTotalGb: num(raw.memory_total_gb) ?? 0,
      diskUsedGb: num(raw.disk_used_gb) ?? 0, diskTotalGb: num(raw.disk_total_gb) ?? 0,
    };
  }
  /** While `updating`: the size it becomes, and whether it moves to a new host for it. */
  get pending(): { size: MachineSizeName; move: boolean } | null {
    const raw = this._field<JsonObject | null>("pending");
    return raw ? { size: (str(raw.size) ?? "small") as MachineSizeName, move: raw.move === true } : null;
  }
  /** The NoClick-managed image it runs, with its harness versions. */
  get image(): string | null {
    return this._field("image");
  }
  /** How many times it restarted after failing, ever. */
  get restarts(): number | null {
    return this._field("restarts");
  }
  get lastRestartAt(): Date | null {
    return parseTime(this._field("last_restart_at"));
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** This machine in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/machines?machine=${encodeURIComponent(String(this._known("id")))}`;
  }
  get files(): MachineFiles {
    return new MachineFiles(this);
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/machines/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/machines", { query: { name } })) as JsonObject[]).filter((r) => r.name === name);
    if (rows.length) return await this.converge(rows[0]);
    if (!this._creates) {
      throw new NotFound(`No machine is named "${name}".`, {
        nextStep: "Create it with Machine.create(...) or pass { createIfMissing: true }.",
        details: { name, kind: "machine" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/machines", { json: await this.wanted() });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/machines/${err.existingId}`));
    }
  }

  private async wanted(): Promise<JsonObject> {
    const volumes = await volumeMountIds(this._createVolumes, { client: this._client, user: this._scope });
    return compact({ ...this._createWith, volumes });
  }

  /** Set the fields `fromName` was given on an existing machine, after checking the ones it can't set. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    if (!this._createWith) return raw;
    checkUnchanged("machine", raw, { region: this._createWith.region, host: this._createWith.host });
    const wanted = await this.wanted();
    // A new size is judged against the ceiling sent with it.
    const changes = Object.fromEntries(
      ["size", "volumes", "network", "max_monthly_usd"].filter((k) => k in wanted && JSON.stringify(raw[k] ?? null) !== JSON.stringify(wanted[k]))
        .map((k) => [k, wanted[k]]),
    );
    if (!Object.keys(changes).length) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/machines/${raw.id}`, { json: changes });
  }

  /** @internal */
  async _path(): Promise<string> {
    return `/v1/machines/${(await this._ensure()).id}`;
  }

  /**
   * Run a shell command on the machine itself (not in a conversation's container): `timeoutS` is 60
   * by default, at most 90; `{ background: true }` returns an `Operation`, for up to an hour.
   */
  exec(command: string, options: ExecOptions & { background: true }): Promise<Operation<ExecResult>>;
  exec(command: string, options?: ExecOptions & { background?: false }): Promise<ExecResult>;
  async exec(command: string, options: ExecOptions = {}): Promise<ExecResult | Operation<ExecResult>> {
    const payload = await this._request("POST", `${await this._path()}/exec`, {
      json: compact({ command, background: options.background || undefined, timeout_s: options.timeoutS }),
    });
    if (options.background) {
      return Operation._fromPayload<ExecResult>(payload, { client: this._client, user: this._callScope(), kind: "machine.exec", reader: toExec });
    }
    return toExec(payload);
  }

  /**
   * Serve `port` at an HTTPS URL on NoClick's domain: private (an API key with the `machines` scope, which the
   * app never sees) unless `public`.
   */
  async expose(port: number, options: { public?: boolean } = {}): Promise<MachinePort> {
    const raw = await this._request("POST", `${await this._path()}/ports`, { json: { port, public: options.public ?? false } });
    this._raw = await this._load();
    return toPort(raw);
  }

  /** Stop serving `port`; its URL stops answering. */
  async closePort(port: number): Promise<void> {
    await this._request("DELETE", `${await this._path()}/ports/${port}`);
    this._raw = await this._load();
  }

  /**
   * Open a shell (`bash -l`) on this machine, as its user, in its home: for the account's owner, with its secret key
   * or signed in, while it's running. Your own machine's too (on a Mac, in NoClick's VM there). Hand `url` and `token`
   * to a browser terminal: `new TerminalConnection(shell.url, shell.token, { renew: async () => (await
   * machine.shell()).token })` renews it in place (with no `renew`, it has no lifetime).
   */
  async shell(): Promise<MachineShell> {
    const raw = asObject(await this._request("POST", `${await this._path()}/shell`));
    return {
      machineId: str(raw.machine_id) ?? "", url: str(raw.url) ?? "", token: str(raw.token) ?? "",
      tokenExpiresAt: parseTime(raw.token_expires_at), idleLimitS: num(raw.idle_limit_s) ?? 0,
    };
  }

  /** The agents that run on it, as their API rows (`Agent.fromId(row.id)` for the object). */
  async agents(): Promise<JsonObject[]> {
    return asList(await this._request("GET", `${await this._path()}/agents`)) as JsonObject[];
  }

  /**
   * Rename it, change its size, volumes, network or price ceiling. New volumes and network apply without a
   * restart (each conversation's from its next turn). A larger size restarts it once running turns finish
   * (`updating`); the new price, its host's, applies from the next day. A size stays on the machine's host. A
   * smaller disk moves a running machine to a new host (a larger size on Hetzner keeps its disk, so moving back
   * down stays a resize), since no host shrinks a disk in place: its user's home is copied over and each conversation loads its files
   * from where they're saved, a longer restart (what's on its disk must fit the smaller one; a move that fails
   * leaves it on its old host). Your own machine takes `maxConversations`, `agentShare`, `appTesting`, `docker` and
   * `workspaces` instead of a size or a price; its server takes them within seconds, each conversation's container at
   * its next start.
   */
  async update(changes: {
    name?: string; size?: MachineSizeName; volumes?: Record<string, VolumeRef>; network?: boolean | string[];
    maxMonthlyUsd?: number; maxConversations?: number | null; agentShare?: number | null; docker?: boolean;
    appTesting?: AppTesting; workspaces?: MachineWorkspaces;
  }): Promise<this> {
    const json = defined({
      name: changes.name, size: changes.size, network: changes.network, max_monthly_usd: changes.maxMonthlyUsd,
      docker: changes.docker, app_testing: changes.appTesting, workspaces: changes.workspaces,
      volumes: await volumeMountIds(changes.volumes, { client: this._client, user: this._callScope() }),
    });
    // Your own machine: null goes back to what its server takes, and to its agents' default share.
    if (changes.maxConversations !== undefined) json.max_conversations = changes.maxConversations;
    if (changes.agentShare !== undefined) json.agent_share = changes.agentShare;
    this._raw = await this._request<JsonObject>("PATCH", await this._path(), { json });
    return this;
  }

  /** Your own machine, until its server is set up: a new code (and command) in place of the last one. */
  async newPairingCode(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this._path()}/pairing_code`);
    return this;
  }

  /**
   * Restart it now (running turns fail as interrupted); its disk and volumes are kept and a `machine.restarted`
   * event follows. Resolves to the machine.
   */
  async restart(): Promise<Operation<Machine>> {
    const payload = await this._request("POST", `${await this._path()}/restart`);
    return Operation._fromPayload<Machine>(payload, {
      client: this._client, user: this._callScope(), kind: "machine.restart",
      reader: (result) => new Machine({ raw: asObject(result), client: this._client, user: this._callScope() }),
    });
  }

  /** Stop it: its agents take no turns until `start()`. It's still charged. */
  async stop(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this._path()}/stop`);
    return this;
  }

  /**
   * Start a stopped machine. One stopped because the balance couldn't pay it is charged what it owes first
   * (`PaymentRequired` while it can't).
   */
  async start(): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${await this._path()}/start`);
    return this;
  }

  /**
   * Delete it with its disk (attached volumes stay); the agents on it go back to their own cloud sandboxes first,
   * each from its next turn. Your own machine is removed from NoClick, which uninstalls itself from the server when
   * it next answers.
   */
  async delete(): Promise<void> {
    await this._request("DELETE", await this._path());
  }
}

/** Where the account's request for machines stands (`Machine.access`). */
export interface MachineAccess {
  status: "not_submitted" | "pending" | "approved" | "rejected";
  /** The machines usage policy's version the request accepted (the current one before any request). */
  policyVersion: string;
  companyName: string | null;
  website: string | null;
  country: string | null;
  useCase: string | null;
  submittedAt: Date | null;
  decidedAt: Date | null;
  /** Why NoClick declined it. */
  reason: string | null;
  raw: JsonObject;
}

/** What `Machine.requestAccess` sends. */
export interface MachineAccessRequest {
  companyName: string;
  website: string;
  country: string;
  useCase: string;
  acceptUsagePolicy: boolean;
  /** From a key: who accepted the policy for the company. */
  acceptedBy?: { name: string; email: string };
  /** From a key: when they accepted it. */
  acceptedAt?: Date;
}

function toMachineAccess(raw: JsonObject): MachineAccess {
  return {
    status: (str(raw.status) ?? "not_submitted") as MachineAccess["status"], policyVersion: str(raw.policy_version) ?? "",
    companyName: str(raw.company_name), website: str(raw.website), country: str(raw.country), useCase: str(raw.use_case),
    submittedAt: parseTime(raw.submitted_at), decidedAt: parseTime(raw.decided_at), reason: str(raw.reason), raw,
  };
}
