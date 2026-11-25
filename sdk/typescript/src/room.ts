/**
 * Room: a realtime room your pages join, to see who else is there, what each says of themselves, the events the
 * server publishes, and broadcasts between them; and for the server to ask the pages in it (`answer`).
 *
 *     const room = await Room.join(`workflow:${workflowId}`, { presence: { cursor: null, selection: [] } });
 *     room.on("presence", (members) => drawCursors(members));
 *     room.on("event", (event) => { if (event.event === "workflow:graph_changed") reload(); });
 *     room.presence.set({ cursor: { x, y } });
 *     room.answer("canvas.get_selected", async () => ({ nodes: selectedIds() }));
 *     room.leave();
 *
 * Rooms are named by what they're about: `workflow:{id}` (everyone who may open the workflow; `room.access` says
 * `edit` or `view`) and `owner` (your own open tabs). Who joins is decided by NoClick's API from the key or session
 * the client holds, and each member is shown under who they are, never what they say: a member's `data` is theirs,
 * its `user` and `color` the room's. A broadcast is relayed only where the room's kind allows it (on a workflow's room,
 * a builder's step edits, from someone who may edit), and the server's events carry `from: null`; one a member
 * published through the API names them.
 *
 * The room reconnects by itself (a new token each time, resuming after the last event it gave you) and renews its
 * connection in place before it ends. In a browser whose server holds the key, give `join` a client that goes through
 * that server, or a `token` function that asks your server for one.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { NoClickError } from "./errors.ts";
import { asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { checkedSocketUrl, spread } from "./sockets.ts";

/** What a token lets you do in a room: edit or view a workflow's, or your own tabs (`own`). */
export type RoomAccess = "edit" | "view" | "own";

/** Where the room's socket stands: `connecting`, `live`, `reconnecting` (it will on its own), or `stopped`. */
export type RoomStatus = "connecting" | "live" | "reconnecting" | "stopped";

/** Who a member is, as their token says: null for one NoClick holds (an agent's sandbox). */
export interface RoomUser {
  id: string;
  name: string;
  avatar: string | null;
  /** NoClick's staff viewing the account as its owner. */
  staff: boolean;
}

export interface RoomMember {
  /** This connection's id in the room: one person's two tabs are two members. */
  id: string;
  user: RoomUser | null;
  /** The colour the room gave them; null for a member NoClick holds. */
  color: string | null;
  /** What they say of themselves (`presence.set`). */
  data: JsonObject;
  joinedAt: Date | null;
  /** One NoClick holds, such as an agent's sandbox at work. */
  server: boolean;
  raw: JsonObject;
}

/** What the server published: NoClick's own (`from` null), or a member's through the API. */
export interface RoomEvent {
  /** Its place in the room (what a reconnect resumes after, and `history({ since })` reads after). */
  id: string;
  event: string;
  data: unknown;
  from: { id: string; name: string } | null;
  raw: JsonObject;
}

/** A run in flight on a workflow's room, as a page joining mid-run is told it. */
export interface RoomRun {
  executionId: string;
  nodeStates: Record<string, string>;
  nodeOutputs: Record<string, unknown>;
}

/** A single-use token for a room's socket (`POST /v1/rooms/{room}/tokens`). */
export interface RoomToken {
  url: string;
  token: string;
  access: RoomAccess;
  expiresAt: Date | null;
  connectionEndsAt: Date | null;
  raw: JsonObject;
}

export interface RoomTokenOptions {
  client?: NoClick;
  /** The page's origin the socket will come from (a browser sends its own). */
  origin?: string;
}

export interface RoomJoinOptions extends RoomTokenOptions {
  /** What you say of yourself as you join (merged; null removes a key). At most 1 KB as JSON. */
  presence?: JsonObject;
  /** Where a token comes from, when not this client: your server's endpoint passing `url` and `token` on. */
  token?: () => Promise<{ url: string; token: string }>;
  onStatus?: (status: RoomStatus) => void;
  /** Stops the room (as `leave`). */
  signal?: AbortSignal;
  /** A WebSocket class, where the runtime has none of its own (Node before 22). */
  WebSocket?: typeof WebSocket;
}

type Handler = (...args: never[]) => void;

/** What a member's broadcast says: its data, and the member who sent it. */
export type BroadcastHandler = (data: unknown, from: string) => void;

