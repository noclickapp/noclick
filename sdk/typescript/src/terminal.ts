/**
 * Take-over: the account's owner drives a coding agent's conversation in its harness's own terminal (Claude Code's
 * or Codex's), then hands it back, and the agent's next turn goes on from what they did.
 *
 *     const coder = Agent.fromName("coder");
 *     const terminal = await coder.takeOver("main", { cols: term.cols, rows: term.rows });
 *     const connection = terminal.connect({
 *       onData: (bytes) => term.write(bytes),
 *       onState: (status) => status.state === "agent" && showHandedBack(),
 *     });
 *     term.onData((text) => connection.write(text));
 *     term.onResize(({ cols, rows }) => connection.resize(cols, rows));
 *     // later
 *     await terminal.handBack();
 *
 * A terminal shows its sandbox's keys and tokens, so only the account's owner opens one: signed in, or from your
 * server with the account's secret key holding the `agents:terminal` scope, which then hands `url` and `token` to
 * the browser that connects.
 */

import type { NoClick } from "./client.ts";
import { ApiObject, num, parseTime, str } from "./object.ts";
import type { JsonObject, ObjectInit } from "./object.ts";
import type { UserOption } from "./scope.ts";

/**
 * `agent` (the agent has it), `taking_over` (its turn in flight finishes first), `person` or `handing_back`; a
 * sandbox shell's (`AgentSandbox.shell`) is `open`, then `exited` as it closes.
 */
export type TerminalState = "agent" | "taking_over" | "person" | "handing_back" | "open" | "exited";

/** Why a take-over (or a sandbox shell) ended: asked (`handed_back`, `canceled` while it waited), or by itself. */
export type TerminalEnd = "handed_back" | "canceled" | "idle" | "detached" | "exited" | "deadline" | "failed";

/** Where the take-over stands, as the terminal's connection reports it. */
export interface TerminalStatus {
  state: TerminalState;
  reason: TerminalEnd | null;
  raw: JsonObject;
}

/** The websocket's close codes that end it for good: the token was used or expired, nothing runs, or it's handed back. */
export const TERMINAL_CLOSED_FOR_GOOD = { unauthorized: 4401, notFound: 4404, ended: 4410 } as const;

export interface TerminalConnectOptions {
  /** The terminal's size as it opens (else the one `takeOver` was given). */
  cols?: number;
  rows?: number;
  /** What the terminal prints, as it prints it. */
  onData?: (data: Uint8Array) => void;
  /** It's open: what the person types reaches the terminal from now. */
  onReady?: (status: TerminalStatus) => void;
  /** The take-over moved (`person`, `handing_back`, then `agent` as it closes). */
  onState?: (status: TerminalStatus) => void;
  /** It closed: `final` when it won't open again with this take-over (handed back, nothing running, or a used token);
   *  otherwise take over again for a new token and connect. */
  onClose?: (event: { code: number; reason: string; final: boolean }) => void;
  /** A WebSocket class, where the runtime has none of its own (Node before 22). */
  WebSocket?: typeof WebSocket;
}

/** An open terminal. */
export class TerminalConnection {
  private readonly socket: WebSocket;
  private readonly encoder = new TextEncoder();
  private open = false;
  private readonly pending: (string | Uint8Array)[] = [];

