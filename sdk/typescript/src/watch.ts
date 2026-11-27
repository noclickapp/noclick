/**
 * Watch: one socket that says which of your objects changed, so a page reads them again instead of polling.
 *
 *     for await (const message of watch({ objects: ["deployment", "domain"], signal })) {
 *       if (message.type === "change") refresh(message.object, message.objectId);
 *       else if (message.type === "reset" || (message.type === "ready" && !message.resumed)) refreshAll();
 *     }
 *
 * A change names an object (as its read's `object` says it: `deployment`, `channel`, `agent`, ...) and its id, never
 * its data: read it again. It is not the event log (`Event`, webhooks), which records what happened, with data, for
 * 30 days and delivers each event at least once. A change is a hint, delivered at most once: re-read everything you
 * show on `reset`, on a `ready` that didn't resume (your first one too, for anything you read before it), and on a
 * slow timer of your own if you must never be stale.
 *
 * Your key follows the account's objects, its users' included; a key acting for one user (`user`), or a user's
 * session, that user's. In a browser whose server holds the key, give `watch` a client that goes through that server
 * (it asks for the token there, then opens the socket itself), or a `token` function that asks your server for one.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { NoClickError } from "./errors.ts";
import { asObject, num, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption } from "./scope.ts";
import { checkedSocketUrl, spread } from "./sockets.ts";

/** What `watch` follows: each an object as its read names it. */
export type WatchedObject =
  | "domain" | "deployment" | "repo" | "mcp_server" | "live_session" | "phone_call" | "workflow" | "workflow_run"
  | "durable_object_class" | "skill" | "memory" | "machine" | "sandbox" | "agent_move" | "connection" | "plan_usage"
  | "agent_trigger" | "approval" | "browser" | "agent" | "coding_agent" | "channel" | "workspace"
  | "workspace_resource" | "channel_sections" | "space_question" | "usage" | "spend_cap" | "notifications"
  | "workstream" | "popups" | "phones" | "operation" | "share" | "hosted_mcp";

/** The socket is open: `resumed` when it carried on from the last change you got, so nothing was missed. */
export interface WatchReady {
  type: "ready";
  resumed: boolean;
}

/** An object changed: read it again. */
export interface WatchChange {
  type: "change";
  /** This change's place in the stream (what a reconnect resumes after). */
  id: string;
  at: Date | null;
  object: WatchedObject | string;
  /** Its id; null for a `coding_agent` change that may be any of them, and for `usage` (the account was charged). */
  objectId: string | null;
  /** Its status as its read gave it then (advisory: the read is the truth); null once it's gone. */
  status: string | null;
  /** What it belongs to: a deployment's project, a call's phone number, a trigger's agent, a run's workflow, ... */
  parent: { object: string; id: string } | null;
  /**
   * What moved: an agent's `turn`, `step`, `definition`, ...; a channel's `message`, `reaction`, `thread`, ...; a
   * workflow run's `step` (one of its steps moved) or `run` (it started or ended).
   */
  change: string | null;
  /** A workflow's graph version now. */
  version: number | null;
  workspaceId: string | null;
  messageId: string | null;
  threadId: string | null;
  raw: JsonObject;
}

/** Someone started or stopped typing in a channel you read (never sent to the one typing). */
export interface WatchTyping {
  type: "typing";
  channelId: string;
  workspaceId: string | null;
  /** Who: a user's id, or `account` for the account's owner. */
  userId: string;
  typing: boolean;
  raw: JsonObject;
}

/** Too much changed to say each: read again everything you show. */
export interface WatchReset {
  type: "reset";
}

export type WatchMessage = WatchReady | WatchChange | WatchTyping | WatchReset;

/** Where the socket stands: `connecting`, `live`, `reconnecting` (it will on its own), or `stopped`. */
export type WatchStatus = "connecting" | "live" | "reconnecting" | "stopped";