const ROOM_PROTOCOL = "noclick.room";
const CLOSE = { renew: 4000, refused: 4401, tooMany: 4429 } as const;
const PING_MS = 30_000;
const BACKOFF_MS = [500, 1_000, 2_000, 5_000, 10_000, 30_000];
const STABLE_MS = 30_000;
const TOO_MANY_MS = 30_000;
// A connection renews this long before it ends.
const RENEW_BEFORE_MS = 60_000;

/** The page's origin, where there is one (a browser's). */
export function pageOrigin(): string | undefined {
  const location = (globalThis as { location?: { origin?: string } }).location;
  return typeof location?.origin === "string" && /^https?:\/\//.test(location.origin) ? location.origin : undefined;
}

/** A room token as the API answers one (`POST /v1/rooms/{room}/tokens`, a public chat page's `.../room`). */
export function roomTokenOf(raw: JsonObject): RoomToken {
  const access = str(raw.access);
  return {
    url: str(raw.url) ?? "", token: str(raw.token) ?? "",
    access: access === "edit" || access === "own" ? access : "view",
    expiresAt: parseTime(raw.expires_at), connectionEndsAt: parseTime(raw.connection_ends_at), raw,
  };
}

function roomPath(name: string): string {
  return `/v1/rooms/${encodeURIComponent(name)}`;
}

function toUser(raw: unknown): RoomUser | null {
  if (!raw || typeof raw !== "object") return null;
  const user = raw as JsonObject;
  return { id: str(user.id) ?? "", name: str(user.name) ?? "", avatar: str(user.avatar), staff: user.staff === true };
}

function toMember(raw: unknown): RoomMember {
  const m = asObject(raw);
  const joined = typeof m.joined_at === "number" ? new Date(m.joined_at) : null;
  return {
    id: str(m.id) ?? "", user: toUser(m.user), color: str(m.color), data: asObject(m.data), joinedAt: joined,
    server: m.server === true, raw: m,
  };
}

function toEvent(raw: JsonObject): RoomEvent {
  const from = raw.from && typeof raw.from === "object" ? raw.from as JsonObject : null;
  return {
    id: str(raw.id) ?? "", event: str(raw.event) ?? "", data: raw.data ?? null,
    from: from ? { id: str(from.id) ?? "", name: str(from.name) ?? "" } : null, raw,
  };
}

function toRun(raw: unknown): RoomRun {
  const r = asObject(raw);
  return {
    executionId: str(r.execution_id) ?? "", nodeStates: asObject(r.node_states) as Record<string, string>,
    nodeOutputs: asObject(r.node_outputs),
  };
}

/** The error that ends a room: refused again right after a fresh token (access ended). */
export class RoomRefused extends NoClickError {
  static override errorType = "room_refused";
}

export class Room {
  readonly name: string;
  /** What your token lets you do here (renewed in place, so it follows an access change). */
  access: RoomAccess = "view";
  /** Your own member, once the room let you in. */
  me: RoomMember | null = null;
  status: RoomStatus = "connecting";
  /** The runs in flight on a workflow's room as you last joined. */
  runs: RoomRun[] = [];

  /** Your presence: `set` merges what you say of yourself; `list` is everyone here now, you included. */
  readonly presence: { set: (data: JsonObject) => void; list: () => RoomMember[] };

  private readonly options: RoomJoinOptions;
  private readonly members = new Map<string, RoomMember>();
  private readonly handlers = new Map<string, Set<Handler>>();
  private readonly answerers = new Map<string, (args: JsonObject) => unknown>();
  private mine: JsonObject;
  private socket: WebSocket | null = null;
  private after: string | null = null;
  private stopped = false;
  private pinger: ReturnType<typeof setInterval> | null = null;
  private renewer: ReturnType<typeof setTimeout> | null = null;
  private scoped: string | null | undefined = undefined;
  private accessTold = false;

  private constructor(name: string, options: RoomJoinOptions) {
    this.name = name;
    this.options = options;
    this.mine = { ...(options.presence ?? {}) };
    this.presence = {
      set: (data) => {
        this.mine = { ...this.mine, ...data };
        for (const [k, v] of Object.entries(this.mine)) if (v === null) delete this.mine[k];
        this.send({ type: "presence", data });
      },
      list: () => [...this.members.values()],
    };
  }

  /** A single-use token for the room's socket, for a page to open with `Room.join(name, { token })`. */
  static async token(name: string, options: RoomTokenOptions = {}): Promise<RoomToken> {
    const origin = options.origin ?? pageOrigin();
    return roomTokenOf(asObject(await resolveClient(options.client).request("POST", `${roomPath(name)}/tokens`, {
      json: origin ? { origin } : {},
    })));
  }

