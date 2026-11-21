/** HTTP transport: auth, the acting user, idempotency, retries and error mapping. */

import { APIConnectionError, Unauthenticated, _setOrigin, errorFromPayload } from "./errors.ts";
import type { JsonObject } from "./errors.ts";
import { USER_HEADER, asUser, resolveScope, userIdOf } from "./scope.ts";
import type { UserOption, UserRef } from "./scope.ts";
import { VERSION } from "./version.ts";

export const DEFAULT_BASE_URL = "https://api.noclick.com";
export const SESSION_TOKEN_PREFIX = "nk_sess_";
export const API_KEY_ENV = "NOCLICK_API_KEY";
export const API_URL_ENV = "NOCLICK_API_URL";
/** What NoClick sets in every deployment's environment: its credential (`Project.current()`). */
export const DEPLOYMENT_TOKEN_ENV = "NOCLICK_DEPLOYMENT_TOKEN";
export const DEPLOYMENT_TOKEN_PREFIX = "nk_dep_";
/** Where the hosted API's objects are shown (only for the hosted base URL). */
export const CONSOLE_BASE_URL = "https://noclick.com/dashboard/developers";

/** Returns the bearer for one attempt; called again on every retry. */
export type ApiKeyProvider = () => string | Promise<string>;

// 520-524: Cloudflare's own answers when it got none from the API (a write retried carries its Idempotency-Key).
const RETRY_STATUSES = new Set([408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524]);
const MAX_RETRY_AFTER_S = 60;

export interface ClientOptions {
  /**
   * A key, or a function returning one per attempt (a refreshing token). Defaults to `NOCLICK_API_KEY`
   * (inside a deployed app without a key, its deployment's own credential, `NOCLICK_DEPLOYMENT_TOKEN`).
   */
  apiKey?: string | ApiKeyProvider;
  /** Defaults to `NOCLICK_API_URL`, then `https://api.noclick.com`. */
  baseUrl?: string;
  /** Per-attempt request timeout (default 60s). */
  timeoutMs?: number;
  /** Retries for 408/429/5xx (never a POST's 500, which is replayed) and network errors (default 3). */
  maxRetries?: number;
  /** First backoff step; doubles per attempt with jitter (default 500ms). */
  backoffMs?: number;
  maxBackoffMs?: number;
  headers?: Record<string, string>;
  /** A custom `fetch` (a proxy agent, a test double). Defaults to the global one. */
  fetch?: typeof fetch;
}

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  json?: unknown;
  /** A raw body (bytes or text) instead of `json`. */
  body?: string | Uint8Array | ArrayBuffer | Blob;
  contentType?: string;
  query?: Record<string, QueryValue>;
  /** `undefined` = the ambient user, `null` = the account. */
  user?: UserOption;
  /** Reused on every retry; generated for each write when omitted. */
  idempotencyKey?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  /** `bytes` returns a `Uint8Array` instead of decoded JSON. */
  responseType?: "json" | "bytes";
  /**
   * In a browser, let the request outlive the page that sent it (fetch's `keepalive`), as a closing tab's last save
   * needs. The browser caps such a body at 64 KB.
   */
  keepalive?: boolean;
}

