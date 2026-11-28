/**
 * Signing in and out: a setup code, a sign-in from a browser, and what the key is. A key is never printed. The key is
 * kept in a file only you can read, where the Python CLI reads it too; this CLI keeps none in an OS keychain.
 */

import { hostname } from "node:os";

import { AgentSignup } from "../../agentSignup.ts";
import { CliLogin, accountStatus } from "../../cliLogin.ts";
import { API_KEY_ENV, API_URL_ENV, DEFAULT_BASE_URL, NoClick } from "../../client.ts";
import { Expired, PermissionDenied, Unauthenticated } from "../../errors.ts";
import { Key } from "../../key.ts";
import type { Values } from "../args.ts";
import { host } from "../host.ts";
import { OK } from "../exits.ts";
import { UsageError } from "../args.ts";
import { load } from "../spec.ts";
import type { KeyStore } from "../keychain.ts";
import { type Io, withRun } from "../output.ts";
import {
  CommandError, PROFILE_SOURCES, type Profile, type ProfileSource, chosenProfile, credentialsPath, fileStore, keyStore,
  readProfiles, resolveCredentials, setDefaultProfile, writeProfile,
} from "../store.ts";
import { answer, harnessOf, noteUnclaimed, on, profileOf, str } from "./kit.ts";

const CLIENT_NAME = "noclick-cli";

/** Where `--store` keeps the key (default `auto`), judged before anything is asked of the API or a person. */
function storeOf(values: Values): { name: string; store: KeyStore } {
  const name = str(values, "store") ?? "auto";
  return { name, store: keyStore(host.env, name) };
}