  /**
   * Joins the room: resolves once you're in (with `members` as they are), and stays in, reconnecting by itself, until
   * `leave` (or `signal`). Throws what trying again can't fix: the token call refused (a room you can't open, a key
   * without the scope) or the room refusing two fresh tokens in a row (`RoomRefused`).
   */
  static async join(name: string, options: RoomJoinOptions = {}): Promise<Room> {
    const room = new Room(name, options);
    await room.connect();
    return room;
  }

  /** Who is in the room now, read through the API (no socket needed). */
  static async members(name: string, options: { client?: NoClick } = {}): Promise<RoomMember[]> {
    const raw = asObject(await resolveClient(options.client).request("GET", `${roomPath(name)}/presence`));
    return Array.isArray(raw.data) ? raw.data.map(toMember) : [];
  }

  /**
   * Publishes `event` with `data` (at most 64 KB as JSON) to everyone in the room, named as from you (needs edit access
   * to a workflow's room); its id in the room. From a server: a page in the room broadcasts instead.
   */
  static async publish(name: string, event: string, data: unknown = null, options: { client?: NoClick } = {}): Promise<string> {
    const raw = asObject(await resolveClient(options.client).request("POST", `${roomPath(name)}/events`, {
      json: { event, data },
    }));
    return str(raw.id) ?? "";
  }

  /**
   * Asks the room's pages that answer `ask` (`room.answer`) and waits for an answer, at most `timeoutS` (25 at most);
   * with `collectMs`, that long after the first for the others'. `{ answer }`, `{ answers }`, or `{ error }`
   * (`no_viewer`, `timeout`). Needs edit access to a workflow's room.
   */
  static async ask(
    name: string, ask: string, args: JsonObject = {},
    options: { client?: NoClick; timeoutS?: number; collectMs?: number } = {},
  ): Promise<JsonObject> {
    const timeoutS = options.timeoutS ?? 10;
    const raw = asObject(await resolveClient(options.client).request("POST", `${roomPath(name)}/ask`, {
      json: { name: ask, args, timeout_s: timeoutS, collect_ms: options.collectMs ?? 0 },
    }));
    const { object: _object, ...answer } = raw;
    return answer;
  }

  /**
   * The room's recent events (at most its last 500 of the last ten minutes), after `since` when it names one still
   * kept; `reset` when it doesn't (read what you show again).
   */
  async history(options: { since?: string | null; client?: NoClick } = {}): Promise<{ events: RoomEvent[]; reset: boolean }> {
    const query = options.since ? { since: options.since } : undefined;
    const raw = asObject(await resolveClient(options.client ?? this.options.client).request(
      "GET", `${roomPath(this.name)}/events`, { query }));
    return { events: Array.isArray(raw.data) ? raw.data.map((e) => toEvent(asObject(e))) : [], reset: raw.reset === true };
  }

  /** Everyone's presence as it changes (`members`, you included). */
  on(event: "presence", handler: (members: RoomMember[]) => void): () => void;
  /** The server's events. */
  on(event: "event", handler: (event: RoomEvent) => void): () => void;
  on(event: "status", handler: (status: RoomStatus) => void): () => void;
  /** What your token lets you do, each time it changes (a renewal after an access change). */
  on(event: "access", handler: (access: RoomAccess) => void): () => void;
  /** What another member broadcast under this name. */
  on(event: string, handler: BroadcastHandler): () => void;
  on(event: string, handler: Handler): () => void {
    let set = this.handlers.get(event);
    if (!set) {
      set = new Set();
      this.handlers.set(event, set);
    }
    set.add(handler);
    return () => set!.delete(handler);
  }

  /** Tells the room's other members something (relayed only where the room's kind allows it). */
  broadcast(event: string, data: unknown = null): void {
    this.send({ type: "broadcast", event, data });
  }

  /** Answers what the server asks this page under `name` (the first answer, or each with collecting, wins). */
  answer(name: string, handler: (args: JsonObject) => unknown): () => void {
    this.answerers.set(name, handler);
    this.send({ type: "answers", names: [...this.answerers.keys()] });
    return () => {
      this.answerers.delete(name);
      this.send({ type: "answers", names: [...this.answerers.keys()] });
    };
  }

  /** On your own room: hear only events for one workflow (and those for none); null hears every one. */
  scope(workflowId: string | null): void {
    this.scoped = workflowId;
    this.send({ type: "scope", workflow: workflowId });
  }

