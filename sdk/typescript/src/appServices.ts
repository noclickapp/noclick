/**
 * App services: email, payments and sign-in for a project, reached through it:
 * `app.email`, `app.payments`, `app.signIn`.
 *
 *     const app = Project.fromName("booking");
 *     await app.email.enable({ domain: "acmebooking.com" });
 *     await app.email.send({ to: "ana@example.com", subject: "Your booking", text: "See you Friday at 3pm." });
 *     await app.email.broadcast({ to: subscribers, subject: "October at Acme", text: "...", idempotencyKey: "october-news" });
 *     console.log((await app.payments.enable({ country: "US" })).claimUrl);
 *     await (await app.signIn.enable(["email", "google"])).wait();
 */

import type { RequestOptions } from "./client.ts";
import { toDnsRecord } from "./domain.ts";
import type { DnsRecord } from "./domain.ts";
import { asObject, compact, num, paginate, parseTime, refId, str } from "./object.ts";
import type { ApiObject, JsonObject } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

/** One of a project's services at `/v1/projects/{id}/<name>`; it acts for the project's user. */
export abstract class ProjectService {
  protected abstract readonly service: string;
  /** @internal */ readonly _project: ApiObject;

  constructor(project: ApiObject) {
    this._project = project;
  }

  /** @internal */
  async _path(...rest: string[]): Promise<string> {
    return [`/v1/projects/${await refId(this._project)}`, this.service, ...rest].join("/");
  }

  /** @internal */
  async _call<T = unknown>(method: string, rest: string[], options: RequestOptions = {}): Promise<T> {
    return await this._project._request<T>(method, await this._path(...rest), options);
  }
}

// --- email ---------------------------------------------------------------------

/**
 * How an app sends email. `status` is `off` (never enabled), `pending` (NoClick is setting up the
 * app's sending, usually within a minute; mail sent meanwhile goes out once it's set up, and
 * `pendingReason` says why when setting it up failed), `pending_dns` (the domain's records aren't
 * seen yet: a domain bought through NoClick turns `active` within minutes), `active`, or `paused`
 * (too many bounces or spam complaints; `pausedReason` says which: `bounce_rate`, `complaint_rate`,
 * `mailbox_provider_feedback` or `blocklisted`). Broadcasts go out apart, from the domain's `news.`
 * subdomain, with a status of their own.
 */
export interface EmailSetup {
  status: "off" | "pending" | "pending_dns" | "active" | "paused";
  /** The address mail goes out from, like `bookings@acmebooking.com`. */
  fromAddress: string | null;
  fromName: string | null;
  /** The sending domain; null while the app uses its default sender. */
  domain: string | null;
  /**
   * What DNS must hold for mail to send and land: DKIM and a bounce subdomain (MX and SPF) for the
   * domain and its `news.` subdomain, and a recommended DMARC policy.
   */
  records: DnsRecord[];
  /** How many messages the app may send a day; it grows as its mail keeps landing. */
  dailyLimit: number | null;
  /** Sent since midnight UTC. */
  sentToday: number | null;
  pausedReason: string | null;
  /** Why the app's sending isn't set up yet, once setting it up failed (NoClick keeps trying); else null. */
  pendingReason: string | null;
  /** The postal address every broadcast's footer carries (null until you give one). */
  postalAddress: string | null;
  /** How many recipients its broadcasts may reach a day, apart from `dailyLimit`. */
  broadcastDailyLimit: number | null;
  /** `needs_domain` (the default sender doesn't send broadcasts), `pending`, `pending_dns`, `active` or `paused`. */
  broadcastStatus: "off" | "needs_domain" | "pending" | "pending_dns" | "active" | "paused";
  /** The address broadcasts go out from, on the `news.` subdomain. */
  broadcastFromAddress: string | null;
  /** Broadcast recipients sent to since midnight UTC. */
  broadcastSentToday: number | null;
  broadcastPausedReason: string | null;
  /** Whether `send` goes out now (`status` is `active`). */
  canSend: boolean;
  raw: JsonObject;
}

/**
 * One broadcast an app sent: how many it was `sent` to, and those it `skipped`, each `{ to, reason }`
 * with `reason` `unsubscribed`, `bounced`, `complained` or `invalid`. From a preview, only the
 * account's own people get it: `captured` counts the copies kept.
 */
