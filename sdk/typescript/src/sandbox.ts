/** Sandboxes: a disposable machine for running code, billed per second for the CPU and memory it reserves. */

import { resolveClient } from "./client.ts";
import { ApiObject, asObject, compact, listAll, listPage, num, parseTime, str } from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { secretIdList } from "./secret.ts";
import type { SecretRef } from "./secret.ts";
import type { RegionName } from "./region.ts";
import { resolveScope } from "./scope.ts";
import { volumeMountIds } from "./volume.ts";
import type { VolumeRef } from "./volume.ts";

/** The server's exec timeout when none is given. */
const EXEC_DEFAULT_TIMEOUT_S = 60;

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  /** Whether the command exited 0. */
  ok: boolean;
  raw: JsonObject;
}

/** @internal */
export function toExecResult(result: unknown): ExecResult {
  const raw = asObject(result);
  const exitCode = typeof raw.exit_code === "number" ? raw.exit_code : null;
  return { stdout: str(raw.stdout) ?? "", stderr: str(raw.stderr) ?? "", exitCode, ok: exitCode === 0, raw };
}

registerResult("sandbox.exec", toExecResult);

export interface ExecOptions {
  /** Seconds before the command is stopped: 60 by default, at most 90, or 3600 with `background`. */
  timeoutS?: number;
  /** Return at once with an `Operation` whose `wait()` resolves to the `ExecResult`. */
  background?: boolean;
}

export type SandboxStatusFilter = "live" | "starting" | "running" | "terminated" | "failed";

/** `true` (anywhere), `false` (nothing) or the hosts it may reach, `"*.example.com"` for a domain and its subdomains. */
export type NetworkAccess = boolean | string[];

export interface SandboxCreateOptions extends CallOptions {
  image?: "python" | "node";
  /** Lifetime before the sandbox is reclaimed. */
  timeoutS?: number;
  cpu?: number;
  memoryMb?: number;
  /**
   * Allow outbound internet access (off by default). A list of up to 50 hosts allows only those, over
   * HTTPS on port 443: `"pypi.org"`, or `"*.example.com"` for a domain and its subdomains (a scheme,
   * path, port or IP address throws `InvalidRequest`).
   */
  network?: NetworkAccess;
  /**
   * Where it runs (`regions()`), for its whole life: `region: agent.region` puts it beside an
   * agent. Omitted, your account's default region, else wherever NoClick has capacity. Pinned to a
   * region it costs what the provider charges there: 1.15x in `eu` and `ap`, 1.75x in `us-east` and
   * `us-west`.
   */
  region?: RegionName;
  /**
   * Volumes to mount read-write, by absolute path, up to 5: `{ "/data": Volume.fromName("datasets") }`
   * (a `Volume`, an id or a name: the sandbox's user's own, else the account's). It sees each as it was
   * when it started; what it writes there is saved every few seconds while it runs, and all of it when
   * it ends. Not `/`, `/workspace` itself or a system folder.
   */
  volumes?: Record<string, VolumeRef>;
  /**
   * Secrets whose keys become environment variables for every command (a `Secret`, an id or a name:
   * the sandbox's user's own, else the account's), up to 20; a later secret's key wins a clash, and
   * the sandbox keeps the values it started with.
   */
  secrets?: SecretRef[];
}

/** Files inside a sandbox: `await sandbox.files.write("a.py", "print(1)")`. */
/**
 * An interactive shell in a sandbox (`sandbox.shell()`): `url` is a websocket, opened once with `token` within a
 * minute. Its first message is `{"type": "auth", token, cols, rows}`; then binary messages carry what you type and
 * what it prints, a text `{"type": "resize", cols, rows}` sizes it, and it closes (code 4410) once bash exits (its
 * last `state` frame naming `exit_code`), after `idleLimitS` with nothing typed, or when the socket closes.
 */
export interface CodeSandboxShell {
  sandboxId: string;
  url: string;
  token: string;
  tokenExpiresAt: Date | null;
  idleLimitS: number;
}

export class SandboxFiles {
  private readonly sandbox: Sandbox;

  constructor(sandbox: Sandbox) {
    this.sandbox = sandbox;
  }

  async write(path: string, data: string | Uint8Array | ArrayBuffer | Blob): Promise<void> {
    await this.sandbox._request("PUT", `${this.sandbox._path()}/files`, { query: { path }, body: data });
  }

  async read(path: string): Promise<Uint8Array> {
    return await this.sandbox._request<Uint8Array>("GET", `${this.sandbox._path()}/files`, {
      query: { path },
      responseType: "bytes",
    });
  }

  async readText(path: string): Promise<string> {
    return new TextDecoder().decode(await this.read(path));
  }
}

