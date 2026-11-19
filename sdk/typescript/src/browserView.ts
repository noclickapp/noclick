/**
 * A browser's live view in a page of your own: the page it shows, as a JPEG each time it changes, and, on a view
 * that drives it (`control`, once you've taken the browser over), what a person does sent back to it.
 *
 *     const view = browser.view({
 *       thumb: true,
 *       onViewport: ({ width, height }) => resize(width, height),
 *       onPicture: (jpeg) => show(new Blob([jpeg], { type: "image/jpeg" })),
 *       onEnd: () => showEnded(),
 *     });
 *     // later
 *     view.close();
 *
 * `Browser.view` asks for a single-use token (`Browser.liveView`) through its client and opens the socket itself,
 * sending the token as its first message, never in its URL. It opens again by itself, with a new token each time:
 * at once when a view ran its 15 minutes, and after a growing wait when the connection dropped (the wait starts over
 * once a view stayed up 30 seconds). It ends for good when the browser closes, a control view's browser is handed
 * back, the browser can't be found, or the token is refused twice in a row; `onEnd` says which.
 *
 * In a page whose server holds the key, give the browser a client that goes through that server: it asks for the
 * token there, and opens the socket to NoClick's API itself.
 */

import type { NoClick } from "./client.ts";
import { NoClickError } from "./errors.ts";
import { ApiObject, parseTime, str } from "./object.ts";
import type { JsonObject, ObjectInit } from "./object.ts";
import type { UserOption } from "./scope.ts";
import { checkedSocketUrl, spread } from "./sockets.ts";

/** What a person does in a view that drives the browser, in the page's CSS pixels. */
export type BrowserViewInput =
  | { type: "tap"; x: number; y: number }
  | { type: "mouse"; action: "down" | "up" | "move"; x: number; y: number }
  | { type: "scroll"; x: number; y: number; dx: number; dy: number }
  | { type: "text"; text: string }
  | { type: "key"; key: string };

/** The size of the page the pictures show, in CSS pixels. */
export interface BrowserViewport {
  width: number;
  height: number;
}

/** `connecting` until the first picture, `live` while pictures come (a view's renewal included), `ended` for good. */
export type BrowserViewState = "connecting" | "live" | "ended";

/** The close codes a view ends with; `renew` opens it again at once, `unauthorized` once more with a new token. */
export const BROWSER_VIEW_CLOSE = {
  renew: 4000, unauthorized: 4401, notFound: 4404, released: 4409, ended: 4410, invalid: 1008,
} as const;
const FINAL: readonly number[] = [BROWSER_VIEW_CLOSE.notFound, BROWSER_VIEW_CLOSE.released, BROWSER_VIEW_CLOSE.ended,
  BROWSER_VIEW_CLOSE.invalid];

const BACKOFF_MS = [500, 1_000, 2_000, 5_000, 10_000, 30_000];
// A view that stayed up this long starts the backoff again; one that drops sooner keeps it climbing.
const STABLE_MS = 30_000;
// What a person did while the view opened again, sent once it's open: their taps, presses and typing, at most this
// many. A move or a scroll is only worth sending as it happens.
const MAX_PENDING = 50;
const PASSING = new Set(["scroll"]);

export interface BrowserViewOptions {
  /** A view that drives the browser: it must be taken over (`takeOver`) first, and the view ends at its hand-back. */
  control?: boolean;
  /** Smaller pictures, at most two a second, for a tile. A view that drives the browser is full size. */
  thumb?: boolean;
}

export interface BrowserViewConnectOptions {
  /** The page's size, before its first picture and whenever it changes. */
  onViewport?: (viewport: BrowserViewport) => void;
  /** The page, as a JPEG. */
  onPicture?: (jpeg: Uint8Array) => void;
  onState?: (state: BrowserViewState) => void;
  /** It ended for good: the close code (`BROWSER_VIEW_CLOSE`), or 0 when asking for a token was refused. */
  onEnd?: (end: { code: number; reason: string }) => void;
  /** A WebSocket class, where the runtime has none of its own (Node before 22). */
  WebSocket?: typeof WebSocket;
}

type Token = { url: string; token: string };

/** An open view; `close()` it when the page stops showing it. */
export class BrowserViewConnection {
  /** Whether it drives the browser (`send`), not only watches it. */
  readonly control: boolean;
  private readonly Socket: typeof WebSocket;
  private socket: WebSocket | null = null;
  private authed = false;
  private stopped = false;
  private failures = 0;
  private refusedInARow = 0;
  private liveSince = 0;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private readonly pending: BrowserViewInput[] = [];
  private current: BrowserViewState = "connecting";
  private readonly token: () => Promise<Token>;
  private readonly options: BrowserViewConnectOptions;
  private readonly reopens: boolean;

  /** @internal `token` gives each socket its token; `reopens`: it opens again by itself, with a new one. */
  constructor(token: () => Promise<Token>, control: boolean, options: BrowserViewConnectOptions, reopens: boolean) {
    const Socket = options.WebSocket ?? globalThis.WebSocket;
    if (!Socket) throw new TypeError("No WebSocket here: pass options.WebSocket");
    this.Socket = Socket;
    this.token = token;
    this.control = control;
    this.options = options;
    this.reopens = reopens;
    void this.open();
  }