export interface Broadcast {
  id: string;
  subject: string | null;
  sent: number;
  skipped: JsonObject[];
  captured: number;
  raw: JsonObject;
}

/**
 * One message an app sent; `error` says why it bounced or failed. `complained` is best-effort: some
 * mailbox providers, Gmail among them, report no single complaint. Sent to several recipients, it
 * shows the worst any met (a bounce, a complaint), else how far the slowest got.
 *
 * A preview's code reaches only the account's own people (its owner and the members of the owner's
 * workspaces): every other copy is kept, never sent or charged, and named in `captured`; a message
 * whose every copy was kept is `captured`, with the `text` and `html` it would have sent.
 * `messages({ environment: "preview" })` is the preview's outbox.
 *
 * A message sent while the account can't pay (out of funds, or at a spend cap) is `held`: kept, and
 * sent and charged once it can pay, or `failed` after 3 days, never charged.
 */
export interface SentEmail {
  id: string;
  to: string[];
  subject: string | null;
  status: "held" | "queued" | "sent" | "delivered" | "bounced" | "complained" | "failed" | "captured";
  /**
   * Whether it was opened, as far as can be told (privacy proxies open some mail on the reader's
   * behalf); null for a message with no HTML, or a sign-in code, which aren't tracked.
   */
  opened: boolean | null;
  bounced: boolean;
  error: string | null;
  at: Date | null;
  /** `message` (`send`), `code` (`sendCode`) or `broadcast`. */
  kind: "message" | "code" | "broadcast";
  /** Where the code that sent it runs. */
  environment: "production" | "preview";
  /** The recipients a preview kept rather than sent to. */
  captured: string[];
  /** What a kept message would have said; null once a message went out. */
  text: string | null;
  html: string | null;
  raw: JsonObject;
}

export interface EmailEnableOptions {
  /**
   * A `Domain` or its name; without one the app sends from its default address. A subdomain of a
   * domain your account holds may send any project's mail, a user's included, from a key acting for
   * the whole account.
   */
  domain?: string | ApiObject;
  /** On `domain`: `noreply@<domain>` unless you pass one. */
  fromAddress?: string;
  fromName?: string;
  /** The address every broadcast's footer carries, as the law asks of bulk mail; `broadcast` needs one. */
  postalAddress?: string;
}

export interface EmailBroadcastOptions {
  /** Up to 50,000 addresses; listing them says each one opted in to mail from the app. */
  to: readonly string[];
  subject: string;
  text?: string;
  html?: string;
  replyTo?: string;
  /** Names the broadcast: sending again with the same key sends nothing new. Required. */
  idempotencyKey: string;
}

export interface EmailCodeOptions {
  /** `sign_in` (the default) or `verify_email`. */
  purpose?: "sign_in" | "verify_email";
  /** Said in the message: 60-86400 seconds. */
  expiresInS?: number;
  idempotencyKey?: string;
}

export interface EmailSendOptions {
  /** One address, or up to 10 that each receive the message. */
  to: string | readonly string[];
  subject: string;
  text?: string;
  html?: string;
  replyTo?: string;
  /**
   * Only worth getting now (a magic link, a password reset): refused (`PaymentRequired`) while the
   * account can't pay, rather than `held` to go out later.
   */
  timeSensitive?: boolean;
  /** Makes a retried send safe: the same key sends once. */
  idempotencyKey?: string;
}

function toEmailSetup(value: unknown): EmailSetup {
  const raw = asObject(value);
  const status = (str(raw.status) ?? "off") as EmailSetup["status"];
  return {
    status,
    canSend: status === "active",
    fromAddress: str(raw.from_address),
    fromName: str(raw.from_name),
    domain: str(raw.domain),
    records: Array.isArray(raw.records) ? raw.records.map(toDnsRecord) : [],
    dailyLimit: num(raw.daily_limit),
    sentToday: num(raw.sent_today),
    pausedReason: str(raw.paused_reason),
    pendingReason: str(raw.pending_reason),
    postalAddress: str(raw.postal_address),
    broadcastDailyLimit: num(raw.broadcast_daily_limit),
    broadcastStatus: (str(raw.broadcast_status) ?? "off") as EmailSetup["broadcastStatus"],
    broadcastFromAddress: str(raw.broadcast_from_address),
    broadcastSentToday: num(raw.broadcast_sent_today),
    broadcastPausedReason: str(raw.broadcast_paused_reason),
    raw,
  };
}

