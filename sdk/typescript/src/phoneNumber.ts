/**
 * Phone numbers: a real number your agents answer and call from.
 *
 *     const [pick] = await PhoneNumber.available({ country: "US", areaCode: "415", limit: 1 });
 *     const number = await PhoneNumber.buy(pick, { maxMonthlyUsd: 5 });
 *     await number.answerWith(host);                     // inbound calls reach this agent
 *     const call = await (await number.call("+14155550100", { goal: "Confirm Friday's 3pm booking." })).wait();
 *     console.log(call.text);                             // the transcript, one turn per line
 *
 * Numbers in the countries NoClick sells in (`PhoneNumber.coverage()`), each at its own price: billed
 * monthly, and once when bought where its carrier charges that; available on accounts with the phone
 * feature (`NotAvailable` otherwise). A number whose country asks for documents is bought with them
 * (`PhoneNumber.uploadDocument`, then `requirements` on `buy`): the carrier reviews them first, so `buy`
 * resolves to a `PhoneNumberOrder` that becomes the number once the carrier approves it. A number you keep
 * with your own phone provider is connected through that
 * provider account (`PhoneNumber.connect`), which bills it. Numbers have names (`PhoneNumber.fromName`).
 * The answering agent can transfer a call to a person, a caller proven to be one of your users runs as
 * that user, `callers` says who gets through, calls both ways are listed, and a number can record its
 * calls. Invite-only beta: the agent texting the caller (`answerWith(agent, { texts: true })`, under a
 * `TextingRegistration` of your business with the US carriers), porting numbers in (`PhoneNumber.portIn`)
 * and moving one away (`number.transferOut()`).
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { agentId } from "./agent.ts";
import type { Agent } from "./agent.ts";
import { Connection } from "./connection.ts";
import { Conflict, NotFound } from "./errors.ts";
import { Human } from "./human.ts";
import {
  ApiObject, asList, asObject, checkUnchanged, compact, defined, givesFields, isoTime, listAll, listPage, num, paginate, parseTime, refId,
  str, toBase64,
} from "./object.ts";
import type { CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult, withKinds } from "./operation.ts";
import type { KindScopedFilters } from "./operation.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption } from "./scope.ts";

/** A kind of number, as the carriers name them. */
export type PhoneNumberType = "local" | "mobile" | "toll_free" | "national" | "shared_cost";

/**
 * One thing a number's country asks before it's sold: the holder's `address` or `contact` information, an
 * answer in text (`textual`: one of `values` where it lists them; `example` is the carrier's), a `document`,
 * or a `step` that can't be taken here.
 */
export interface NumberRequirement {
  id: string;
  kind: "address" | "contact" | "textual" | "document" | "step";
  name: string;
  description: string;
  example: string;
  values: string[];
}

/**
 * What a number's country asks before it's sold: `none`, `address` (pass `address` to `buy`), `documents`
 * (pass `requirements` to `buy` too, uploading each document with `PhoneNumber.uploadDocument`; the carrier
 * reviews them before the number is yours) or `steps` (it can't be bought through the API yet).
 */
export interface NumberRequirements {
  needs: "none" | "address" | "documents" | "steps";
  items: NumberRequirement[];
}

/**
 * A document you uploaded for one of a number's requirements (`PhoneNumber.uploadDocument`): pass it, or its
 * `id`, in `requirements` when you buy. The carrier holds the file; NoClick keeps its name and what it's for.
 * One no purchase names within 25 minutes is gone; one a purchase named can be named again.
 */
export interface NumberDocument {
  id: string;
  requirementId: string;
  requirementName: string;
  filename: string;
  uploadedAt: Date | null;
  raw: JsonObject;
}

/**
 * A number you can buy: `PhoneNumber.buy(available, { maxMonthlyUsd })`. `monthlyUsd` it costs a month and
 * `upfrontUsd` once, when it's bought. `texting`: `registration` (a US local number, which texts under
 * your business's US carrier registration), `unavailable` (texting from its country, or from a toll-free
 * number, isn't available yet) or `none` (it can't text).
 */
export interface AvailableNumber {
  number: string;
  country: string;
  type: PhoneNumberType;
  monthlyUsd: number | null;
  upfrontUsd: number | null;
  locality: string | null;
  region: string | null;
  capabilities: string[];
  requirements: NumberRequirements;
  texting: "registration" | "unavailable" | "none";
  raw: JsonObject;
}

/** Who a number is registered to, for a country that asks who holds it (a requirement's `kind` is `address` or
 *  `contact`). */
export interface NumberHolder {
  /** First and last name. */
  name: string;
  businessName?: string;
  street: string;
  street2?: string;
  city: string;
  /** State, province or county, where the country has one. */
  region?: string;
  postalCode: string;
  /** ISO alpha-2. */
  country: string;
  /** A number to contact them on, in E.164; required where one of the requirements' `kind` is `contact`. */
  phone?: string;
}

/** A country numbers are for sale in, the kinds in stock there, the kinds that can text, the kinds bought with
 *  documents the carrier reviews first (`documentsTypes`) and the kinds that ask a step that can't be taken here
 *  (`stepsTypes`: these can't be bought through the API yet). */
export interface NumberCoverage {
  country: string;
  types: PhoneNumberType[];
  textingTypes: PhoneNumberType[];
  documentsTypes: PhoneNumberType[];
  stepsTypes: PhoneNumberType[];
}

/** A place numbers of a kind are for sale in: a city, or an area code in North America. */
export interface NumberPlace {
  kind: "locality" | "area_code";
  value: string;
  region: string;
}

/**
 * Where a number came from: `bought` through NoClick or `connected` (kept with your own phone provider
 * account, which bills it); `ported` (moved to NoClick from its carrier) is in invite-only beta.
 */
export type PhoneNumberSource = "bought" | "connected" | "ported";

/**
 * A number in your phone provider account, from `PhoneNumber.connectable`: connect it with
 * `PhoneNumber.connect(connectable, { connection })`.
 */
export interface ConnectableNumber {
  number: string;
  /** The provider account's own name for it. */
  label: string | null;
  /** Its calls go somewhere today (a URL, an application, a SIP trunk): answering it takes them over, and `disconnect()` puts that back. */
  routedElsewhere: boolean;
  /** The NoClick number it's already connected as (null when it isn't); connecting it again throws `Conflict`. */
  phoneNumberId: string | null;
  /** The agent answering it, when it's already connected (null otherwise). */
  agentId: string | null;
  raw: JsonObject;
}

/** Invite-only beta. A US address: a carrier account's service address, or a business's for its `TextingRegistration`. */
export interface StreetAddress {
  street: string;
  street2?: string;
  city: string;
  /** The state, like `CA`. */
  region: string;
  postalCode: string;
}

/**
 * Invite-only beta. How the current carrier knows the numbers' account, as its bill shows it,
 * for `PhoneNumber.portIn`.
 */