  get state(): BrowserViewState {
    return this.current;
  }

  /** What a person did, on a view that drives the browser; while it opens again, their taps, presses and typing wait
   *  for it. */
  send(input: BrowserViewInput): void {
    if (!this.control) throw new TypeError("This view only watches: take the browser over and open one with control to drive it");
    if (this.stopped) return;
    const ws = this.socket;
    if (ws && this.authed && ws.readyState === this.Socket.OPEN) {
      ws.send(JSON.stringify(input));
    } else if (!(PASSING.has(input.type) || (input.type === "mouse" && input.action === "move")) && this.pending.length < MAX_PENDING) {
      this.pending.push(input);
    }
  }

  /** Stop showing it: the socket closes and nothing opens it again. */
  close(): void {
    if (this.stopped) return;
    this.stopped = true;
    clearTimeout(this.retry);
    this.socket?.close(1000);
    this.socket = null;
  }

  private set(state: BrowserViewState): void {
    if (this.current === state) return;
    this.current = state;
    this.options.onState?.(state);
  }

  private async open(): Promise<void> {
    let token: Token;
    try {
      token = await this.token();
    } catch (err) {
      if (this.stopped) return;
      const lasting = err instanceof NoClickError && err.status !== null && err.status < 500 && err.status !== 429;
      if (lasting || !this.reopens) this.end(0, err instanceof Error ? err.message : String(err));
      else this.later();
      return;
    }
    if (this.stopped) return;
    let url: string;
    try {
      url = checkedSocketUrl(token.url, "browser view");
    } catch (err) {
      this.end(0, (err as Error).message);
      return;
    }
    const ws = new this.Socket(url);
    ws.binaryType = "arraybuffer";
    this.socket = ws;
    this.authed = false;
    let pictured = false;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: token.token }));
      this.authed = true;
      for (const input of this.pending.splice(0)) ws.send(JSON.stringify(input));
    };
    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data) as JsonObject;
        if (message.type === "viewport") {
          this.options.onViewport?.({ width: Number(message.width), height: Number(message.height) });
        }
        return;
      }
      if (!pictured) {
        pictured = true;
        this.refusedInARow = 0;
        if (this.current !== "live") this.liveSince = Date.now();
        this.set("live");
      }
      this.options.onPicture?.(new Uint8Array(event.data as ArrayBuffer));
    };
    ws.onerror = () => { /* a close follows */ };
    ws.onclose = (event: CloseEvent) => {
      if (this.socket === ws) this.socket = null;
      this.authed = false;
      if (!this.stopped) this.closed(event.code, event.reason, pictured);
    };
  }

  private closed(code: number, reason: string, pictured: boolean): void {
    if (this.current === "live" && Date.now() - this.liveSince >= STABLE_MS) this.failures = 0;
    if (!this.reopens || FINAL.includes(code)) {
      this.end(code, reason);
      return;
    }
    if (code === BROWSER_VIEW_CLOSE.unauthorized) {
      if (++this.refusedInARow >= 2) {
        this.end(code, reason);
        return;
      }
    }
    if (code === BROWSER_VIEW_CLOSE.renew && pictured) {
      void this.open(); // it ran its time: the next view takes over where it was, still live
      return;
    }
    this.set("connecting");
    this.later();
  }

  private later(): void {
    this.retry = setTimeout(() => void this.open(), spread(BACKOFF_MS[Math.min(this.failures++, BACKOFF_MS.length - 1)]));
  }

  private end(code: number, reason: string): void {
    this.stopped = true;
    clearTimeout(this.retry);
    this.set("ended");
    this.options.onEnd?.({ code, reason });
  }
}

/**
 * A browser's live view as `Browser.liveView` gives it: a single-use `token` for the websocket at `url`, valid two
 * minutes, for a page to `connect()` with (or for your server to hand to one). `Browser.view` asks for one and
 * connects, again and again as the view needs.
 */
export class BrowserLiveView extends ApiObject {
  private connected = false;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _from(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): BrowserLiveView {
    return new BrowserLiveView({ raw, client: init.client, user: init.user });
  }

  get browserId(): string {
    return this._field("browser_id");
  }
  /** Whether it drives the browser, not only watches it. */
  get control(): boolean {
    return this._field("control") === true;
  }
  get thumb(): boolean {
    return this._field("thumb") === true;
  }
  /** The view's websocket. */
  get url(): string {
    return this._field("url");
  }
  /** Opens `url` once, within two minutes: the socket's first message, `{"type": "auth", "token": ...}`. */
  get token(): string | null {
    return str(this._field("token"));
  }
  get tokenExpiresAt(): Date | null {
    return parseTime(this._field("token_expires_at"));
  }

  protected _load(): Promise<JsonObject> {
    return Promise.resolve(this._raw ?? {});
  }

  /** Open this view, once: it doesn't open again by itself (`Browser.view` does). */
  connect(options: BrowserViewConnectOptions = {}): BrowserViewConnection {
    const { url, token } = this;
    if (!url || !token) throw new TypeError("This live view has no token: ask for one with browser.liveView()");
    if (this.connected) throw new TypeError("A live view's token opens it once: ask for another with browser.liveView()");
    this.connected = true;
    return new BrowserViewConnection(() => Promise.resolve({ url, token }), this.control, options, false);
  }
}