function toBroadcast(value: unknown): Broadcast {
  const raw = asObject(value);
  return {
    id: String(raw.id ?? ""),
    subject: str(raw.subject),
    sent: num(raw.sent) ?? 0,
    skipped: Array.isArray(raw.skipped) ? raw.skipped.map(asObject) : [],
    captured: num(raw.captured) ?? 0,
    raw,
  };
}

registerResult("project.email.broadcast", toBroadcast);

function toSentEmail(value: unknown): SentEmail {
  const raw = asObject(value);
  return {
    id: String(raw.id),
    to: typeof raw.to === "string" ? [raw.to] : strings(raw.to),
    subject: str(raw.subject),
    status: (str(raw.status) ?? "queued") as SentEmail["status"],
    opened: typeof raw.opened === "boolean" ? raw.opened : null,
    bounced: raw.bounced === true,
    error: str(raw.error),
    at: parseTime(raw.at),
    kind: (str(raw.kind) ?? "message") as SentEmail["kind"],
    environment: (str(raw.environment) ?? "production") as SentEmail["environment"],
    captured: strings(raw.captured),
    text: str(raw.text),
    html: str(raw.html),
    raw,
  };
}

async function domainName(domain: string | ApiObject | undefined): Promise<string | undefined> {
  if (domain === undefined || typeof domain === "string") return domain;
  const known = domain._known("name");
  return typeof known === "string" ? known : String((await domain._ensure()).name);
}

/**
 * `app.email`: transactional email from the app's own address
 * (receipts, booking confirmations), rate-capped and charged per recipient. One-time sign-in
 * codes go through `sendCode`, on a lane of their own; newsletters and announcements through
 * `broadcast`, on a stream of their own.
 */
export class ProjectEmail extends ProjectService {
  protected readonly service = "email";

  /**
   * Turn email on, or change what you pass (the rest keeps its value). With a domain, broadcasts go
   * from the same name on its `news.` subdomain. The first call answers `pending` while NoClick sets
   * up the app's sending (what it sends meanwhile goes out once that's done). A domain bought through
   * NoClick gets its DNS records written and turns `active` within minutes; any other is connected
   * for you and `records` lists what to add (within seconds of this call).
   */
  async enable(options: EmailEnableOptions = {}): Promise<EmailSetup> {
    const json = compact({
      domain: await domainName(options.domain),
      from_address: options.fromAddress,
      from_name: options.fromName,
      postal_address: options.postalAddress,
    });
    return toEmailSetup(await this._call("POST", [], { json }));
  }

  /** How the app sends email, with the domain's records checked again (`off` if never enabled). */
  async status(): Promise<EmailSetup> {
    return toEmailSetup(await this._call("GET", []));
  }

  /**
   * Send one message; `ActionRequired` while the domain's records are pending, `RateLimited` past the
   * daily limit. While the account can't pay it resolves `held`: sent and charged once it can, so a
   * form never fails on it (`timeSensitive` refuses instead).
   */
  async send(options: EmailSendOptions): Promise<SentEmail> {
    if (options.text === undefined && options.html === undefined) throw new TypeError("Pass text, html or both.");
    const json = compact({
      to: typeof options.to === "string" ? [options.to] : [...options.to],
      subject: options.subject,
      text: options.text,
      html: options.html,
      reply_to: options.replyTo,
      time_sensitive: options.timeSensitive || undefined,
    });
    return toSentEmail(await this._call("POST", ["send"], { json, idempotencyKey: options.idempotencyKey }));
  }

  /**
   * Send a one-time `code` (4-12 letters and digits) to `to` in a short message NoClick writes in the
   * app's name. Codes have a daily limit of their own, apart from `dailyLimit`; one address gets at
   * most 5 in 15 minutes (`RateLimited`). Each is charged as one message. `app.signIn` sends its
   * codes this way.
   */
  async sendCode(to: string, code: string, options: EmailCodeOptions = {}): Promise<SentEmail> {
    const json = compact({ to, code, purpose: options.purpose ?? "sign_in", expires_in_s: options.expiresInS });
    return toSentEmail(await this._call("POST", ["codes"], { json, idempotencyKey: options.idempotencyKey }));
  }