function apiUrlOf(): string {
  return (host.env[API_URL_ENV] || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

/** What login says when the OS keychain won't take the key, word for word as the Python CLI says it. */
export const KEYCHAIN_REFUSED = "The OS keychain refused the key, so it's kept in a file only you can read instead.";

interface Got { key: string; key_id?: string | null; key_name?: string | null; email?: string | null; claim_url?: string; said?: string }

/** Keep a key login, setup or signup got for the profile, in `store` (with `auto`, the file when the keychain
 *  refuses), and say where it went: as the Python CLI's `keep_key`. */
function keepKey(io: Io, values: Values, storeName: string, store: KeyStore, apiUrl: string, got: Got): void {
  const profile = profileOf(values);
  try {
    store.write(profile, got.key);
  } catch (err) {
    if (storeName !== "auto" || !(err instanceof CommandError)) throw err;
    io.err(KEYCHAIN_REFUSED); // the OS's own words differ by tool: the line is the same in both CLIs
    store = fileStore(host.env);
    store.write(profile, got.key);
  }
  writeProfile(host.env, profile, {
    api_url: apiUrl, store: store.name, key_id: got.key_id ?? null, key_name: got.key_name ?? null,
    key_prefix: got.key.slice(0, 12), email: got.email ?? null, ...(got.claim_url ? { claim_url: got.claim_url } : {}),
  });
  const where = store.name === "keychain" ? "the OS keychain" : `${credentialsPath(host.env)} (only you can read it)`;
  const said = got.said ?? `Signed in as ${got.email || "your account"}.`;
  if (said) io.out(said);
  io.err(`The key "${got.key_name ?? "None"}" is in ${where}. noclick logout revokes it.`);
  if (host.env[API_KEY_ENV]) io.err(`${API_KEY_ENV} is set in this shell, and wins over the stored key: unset it to use this one.`);
}

function anonymous(apiUrl: string): NoClick {
  return new NoClick({ baseUrl: apiUrl, fetch: host.fetch, apiKey: "" });
}

function signedInAs(account: { id?: string; name?: string; email?: string; acting_for?: { id: string; name?: string; email?: string } | null }): string {
  const user = account.acting_for;
  if (user) return `User ${user.id}${[user.name, user.email].some(Boolean) ? ` (${[user.name, user.email].filter(Boolean).join(", ")})` : ""}`;
  const known = [account.name, account.email].filter(Boolean).join(", ");
  return known ? `${known} (${account.id})` : String(account.id);
}

export async function setup(values: Values, io: Io): Promise<number> {
  const apiUrl = apiUrlOf();
  const { name, store } = storeOf(values);
  const key = await Key.redeemSetupCode(String(values.code), { client: anonymous(apiUrl) });
  keepKey(io, values, name, store, apiUrl, {
    key: key.secret!, key_id: key.id, key_name: key.name, email: (key.raw.email as string | undefined) ?? null,
  });
  io.err("Next: noclick init, or noclick deploy in your app's folder.");
  return OK;
}

/** An agent with no account makes one for itself: the key kept as `login` keeps it, the claim link printed last. */
export async function signup(values: Values, io: Io): Promise<number> {
  const words = load().manifest.screens.signup;
  if (!on(values, "accept_terms")) {
    throw new UsageError(`Signing up accepts NoClick's Developer Terms and Acceptable Use Policy: ${words.terms.join(" and ")}.`,
      "Read them, then run noclick signup --accept-terms.");
  }
  if (readProfiles(host.env)[profileOf(values)]?.store) {
    throw withRun(new CommandError(`The profile ${profileOf(values)} is signed in already: signing up would make another account.`, {
      nextStep: "noclick signup --profile <another> --accept-terms, or noclick logout first.",
    }), ["noclick signup --profile <another> --accept-terms", "noclick logout"]);
  }
  const { name: storeName, store } = storeOf(values);
  const apiUrl = apiUrlOf();
  const agent = str(values, "agent") ?? harnessOf();
  const made = await AgentSignup.signUp(agent, {
    acceptTerms: true, purpose: str(values, "purpose"), email: str(values, "email"), client: anonymous(apiUrl),
  });
  const { key, ...shown } = made;
  keepKey(io, values, storeName, store, apiUrl, {
    key: String(key), key_id: (made.key_id as string | undefined) ?? null, key_name: `Signed up by ${agent}`,
    claim_url: String(made.claim_url), said: on(values, "json") ? "" : `Signed up: a NoClick account for ${agent}, which a person claims.`,
  });
  const limits = (made.limits ?? {}) as { unclaimed_days?: number; until_claimed?: string[] };
  answer(io, values, shown, () => {
    io.err(words.works);
    io.err(`Waits for a person to claim it (within ${limits.unclaimed_days ?? 7} days):`);
    for (const held of limits.until_claimed ?? []) io.err(`  - ${held}`);
    io.err("Give your person this link to claim the account:");
    return [String(made.claim_url)];
  });
  return OK;
}

interface Pending {
  device_code: string;
  user_code: string;
  verification_url: string;
  /** The link with the code in it, which opens in a browser. */
  open_url?: string;
  expires_at: string | null;
  interval_s: number;
}

/** A sign-in from a browser. The link is printed first; a run cut short leaves it pending, and the next run picks
 *  the same one up rather than asking the person again. */
export async function login(values: Values, io: Io): Promise<number> {
  const { name: storeName, store } = storeOf(values); // a missing keychain is refused before the browser opens
  const apiUrl = apiUrlOf();
  const api = anonymous(apiUrl);
  const profiles = readProfiles(host.env) as Record<string, Profile & { pending_login?: Pending }>;
  const stored = profiles[profileOf(values)] ?? {};
  let pending = stored.pending_login;
  if (!pending || (pending.expires_at && Date.parse(pending.expires_at) <= Date.now())) {
    const start = await CliLogin.start({ name: CLIENT_NAME, hostname: hostname(), client: api });
    pending = {
      device_code: start.deviceCode, user_code: start.userCode, interval_s: start.intervalS,
      verification_url: start.verificationUrl, open_url: start.verificationUrlComplete ?? start.verificationUrl, expires_at: start.expiresAt,
    };
    writeProfile(host.env, profileOf(values), { ...stored, pending_login: pending } as Profile);
  }
  io.out(`Open ${pending.verification_url} and enter the code ${pending.user_code}`);
  if (!on(values, "no_browser") && host.stdinIsTty()) host.openUrl(pending.open_url ?? pending.verification_url);
  let interval = pending.interval_s;
  for (;;) {
    await host.sleep(interval * 1000);
    let poll;
    try {
      poll = await CliLogin.poll(pending.device_code, { client: api });
    } catch (err) {
      if (err instanceof Expired || err instanceof PermissionDenied) writeProfile(host.env, profileOf(values), { ...stored, pending_login: undefined } as Profile);
      throw err;
    }
    if (poll.status === "approved" && poll.key) {
      keepKey(io, values, storeName, store, apiUrl, { key: poll.key, key_id: poll.keyId, key_name: poll.keyName, email: poll.email });
      return OK;
    }
    interval = poll.intervalS ?? interval;
  }
}

export async function whoami(values: Values, io: Io): Promise<number> {
  const creds = resolveCredentials(host.env, profileOf(values));
  host.signIn(profileOf(values));
  if (creds.source === "env" && creds.login.store) {
    io.err(`${API_KEY_ENV} overrides the login stored for this profile (${creds.login.email ?? ""}).`);
  }
  // What login stored names its own key, not one NOCLICK_API_KEY holds: the API's word on the caller first, then that.
  const login = creds.source === "env" ? {} : creds.login;
  const masked = `${creds.key!.slice(0, 12)}…`;
  const keyRow = (name: string | null | undefined) => `Key      ${name ? `${name} (${masked})` : masked}, ${{ env: `from ${API_KEY_ENV}`, keychain: "in the OS keychain", file: "in a file", none: "in a file" }[creds.source]}`;
  const why = (str(values, "profile_source") ?? "default") as ProfileSource;
  const rows = [`Profile  ${creds.profile} (${PROFILE_SOURCES[why]})`, `API      ${creds.apiUrl}`];
  let status: Awaited<ReturnType<typeof accountStatus>>;
  try {
    status = await accountStatus();
  } catch (err) {
    if (!values.json) for (const line of [keyRow(login.key_name), ...rows]) io.out(line); // which key the API refused
    throw err;
  }
  const account = (status.account ?? {}) as Parameters<typeof signedInAs>[0];
  const caller = (status.caller ?? {}) as { key_id?: string | null; key_name?: string | null };
  const keyName = caller.key_name ?? login.key_name ?? null;
  answer(io, values, {
    profile: creds.profile, profile_source: why, source: creds.source, key_prefix: creds.key!.slice(0, 12), api_url: creds.apiUrl,
    email: login.email ?? null, key_name: keyName, key_id: caller.key_id ?? login.key_id ?? null, account,
  }, () => [account.acting_for ? `User     ${signedInAs(account).slice(5)}: the key acts for this user, not the account`
    : `Account  ${signedInAs(account)}`, keyRow(keyName), ...rows]);
  if (!values.json) await noteUnclaimed(values, io);
  return OK;
}

export async function logout(values: Values, io: Io): Promise<number> {
  const profile = profileOf(values);
  const login = readProfiles(host.env)[profile];
  if (!login) {
    io.err(host.env[API_KEY_ENV] ? `This shell uses ${API_KEY_ENV}, which logout can't clear: unset it.` : "You're not signed in.");
    return OK;
  }
  const store = keyStore(host.env, login.store ?? "file");
  const key = store.read(profile);
  if (key) { // revoke it first: a key that can't be revoked stays stored, so you can retry
    try {
      await Key.revokeCurrent({ client: new NoClick({ apiKey: key, baseUrl: login.api_url || DEFAULT_BASE_URL, fetch: host.fetch }) });
      io.err(`Revoked the key "${login.key_name || login.key_prefix || "None"}".`);
    } catch (err) {
      if (!(err instanceof Unauthenticated)) throw err;
      io.err("The key was already revoked.");
    }
  }
  store.delete(profile);
  writeProfile(host.env, profile, null);
  if (chosenProfile(host.env) === profile) setDefaultProfile(host.env, null);
  io.out("Signed out.");
  return OK;
}