  /** On a workflow's room: stop a run (if you may edit, or it's yours). */
  stop(executionId: string): void {
    this.send({ type: "stop", execution: executionId });
  }

  /** Leaves the room: the socket closes and nothing more is heard. */
  leave(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.clearTimers();
    this.socket?.close(1000);
    this.socket = null;
    this.setStatus("stopped");
  }

  // ── the socket ─────────────────────────────────────────────────────────────

  private emit(event: string, ...args: unknown[]): void {
    for (const handler of this.handlers.get(event) ?? []) {
      try {
        (handler as (...a: unknown[]) => void)(...args);
      } catch (err) {
        console.error(`[noclick] a room's "${event}" handler threw`, err);
      }
    }
  }

  private setStatus(status: RoomStatus): void {
    if (this.status === status) return;
    this.status = status;
    this.options.onStatus?.(status);
    this.emit("status", status);
  }

  private send(frame: JsonObject): void {
    if (this.socket?.readyState === 1 && this.me) this.socket.send(JSON.stringify(frame));
  }

  private clearTimers(): void {
    if (this.pinger) clearInterval(this.pinger);
    if (this.renewer) clearTimeout(this.renewer);
    this.pinger = null;
    this.renewer = null;
  }

  private async mint(): Promise<{ url: string; token: string; endsAt: Date | null }> {
    if (this.options.token) {
      const t = await this.options.token();
      return { ...t, endsAt: null };
    }
    const t = await Room.token(this.name, this.options);
    return { url: t.url, token: t.token, endsAt: t.connectionEndsAt };
  }

  /** Connects, resolving at the first `ready` and rejecting what trying again can't fix; then keeps reconnecting. */
  private connect(): Promise<void> {
    const Socket = this.options.WebSocket ?? globalThis.WebSocket;
    if (!Socket) return Promise.reject(new TypeError("No WebSocket here: pass options.WebSocket"));
    this.options.signal?.addEventListener("abort", () => this.leave(), { once: true });
    return new Promise<void>((resolveFirst, rejectFirst) => {
      let first = true;
      let failures = 0;
      let refusedInARow = 0;
      const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
      const fail = (err: unknown) => {
        if (first) {
          first = false;
          rejectFirst(err);
        }
        this.leave();
      };
      const open = async (): Promise<void> => {
        while (!this.stopped) {
          let minted: { url: string; token: string; endsAt: Date | null };
          try {
            minted = await this.mint();
          } catch (err) {
            if (err instanceof NoClickError && err.status !== null && err.status < 500 && err.status !== 429) {
              fail(err);
              return;
            }
            this.setStatus("reconnecting");
            await sleep(spread(BACKOFF_MS[Math.min(failures++, BACKOFF_MS.length - 1)]));
            continue;
          }
          let closed: { code: number; reason: string; ready: boolean; stable: boolean };
          try {
            closed = await this.run(Socket, minted, () => {
              refusedInARow = 0;
              if (first) {
                first = false;
                resolveFirst();
              }
            });
          } catch (err) {
            fail(err); // an address this SDK sends no token to: trying again can't fix it
            return;
          }
          if (this.stopped) return;
          if (closed.stable) failures = 0;
          if (closed.code === CLOSE.refused) {
            refusedInARow = closed.ready ? 1 : refusedInARow + 1;
            if (refusedInARow >= 2) {
              fail(new RoomRefused(`The room refused this page: ${closed.reason || "access ended"}.`, {
                nextStep: "Check the key or session may still open this room, then join again.",
              }));
              return;
            }
          }
          this.setStatus("reconnecting");
          if (closed.code === CLOSE.tooMany) await sleep(spread(TOO_MANY_MS));
          else if (closed.code !== CLOSE.renew) await sleep(spread(BACKOFF_MS[Math.min(failures++, BACKOFF_MS.length - 1)]));
        }
      };
      void open();
    });
  }