  /**
   * The messages the app sent, newest first: 50 unless `limit` says (`to` keeps one address's,
   * `environment` those its production or its previews sent). A preview's code reaches only the
   * account's own people, so `environment: "preview"` is its outbox: each message names the
   * recipients it kept in `captured`, with the `text` and `html` it would have sent.
   */
  async messages(
    options: { to?: string; limit?: number; environment?: "production" | "preview" } = {},
  ): Promise<SentEmail[]> {
    const rows = await paginate(this._project._api, await this._path("messages"), {
      query: { to: options.to, environment: options.environment },
      user: this._project._callScope() ?? null,
      limit: options.limit ?? 50,
    });
    return rows.map(toSentEmail);
  }

  /**
   * Send one message to many people who asked for it (a newsletter, an announcement). Anyone who
   * unsubscribed from the app's broadcasts (until they opt in again and you `resubscribe` them),
   * bounced or complained is skipped. It goes out on a bulk stream of its own under
   * `broadcastDailyLimit`, from `broadcastFromAddress`, so a campaign never pauses transactional
   * mail; it needs a domain of the app's own (`ActionRequired` on the default sender) and goes out
   * at the pace mail can be sent, so a large one takes minutes.
   * Every message carries its recipient's own `List-Unsubscribe` header with one-click unsubscribe,
   * and a footer with an unsubscribe link and the `postalAddress` (`ActionRequired` until there is
   * one). `wait()` resolves to the `Broadcast`.
   */
  async broadcast(options: EmailBroadcastOptions): Promise<Operation<Broadcast>> {
    if (options.text === undefined && options.html === undefined) throw new TypeError("Pass text, html or both.");
    if (typeof options.to === "string") throw new TypeError("broadcast() takes a list of addresses; send() is for one message.");
    const payload = await this._call("POST", ["broadcasts"], {
      json: compact({ to: [...options.to], subject: options.subject, text: options.text, html: options.html, reply_to: options.replyTo }),
      idempotencyKey: options.idempotencyKey,
    });
    return Operation._fromPayload<Broadcast>(payload, {
      client: this._project._client, user: this._project._callScope(), kind: "project.email.broadcast", reader: toBroadcast,
    });
  }

  /**
   * Lift `address`'s unsubscribe from the app's broadcasts once they've asked for them again and
   * confirmed it (a click on a link you emailed that address); call it only on such a confirmed
   * opt-in. A bounce or a spam complaint isn't lifted. Resolves to `true` if the address was
   * unsubscribed, `false` if it wasn't.
   */
  async resubscribe(address: string): Promise<boolean> {
    const raw = asObject(await this._call("POST", ["resubscribe"], { json: { address } }));
    return raw.resubscribed === true;
  }
}

// --- payments ------------------------------------------------------------------

/**
 * Where an app's payments go. `mode` is `off`, `test` (a test account waiting to be claimed),
 * `claimed` (the owner is finishing the steps `claimStep` names), `live` (live keys are in the
 * app's production secrets and the account can take payments) or `disconnected` (the owner removed
 * NoClick's payments app or its keys). Money goes straight to the owner's account; NoClick takes no cut.
 */
export interface PaymentsSetup {
  mode: "off" | "test" | "claimed" | "live" | "disconnected";
  /**
   * While claiming: `claim` (send the owner `claimUrl`), `application` (the owner gives the payment
   * processor their business details), `install` (the owner installs NoClick's payments app on their
   * live account) or `verification` (the processor is verifying the business).
   */
  claimStep: "claim" | "application" | "install" | "verification" | null;
  /** What to do now, in a sentence. */
  nextStep: string | null;
  /** Where the owner claims the account: a NoClick link that always leads to their next step, working until `testExpiresAt`. */
  claimUrl: string | null;
  /** When the test account and its data are deleted unless claimed; after that `enable()` opens a fresh one. */
  testExpiresAt: Date | null;
  /** The owner's own dashboard at the payment processor, once claimed. */
  dashboardUrl: string | null;
  /** The project secrets that hold the account's keys: live keys in production once `live`, test keys in previews always. */
  secrets: string[];
  /**
   * Which payment processor apps are paid through, by the name its own client library goes by, so the
   * app's code can pick the library that reads `secrets`. It's the same for every app, so `status()`
   * reports it even while `off`, and code can be written before `enable()`.
   */
  processor: string | null;
  /** Where the business is (ISO 3166-1 alpha-2), fixed when the account was opened. */
  country: string | null;
  /** Where the processor delivers the account's events: the app's `/api/payments/webhook`. */
  webhookUrl: string | null;
  raw: JsonObject;
}