export interface PortDetails {
  /** The person authorized on the account, who signs the letter of authorization on a NoClick page: a `Human` with an email, or the email. */
  accountHolder: Human | string;
  /** The name on the account, often a business, not the signer. */
  accountName: string;
  serviceAddress: StreetAddress;
  accountNumber: string;
  /** The account's main number (the first number when omitted). */
  billingNumber?: string;
  /** The account's PIN, or a mobile account's transfer PIN, where the carrier has one. */
  pin?: string;
  /** A recent bill from the current carrier (PDF bytes), which some carriers ask for. */
  bill?: Uint8Array;
  /** When you'd like them to move; the carrier sets the dates, a few business days out at the earliest, and refuses one it doesn't allow. */
  requestedAt?: Date | string;
  /**
   * The account's numbers that stay with the carrier, when not all of them move; left out, every number on the
   * account moves. When the billing number moves, the first of them becomes the account's billing number.
   */
  remainingNumbers?: string[];
}

export interface PortInOptions extends CallOptions, PortDetails {
  /** The most each may cost a month once it's yours, in US dollars; above it `PriceExceeded`, and nothing is sent. */
  maxMonthlyUsd: number;
  /** What your code calls the number, when you port one. */
  name?: string;
}

/** Invite-only beta. One number on a port's letter of authorization: a carrier can move them on different days. */
export interface PortRequestNumber {
  number: string;
  /** `draft`, `submitted`, `scheduled`, `rejected` or `ported`. */
  status: string | null;
  portAt: Date | null;
}

/**
 * Invite-only beta. A text a number's agent sent a caller (`direction` `outbound`) or one the
 * number received (`inbound`).
 */
export interface PhoneText {
  id: string | null;
  direction: string | null;
  fromNumber: string | null;
  to: string | null;
  text: string | null;
  /**
   * `stop`, `start` or `help` when a received text was one: STOP stops texts to its sender, START
   * lets them through again, and both are answered in your business's name.
   */
  keyword: string | null;
  /** `sent`, then `delivered` or `failed`, for one sent; `received` for one received. */
  status: string | null;
  segments: number | null;
  /** What it was charged: its segments, and the other person's network fee once it's reported (a network may charge to send a text, to receive one, or both). */
  costUsd: number | null;
  callId: string | null;
  error: string | null;
  createdAt: Date | null;
  raw: JsonObject;
}

/**
 * Invite-only beta. What the carrier you're moving a number to asks for, from
 * `number.transferOut()`: the account the number is on (its name, its account and billing numbers, which are
 * the number itself, and its service address) and a transfer `pin` for this number, good until `expiresAt`.
 * Until then another carrier may take the number; after it, a request is refused. Printing it never shows the
 * PIN.
 */
export class TransferOut {
  readonly phoneNumberId: string | null;
  readonly number: string | null;
  readonly accountName: string | null;
  readonly accountNumber: string | null;
  readonly billingNumber: string | null;
  readonly pin: string | null;
  readonly serviceAddress: string | null;
  readonly expiresAt: Date | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.phoneNumberId = str(raw.phone_number_id);
    this.number = str(raw.number);
    this.accountName = str(raw.account_name);
    this.accountNumber = str(raw.account_number);
    this.billingNumber = str(raw.billing_number);
    this.pin = str(raw.pin);
    this.serviceAddress = str(raw.service_address);
    this.expiresAt = parseTime(raw.expires_at);
    this.raw = raw;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return `TransferOut { number: ${this.number}, accountName: ${this.accountName}, accountNumber: ${this.accountNumber}, expiresAt: ${this.expiresAt?.toISOString() ?? null} }`;
  }
}

export interface TranscriptTurn {
  /** `assistant` (the agent) or `user` (the other party). */
  role: string;
  text: string;
  /** Seconds into the call. */
  at: number | null;
}

/** One line said on a call, as a person reads its turns: the other party (`them`) or the agent's voice (`agent`). */
export interface CallLine {
  /** The turn it was said in, counted from the call's start. */
  turn: number;
  who: "them" | "agent";
  text: string;
}

/**
 * One call on a number, answered (`direction` `inbound`) or placed (`outbound`). `transcript` is filled
 * in at hang-up; `text` reads it as lines. `PhoneNumber.getCall` reads one while it goes, with what was
 * said so far (`lines`).
 */
export interface PhoneCall {
  id: string | null;
  direction: string | null;
  to: string | null;
  fromNumber: string | null;
  /** `calling` while it runs; ends `completed`, `not_connected`, `refused` (turned away by `callers`), `failed` or `lost`. */
  status: string | null;
  goal: string | null;
  agentId: string | null;
  transcript: TranscriptTurn[];
  /** The transcript as `role: text` lines. */
  text: string;
  seconds: number | null;
  /** What the call was charged, as your usage shows it (null until it has ended and its charge is recorded, or
   * when it never connected). */
  costUsd: number | null;
  error: string | null;
  createdAt: Date | null;
  endedAt: Date | null;
  /**
   * The user the call ran as: on an account number, a caller proven to be one of your users (their
   * verified phone, attested by the carrier), whatever the number's `callers`; on a user's number, its user.
   */
  userId: string | null;
  /**
   * A signed link to the recording (both sides, one file), valid for an hour from when you read the
   * call; null unless the number records its calls, or once the recording is deleted.
   */
  recordingUrl: string | null;
  /** Where the agent handed the caller (`to`) and whether they picked up (`status`, `seconds`); null if nobody was. */
  transfer: { to: string; status: string; seconds?: number } | null;
  /** When the call reached the agent's voice: a placed call's person picked up (null while it rings, and for a call nobody answered). */
  answeredAt: Date | null;
  /** `hang_up` when `PhoneNumber.hangUp` ended it; null when the other end, the agent or the call's limit did, and while it goes. */
  endedBy: "hang_up" | null;
  /** What was said so far, turn by turn, as `PhoneNumber.getCall` reads a call while it goes; empty in a number's `calls()`. */
  lines: CallLine[];
  raw: JsonObject;
}

/**
 * Who gets through to a number: every caller, only your users, or only its owner (the number's own
 * user, or your account's owner), each a verified phone the carrier attests. It never changes who a
 * call runs as.
 */
export type PhoneCallers = "anyone" | "users" | "owner";

export interface AnswerWithOptions {
  /**
   * Gives the agent a `transfer_call` tool that hands the caller to this number (E.164) or `Human`
   * with a `phone`, once the agent has said so; who picks up hears why first, and a transfer nobody
   * picks up comes back to the agent, which is told.
   */
  transferTo?: string | Human;
  /**
   * Invite-only beta. Gives the agent a `send_text` tool that texts the caller, and only the
   * caller (a link, a confirmation, an address), after asking and hearing a yes. Each text is signed
   * with your brand (`Harbor Dental: ...`), the first to a caller says how to opt out, and a caller who
   * texted STOP is never texted again. Texting from a US local number needs your business registered
   * with the US carriers (`TextingRegistration`); until that's approved this throws `ActionRequired`
   * naming it, and a number that can't text (one kept with your own phone provider, a toll-free one)
   * throws `NotAvailable`. Until texting ships it throws `NotAvailable`.
   */
  texts?: boolean;
  /**
   * Who gets through: `anyone` (the default), `users` (only a caller whose
   * number is a user's verified phone, attested by the carrier) or `owner` (only the number's own
   * user, or your account's owner). On an account number such a user's call runs as them under every
   * setting; a user's own number runs every call as that user.
   */
  callers?: PhoneCallers;
  /**
   * The agent's conversation each call lands in, a template over `{caller}` and `{number}`:
   * `"owner"` puts every call in the same conversation as `agent.message(..., { conversation: "owner" })`.
   * Omitted, each caller has a conversation of their own on the number.
   */
  conversation?: string;
}