  /** One socket's life: resolves with how it closed. */
  private run(
    Socket: typeof WebSocket, minted: { url: string; token: string; endsAt: Date | null }, onReady: () => void,
  ): Promise<{ code: number; reason: string; ready: boolean; stable: boolean }> {
    return new Promise((resolve) => {
      const url = new URL(checkedSocketUrl(minted.url, "room socket"));
      if (this.after) url.searchParams.set("after", this.after);
      const ws = new Socket(url.toString(), [ROOM_PROTOCOL]);
      this.socket = ws;
      let lastHeard = Date.now();
      let readyAt = 0;
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "auth", token: minted.token }));
        this.pinger = setInterval(() => {
          if (Date.now() - lastHeard > 2 * PING_MS) ws.close(4000, "no answer");
          else ws.send("ping");
        }, PING_MS);
      };
      ws.onmessage = (message: MessageEvent) => {
        lastHeard = Date.now();
        if (message.data === "pong") return;
        let raw: JsonObject;
        try {
          raw = asObject(JSON.parse(String(message.data)));
        } catch {
          return;
        }
        if (raw.type === "ready") {
          readyAt = Date.now();
          this.onReady(raw, minted.endsAt);
          onReady();
          return;
        }
        this.onFrame(ws, raw);
      };
      ws.onclose = (event: CloseEvent) => {
        this.clearTimers();
        if (this.socket === ws) this.socket = null;
        resolve({ code: event.code, reason: event.reason, ready: readyAt > 0, stable: readyAt > 0 && Date.now() - readyAt >= STABLE_MS });
      };
      ws.onerror = () => { /* a close follows */ };
    });
  }

  private onReady(raw: JsonObject, endsAt: Date | null): void {
    this.me = toMember(raw.member);
    this.noteAccess(str(raw.access));
    this.runs = Array.isArray(raw.runs) ? raw.runs.map(toRun) : [];
    this.members.clear();
    for (const m of Array.isArray(raw.members) ? raw.members : []) {
      const member = toMember(m);
      this.members.set(member.id, member);
    }
    // What this page says of itself, what it answers and what it hears, again on every connection.
    if (Object.keys(this.mine).length) this.send({ type: "presence", data: this.mine });
    if (this.answerers.size) this.send({ type: "answers", names: [...this.answerers.keys()] });
    if (this.scoped !== undefined) this.send({ type: "scope", workflow: this.scoped });
    this.setStatus("live");
    this.emit("presence", this.presence.list());
    const ends = typeof raw.ends_at === "number" ? new Date(raw.ends_at * 1000) : endsAt;
    this.scheduleRenewal(ends);
  }

  /** A fresh token for the same socket before its connection ends: its access follows any change, and it stays. */
  private scheduleRenewal(endsAt: Date | null): void {
    if (this.renewer) clearTimeout(this.renewer);
    if (!endsAt || this.options.token) return;
    const wait = Math.max(5_000, endsAt.getTime() - Date.now() - RENEW_BEFORE_MS * (0.5 + Math.random() / 2));
    this.renewer = setTimeout(async () => {
      try {
        const t = await Room.token(this.name, this.options);
        this.send({ type: "auth", token: t.token });
      } catch { /* the connection ends at its time and reconnects */ }
    }, wait);
  }

  private noteAccess(raw: string | null): void {
    const access: RoomAccess = raw === "edit" || raw === "own" ? raw : "view";
    if (access === this.access && this.accessTold) return;
    this.accessTold = true;
    this.access = access;
    this.emit("access", access);
  }

  private onFrame(ws: WebSocket, raw: JsonObject): void {
    switch (raw.type) {
      case "presence": {
        const member = toMember(raw.member);
        if (raw.change === "leave") this.members.delete(member.id);
        else this.members.set(member.id, member);
        if (this.me && member.id === this.me.id) this.me = member;
        this.emit("presence", this.presence.list());
        return;
      }
      case "event": {
        const event = toEvent(raw);
        if (event.id) this.after = event.id;
        this.emit("event", event);
        return;
      }
      case "broadcast": {
        const name = str(raw.event);
        if (name && !["presence", "event", "status", "access"].includes(name)) this.emit(name, raw.data ?? null, str(raw.from) ?? "");
        return;
      }
      case "renewed": {
        this.noteAccess(str(raw.access));
        this.scheduleRenewal(typeof raw.ends_at === "number" ? new Date(raw.ends_at * 1000) : null);
        return;
      }
      case "ask":
        void this.onAsk(ws, raw);
        return;
      default:
        return; // `refused`, and what this version doesn't know
    }
  }

  private async onAsk(ws: WebSocket, raw: JsonObject): Promise<void> {
    const id = str(raw.id);
    const handler = this.answerers.get(str(raw.name) ?? "");
    if (!id || !handler) return;
    let reply: JsonObject;
    try {
      reply = { type: "answer", id, result: (await handler(asObject(raw.args))) ?? null };
    } catch (err) {
      reply = { type: "answer", id, error: err instanceof Error ? err.message : String(err) };
    }
    if (ws.readyState === 1) ws.send(JSON.stringify(reply));
  }
}
