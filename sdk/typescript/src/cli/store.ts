/**
 * Where the CLI keeps its sign-ins, in the Python CLI's own format, so either one signs in for both.
 *
 * Sign-ins: `NOCLICK_API_KEY` always wins. Else the profile's key is read from where its login says it's kept: the
 * OS keychain (`keychain.ts`), or `credentials.json` beside `config.json` in the config directory
 * (`NOCLICK_CONFIG_DIR`, else `$XDG_CONFIG_HOME/noclick` or `~/.config/noclick`), readable only by you.
 */

import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { API_KEY_ENV, API_URL_ENV, DEFAULT_BASE_URL } from "../client.ts";
import { NoClickError, Unauthenticated } from "../errors.ts";
import { KEYCHAIN_ENV, type KeyStore, keychainOff, osKeychain } from "./keychain.ts";
import { jsonText, withRun } from "./output.ts";

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
  /** The claim link of an account `noclick signup` made, until a person has claimed it. */
  claim_url?: string;
}

export interface Credentials {
  key: string | null;
  source: "env" | "file" | "keychain" | "none";
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
  writeFileSync(path, `${jsonText(data)}\n`, { mode: 0o600 });
  chmodSync(path, 0o600);
}

/** The profile `noclick profile use` set, in config.json beside the profiles. */
export const DEFAULT_PROFILE_KEY = "default_profile";

export type ProfileSource = "flag" | "env" | "config" | "default";

/** Why a profile is the one a command uses, in the words `whoami` and `profile` say it. */
export const PROFILE_SOURCES: Record<ProfileSource, string> = {
  flag: "from --profile", env: `from ${PROFILE_ENV}`, config: "set by noclick profile use", default: "the default",
};

function readConfig(env: Env): { profiles?: Record<string, Profile>; [DEFAULT_PROFILE_KEY]?: string } {
  return readJson(join(configDir(env), "config.json"), {});
}

/** The profile a command uses and why: `--profile`, else `NOCLICK_PROFILE`, else the one `noclick profile use` set,
 *  else `default`. */
export function activeProfile(env: Env, given?: string): [string, ProfileSource] {
  if (given) return [given, "flag"];
  if (env[PROFILE_ENV]) return [env[PROFILE_ENV]!, "env"];
  const chosen = chosenProfile(env);
  return chosen ? [chosen, "config"] : ["default", "default"];
}

/** The profile `noclick profile use` set, if any. */
export function chosenProfile(env: Env): string | undefined {
  return readConfig(env)[DEFAULT_PROFILE_KEY];
}

/** Make `name` the profile commands use (null: none, so `default`). */
export function setDefaultProfile(env: Env, name: string | null): void {
  const path = join(configDir(env), "config.json");
  const config = readConfig(env);
  if (name) config[DEFAULT_PROFILE_KEY] = name;
  else delete config[DEFAULT_PROFILE_KEY];
  writePrivate(path, config);
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

export const credentialsPath = (env: Env) => join(configDir(env), "credentials.json");

/** `credentials.json`, readable only by you. */
export function fileStore(env: Env): KeyStore {
  const all = () => readJson<Record<string, string>>(credentialsPath(env), {});
  return {
    name: "file",
    read: (profile) => all()[profile] ?? null,
    write: (profile, key) => writePrivate(credentialsPath(env), { ...all(), [profile]: key }),
    delete: (profile) => {
      const keys = all();
      if (profile in keys) {
        delete keys[profile];
        writePrivate(credentialsPath(env), keys);
      }
    },
  };
}

/** `keychain`, `file`, or `auto`: the OS keychain where this machine has one to keep it in, else the file. */
export function keyStore(env: Env, name: string): KeyStore {
  if (name === "file") return fileStore(env);
  const keychain = osKeychain();
  if (keychain) return keychain;
  if (name === "auto") return fileStore(env);
  throw new CommandError(keychainOff(env[KEYCHAIN_ENV]) ? `The OS keychain is off here (${KEYCHAIN_ENV}=${env[KEYCHAIN_ENV]}).`
    : "No OS keychain is reachable on this machine.", { nextStep: "Pass --store file to keep the key in a file only you can read." });
}

export function storeKey(env: Env, profile: string, key: string | null): void {
  if (key) fileStore(env).write(profile, key);
  else fileStore(env).delete(profile);
}

export function resolveCredentials(env: Env, profile: string): Credentials {
  const login = readProfiles(env)[profile] ?? {};
  const envKey = env[API_KEY_ENV];
  if (envKey) return { key: envKey, source: "env", profile, apiUrl: env[API_URL_ENV] || DEFAULT_BASE_URL, login };
  if (login.store) {
    const key = keyStore(env, login.store).read(profile);
    if (key) return { key, source: login.store, profile, apiUrl: login.api_url || DEFAULT_BASE_URL, login };
  }
  return { key: null, source: "none", profile, apiUrl: env[API_URL_ENV] || DEFAULT_BASE_URL, login };
}

/** The profile's credentials, or why there are none. */
export function signedIn(env: Env, profile: string): Credentials {
  const creds = resolveCredentials(env, profile);
  if (creds.key) return creds;
  throw withRun(new Unauthenticated("You're not signed in.", {
    nextStep: `Run noclick login (or noclick setup <code>, a code from the console's Quickstart), or set ${API_KEY_ENV}.`,
  }), ["noclick login"]);
}