/** A single-use token for the socket at `url`, good until `expiresAt`. */
export interface WatchToken {
  /**
   * The socket's address, carrying its ticket (which lets the socket wait for this token and nothing more): open it
   * as it is, and send `token` as its first frame.
   */
  url: string;
  token: string;
  expiresAt: Date | null;
  /** When the connection it opens ends (watch then reconnects with a new token). */
  connectionEndsAt: Date | null;
  objects: string[];
  /** The user whose objects it follows; null for the account's. */
  userId: string | null;
  /** The page's origin the socket must come from, when one was given. */
  origin: string | null;
  raw: JsonObject;
}

export interface WatchTokenOptions {
  client?: NoClick;
  /** Act for one of your users: follow only their objects. */
  user?: UserOption;
  /** Follow only these (default: every object the key may read). */
  objects?: readonly (WatchedObject | string)[];
  /** The page's origin the socket will come from (a browser sends its own). */
  origin?: string;
}

export interface WatchOptions extends WatchTokenOptions {
  /** Stops watching (the generator returns). */
  signal?: AbortSignal;
  /**
   * Where a token comes from, when not this client: your own server's endpoint that calls `watchToken` and passes its
   * `url` and `token` on as they are.
   */
  token?: () => Promise<{ url: string; token: string }>;
  /** Where the socket stands, as it moves. */
  onStatus?: (status: WatchStatus) => void;
  /** A WebSocket class, where the runtime has none of its own (Node before 22). */
  WebSocket?: typeof WebSocket;
}

/**
 * The close codes the room sends: renew (lifetime reached), refused (token or access), too many connections. Its
 * others (4400, the first frame wasn't the token; 4408, no token in time) are retried as any drop is.
 */
const WATCH_CLOSE = { renew: 4000, refused: 4401, tooMany: 4429 } as const;
/** The socket's subprotocol, offered alone: the token is the socket's first frame, never a header or the URL. */
const WATCH_PROTOCOL = "noclick.watch";

const PING_MS = 30_000;
// A page coming back into view asks its socket at once, and drops it unless it answers this soon: a phone may have cut
// the connection while the page was hidden without a close the page could hear.
const SHOWN_ANSWER_MS = 3_000;
const BACKOFF_MS = [500, 1_000, 2_000, 5_000, 10_000, 30_000];
// A connection that stayed up this long after `ready` starts the backoff again; one that drops sooner keeps it
// climbing, so a socket cut right after it opens isn't retried twice a second forever.
const STABLE_MS = 30_000;
const TOO_MANY_MS = 30_000;
// After a refusal, past a revoke's `before` (the backend's clock rounded up to the second, plus REVOKE_MARGIN_S, 5 s)
// by a token clock up to a second behind: the next token opens, unless access really ended, which a second refusal
// says.
const REFUSED_WAIT_MS = 8_000;
// Messages held for a reader slower than the room: past this many, they give way to one `reset`.
const MAX_QUEUED = 1_000;
/** The socket's address, if the token's answer named one this SDK sends a token to. */
function socketUrl(url: string): string {
  return checkedSocketUrl(url, "watch socket");
}

/** The socket's address, resuming after `after` (a cursor, never a secret). */
function withCursor(url: string, after: string | null): string {
  if (!after) return url;
  const at = new URL(url);
  at.searchParams.set("after", after);
  return at.toString();
}

function pageOrigin(): string | undefined {
  const location = (globalThis as { location?: { origin?: string } }).location;
  return typeof location?.origin === "string" && /^https?:\/\//.test(location.origin) ? location.origin : undefined;
}

function toToken(raw: JsonObject): WatchToken {
  return {
    url: str(raw.url) ?? "", token: str(raw.token) ?? "", expiresAt: parseTime(raw.expires_at),
    connectionEndsAt: parseTime(raw.connection_ends_at), userId: str(raw.user_id), origin: str(raw.origin),
    objects: Array.isArray(raw.objects) ? raw.objects.filter((o): o is string => typeof o === "string") : [], raw,
  };
}