function toAvailable(raw: JsonObject): AvailableNumber {
  const requirements = asObject(raw.requirements) as unknown as NumberRequirements;
  return {
    number: String(raw.number), country: String(raw.country), type: raw.type as PhoneNumberType,
    monthlyUsd: num(raw.monthly_usd), upfrontUsd: num(raw.upfront_usd), locality: str(raw.locality),
    region: str(raw.region), capabilities: (raw.capabilities as string[] | undefined) ?? [], requirements,
    texting: raw.texting as AvailableNumber["texting"], raw,
  };
}

/** What `PhoneNumber.buy` takes beside the number. A purchase that files nothing (no `address`, no
 *  `requirements`) resolves to the number; one that files something may resolve to its order instead. */
export type PhoneNumberBuyOptions = CallOptions & {
  maxMonthlyUsd: number; maxUpfrontUsd?: number; country?: string; type?: PhoneNumberType;
  address?: NumberHolder; requirements?: Record<string, string | NumberDocument>; name?: string;
};

function toDocument(raw: JsonObject): NumberDocument {
  return {
    id: String(raw.id), requirementId: String(raw.requirement_id), requirementName: String(raw.requirement_name),
    filename: String(raw.filename), uploadedAt: parseTime(raw.uploaded_at), raw,
  };
}

/** `requirements` on the wire: each answer's text, or a document's id. */
function requirementsWire(requirements: Record<string, string | NumberDocument> | undefined): JsonObject | undefined {
  if (!requirements) return undefined;
  return Object.fromEntries(Object.entries(requirements).map(([key, value]) => [key, typeof value === "string" ? value : value.id]));
}

async function documentBytes(file: Uint8Array | ArrayBuffer | Blob): Promise<Uint8Array> {
  if (file instanceof Uint8Array) return file;
  if (file instanceof ArrayBuffer) return new Uint8Array(file);
  return new Uint8Array(await file.arrayBuffer());
}

function numberHolderWire(holder: NumberHolder): JsonObject {
  return compact({
    name: holder.name, business_name: holder.businessName, street: holder.street, street2: holder.street2,
    city: holder.city, region: holder.region, postal_code: holder.postalCode, country: holder.country,
    phone: holder.phone,
  });
}

function toConnectable(raw: JsonObject): ConnectableNumber {
  return {
    number: String(raw.number), label: str(raw.label), routedElsewhere: raw.routed_elsewhere === true,
    phoneNumberId: str(raw.phone_number_id), agentId: str(raw.agent_id), raw,
  };
}

/** `connection` on the wire: a name or id in the number's own scope, or a `Connection`'s id. */
/** A phone number's digits, so `+1 415-555-0123` and `+14155550123` compare equal. */
function digits(number: unknown): string {
  return String(number ?? "").replace(/\D/g, "");
}

async function connectionWire(connection: Connection | string): Promise<string> {
  if (typeof connection === "string") return connection;
  if (connection instanceof Connection) return String(await refId(connection));
  throw new TypeError(`connection is a Connection or its name, not ${JSON.stringify(connection)}`);
}

function addressWire(address: StreetAddress | undefined): JsonObject | undefined {
  if (address === undefined) return undefined;
  return compact({ street: address.street, street2: address.street2, city: address.city, region: address.region, postal_code: address.postalCode });
}

/** `accountHolder` on the wire: the signer's email. */
function holderWire(holder: Human | string | undefined): string | undefined {
  if (holder === undefined || typeof holder === "string") return holder;
  if (!(holder instanceof Human)) throw new TypeError(`accountHolder is a Human or an email, not ${JSON.stringify(holder)}`);
  const email = str(holder._address.email);
  if (!email) throw new TypeError('accountHolder takes a Human with an email, like new Human({ email: "dana@co.test" })');
  return email;
}

/** The port details on the wire; `undefined` fields are left out (a retry keeps what it had). */
function portWire(details: Partial<PortDetails>): JsonObject {
  return compact({
    account_holder: holderWire(details.accountHolder),
    account_name: details.accountName,
    service_address: addressWire(details.serviceAddress),
    account_number: details.accountNumber,
    billing_number: details.billingNumber,
    pin: details.pin,
    bill: details.bill === undefined ? undefined : toBase64(details.bill),
    requested_at: isoTime(details.requestedAt),
    remaining_numbers: details.remainingNumbers === undefined ? undefined : [...details.remainingNumbers],
  });
}