export interface PaymentsEnableOptions {
  /** Where the owner's business is (ISO 3166-1 alpha-2): required the first time, fixed after. */
  country?: string;
  /** Who the processor reminds before an unclaimed test account expires (your account's email unless given). */
  ownerEmail?: string;
  /** Prefills the claim (the app's name unless given). */
  businessName?: string;
}

function toPaymentsSetup(value: unknown): PaymentsSetup {
  const raw = asObject(value);
  return {
    mode: (str(raw.mode) ?? "off") as PaymentsSetup["mode"],
    claimStep: str(raw.claim_step) as PaymentsSetup["claimStep"],
    nextStep: str(raw.next_step),
    claimUrl: str(raw.claim_url),
    testExpiresAt: parseTime(raw.test_expires_at),
    dashboardUrl: str(raw.dashboard_url),
    secrets: strings(raw.secrets),
    processor: str(raw.processor),
    country: str(raw.country),
    webhookUrl: str(raw.webhook_url),
    raw,
  };
}

/**
 * `app.payments`: take payments without a payments account of your
 * own. NoClick opens a test account and puts its keys in the app's secrets; the owner claims
 * it to take real money.
 */
export class ProjectPayments extends ProjectService {
  protected readonly service = "payments";

  /**
   * Open the app's test account (`country` required the first time; `NotAvailable` for one the
   * processor doesn't serve), or answer the one it has. After `testExpiresAt` passes unclaimed it
   * opens a fresh one with new keys; a `disconnected` account reconnects once the owner reinstalled
   * NoClick's payments app.
   */
  async enable(options: PaymentsEnableOptions = {}): Promise<PaymentsSetup> {
    const json = compact({ country: options.country, owner_email: options.ownerEmail, business_name: options.businessName });
    return toPaymentsSetup(await this._call("POST", [], { json }));
  }

  /** Where the app's payments stand: `mode` moves from `test` to `claimed` to `live`; `processor` is there even while `off`. */
  async status(): Promise<PaymentsSetup> {
    return toPaymentsSetup(await this._call("GET", []));
  }
}

// --- sign-in -------------------------------------------------------------------

export type SignInProvider = "email" | "google" | "apple" | "microsoft" | "github";

/**
 * An app's sign-in. `status` is `off`, `installing` (a change is being committed and deployed),
 * `active` or `failed` (the first change failed; a later one that fails leaves sign-in `active`, with
 * `error`). The code lives in the app's repo, the users in `usersTable`.
 */
export interface SignInSetup {
  status: "off" | "installing" | "active" | "failed";
  providers: string[];
  /**
   * The providers that sign in through NoClick, with nothing to set up at the provider (its screen names
   * NoClick). The rest of `providers` but `email` use your own client there.
   */
  managedProviders: string[];
  usersTable: string | null;
  /** Every table sign-in keeps: `usersTable` first, then its sessions, linked accounts, pending codes and rate limits. */
  tables: string[];
  /** The binding of the database the users are kept in. */
  database: string | null;
  /** The open-source library the code is written with, and its version. */
  library: string;
  version: string | null;
  /** A newer version NoClick ships (`upgrade()` moves to it), else null. */
  updateAvailable: string | null;
  /** The commit that added or last changed sign-in. */
  commit: string | null;
  /** Where that commit went when it wasn't the production branch (yours, or one NoClick made beside your edits). */
  branch: string | null;
  /** Files holding edits of yours that the last change left alone, committing on `branch` instead. */
  editedFiles: string[];
  /** Where each provider on your own client sends people back to; register it with that provider. */
  callbackUrls: Record<string, string>;
  /** Project secrets a provider on your own client still needs (`GOOGLE_CLIENT_ID`, ...). */
  missingSecrets: string[];
  /**
   * The secrets NoClick writes itself and never shows: `AUTH_SECRET`, `AUTH_URL`, `AUTH_PROXY_SECRET`,
   * and the app's client of NoClick's sign-in (`NOCLICK_SIGN_IN_CLIENT_ID`, `_SECRET`) while any provider is managed.
   */
  secrets: string[];
  error: JsonObject | null;
  raw: JsonObject;
}