function toMessage(raw: JsonObject): WatchMessage | null {
  switch (raw.type) {
    case "ready":
      return { type: "ready", resumed: raw.resumed === true };
    case "reset":
      return { type: "reset" };
    case "typing":
      return {
        type: "typing", channelId: str(raw.channel_id) ?? "", workspaceId: str(raw.workspace_id),
        userId: str(raw.user_id) ?? "", typing: raw.typing === true, raw,
      };
    case "change": {
      const parent = raw.parent ? asObject(raw.parent) : null;
      return {
        type: "change", id: str(raw.id) ?? "", at: parseTime(raw.at), object: str(raw.object) ?? "",
        objectId: str(raw.object_id), status: str(raw.status),
        parent: parent && str(parent.object) && str(parent.id) ? { object: str(parent.object)!, id: str(parent.id)! } : null,
        change: str(raw.change), version: num(raw.version), workspaceId: str(raw.workspace_id),
        messageId: str(raw.message_id), threadId: str(raw.thread_id), raw,
      };
    }
    default:
      return null; // a message type this version doesn't know: ignored, so the stream can grow
  }
}

/** A single-use token for the watch socket (`POST /v1/watch/tokens`), for a page to open with `watch({ token })`. */
export async function watchToken(options: WatchTokenOptions = {}): Promise<WatchToken> {
  const body: JsonObject = {};
  if (options.objects) body.objects = [...options.objects];
  const origin = options.origin ?? pageOrigin();
  if (origin) body.origin = origin;
  const raw = await resolveClient(options.client).request("POST", "/v1/watch/tokens", {
    json: body, user: resolveScope(options.user),
  });
  return toToken(asObject(raw));
}

/** The error that ends a watch: the room refused it again right after a fresh token (access ended). */
export class WatchRefused extends NoClickError {
  static override errorType = "watch_refused";
}

/**
 * Follow your objects' changes until `signal` aborts or you stop reading. Reconnects by itself (a new token each
 * time), resuming after the last change it gave you; it throws only what can't be fixed by trying again: the token
 * call refused (a revoked key, a scope the key lacks, a deployment where watching isn't available) or the room
 * refusing two fresh tokens in a row (`WatchRefused`). In a page, coming back into view checks the socket at once and
 * replaces one that doesn't answer within seconds (a phone may cut it while the page is hidden).
 *
 * A change can be lost (a deploy, a dropped connection, a busy second), and nothing says so but these: read again
 * what you show on `reset`, on a `ready` that didn't resume, and on a slow timer of your own if it must never be stale.
 */