function toText(raw: JsonObject): PhoneText {
  return {
    id: str(raw.id),
    direction: str(raw.direction),
    fromNumber: str(raw.from),
    to: str(raw.to),
    text: str(raw.text),
    keyword: str(raw.keyword),
    status: str(raw.status),
    segments: num(raw.segments),
    costUsd: num(raw.cost_usd),
    callId: str(raw.call_id),
    error: str(raw.error),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

function toCall(value: unknown): PhoneCall {
  const raw = asObject(value);
  const transcript = (Array.isArray(raw.transcript) ? (raw.transcript as JsonObject[]) : []).map((turn) => ({
    role: str(turn.role) ?? "", text: str(turn.text) ?? "", at: num(turn.at),
  }));
  return {
    id: str(raw.id),
    direction: str(raw.direction),
    to: str(raw.to),
    fromNumber: str(raw.from),
    status: str(raw.status),
    goal: str(raw.goal),
    agentId: str(raw.agent_id),
    transcript,
    text: transcript.map((turn) => `${turn.role}: ${turn.text}`).join("\n"),
    seconds: num(raw.seconds),
    costUsd: num(raw.cost_usd),
    error: str(raw.error),
    createdAt: parseTime(raw.created_at),
    endedAt: parseTime(raw.ended_at),
    userId: str(raw.user_id),
    recordingUrl: str(raw.recording_url),
    transfer: raw.transfer ? (asObject(raw.transfer) as unknown as { to: string; status: string; seconds?: number }) : null,
    answeredAt: parseTime(raw.answered_at),
    endedBy: raw.ended_by === "hang_up" ? "hang_up" : null,
    lines: asList(raw.lines).map((line) => {
      const said = asObject(line);
      return { turn: num(said.turn) ?? 0, who: said.who === "them" ? "them" : "agent", text: str(said.text) ?? "" };
    }),
    raw,
  };
}

registerResult("phone.call", toCall);

/**
 * The call `call` names and how to reach it: an id, with `options`' client and user; or the operation
 * `number.call()` returned, with its own client and user unless `options` names them.
 */
async function callTarget(call: string | Operation<unknown>, options: CallOptions): Promise<{ id: string; api: NoClick; user: UserOption }> {
  if (typeof call === "string") return { id: call, api: resolveClient(options.client), user: resolveScope(options.user) };
  const raw = await call._ensure();
  const id = str(raw.call_id) ?? str(asObject(raw.result).id);
  if (!id) throw new TypeError(`Operation ${String(raw.id)} isn't a call: pass a call's id, or what number.call() returned.`);
  return {
    id,
    api: options.client ? resolveClient(options.client) : call._api,
    user: options.user !== undefined ? options.user : call._callScope(),
  };
}

/** A finished port settles with `{ phone_numbers: [<each number's view>] }`. */
function readNumbers(result: unknown, op: Operation<unknown>): PhoneNumber[] {
  return asList(asObject(result).phone_numbers).map((raw) => PhoneNumber._fromRaw(asObject(raw), { client: op._client, user: op._scope }));
}

registerResult("phone.port_in", readNumbers);

const PORT_KINDS = ["phone.port_in"] as const;

function phoneOf(target: string | Human): string {
  if (typeof target === "string") return target;
  const phone = str(target._address.phone);
  if (!phone) throw new TypeError('transferTo takes a Human with a phone, like new Human({ phone: "+14155550142" })');
  return phone;
}

/**
 * Invite-only beta. Numbers moving to NoClick from their carrier on one letter of
 * authorization: the operation `PhoneNumber.portIn` returns. It waits in `awaiting_human` until the
 * account holder signs the letter at `signUrl`, then runs (`step` `submitted`, then `scheduled` once
 * the carrier has given every number its date, `portAt` the latest) and resolves to the `PhoneNumber`s
 * (`source` `ported`) once they've moved. A rejection fails it with the carrier's reason:
 * `InvalidRequest` whose `field` names what didn't match its records (`account_name`,
 * `account_holder`, `service_address`, `account_number`, `billing_number`, `pin`, `numbers`,
 * `remaining_numbers`, `bill` or `requested_at`); `retry` sends corrected details. `cancel()` works until the carrier has committed to
 * a date. The numbers keep working with their carrier until they move.
 */
export class PortRequest extends Operation<PhoneNumber[]> {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromResponse(payload: unknown, init: { client?: NoClick; user?: UserOption }): PortRequest {
    const port = new PortRequest(Operation._init(payload, { ...init, kind: "phone.port_in" }));
    port._reader = readNumbers;
    return port;
  }

  /** A lazy reference to a port by operation id: resume it anywhere (`Operation.fromId` gives a plain operation). */
  static portFromId(operationId: string, options: CallOptions = {}): PortRequest {
    return PortRequest._fromResponse(operationId, { client: options.client, user: options.user });
  }

  /** Port requests (kind `phone.port_in`), newest first; takes `Operation.list`'s filters except `kind`. */
  static override async list(options: KindScopedFilters & { limit?: number } = {}): Promise<PortRequest[]> {
    const ops = await Operation.list(withKinds(options, PORT_KINDS, "PortRequest.list"));
    return ops.map((op) => PortRequest._fromResponse(op.raw, { client: options.client, user: op._scope }));
  }

  /** One page of port requests; pass `nextCursor` back as `cursor`. */
  static override async listPage(options: KindScopedFilters & PageOptions = {}): Promise<Page<PortRequest>> {
    const page = await Operation.listPage(withKinds(options, PORT_KINDS, "PortRequest.listPage"));
    return { data: page.data.map((op) => PortRequest._fromResponse(op.raw, { client: options.client, user: op._scope })), nextCursor: page.nextCursor };
  }

  /** The first number on the letter, in E.164 form. */
  get number(): string | null {
    return str(this._known("number"));
  }
  /** Each number on the letter, with its own `status` and `portAt`: a carrier can move them on different days. */
  get numbers(): PortRequestNumber[] {
    return asList(this._known("numbers")).map((value) => {
      const row = asObject(value);
      return { number: String(row.number), status: str(row.status), portAt: parseTime(row.port_at) };
    });
  }
  /** While `awaiting_human`: the page where the account holder signs (it's emailed to them too). */
  get signUrl(): string | null {
    return this._known("status") === "awaiting_human" ? str(this._known("sign_url")) : null;
  }
  /** When the last number moves, once every one is `scheduled`. */
  get portAt(): Date | null {
    return parseTime(this._known("port_at"));
  }
  /** What each number costs a month once it's yours, in US dollars. */
  get monthlyUsd(): number | null {
    return num(this._known("monthly_usd"));
  }

  /**
   * Send a port the carrier refused again with corrected details, for the numbers that haven't moved; a
   * detail you leave out keeps what it had. A change to what the letter says (the account holder, the
   * account's name, the service address, the account or billing number), or a refusal of the name it
   * was signed with, asks the account holder to sign again; a new `pin`, `bill`, `requestedAt` or
   * `remainingNumbers` goes straight back. Resolves to a new `PortRequest` for the same numbers.
   */
  async retry(corrections: Partial<PortDetails> = {}): Promise<PortRequest> {
    const payload = await this._request("POST", `/v1/phone_numbers/port_in/${this._id()}/retry`, { json: portWire(corrections) });
    return PortRequest._fromResponse(payload, { client: this._client, user: this._callScope() });
  }
}

/** Invite-only beta. The person the carriers' registry contacts: your business's own, never NoClick's. */
export interface TextingContact {
  name: string;
  email: string;
  phone: string;
}

/** Invite-only beta. What `TextingRegistration.create` takes; `update` takes any of them. */
export interface TextingRegistrationDetails {
  /** The legal entity as its tax records name it. */
  legalName: string;
  entityType: "private_company" | "public_company" | "nonprofit" | "government" | "sole_proprietor";
  /** One of the registry's (`healthcare`, `retail`, `professional`, ...). */
  industry: string;
  /** Its US address. */
  address: StreetAddress;
  /** `website`, `privacyUrl` and `termsUrl` are pages anyone can open; the privacy policy must say phone numbers aren't shared. */
  website: string;
  contact: TextingContact;
  privacyUrl: string;
  termsUrl: string;
  /** Refused (`PriceExceeded`, nothing registered) above this once, in US dollars. */
  maxSetupUsd: number;
  /** Refused (`PriceExceeded`, nothing registered) above this a month, in US dollars. */
  maxMonthlyUsd: number;
  /** Its EIN (none for a sole proprietor). */
  taxId?: string;
  /** What texts are signed with (the legal name when omitted). */
  brandName?: string;
  /** A public company's listing. */
  stock?: { symbol: string; exchange: string };
}

function registrationWire(details: Partial<TextingRegistrationDetails>): JsonObject {
  return compact({
    legal_name: details.legalName,
    brand_name: details.brandName,
    entity_type: details.entityType,
    industry: details.industry,
    tax_id: details.taxId,
    address: addressWire(details.address),
    website: details.website,
    contact: details.contact,
    stock: details.stock,
    privacy_url: details.privacyUrl,
    terms_url: details.termsUrl,
    max_setup_usd: details.maxSetupUsd,
    max_monthly_usd: details.maxMonthlyUsd,
  });
}

/**
 * Invite-only beta. Your business registered with the US carriers, which texting from a US
 * number needs: the brand the carriers' registry verifies, and the campaign NoClick writes for it (a
 * voice agent texting a caller one thing they asked for, after a spoken yes). One per scope: your
 * account's, or one of your users' (a user's own number texts under its user's registration when there
 * is one, else the account's). Review takes days to weeks; `status` follows it: `pending`,
 * `awaiting_human` (its contact must answer the registry: a public company's verification email, or a
 * sole proprietor's texted code, sent back with `verify`), `in_review`, then `approved`, `rejected`
 * (`statusReason`, and `fields` names the facts to correct with `update`) or `suspended`. `delete()`
 * stops texting and its monthly fee.
 */
export class TextingRegistration extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Register the business with the US carriers, as the legal entity on its tax records. Resolves to the
   * registration, `pending`; its brand's fee is charged now. A scope that has one throws `Conflict` with
   * its `existingId`.
   */
  static async create(options: TextingRegistrationDetails & CallOptions): Promise<TextingRegistration> {
    const scope = resolveScope(options.user);
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/texting_registrations", {
      json: registrationWire(options),
      user: scope,
    });
    return new TextingRegistration({ raw, client: options.client, user: scope });
  }

  static fromId(registrationId: string, options: CallOptions = {}): TextingRegistration {
    return new TextingRegistration({ hints: { id: registrationId }, client: options.client, user: options.user });
  }

  /** Load a registration by id now; an unknown or deleted one throws `NotFound`. */
  static async get(registrationId: string, options: CallOptions = {}): Promise<TextingRegistration> {
    return await TextingRegistration.fromId(registrationId, options).hydrate();
  }

  /** The registrations of the current user (or, without one, the account's), or those `userFilter` covers, newest first. */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<TextingRegistration[]> {
    return await listAll({ ...options, path: "/v1/texting_registrations" }, (raw, user) => new TextingRegistration({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  /** `pending`, `awaiting_human`, `in_review`, `approved`, `rejected` or `suspended`. */
  get status(): string | null {
    return this._field("status");
  }
  /** The reviewer's words, when it refused or suspended it. */
  get statusReason(): string | null {
    return this._field("status_reason");
  }
  /** The facts a refusal named, to correct with `update`. */
  get fields(): string[] {
    return asList(this._field("fields")).map(String);
  }
  get legalName(): string | null {
    return this._field("legal_name");
  }
  /** What its texts are signed with: `Harbor Dental: ...`. */
  get brandName(): string | null {
    return this._field("brand_name");
  }
  get entityType(): string | null {
    return this._field("entity_type");
  }
  get industry(): string | null {
    return this._field("industry");
  }
  get website(): string | null {
    return this._field("website");
  }
  /** The EIN, its last four digits shown. */
  get taxId(): string | null {
    return this._field("tax_id");
  }
  get privacyUrl(): string | null {
    return this._field("privacy_url");
  }
  get termsUrl(): string | null {
    return this._field("terms_url");
  }
  /** Charged once, as the registry charges it: the brand when registered, the campaign's review and first months when it opens. */
  get setupUsd(): number | null {
    return this._field("setup_usd");
  }
  /** The campaign's monthly fee, after its first months. */
  get monthlyUsd(): number | null {
    return this._field("monthly_usd");
  }
  /** What a text costs a segment (160 characters), sent or received, before the other person's network fee, which is charged as reported. */
  get segmentUsd(): number | null {
    return this._field("segment_usd");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get approvedAt(): Date | null {
    return parseTime(this._field("approved_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  private get path(): string {
    return `/v1/texting_registrations/${this._known("id")}`;
  }

  protected async _load(): Promise<JsonObject> {
    return await this._request<JsonObject>("GET", this.path);
  }

  /**
   * Resubmit a refused registration (or one waiting on its contact) with corrected facts; a fact you
   * leave out keeps what it had. A corrected `privacyUrl` or `termsUrl` opens a new campaign, whose
   * review and first months are charged again. Resolves to this registration, back in review.
   */
  async update(corrections: Partial<TextingRegistrationDetails>): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", this.path, { json: registrationWire(corrections) });
    return this;
  }

  /** A sole proprietor's contact sends back the code the registry texted them (`InvalidRequest` naming `code` when it's wrong or expired). */
  async verify(code: string): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `${this.path}/verify`, { json: { code } });
    return this;
  }

  /** Stop texting under it: its numbers stop texting, its campaign closes and its monthly fee ends. */
  async delete(): Promise<void> {
    await this._request("DELETE", this.path);
  }
}

/** A number you own. `release()` gives it back (billing stops). */
export class PhoneNumber extends ApiObject {
  private _createWith: JsonObject | null = null;
  /** Set when `fromName` connects the number rather than buying one. */
  private _connectVia: Connection | string | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal From a number's view another call returned (a finished port). */
  static _fromRaw(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): PhoneNumber {
    return new PhoneNumber({ raw, client: init.client, user: init.user });
  }

  /**
   * Numbers for sale in `country` (`US` by default) of `type` (`local` by default), narrowed by `areaCode`,
   * `locality` (a city), `region`, `contains` (digits, letters or `*` wildcards), `startsWith` and `endsWith`
   * (digits of the national number), and `features` (`voice`, or `voice_sms` for numbers that take texts
   * too). Each comes with its prices and what its country asks before it's sold.
   */
  static async available(
    options: CallOptions & {
      country?: string; type?: PhoneNumberType; areaCode?: string | number; locality?: string; region?: string;
      contains?: string; startsWith?: string; endsWith?: string; features?: "voice" | "voice_sms"; limit?: number;
    } = {},
  ): Promise<AvailableNumber[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/phone_numbers/available", {
      query: {
        country: options.country, type: options.type, area_code: options.areaCode, locality: options.locality,
        region: options.region, contains: options.contains, starts_with: options.startsWith,
        ends_with: options.endsWith, features: options.features, limit: options.limit,
      },
      user: resolveScope(options.user),
    });
    return (asList(page) as JsonObject[]).map(toAvailable);
  }

  /** The countries numbers are for sale in, with the kinds of number sold in each. Right after a deploy, while that
   *  is still being found out, the API answers 503 with `Retry-After`, which the client retries on its own. */
  static async coverage(options: CallOptions = {}): Promise<NumberCoverage[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/phone_numbers/coverage", {
      user: resolveScope(options.user),
    });
    return (asList(page) as JsonObject[]).map((c) => ({
      country: String(c.country), types: c.types as PhoneNumberType[], textingTypes: c.texting_types as PhoneNumberType[],
      documentsTypes: (c.documents_types ?? []) as PhoneNumberType[], stepsTypes: (c.steps_types ?? []) as PhoneNumberType[],
    }));
  }

  /** Where in `country` numbers of `type` (`local` by default) are for sale: cities, or area codes in North America. */
  static async places(country: string, options: CallOptions & { type?: PhoneNumberType } = {}): Promise<NumberPlace[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/phone_numbers/places", {
      query: { country, type: options.type },
      user: resolveScope(options.user),
    });
    return (asList(page) as JsonObject[]).map((p) => ({
      kind: p.kind as NumberPlace["kind"], value: String(p.value), region: String(p.region ?? ""),
    }));
  }

  /**
   * Buy `number`; refused with `PriceExceeded` if it costs more than `maxMonthlyUsd` a month or
   * `maxUpfrontUsd` once (by default, the `upfrontUsd` an `AvailableNumber` showed; 0 for a number passed
   * as a string). A number whose country asks who holds it takes `address`, with a `phone` where a
   * requirement's `kind` is `contact`. One whose country asks for documents takes `requirements`: each
   * textual and document requirement's answer by its `id` (the text, or a `NumberDocument` from
   * `PhoneNumber.uploadDocument`); it resolves to a `PhoneNumberOrder` in the carrier's review (days,
   * sometimes), and nothing is charged until it completes. `name` is what your code calls it, unique among
   * its user's numbers (a taken one is a `Conflict` with `existingId`, before anything is bought).
   */
  static buy(number: string | AvailableNumber, options: PhoneNumberBuyOptions & { address?: undefined; requirements?: undefined }): Promise<PhoneNumber>;
  static buy(number: string | AvailableNumber, options: PhoneNumberBuyOptions): Promise<PhoneNumber | PhoneNumberOrder>;
  static async buy(number: string | AvailableNumber, options: PhoneNumberBuyOptions): Promise<PhoneNumber | PhoneNumberOrder> {
    const scope = resolveScope(options.user);
    const picked = typeof number === "string" ? null : number;
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/phone_numbers", {
      json: compact({
        number: picked ? picked.number : number, country: options.country ?? picked?.country,
        type: options.type ?? picked?.type, max_monthly_usd: options.maxMonthlyUsd,
        max_upfront_usd: options.maxUpfrontUsd ?? picked?.upfrontUsd ?? undefined,
        address: options.address ? numberHolderWire(options.address) : undefined,
        requirements: requirementsWire(options.requirements), name: options.name,
      }),
      user: scope,
    });
    if (raw.object === "phone_number_order") return PhoneNumberOrder._fromRaw(raw, { client: options.client, user: scope });
    return new PhoneNumber({ raw, client: options.client, user: scope });
  }

  /**
   * Upload a document one of a number's requirements asks for (a requirement of `kind` `document` in
   * `country`'s numbers of `type`, `local` by default): a PDF, PNG or JPEG up to 20 MB. `requirement` is the
   * requirement or its `id`. The carrier holds the file; NoClick keeps only its name and what it's for.
   * Pass the result in `requirements` when you buy.
   */
  static async uploadDocument(
    file: Uint8Array | ArrayBuffer | Blob,
    options: CallOptions & { requirement: string | NumberRequirement; country: string; type?: PhoneNumberType; filename: string },
  ): Promise<NumberDocument> {
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/phone_numbers/documents", {
      json: {
        country: options.country, type: options.type ?? "local",
        requirement_id: typeof options.requirement === "string" ? options.requirement : options.requirement.id,
        filename: options.filename, file: toBase64(await documentBytes(file)),
      },
      user: resolveScope(options.user),
    });
    return toDocument(raw);
  }

  /**
   * The numbers (up to 1,000) in your phone provider account that `connection` (a `Connection` or its
   * name, connected with the account's own credentials; one holding a restricted API key throws
   * `InvalidRequest` naming `connection`) can route, each with its `label`, whether its calls go
   * somewhere today and, when it's already connected to NoClick, its `phoneNumberId` and `agentId`.
   */
  static async connectable(connection: Connection | string, options: CallOptions = {}): Promise<ConnectableNumber[]> {
    const page = await resolveClient(options.client).request("GET", "/v1/phone_numbers/connectable", {
      query: { connection: await connectionWire(connection) },
      user: resolveScope(options.user),
    });
    return (asList(page) as JsonObject[]).map(toConnectable);
  }

  /**
   * Connect `number`, which you keep with your own phone provider, through `connection` (its account,
   * connected with the account's own credentials: NoClick checks the provider's signed calls with the
   * account's secret, which a restricted key can't). NoClick remembers where its calls go today and
   * leaves them there until `answerWith` routes them to an agent; `disconnect()` puts them back. The
   * provider bills the number and its minutes; NoClick bills only what it adds (the agent's time on a
   * call). Inside `asUser` it's the user's number on the user's connection. A number already connected,
   * or one another NoClick workflow answers, throws `Conflict`; one on a SIP trunk, `InvalidRequest`.
   */
  static async connect(
    number: string | ConnectableNumber,
    options: CallOptions & { connection: Connection | string; name?: string; recordCalls?: boolean },
  ): Promise<PhoneNumber> {
    const scope = resolveScope(options.user);
    const raw = await resolveClient(options.client).request<JsonObject>("POST", "/v1/phone_numbers/connect", {
      json: compact({
        number: typeof number === "string" ? number : number.number, connection: await connectionWire(options.connection),
        name: options.name, record_calls: options.recordCalls || undefined,
      }),
      user: scope,
    });
    return new PhoneNumber({ raw, client: options.client, user: scope });
  }

  /**
   * Invite-only beta. Port US local numbers in from their carrier, so they become NoClick
   * numbers: one, or several on one account at that carrier (one letter of authorization covers them).
   * `accountHolder` signs the letter on a NoClick page, branded like your other pages; the rest is how
   * the current carrier knows the account, as its bill shows it. Every number on the account moves unless
   * `remainingNumbers` names the ones that stay. Each number keeps working with its carrier until it moves
   * (moving it is free); then it's a NoClick number, billed monthly like a bought one
   * (`PriceExceeded`, nothing sent, above `maxMonthlyUsd`). A number you connected through your own
   * phone provider is disconnected first (`InvalidRequest` otherwise); for one kept with Twilio, the
   * account's name is "Twilio, Inc.", its number the last 8 characters of your Account SID, and the PIN
   * comes from Twilio's support. Resolves to a `PortRequest` whose `wait()` gives the `PhoneNumber`s.
   */
  static async portIn(numbers: string | string[], options: PortInOptions): Promise<PortRequest> {
    const scope = resolveScope(options.user);
    const payload = await resolveClient(options.client).request("POST", "/v1/phone_numbers/port_in", {
      json: compact({
        numbers: typeof numbers === "string" ? [numbers] : [...numbers],
        max_monthly_usd: options.maxMonthlyUsd,
        name: options.name,
        ...portWire(options),
      }),
      user: scope,
    });
    return PortRequest._fromResponse(payload, { client: options.client, user: scope });
  }

  /**
   * A lazy reference to the number called `name` for the current (or given) user. A `recordCalls` you
   * pass is set on it every run. With `createIfMissing`, the first time it's used with none of that name,
   * NoClick buys a US local number in `areaCode` (any US one when omitted) for at most `maxMonthlyUsd` a
   * month and `maxUpfrontUsd` once, and names it, or with `connect` connects that number of yours through
   * `connection` instead; without it, a missing number throws `NotFound`. `areaCode` and the prices say
   * how to buy one, so they matter only then. The number itself never changes: an existing
   * number other than `connect` throws `Conflict` naming it.
   */
  static fromName(
    name: string,
    options: CallOptions & {
      createIfMissing?: boolean;
      areaCode?: string | number;
      maxMonthlyUsd?: number;
      maxUpfrontUsd?: number;
      connect?: string;
      connection?: Connection | string;
      recordCalls?: boolean;
    } = {},
  ): PhoneNumber {
    const number = new PhoneNumber({ hints: { name }, client: options.client, user: options.user });
    number._creates = Boolean(options.createIfMissing);
    let definition: JsonObject;
    if (options.connect !== undefined) {
      if (number._creates && options.connection === undefined) throw new TypeError("PhoneNumber.fromName(..., { connect }) needs connection");
      if (options.areaCode !== undefined || options.maxMonthlyUsd !== undefined || options.maxUpfrontUsd !== undefined) {
        throw new TypeError("PhoneNumber.fromName takes connect (a number you keep) or areaCode and maxMonthlyUsd (one to buy), not both");
      }
      number._connectVia = options.connection ?? null;
      definition = compact({ name, number: options.connect, record_calls: options.recordCalls });
    } else {
      if (number._creates && options.maxMonthlyUsd === undefined) {
        throw new TypeError("PhoneNumber.fromName(..., { createIfMissing: true }) needs maxMonthlyUsd");
      }
      definition = compact({
        name,
        area_code: options.areaCode === undefined ? undefined : String(options.areaCode),
        max_monthly_usd: options.maxMonthlyUsd,
        max_upfront_usd: options.maxUpfrontUsd,
        record_calls: options.recordCalls,
      });
    }
    if (number._creates || givesFields(options)) number._createWith = definition;
    return number;
  }

  static fromId(numberId: string, options: CallOptions = {}): PhoneNumber {
    return new PhoneNumber({ hints: { id: numberId }, client: options.client, user: options.user });
  }

  static async get(numberId: string, options: CallOptions = {}): Promise<PhoneNumber> {
    return await PhoneNumber.fromId(numberId, options).hydrate();
  }

  /** The numbers you own (the current user's inside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<PhoneNumber[]> {
    return await listAll({ ...options, path: "/v1/phone_numbers" }, (raw, user) => new PhoneNumber({ raw, client: options.client, user }));
  }

  /** One page of numbers; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<PhoneNumber>> {
    return await listPage({ ...options, path: "/v1/phone_numbers" }, (raw, user) => new PhoneNumber({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  /** What your code calls it (null for one bought without a name). */
  get name(): string | null {
    return this._field("name");
  }
  /** The number in E.164 form. */
  get number(): string {
    return this._field("number");
  }
  /** Where it came from: `bought` or `connected` (`ported` is in invite-only beta). */
  get source(): PhoneNumberSource | null {
    return this._field("source") ?? null;
  }
  /** The phone provider connection a connected number runs through (its name; null otherwise). */
  get connection(): string | null {
    return this._field("connection") ?? null;
  }
  /** Where the answering agent's `transfer_call` tool sends a call (null: no such tool). */
  get transferTo(): string | null {
    return this._field("transfer_to");
  }
  /** Invite-only beta. Whether the answering agent can text the caller (`send_text`). */
  get texts(): boolean {
    return this._field("texts") === true;
  }
  /**
   * Invite-only beta. Whether the US carriers have taken the number onto your registration's campaign, so its
   * texts go out. Until then the agent has no `send_text`.
   */
  get textsReady(): boolean {
    return this._field("texts_ready") === true;
  }
  /** Invite-only beta. Why the carriers didn't take the number onto the campaign, when they refused it. */
  get textsError(): string | null {
    return this._field("texts_error");
  }
  /** Who gets through: `anyone`, `users` or `owner`. */
  get callers(): PhoneCallers | null {
    return this._field("callers");
  }
  /** Whether its calls, both ways, are recorded. */
  get recordCalls(): boolean {
    return this._field("record_calls") === true;
  }
  /** Whether `release()` gave the number back, or `disconnect()` handed it back to its provider account. */
  get released(): boolean {
    return this._known("deleted") === true;
  }
  /** The agent that answers inbound calls (null if none). */
  get agentId(): string | null {
    return this._field("agent_id");
  }
  /** What NoClick bills for it a month, in US dollars (null for a connected number, which its provider bills). */
  get monthlyUsd(): number | null {
    return this._field("monthly_usd");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  /** Its path once its id is known (a number reached by name loads first). */
  private async path(): Promise<string> {
    const id = this._known("id") ?? (await this._ensure()).id;
    return `/v1/phone_numbers/${id}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/phone_numbers/${id}`);
    const name = String(this._hints.name);
    const rows = (asList(await this._request("GET", "/v1/phone_numbers", { query: { name } })) as JsonObject[]).filter((row) => row.name === name);
    if (rows.length) return await this.converge(rows[0]);
    if (!this._createWith || !this._creates) {
      throw new NotFound(`No phone number is named "${name}".`, {
        nextStep: "Buy it with PhoneNumber.buy(..., { name }) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    const [path, json] = this._connectVia === null
      ? ["/v1/phone_numbers", this._createWith]
      : ["/v1/phone_numbers/connect", { ...this._createWith, connection: await connectionWire(this._connectVia) }];
    try {
      return await this._request<JsonObject>("POST", path, { json });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // made concurrently: adopt it
      return await this.converge(await this._request<JsonObject>("GET", `/v1/phone_numbers/${err.existingId}`));
    }
  }

  /** Set `recordCalls` on an existing number, once it's the number `connect` named. */
  private async converge(raw: JsonObject): Promise<JsonObject> {
    const connected = this._createWith?.number;
    if (connected !== undefined && digits(raw.number) !== digits(connected)) checkUnchanged("phone number", raw, { number: connected });
    const wanted = this._createWith?.record_calls;
    if (wanted === undefined || raw.record_calls === wanted) return raw;
    return await this._request<JsonObject>("PATCH", `/v1/phone_numbers/${raw.id}`, { json: { record_calls: wanted } });
  }

  override toString(): string {
    return str(this._known("number")) ?? `PhoneNumber(${this._known("id")})`;
  }

  /** Give the number back; it stops ringing and billing. A connected number throws `Conflict`: `disconnect()` it. */
  async release(): Promise<void> {
    const raw = asObject(await this._request("DELETE", await this.path()));
    this._raw = { ...(this._raw ?? this._hints), ...raw, deleted: true };
  }

  /**
   * Hand a connected number back to its provider account: NoClick takes it off its agent, puts back
   * where its calls went before, and it leaves your list. A bought number throws `Conflict`: `release()` it.
   */
  async disconnect(): Promise<void> {
    const raw = asObject(await this._request("POST", `${await this.path()}/disconnect`));
    this._raw = { ...(this._raw ?? this._hints), ...raw, deleted: true };
  }

  /**
   * Rename it (`name: null` removes its name; one another of its user's numbers has is a `Conflict`),
   * or start or stop recording its calls from the next call (both sides in one file; the caller hears
   * that the call is recorded before the agent speaks).
   */
  async update(changes: { name?: string | null; recordCalls?: boolean }): Promise<this> {
    this._raw = await this._request<JsonObject>("PATCH", await this.path(), {
      json: defined({ name: changes.name, record_calls: changes.recordCalls }),
    });
    return this;
  }

  /**
   * Route inbound calls to `agent`, an agent on the `sdk` harness, whose tools and connections work
   * during a call as in a message; one on a coding harness can't answer calls (`NotAvailable`). Calling it again replaces the whole setup: an option left out goes
   * back to its default.
   */
  async answerWith(agent: Agent | string, options: AnswerWithOptions = {}): Promise<this> {
    const callers = options.callers ?? "anyone";
    if (!["anyone", "users", "owner"].includes(callers)) throw new TypeError(`callers is "anyone", "users" or "owner", not ${JSON.stringify(callers)}`);
    const json: JsonObject = { agent_id: await agentId(agent) };
    if (options.transferTo !== undefined) json.transfer_to = phoneOf(options.transferTo);
    if (options.texts) json.texts = true;
    if (callers !== "anyone") json.callers = callers;
    if (options.conversation !== undefined) json.conversation = options.conversation;
    const raw = asObject(await this._request("POST", `${await this.path()}/answer`, { json }));
    if (raw.id) this._raw = raw;
    return this;
  }

  /**
   * Call `to` with the number's answering agent working toward `goal` (`agent`, if given, must
   * be that agent). `wait()` resolves to the `PhoneCall` with its transcript at hang-up.
   */
  async call(to: string, options: { goal: string; agent?: Agent | string }): Promise<Operation<PhoneCall>> {
    const payload = await this._request("POST", `${await this.path()}/calls`, {
      json: compact({ to, goal: options.goal, agent_id: await agentId(options.agent) }),
    });
    return Operation._fromPayload<PhoneCall>(payload, {
      client: this._client, user: this._callScope(), kind: "phone.call", reader: toCall,
    });
  }

  /**
   * One call as it stands, read live while it goes (`call` is its id, or the operation `number.call()` returned):
   * its `status`, when it was `answeredAt`, what was said so far turn by turn (`lines`), who ended it (`endedBy`)
   * and, once it has ended, its `transcript`. An unknown call throws `NotFound`.
   */
  static async getCall(call: string | Operation<unknown>, options: CallOptions = {}): Promise<PhoneCall> {
    const { id, api, user } = await callTarget(call, options);
    return toCall(await api.request("GET", `/v1/phone_numbers/calls/${id}`, { user }));
  }

  /**
   * Hang up a call the number placed, ringing or live: the agent says goodbye and the call ends (a ringing one is
   * cancelled). `call` is its id, or the operation `number.call()` returned. Resolves to the call as it stands; it
   * ends a moment later with `endedBy` `hang_up`, and its operation settles with the transcript as at any hang-up.
   * A call that already ended throws `Conflict`; one the number answered throws `NotAvailable`.
   */
  static async hangUp(call: string | Operation<unknown>, options: CallOptions = {}): Promise<PhoneCall> {
    const { id, api, user } = await callTarget(call, options);
    return toCall(await api.request("POST", `/v1/phone_numbers/calls/${id}/hang_up`, { user }));
  }

  /**
   * The calls on this number, newest first: the calls it answered with the ones it placed. `direction`
   * keeps one kind, `since` those that started at or after it, and `limit` the newest that many.
   */
  async calls(options: { direction?: "inbound" | "outbound"; since?: Date | string; limit?: number } = {}): Promise<PhoneCall[]> {
    const rows = await paginate(this._api, `${await this.path()}/calls`, {
      query: { direction: options.direction, since: isoTime(options.since) },
      user: this._callScope() ?? null,
      limit: options.limit,
    });
    return rows.map(toCall);
  }

  /**
   * Invite-only beta. The texts its answering agent sent callers (`send_text`) and the texts the
   * number received, newest first. A reply doesn't wake the agent: read it here, or take
   * `phone.text.received` events. `direction` keeps one kind, `since` those at or after it.
   */
  async textMessages(options: { direction?: "inbound" | "outbound"; since?: Date | string; limit?: number } = {}): Promise<PhoneText[]> {
    const rows = await paginate(this._api, `${await this.path()}/texts`, {
      query: { direction: options.direction, since: isoTime(options.since) },
      user: this._callScope() ?? null,
      limit: options.limit,
    });
    return rows.map(toText);
  }

  /**
   * Invite-only beta. Move the number to another carrier: what that carrier asks for (the account
   * it's on, whose account and billing numbers are the number itself, and a transfer PIN for it). Another carrier may take the number for 30 days from now; a
   * request outside that window, or quoting another PIN, is refused, so nobody takes it without you.
   * Once it moves, it leaves your numbers and its billing stops.
   */
  async transferOut(): Promise<TransferOut> {
    return new TransferOut(asObject(await this._request("POST", `${await this.path()}/transfer_out`)));
  }
}

/**
 * A number ordered while the carrier reviews the documents filed for it (`PhoneNumber.buy` of a number whose
 * country asks for them). Nothing is yours, or charged, until it completes: `status` is `in_review`,
 * `rejected` (the carrier sent it back: `reason` says why; `resubmit` corrections before `deadline`),
 * `completed` (`phoneNumber()` is the number) or `failed` (it ended without the number; nothing was charged).
 */
export class PhoneNumberOrder extends ApiObject {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal From the order a purchase returned. */
  static _fromRaw(raw: JsonObject, init: { client?: NoClick; user?: UserOption }): PhoneNumberOrder {
    return new PhoneNumberOrder({ raw, client: init.client, user: init.user });
  }

  /** Load an order by id now; an unknown id throws `NotFound`. */
  static async retrieve(orderId: string, options: CallOptions = {}): Promise<PhoneNumberOrder> {
    return await new PhoneNumberOrder({ hints: { id: orderId }, client: options.client, user: options.user }).hydrate();
  }

  get id(): string {
    return this._field("id");
  }
  /** The number ordered, in E.164 form. */
  get number(): string {
    return this._field("number");
  }
  get country(): string | null {
    return this._field("country");
  }
  get type(): PhoneNumberType | null {
    return this._field("type");
  }
  /** `in_review`, `rejected`, `completed` or `failed`. */
  get status(): "in_review" | "rejected" | "completed" | "failed" {
    return this._field("status");
  }
  /** The carrier's words when it sent the order back or ended it (null otherwise). */
  get reason(): string | null {
    return this._field("reason");
  }
  /** When a sent-back order must be corrected by. */
  get deadline(): Date | null {
    return parseTime(this._field("deadline"));
  }
  /** What the number costs a month, once it's yours. */
  get monthlyUsd(): number | null {
    return this._field("monthly_usd");
  }
  /** What it costs once, charged when the order completes. */
  get upfrontUsd(): number | null {
    return this._field("upfront_usd");
  }
  /** The number, once the order completed. */
  get phoneNumberId(): string | null {
    return this._field("phone_number_id");
  }
  /** While it's open: what its country asks, which a `resubmit` answers. */
  get requirements(): NumberRequirements | null {
    return this._field("requirements");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }

  protected async _load(): Promise<JsonObject> {
    return await this._request<JsonObject>("GET", `/v1/phone_numbers/orders/${this._known("id")}`);
  }

  override toString(): string {
    return str(this._known("number")) ?? `PhoneNumberOrder(${this._known("id")})`;
  }

  /**
   * File corrected answers for an order the carrier sent back (`status` `rejected`), for its review again:
   * `address` and `requirements` as `PhoneNumber.buy` takes them. Any other order throws `Conflict`.
   */
  async resubmit(options: { address?: NumberHolder; requirements?: Record<string, string | NumberDocument> } = {}): Promise<this> {
    this._raw = await this._request<JsonObject>("POST", `/v1/phone_numbers/orders/${this._known("id")}/resubmit`, {
      json: compact({
        address: options.address ? numberHolderWire(options.address) : undefined,
        requirements: requirementsWire(options.requirements),
      }),
    });
    return this;
  }

  /** The number, once the order completed; `Conflict` while it hasn't (`refresh()` first). */
  async phoneNumber(): Promise<PhoneNumber> {
    const raw = await this._ensure();
    if (typeof raw.phone_number_id !== "string") {
      throw new Conflict(`Order ${raw.id} is ${raw.status}: the number is yours once it completes.`, {
        nextStep: "Refresh the order, and read the number once its status is completed.",
        details: { status: raw.status },
      });
    }
    const number = await this._request<JsonObject>("GET", `/v1/phone_numbers/${raw.phone_number_id}`);
    return PhoneNumber._fromRaw(number, { client: this._client, user: this._scope });
  }
}