  /** @internal */
  constructor(url: string, token: string, options: TerminalConnectOptions) {
    const Socket = options.WebSocket ?? globalThis.WebSocket;
    if (!Socket) throw new TypeError("No WebSocket here: pass options.WebSocket");
    const socket = new Socket(url);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "auth", token, cols: options.cols, rows: options.rows }));
    };
    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== "string") {
        options.onData?.(new Uint8Array(event.data as ArrayBuffer));
        return;
      }
      const message = JSON.parse(event.data) as JsonObject;
      const status = toStatus(message);
      if (message.type === "ready") {
        this.open = true;
        for (const queued of this.pending.splice(0)) this.send(queued);
        options.onReady?.(status);
      } else if (message.type === "state") {
        options.onState?.(status);
      }
    };
    socket.onclose = (event: CloseEvent) => {
      this.open = false;
      const final = (Object.values(TERMINAL_CLOSED_FOR_GOOD) as number[]).includes(event.code);
      options.onClose?.({ code: event.code, reason: event.reason, final });
    };
  }

  /** What the person typed (xterm.js's `onData` gives a string). */
  write(data: string | Uint8Array): void {
    if (!this.open) {
      this.pending.push(data);
      return;
    }
    this.send(data);
  }

  /** The terminal's new size. */
  resize(cols: number, rows: number): void {
    if (this.open) this.socket.send(JSON.stringify({ type: "resize", cols, rows }));
  }

  /** Close this view of it (the take-over goes on until it's handed back). */
  close(): void {
    this.socket.close(1000);
  }

  private send(data: string | Uint8Array): void {
    this.socket.send((typeof data === "string" ? this.encoder.encode(data) : data) as BufferSource);
  }
}

function toStatus(raw: JsonObject): TerminalStatus {
  return { state: (str(raw.state) ?? "agent") as TerminalState, reason: str(raw.reason) as TerminalEnd | null, raw };
}

/**
 * A coding agent's conversation as its harness's own terminal. While it's taken over the agent's messages wait; it
 * hands itself back after `idleLimitS` with nobody typing, `detachedLimitS` with no terminal open, or at `endsAt`
 * (its sandbox's time limit). From `agent.takeOver` it carries a single-use `token` for `url`, valid two minutes:
 * `connect()` once; take over again (it's idempotent while taken over) for a new one.
 */
export class Terminal extends ApiObject {
  private connected = false;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _from(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): Terminal {
    return new Terminal({ raw, client: init.client, user: init.user });
  }

  get agentId(): string {
    return this._field("agent_id");
  }
  get conversation(): string {
    return this._field("conversation");
  }
  /** `claude_code` or `codex`. */
  get harness(): string {
    return this._field("harness");
  }
  get state(): TerminalState {
    return this._field("state");
  }
  /** Taken over once the agent's turn in flight ends. */
  get waitingForTurn(): boolean {
    return this._field("waiting_for_turn") === true;
  }
  get since(): Date | null {
    return parseTime(this._field("since"));
  }
  /** When it hands itself back at the latest: its sandbox's time limit. */
  get endsAt(): Date | null {
    return parseTime(this._field("ends_at"));
  }
  get idleLimitS(): number | null {
    return num(this._field("idle_limit_s"));
  }
  get detachedLimitS(): number | null {
    return num(this._field("detached_limit_s"));
  }
  /** Why the last take-over ended. */
  get endedBecause(): TerminalEnd | null {
    return this._field("ended_because");
  }
  /** The terminal's websocket (from `takeOver` only). */
  get url(): string | null {
    return str(this._field("url"));
  }
  /** Opens `url` once, within two minutes (from `takeOver` only). */
  get token(): string | null {
    return str(this._field("token"));
  }
  get tokenExpiresAt(): Date | null {
    return parseTime(this._field("token_expires_at"));
  }

  private get path(): string {
    return `/v1/agents/${this._known("agent_id")}/conversations/${encodeURIComponent(String(this._known("conversation")))}/terminal`;
  }

  protected _load(): Promise<JsonObject> {
    return this._request<JsonObject>("GET", this.path);
  }

  /** Open the terminal: once per token (`takeOver` again for another). */
  connect(options: TerminalConnectOptions = {}): TerminalConnection {
    const { url, token } = this;
    if (!url || !token) throw new TypeError("This terminal has no token: take it over (agent.takeOver) to open it");
    if (this.connected) throw new TypeError("A terminal token opens it once: take it over again for another");
    this.connected = true;
    return new TerminalConnection(url, token, options);
  }

  /**
   * Give the conversation back to the agent: the terminal closes, what was said in it joins the conversation's
   * history (`via: "terminal"`), and the messages that waited reach the agent.
   */
  async handBack(): Promise<this> {
    this._raw = await this._request<JsonObject>("DELETE", this.path);
    return this;
  }
}