export async function* watch(options: WatchOptions = {}): AsyncGenerator<WatchMessage> {
  const Socket = options.WebSocket ?? globalThis.WebSocket;
  if (!Socket) throw new TypeError("No WebSocket here: pass options.WebSocket");
  const queue: (WatchMessage | { close: { code: number; reason: string } })[] = [];
  let wake: (() => void) | null = null;
  const push = (item: (typeof queue)[number]) => {
    if (!("close" in item) && queue.length >= MAX_QUEUED) {
      // The reader is behind for good: what's queued gives way to one reset (it reads everything again).
      queue.splice(0, queue.length, { type: "reset" }, ...queue.filter((queued) => "close" in queued));
    }
    queue.push(item);
    wake?.();
  };
  const next = () => new Promise<void>((resolve) => {
    if (queue.length || options.signal?.aborted) resolve();
    else wake = resolve;
  });
  const onAbort = () => wake?.();
  options.signal?.addEventListener("abort", onAbort);
  const status = (s: WatchStatus) => options.onStatus?.(s);

  let after: string | null = null;
  let failures = 0;
  let refusedInARow = 0;
  let socket: WebSocket | null = null;
  let pinger: ReturnType<typeof setInterval> | null = null;
  let unwatchShown: (() => void) | null = null;
  const sleep = (ms: number) => new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    options.signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });

  try {
    status("connecting");
    while (!options.signal?.aborted) {
      let token: { url: string; token: string };
      try {
        token = options.token ? await options.token() : await watchToken(options);
      } catch (err) {
        if (err instanceof NoClickError && err.status !== null && err.status < 500 && err.status !== 429) throw err;
        status("reconnecting");
        await sleep(spread(BACKOFF_MS[Math.min(failures++, BACKOFF_MS.length - 1)]));
        continue;
      }
      const ws = new Socket(withCursor(socketUrl(token.url), after), [WATCH_PROTOCOL]);
      socket = ws;
      let lastHeard = Date.now();
      const secret = token.token;
      // Dropped at once, not on its close: a connection that's gone may never send one.
      const drop = () => {
        ws.onclose = null;
        ws.onmessage = null;
        ws.close(4000, "no answer");
        push({ close: { code: 4000, reason: "no answer" } });
      };
      ws.onopen = () => {
        // The token is the first frame (headers and URLs reach logs); the room answers `ready` once it checks out.
        ws.send(JSON.stringify({ type: "auth", token: secret }));
        pinger = setInterval(() => {
          if (Date.now() - lastHeard > 2 * PING_MS) drop();
          else ws.send("ping");
        }, PING_MS);
      };
      const page = (globalThis as { document?: Document }).document;
      let checking: ReturnType<typeof setTimeout> | null = null;
      const onShown = () => {
        if (page?.visibilityState !== "visible" || (ws.readyState ?? 1) !== 1 || checking) return;
        const asked = Date.now();
        ws.send("ping");
        checking = setTimeout(() => {
          checking = null;
          if (lastHeard < asked) drop();
        }, SHOWN_ANSWER_MS);
      };
      page?.addEventListener("visibilitychange", onShown);
      unwatchShown = () => {
        page?.removeEventListener("visibilitychange", onShown);
        if (checking) clearTimeout(checking);
      };
      ws.onmessage = (event: MessageEvent) => {
        lastHeard = Date.now();
        if (event.data === "pong") return;
        let raw: unknown;
        try {
          raw = JSON.parse(String(event.data));
        } catch {
          return;
        }
        const message = toMessage(asObject(raw));
        if (message) push(message);
      };
      ws.onclose = (event: CloseEvent) => push({ close: { code: event.code, reason: event.reason } });
      ws.onerror = () => { /* a close follows */ };

      let ready = false;
      let readyAt = 0;
      while (true) {
        await next();
        if (options.signal?.aborted) return;
        const item = queue.shift();
        if (!item) continue;
        if ("close" in item) {
          if (pinger) clearInterval(pinger);
          pinger = null;
          unwatchShown?.();
          unwatchShown = null;
          socket = null;
          const { code, reason } = item.close;
          if (ready && Date.now() - readyAt >= STABLE_MS) failures = 0;
          if (code === WATCH_CLOSE.refused) {
            refusedInARow = ready ? 1 : refusedInARow + 1;
            if (refusedInARow >= 2) {
              throw new WatchRefused(`The watch socket was refused: ${reason || "access ended"}.`, {
                nextStep: "Check the key is still live and may read these objects, then watch again.",
              });
            }
          } else {
            refusedInARow = 0;
          }
          status("reconnecting");
          if (code === WATCH_CLOSE.tooMany) await sleep(spread(TOO_MANY_MS));
          else if (code === WATCH_CLOSE.refused) await sleep(REFUSED_WAIT_MS * (1 + Math.random() / 2));
          else if (code !== WATCH_CLOSE.renew) {
            await sleep(spread(BACKOFF_MS[Math.min(failures++, BACKOFF_MS.length - 1)]));
          }
          break;
        }
        if (item.type === "ready") {
          ready = true;
          readyAt = Date.now();
          refusedInARow = 0;
          status("live");
        } else if (item.type === "change" && item.id) {
          after = item.id;
        }
        yield item;
      }
    }
  } finally {
    options.signal?.removeEventListener("abort", onAbort);
    if (pinger) clearInterval(pinger);
    unwatchShown?.();
    socket?.close(1000);
    status("stopped");
  }
}