function toSignInSetup(value: unknown): SignInSetup {
  const raw = asObject(value);
  const urls = asObject(raw.callback_urls);
  return {
    status: (str(raw.status) ?? "off") as SignInSetup["status"],
    providers: strings(raw.providers),
    managedProviders: strings(raw.managed_providers),
    usersTable: str(raw.users_table),
    tables: strings(raw.tables),
    database: str(raw.database),
    library: str(raw.library) ?? "",
    version: str(raw.version),
    updateAvailable: str(raw.update_available),
    commit: str(raw.commit),
    branch: str(raw.branch),
    editedFiles: strings(raw.edited_files),
    callbackUrls: Object.fromEntries(Object.entries(urls).map(([provider, url]) => [provider, String(url)])),
    missingSecrets: strings(raw.missing_secrets),
    secrets: strings(raw.secrets),
    error: raw.error && typeof raw.error === "object" ? asObject(raw.error) : null,
    raw,
  };
}

registerResult("project.sign_in.enable", toSignInSetup);
registerResult("project.sign_in.upgrade", toSignInSetup);

export interface SignInEnableOptions {
  /**
   * Of `google` and `microsoft`, those that sign in with your own client at the provider, to show your own
   * name on its screen (set its id and secret as the app's secrets: `missingSecrets`). The rest, and `apple`,
   * sign in through NoClick, with nothing to set up; `github` always uses your own client. Omitted, each
   * provider keeps how it signs in now.
   */
  ownCredentials?: readonly Exclude<SignInProvider, "email" | "apple">[];
  usersTable?: string;
  /** The binding of the database to keep users in; needed only when the app binds more than one. */
  database?: string;
  branch?: string;
  /**
   * `false`: set it up (its secrets and tables) and commit its code without deploying, so it goes live with the
   * branch's next deploy, beside changes of your own.
   */
  deploy?: boolean;
}

/**
 * `app.signIn`: accounts for the app's own users. Enabling it
 * commits sign-in code into the app's repo and keeps the users in the app's bound database.
 */
export class ProjectSignIn extends ProjectService {
  protected readonly service = "sign_in";

  /**
   * Commit sign-in for `providers` to `branch` (the default branch unless given), create
   * `usersTable` (`users`) and the tables it needs in the bound database and deploy; `nextjs`,
   * `remix` and `astro` apps, and a `static` site as it is, with a worker in front of its files
   * (`NotAvailable` for client-only `vite`, or a site already running its own worker). `google`,
   * `apple` and `microsoft` sign in through NoClick with nothing to set up (`google` and `microsoft`
   * on your own client when named in `ownCredentials`); `github` uses your own client. A file holding
   * edits of yours is never overwritten: the change goes on a branch of its own. `deploy: false` commits
   * it without deploying. `wait()` gives the `SignInSetup`.
   *
   * ```ts
   * await (await app.signIn.enable(["email"], { deploy: false })).wait();
   * await app.repo!.commit({ "app/routes/_index.tsx": page }, { message: "Show who's signed in" });
   * await (await app.deploy()).wait();
   * ```
   */
  async enable(providers: readonly SignInProvider[], options: SignInEnableOptions = {}): Promise<Operation<SignInSetup>> {
    const payload = await this._call("POST", [], {
      json: compact({
        providers: [...providers], own_credentials: options.ownCredentials ? [...options.ownCredentials] : undefined,
        users_table: options.usersTable ?? "users", database: options.database, branch: options.branch,
        deploy: options.deploy === false ? false : undefined,
      }),
    });
    return Operation._fromPayload<SignInSetup>(payload, {
      client: this._project._client, user: this._project._callScope(), kind: "project.sign_in.enable", reader: toSignInSetup,
    });
  }

  /**
   * Move the sign-in code to the library version NoClick ships now (`updateAvailable`), with the
   * same providers and the same care for edited files (`deploy: false` commits it without deploying,
   * as `enable` takes it). `wait()` gives the `SignInSetup`.
   */
  async upgrade(options: { branch?: string; deploy?: boolean } = {}): Promise<Operation<SignInSetup>> {
    const payload = await this._call("POST", ["upgrade"], {
      json: compact({ branch: options.branch, deploy: options.deploy === false ? false : undefined }),
    });
    return Operation._fromPayload<SignInSetup>(payload, {
      client: this._project._client, user: this._project._callScope(), kind: "project.sign_in.upgrade", reader: toSignInSetup,
    });
  }

  /** The app's sign-in: its providers, where its users are kept and what it still needs (`off` if never enabled). */
  async status(): Promise<SignInSetup> {
    return toSignInSetup(await this._call("GET", []));
  }
}