/** The runtime's `process.env`, where it has one (never in a browser; on Cloudflare Workers, with `nodejs_compat`). */
function processEnv(): Record<string, string | undefined> | undefined {
  return (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
}

/** @internal An environment variable, where the runtime has one (never in a browser). */
export function env(name: string): string | undefined {
  const value = processEnv()?.[name];
  return value ? value : undefined;
}

/**
 * The key a client given none signs in with, the same rule in both SDKs: `NOCLICK_API_KEY`, else a
 * deployed app's own credential, `NOCLICK_DEPLOYMENT_TOKEN` (so the whole client acts as the app).
 */
function environmentKey(): string | undefined {
  return env(API_KEY_ENV) ?? env(DEPLOYMENT_TOKEN_ENV);
}

/** Cloudflare's Workers runtime, which names itself in `navigator.userAgent`. */
function onWorkers(): boolean {
  return (globalThis as { navigator?: { userAgent?: string } }).navigator?.userAgent === "Cloudflare-Workers";
}

/**
 * The refusal for a call with no credential (`needed`: a key, or the app's own), naming the fix where the
 * code runs: a Worker or a runtime whose `process.env` doesn't hold it, a page, or a server.
 */
function missingCredential(needed: "key" | "app"): Unauthenticated {
  const name = needed === "app" ? DEPLOYMENT_TOKEN_ENV : API_KEY_ENV;
  const passIt = needed === "app"
    ? `Project.current({ client: new NoClick({ apiKey: env.${name} }) })`
    : `configure({ apiKey: env.${name} })`;
  if (onWorkers()) {
    return new Unauthenticated(`No NoClick credential is configured: this Worker's process.env doesn't hold ${name}.`, {
      nextStep: "Turn on the nodejs_compat flag (with a compatibility date from 2025-04-01), which fills process.env " +
        `from the Worker's environment, or pass it from the handler's env: ${passIt}.`,
    });
  }
  if (inBrowser()) {
    return new Unauthenticated("No NoClick credential is configured, and a web page never holds a secret key.", {
      nextStep: "Mint the signed-in user a session on your server (user.session(...)) and pass NoClick.forSession(token).",
    });
  }
  if (!processEnv()) {
    return new Unauthenticated(`No NoClick credential is configured: this runtime has no process.env to read ${name} from.`, {
      nextStep: `Pass it from the runtime's own environment: ${passIt}.`,
    });
  }
  if (needed === "app") {
    return new Unauthenticated(`Project.current() runs inside a deployed app, where NoClick sets ${DEPLOYMENT_TOKEN_ENV}.`, {
      nextStep: "Outside a deployment, use Project.fromName(...) with your own key.",
    });
  }
  return new Unauthenticated("No NoClick API key is configured.", {
    nextStep: `Set ${API_KEY_ENV} or pass new NoClick({ apiKey }). A deployed app needs neither: the client signs in ` +
      `with the credential NoClick puts in its environment, ${DEPLOYMENT_TOKEN_ENV}.`,
  });
}

/** A browser page or worker: it owns the User-Agent header. */
function inBrowser(): boolean {
  const scope = globalThis as { document?: unknown; WorkerGlobalScope?: new () => unknown };
  return scope.document !== undefined || (scope.WorkerGlobalScope !== undefined && globalThis instanceof scope.WorkerGlobalScope);
}

function newIdempotencyKey(): string {
  const cryptoApi = (globalThis as { crypto?: Crypto }).crypto;
  if (cryptoApi?.randomUUID) return `nc_${cryptoApi.randomUUID().replace(/-/g, "")}`;
  const bytes = new Uint8Array(16);
  if (cryptoApi?.getRandomValues) cryptoApi.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return `nc_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

function retryAfterSeconds(response: Response): number | undefined {
  const value = response.headers.get("retry-after");
  if (!value) return undefined;
  const seconds = Number(value);
  if (!Number.isNaN(seconds)) return Math.max(0, seconds);
  const when = Date.parse(value);
  return Number.isNaN(when) ? undefined : Math.max(0, (when - Date.now()) / 1000);
}

function parseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function isRetryable(verb: string, response: Response, body: unknown): boolean {
  const status = response.status;
  if (!RETRY_STATUSES.has(status)) return false;
  // The server replays a POST's stored 500 for the same Idempotency-Key.
  if (status === 500 && verb === "POST") return false;
  // A replayed answer is the first one, every time: the server kept it because the work may have happened.
  if (response.headers.get("idempotent-replayed") === "true") return false;
  const error = body && typeof body === "object" ? (body as JsonObject).error : undefined;
  if (!error || typeof error !== "object") return true;
  // OpenAI-shaped errors (`/v1/ai`) carry the type in `code`.
  const kind = (error as JsonObject).code ?? (error as JsonObject).type;
  // A spent quota won't come back in seconds; a timeout's work may still be going on.
  return kind !== "quota_exceeded" && kind !== "request_timeout";
}

/**
 * Connection settings for the platform API. Most code never builds one: the
 * default client reads `NOCLICK_API_KEY` / `NOCLICK_API_URL` (inside a deployed
 * app without a key, it signs in as the app with `NOCLICK_DEPLOYMENT_TOKEN`). Pass
 * `{ client }` to any method to use another account or endpoint.
 */
export class NoClick {
  // Private fields: printing, serializing or spreading a client (or anything holding one) never reaches the key.
  readonly #apiKey: string | ApiKeyProvider | undefined;
  readonly #headers: Record<string, string>;
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly maxRetries: number;
  readonly backoffMs: number;
  readonly maxBackoffMs: number;
  private readonly fetchImpl: typeof fetch | undefined;
  get apiKey(): string | ApiKeyProvider | undefined {
    return this.#apiKey;
  }
  /**
   * Whether this client signs in as a deployed app's own code (its deployment's credential), where
   * `fromName` resolves names in the app's own namespace for the environment it runs in.
   */
  get inApp(): boolean {
    return typeof this.apiKey === "string" && this.apiKey.startsWith(DEPLOYMENT_TOKEN_PREFIX);
  }
  /** @internal Swapped by tests for instant, observable backoff. */
  _sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  constructor(options: ClientOptions = {}) {
    this.#apiKey = options.apiKey ?? environmentKey();
    this.baseUrl = (options.baseUrl ?? env(API_URL_ENV) ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? 60_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.backoffMs = options.backoffMs ?? 500;
    this.maxBackoffMs = options.maxBackoffMs ?? 8_000;
    this.#headers = { ...(options.headers ?? {}) };
    this.fetchImpl = options.fetch;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return `NoClick { baseUrl: ${JSON.stringify(this.baseUrl)} }`;
  }

  /**
   * A client that authenticates with a user session (a `Session` or its
   * `nk_sess_...` token): every call acts for the session's user with its
   * scopes. The same as `new NoClick({ apiKey: token })`.
   */
  static forSession(session: string | { token: string; baseUrl?: string }, options: Omit<ClientOptions, "apiKey"> = {}): NoClick {
    const token = typeof session === "string" ? session : session.token;
    if (typeof token !== "string" || !token.startsWith(SESSION_TOKEN_PREFIX)) {
      throw new TypeError(`NoClick.forSession() takes a Session or a ${SESSION_TOKEN_PREFIX}... token; use new NoClick({ apiKey }) for a secret key.`);
    }
    const baseUrl = options.baseUrl ?? (typeof session === "string" ? undefined : session.baseUrl);
    return new NoClick({ ...options, apiKey: token, baseUrl });
  }

  /** Run `fn` acting for `user`; the same as the module-level `asUser`. */
  asUser<T>(user: UserRef | null, fn: () => T | Promise<T>): Promise<T> {
    return asUser(user, fn);
  }

  /**
   * Send one API call and return its decoded body. Writes carry an
   * `Idempotency-Key` reused on every retry, so a retried POST can't do the work twice.
   */
  async request<T = unknown>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    if (!this.apiKey) throw missingCredential("key");
    const verb = method.toUpperCase();
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(inBrowser() ? {} : { "User-Agent": `noclick-typescript/${VERSION}` }),
      ...this.#headers,
    };
    const scope = resolveScope(options.user);
    const user = await userIdOf(scope);
    if (user) headers[USER_HEADER] = user;
    if (verb !== "GET") headers["Idempotency-Key"] = options.idempotencyKey ?? newIdempotencyKey();

    let body: BodyInit | undefined;
    if (options.body !== undefined) {
      body = options.body as BodyInit;
      headers["Content-Type"] = options.contentType ?? "application/octet-stream";
    } else if (options.json !== undefined) {
      body = JSON.stringify(options.json);
      headers["Content-Type"] = "application/json";
    }

    const url = new URL(this.baseUrl + path);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }

    const fetchFn = this.fetchImpl ?? globalThis.fetch;
    const timeoutMs = options.timeoutMs ?? this.timeoutMs;
    for (let attempt = 0; ; attempt++) {
      let response: Response;
      // Abort and the timeout cover the key provider too: a stuck provider must not hang the call.
      const controller = new AbortController();
      const onAbort = () => controller.abort(options.signal?.reason);
      if (options.signal?.aborted) onAbort();
      options.signal?.addEventListener("abort", onAbort, { once: true });
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const authorization = `Bearer ${await this.bearer(controller.signal, options.signal, timeoutMs)}`;
        try {
          response = await fetchFn(url.toString(), {
            method: verb, headers: { Authorization: authorization, ...headers }, body, signal: controller.signal,
            ...(options.keepalive ? { keepalive: true } : {}),
          });
        } catch (err) {
          if (options.signal?.aborted) throw err;
          if (attempt >= this.maxRetries) {
            const detail = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
            throw new APIConnectionError(`Could not reach the NoClick API at ${this.baseUrl}: ${detail}`, {
              nextStep: `Check your network and ${API_URL_ENV}, then retry.`,
              attempts: attempt + 1,
            });
          }
          await this._sleep(this.backoffDelay(attempt, undefined));
          continue;
        }
      } finally {
        clearTimeout(timer);
        options.signal?.removeEventListener("abort", onAbort);
      }

      if (response.ok && options.responseType === "bytes") {
        return new Uint8Array(await response.arrayBuffer()) as T;
      }
      const text = await response.text();
      const decoded = parseJson(text);
      if (response.ok) return (decoded === undefined ? text : decoded) as T;
      if (isRetryable(verb, response, decoded) && attempt < this.maxRetries) {
        await this._sleep(this.backoffDelay(attempt, retryAfterSeconds(response)));
        continue;
      }
      const err = this.errorFor(response, verb, url, decoded, text);
      err.attempts = attempt + 1;
      _setOrigin(err, { client: this, user: scope });
      throw err;
    }
  }

  /**
   * @internal `(event, data)` pairs from a server-sent-events response as each arrives; an `error`
   * event (or data carrying an `error`, OpenAI's way) throws its `NoClickError`, and `data: [DONE]`
   * ends it. A stream refused before it starts is retried like a request; once started it isn't, and
   * isn't timed out: the server sends a comment every 15 seconds, and `signal` stops the stream.
   */
  async *_events(
    method: string,
    path: string,
    options: { json?: unknown; query?: Record<string, QueryValue>; user?: UserOption; signal?: AbortSignal } = {},
  ): AsyncGenerator<[string, JsonObject]> {
    if (!this.apiKey) throw missingCredential("key");
    const verb = method.toUpperCase();
    const headers: Record<string, string> = {
      Accept: "text/event-stream",
      ...(inBrowser() ? {} : { "User-Agent": `noclick-typescript/${VERSION}` }),
      ...this.#headers,
    };
    const user = await userIdOf(resolveScope(options.user));
    if (user) headers[USER_HEADER] = user;
    if (verb !== "GET") headers["Idempotency-Key"] = newIdempotencyKey();
    if (options.json !== undefined) headers["Content-Type"] = "application/json";
    const url = new URL(this.baseUrl + path);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
    const signal = options.signal ?? new AbortController().signal;
    let response: Response;
    for (let attempt = 0; ; attempt++) {
      headers.Authorization = `Bearer ${await this.bearer(AbortSignal.timeout(this.timeoutMs), signal, this.timeoutMs)}`;
      try {
        response = await (this.fetchImpl ?? globalThis.fetch)(url.toString(), {
          method: verb, headers, body: options.json === undefined ? undefined : JSON.stringify(options.json), signal,
        });
      } catch (err) {
        if (signal.aborted) throw err;
        throw new APIConnectionError(`Could not reach the NoClick API at ${this.baseUrl}: ${err instanceof Error ? err.message : String(err)}`, {
          nextStep: `Check your network and ${API_URL_ENV}, then stream again.`,
        });
      }
      if (response.ok && response.body) break;
      const text = await response.text();
      const decoded = parseJson(text);
      if (isRetryable(verb, response, decoded) && attempt < this.maxRetries) {
        await this._sleep(this.backoffDelay(attempt, retryAfterSeconds(response)));
        continue;
      }
      const err = this.errorFor(response, verb, url, decoded, text);
      err.attempts = attempt + 1;
      throw err;
    }
    const requestId = response.headers.get("x-request-id");
    for await (const [event, data] of sseEvents(response.body!)) {
      if (event === "error" || (data.error !== null && typeof data.error === "object")) throw errorFromPayload(data, { requestId });
      yield [event, data];
    }
  }

  /** @internal The bearer a call sends now (`AI.headers` hands it to another client). */
  async _bearer(): Promise<string> {
    if (!this.apiKey) throw missingCredential("key");
    return await this.bearer(AbortSignal.timeout(this.timeoutMs), undefined, this.timeoutMs);
  }

  /** The bearer for one attempt (a provider is asked each time, and given up on when `signal` aborts). */
  private async bearer(signal: AbortSignal, userSignal: AbortSignal | undefined, timeoutMs: number): Promise<string> {
    const provided = Promise.resolve(typeof this.apiKey === "function" ? this.apiKey() : this.apiKey);
    provided.catch(() => {}); // a provider that rejects after we gave up on it is not an unhandled rejection
    let onAbort = () => {};
    const aborted = new Promise<never>((_, reject) => {
      onAbort = () => reject(signal.reason);
      if (signal.aborted) onAbort();
      else signal.addEventListener("abort", onAbort, { once: true });
    });
    let key: string | undefined;
    try {
      key = await Promise.race([provided, aborted]);
    } catch (err) {
      if (!signal.aborted || userSignal?.aborted) throw err;
      throw new Unauthenticated(`The NoClick API key provider did not return a key within ${timeoutMs}ms.`, {
        nextStep: "Make the apiKey function resolve (or reject) promptly.",
      });
    } finally {
      signal.removeEventListener("abort", onAbort);
    }
    if (!key) {
      throw new Unauthenticated("The NoClick API key provider returned no key.", {
        nextStep: "Return a key or token from the apiKey function.",
      });
    }
    return key;
  }

  /**
   * The developer console page for an object (`operations?op=`, `agents/`, `users/`), or
   * null when this client doesn't talk to the hosted API.
   */
  consoleUrl(section: string, id: string): string | null {
    if (this.baseUrl !== DEFAULT_BASE_URL) return null;
    const ref = encodeURIComponent(id);
    return section === "operations" ? `${CONSOLE_BASE_URL}/operations?op=${ref}` : `${CONSOLE_BASE_URL}/${section}/${ref}`;
  }

  private backoffDelay(attempt: number, retryAfter: number | undefined): number {
    if (retryAfter !== undefined) return Math.min(retryAfter, MAX_RETRY_AFTER_S) * 1000;
    const delay = Math.min(this.maxBackoffMs, this.backoffMs * 2 ** attempt);
    return delay * (0.5 + Math.random() / 2);
  }

  private errorFor(response: Response, verb: string, url: URL, decoded: unknown, text: string) {
    // Cloudflare's ray names a request the API never answered (its own 52x); NoClick support finds either.
    const edgeId = response.headers.get("cf-ray");
    const requestId = response.headers.get("x-request-id") ?? edgeId;
    const hasError = decoded && typeof decoded === "object" && typeof (decoded as JsonObject).error === "object";
    const payload = hasError
      ? decoded
      : {
          message: `HTTP ${response.status} from ${verb} ${url.pathname}` + (requestId ? ` (request ${requestId})` : "") +
            (text && !decoded ? `: ${text.slice(0, 300)}` : ""),
        };
    const err = errorFromPayload(payload, { status: response.status, requestId });
    if (edgeId && err.details.cf_ray === undefined) err.details.cf_ray = edgeId;
    const retryAfter = retryAfterSeconds(response);
    if (retryAfter !== undefined && err.details.retry_after === undefined) err.details.retry_after = retryAfter;
    return err;
  }
}

let defaultInstance: NoClick | null = null;

/** The client used when no `{ client }` is given (built from the environment). */
export function defaultClient(): NoClick {
  defaultInstance ??= new NoClick();
  return defaultInstance;
}

/**
 * @internal The client a deployed app's own code acts with (`Project.current()`): the default one when it
 * signs in as the app (no `NOCLICK_API_KEY` beside the deployment's credential), else one with that credential.
 */
export function appClient(): NoClick {
  const client = defaultClient();
  if (client.inApp) return client;
  const token = env(DEPLOYMENT_TOKEN_ENV);
  if (!token) throw missingCredential("app");
  return new NoClick({ apiKey: token });
}

/** Replace the default client, e.g. `configure({ apiKey: "nk_live_..." })`. */
export function configure(options: ClientOptions = {}): NoClick {
  defaultInstance = new NoClick(options);
  return defaultInstance;
}

export function resolveClient(client: NoClick | undefined): NoClick {
  return client ?? defaultClient();
}

/** `(event, data)` pairs from a server-sent-events body, as each arrives. */
async function* sseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<[string, JsonObject]> {
  const decoder = new TextDecoder();
  const reader = body.getReader();
  let buffer = "";
  let event = "message";
  let data: string[] = [];
  let finished = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      finished = done;
      buffer += done ? "\n\n" : decoder.decode(value, { stream: true });
      let cut: number;
      while ((cut = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, cut).replace(/\r$/, "");
        buffer = buffer.slice(cut + 1);
        if (!line) {
          if (data.length === 1 && data[0] === "[DONE]") return;
          if (data.length) {
            const parsed: unknown = JSON.parse(data.join("\n"));
            yield [event, parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as JsonObject) : {}];
          }
          event = "message";
          data = [];
        } else if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (done) return;
    }
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined); // the caller stopped early: close the connection
    reader.releaseLock();
  }
}
