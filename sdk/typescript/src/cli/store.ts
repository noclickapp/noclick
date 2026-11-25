/**
 * Where the CLI keeps its sign-ins, in the Python CLI's own format, so either one signs in for both.
 *
 * Sign-ins: `NOCLICK_API_KEY` always wins. Else the profile's key is read from `credentials.json` beside
 * `config.json` in the config directory (`NOCLICK_CONFIG_DIR`, else `$XDG_CONFIG_HOME/noclick` or
 * `~/.config/noclick`), readable only by you. This CLI never reads an OS keychain: a key the Python CLI kept there is
 * named, not read.
 */

import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { API_KEY_ENV, API_URL_ENV, DEFAULT_BASE_URL } from "../client.ts";
import { NoClickError, Unauthenticated } from "../errors.ts";

export const PROFILE_ENV = "NOCLICK_PROFILE";
export const CONFIG_DIR_ENV = "NOCLICK_CONFIG_DIR";

type Env = Record<string, string | undefined>;

/** A problem found on this machine, not an API refusal: a file, git, the folder. */
export class CommandError extends NoClickError {
  static override errorType = "command_error";
}

export interface Profile {
  api_url?: string;
  store?: "file" | "keychain";
  key_id?: string | null;
  key_name?: string | null;
  key_prefix?: string;
  email?: string | null;
}

export interface Credentials {
  key: string | null;
  source: "env" | "file" | "none";
  profile: string;
  apiUrl: string;
  login: Profile;
}

export function configDir(env: Env): string {
  return env[CONFIG_DIR_ENV] || join(env.XDG_CONFIG_HOME || join(env.HOME || homedir(), ".config"), "noclick");
}

function readJson<T>(path: string, empty: T): T {
  return existsSync(path) ? (JSON.parse(readFileSync(path, "utf8")) as T) : empty;
}

/** Written so only you can read it, whatever the umask. */
function writePrivate(path: string, data: unknown): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`, { mode: 0o600 });
  chmodSync(path, 0o600);
}

export function readProfiles(env: Env): Record<string, Profile> {
  return readJson<{ profiles?: Record<string, Profile> }>(join(configDir(env), "config.json"), {}).profiles ?? {};
}

export function writeProfile(env: Env, name: string, profile: Profile | null): void {
  const path = join(configDir(env), "config.json");
  const config = readJson<{ profiles?: Record<string, Profile> }>(path, {});
  const profiles = { ...(config.profiles ?? {}) };
  if (profile) profiles[name] = profile;
  else delete profiles[name];
  writePrivate(path, { ...config, profiles });
}

const credentialsPath = (env: Env) => join(configDir(env), "credentials.json");

export function storeKey(env: Env, profile: string, key: string | null): void {
  const keys = { ...readJson<Record<string, string>>(credentialsPath(env), {}) };
  if (key) keys[profile] = key;
  else delete keys[profile];
  writePrivate(credentialsPath(env), keys);
}

export function resolveCredentials(env: Env, profile: string): Credentials {
  const login = readProfiles(env)[profile] ?? {};
  const envKey = env[API_KEY_ENV];
  if (envKey) return { key: envKey, source: "env", profile, apiUrl: env[API_URL_ENV] || DEFAULT_BASE_URL, login };
  if (login.store === "file") {
    const key = readJson<Record<string, string>>(credentialsPath(env), {})[profile];
    if (key) return { key, source: "file", profile, apiUrl: login.api_url || env[API_URL_ENV] || DEFAULT_BASE_URL, login };
  }
  return { key: null, source: "none", profile, apiUrl: env[API_URL_ENV] || DEFAULT_BASE_URL, login };
}

/** The profile's credentials, or why there are none. */
export function signedIn(env: Env, profile: string): Credentials {
  const creds = resolveCredentials(env, profile);
  if (creds.key) return creds;
  if (creds.login.store === "keychain") {
    throw new Unauthenticated("This profile's key is in the OS keychain, which npx noclick doesn't read.", {
      nextStep: `Set ${API_KEY_ENV}, or sign in here too: noclick login, or noclick setup <code>.`,
    });
  }
  throw new Unauthenticated("You're not signed in.", {
    nextStep: `Run noclick login (or noclick setup <code>, a code from the console's Quickstart), or set ${API_KEY_ENV}.`,
  });
}
