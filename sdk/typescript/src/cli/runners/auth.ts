/**
 * Signing in and out: a setup code, a sign-in from a browser, and what the key is. A key is never printed. The key is
 * kept in a file only you can read, where the Python CLI reads it too; this CLI keeps none in an OS keychain.
 */

import { hostname } from "node:os";

import { CliLogin, accountStatus } from "../../cliLogin.ts";
import { API_KEY_ENV, NoClick, defaultClient } from "../../client.ts";
import { Expired, PermissionDenied, Unauthenticated } from "../../errors.ts";
import { Key } from "../../key.ts";
import type { Values } from "../args.ts";
import { host } from "../host.ts";
import { OK } from "../exits.ts";
import type { Io } from "../output.ts";
import { CommandError, type Profile, readProfiles, resolveCredentials, storeKey, writeProfile } from "../store.ts";
import { answer, profileOf, str } from "./kit.ts";

const CLIENT_NAME = "noclick-cli";

/** `--store keychain` asks for what this CLI never does. */
function fileStore(values: Values): void {
  if (str(values, "store") === "keychain") {
    throw new CommandError("npx noclick keeps the key in a file only you can read, never in an OS keychain.", {
      nextStep: "noclick login --store file (or leave out --store); pip install noclick keeps one in the keychain.",
    });
  }
}

function apiUrlOf(values: Values): string {
  return resolveCredentials({ ...host.env, [API_KEY_ENV]: undefined }, profileOf(values)).apiUrl;
}

function keep(values: Values, key: string, profile: Profile): void {
  storeKey(host.env, profileOf(values), key);
  writeProfile(host.env, profileOf(values), { ...profile, store: "file", key_prefix: key.slice(0, 12) });
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
  fileStore(values);
  const apiUrl = apiUrlOf(values);
  const key = (await Key.redeemSetupCode(String(values.code), { client: anonymous(apiUrl) })).secret!;
  keep(values, key, { api_url: apiUrl });
  const status = await accountStatus({ client: new NoClick({ apiKey: key, baseUrl: apiUrl, fetch: host.fetch }) });
  const account = (status.account ?? {}) as Parameters<typeof signedInAs>[0];
  answer(io, values, { signed_in: true, profile: profileOf(values), account }, () => [`Signed in. Account: ${signedInAs(account)}`]);
  io.err(`The key is in ${host.env.NOCLICK_CONFIG_DIR ?? "~/.config/noclick"}/credentials.json (only you can read it). noclick logout revokes it.`);
  return OK;
}

interface Pending {
  device_code: string;
  user_code: string;
  verification_url: string;
  expires_at: string | null;
  interval_s: number;
}

/** A sign-in from a browser. The link is printed first; a run cut short leaves it pending, and the next run picks
 *  the same one up rather than asking the person again. */
export async function login(values: Values, io: Io): Promise<number> {
  fileStore(values);
  const apiUrl = apiUrlOf(values);
  const api = anonymous(apiUrl);
  const profiles = readProfiles(host.env) as Record<string, Profile & { pending_login?: Pending }>;
  const stored = profiles[profileOf(values)] ?? {};
  let pending = stored.pending_login;
  if (!pending || (pending.expires_at && Date.parse(pending.expires_at) <= Date.now())) {
    const start = await CliLogin.start({ name: CLIENT_NAME, hostname: hostname(), client: api });
    pending = {
      device_code: start.deviceCode, user_code: start.userCode, interval_s: start.intervalS,
      verification_url: start.verificationUrlComplete ?? start.verificationUrl, expires_at: start.expiresAt,
    };
    writeProfile(host.env, profileOf(values), { ...stored, pending_login: pending } as Profile);
  }
  io.out(`Open ${pending.verification_url} and enter the code ${pending.user_code}`);
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
      keep(values, poll.key, { api_url: apiUrl, key_id: poll.keyId, key_name: poll.keyName, email: poll.email });
      answer(io, values, { signed_in: true, email: poll.email }, () => [`Signed in as ${poll.email ?? "your account"}.`]);
      io.err(`The key "${poll.keyName ?? CLIENT_NAME}" is in a file only you can read. noclick logout revokes it.`);
      return OK;
    }
    interval = poll.intervalS ?? interval;
  }
}

export async function whoami(values: Values, io: Io): Promise<number> {
  const creds = resolveCredentials(host.env, profileOf(values));
  host.signIn(profileOf(values));
  if (creds.source === "env" && creds.login.store) io.err(`${API_KEY_ENV} overrides the login stored for this profile.`);
  const status = await accountStatus();
  const account = (status.account ?? {}) as Parameters<typeof signedInAs>[0];
  const key = `${creds.login.key_name ? `${creds.login.key_name} ` : ""}(${creds.key!.slice(0, 12)}…), ${creds.source === "env" ? `from ${API_KEY_ENV}` : "in a file"}`;
  answer(io, values, {
    profile: creds.profile, source: creds.source, key_prefix: creds.key!.slice(0, 12), api_url: creds.apiUrl,
    email: creds.login.email ?? null, key_name: creds.login.key_name ?? null, account,
  }, () => [`Account  ${signedInAs(account)}`, `Key      ${key}`, `Profile  ${creds.profile}`, `API      ${creds.apiUrl}`]);
  return OK;
}

export async function logout(values: Values, io: Io): Promise<number> {
  const creds = resolveCredentials(host.env, profileOf(values));
  if (creds.source === "env") {
    io.err(`This shell uses ${API_KEY_ENV}, which logout can't clear: unset it.`);
    return OK;
  }
  if (!creds.key) {
    io.err("You're not signed in.");
    return OK;
  }
  host.signIn(profileOf(values));
  try {
    await Key.revokeCurrent({ client: defaultClient() });
  } catch (err) {
    if (!(err instanceof Unauthenticated)) throw err; // already revoked: forget it all the same
  }
  storeKey(host.env, profileOf(values), null);
  writeProfile(host.env, profileOf(values), null);
  io.err("Signed out: the key is revoked and forgotten.");
  return OK;
}