export class Sandbox extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  static async create(options: SandboxCreateOptions = {}): Promise<Sandbox> {
    const scope = resolveScope(options.user);
    const refs = { user: scope, client: options.client };
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/sandboxes", {
      json: compact({
        image: options.image, timeout_s: options.timeoutS, cpu: options.cpu, memory_mb: options.memoryMb, network: options.network,
        region: options.region,
        volumes: await volumeMountIds(options.volumes, refs),
        secret_ids: await secretIdList(options.secrets, refs),
      }),
      user: scope,
    });
    return new Sandbox({ raw, client: options.client, user: scope });
  }

  static fromId(sandboxId: string, options: CallOptions = {}): Sandbox {
    return new Sandbox({ hints: { id: sandboxId }, client: options.client, user: options.user });
  }

  static async get(sandboxId: string, options: CallOptions = {}): Promise<Sandbox> {
    return await Sandbox.fromId(sandboxId, options).hydrate();
  }

  /** `status: "live"` lists the ones still starting or running. */
  static async list(options: ReadOptions & { status?: SandboxStatusFilter; limit?: number } = {}): Promise<Sandbox[]> {
    return await listAll(
      { ...options, path: "/v1/sandboxes", query: { status: options.status } },
      (raw, user) => new Sandbox({ raw, client: options.client, user }),
    );
  }

  /** One page of sandboxes; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions & { status?: SandboxStatusFilter } = {}): Promise<Page<Sandbox>> {
    return await listPage(
      { ...options, path: "/v1/sandboxes", query: { status: options.status } },
      (raw, user) => new Sandbox({ raw, client: options.client, user }),
    );
  }

  get id(): string {
    return this._field("id");
  }
  get status(): string {
    return this._field("status");
  }
  get image(): string | null {
    return this._field("image");
  }
  get timeoutS(): number | null {
    return this._field("timeout_s");
  }
  get cpu(): number | null {
    return this._field("cpu");
  }
  get memoryMb(): number | null {
    return this._field("memory_mb");
  }
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** The region it runs in, or `null`: wherever NoClick had capacity. */
  get region(): RegionName | null {
    return this._field("region");
  }
  /** The volumes it mounts: `{ path: volume id }`. */
  get volumes(): Record<string, string> {
    return this._field<Record<string, string> | null>("volumes") ?? {};
  }
  /** The secrets in its environment, in order (a later one's key wins). */
  get secretIds(): string[] {
    return this._field<string[] | null>("secret_ids") ?? [];
  }
  /** What it may reach: `false` (nothing), `true` (anywhere) or the hosts it may reach, as sent. */
  get network(): NetworkAccess | null {
    return this._field("network");
  }

  /** @internal */
  _path(): string {
    return `/v1/sandboxes/${this._known("id")}`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this._path());
  }

  get files(): SandboxFiles {
    return new SandboxFiles(this);
  }

  /**
   * Run a bash command in `/workspace`; a non-zero exit is a normal result, not an error.
   * `{ background: true }` returns at once with an `Operation` whose `wait()` resolves to the
   * `ExecResult`: for commands longer than one request allows (`timeoutS` up to 3600, within the
   * sandbox's own lifetime).
   */
  exec(command: string, options: ExecOptions & { background: true }): Promise<Operation<ExecResult>>;
  exec(command: string, options?: ExecOptions & { background?: false }): Promise<ExecResult>;
  async exec(command: string, options: ExecOptions = {}): Promise<ExecResult | Operation<ExecResult>> {
    if (options.background) {
      const payload = await this._request("POST", `${this._path()}/exec`, {
        json: compact({ command, background: true, timeout_s: options.timeoutS }),
      });
      return Operation._fromPayload<ExecResult>(payload, {
        client: this._client, user: this._callScope(), kind: "sandbox.exec", reader: toExecResult,
      });
    }
    return toExecResult(await this._request("POST", `${this._path()}/exec`, {
      json: compact({ command, timeout_s: options.timeoutS }),
      timeoutMs: ((options.timeoutS ?? EXEC_DEFAULT_TIMEOUT_S) + 15) * 1000,
    }));
  }

  /**
   * Open an interactive shell (`bash -l` in `/workspace`, in a PTY) in this running sandbox: the websocket's `url`
   * and its single-use `token` (good for two minutes), for a browser terminal (xterm.js) or `TerminalConnection`.
   * `noclick shell <sandbox>` opens one in your own terminal.
   */
  async shell(): Promise<CodeSandboxShell> {
    const raw = asObject(await this._request("POST", `${this._path()}/shell`));
    return {
      sandboxId: str(raw.sandbox_id) ?? "", url: str(raw.url) ?? "", token: str(raw.token) ?? "",
      tokenExpiresAt: parseTime(raw.token_expires_at), idleLimitS: num(raw.idle_limit_s) ?? 0,
    };
  }

  /** Stop the sandbox now (billing stops with it). */
  async terminate(): Promise<void> {
    const raw = asObject(await this._request("DELETE", this._path()));
    this._raw = raw.id ? raw : { ...(this._raw ?? this._hints), status: "terminated" };
  }
}
