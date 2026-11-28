/**
 * Where you work from, as the Python CLI's `parts/account.py`: `noclick profile` (the logins this machine keeps, and
 * which one commands use), `noclick completion` (Tab for your shell), `noclick dashboard` (the console in a browser)
 * and `noclick changelog` (what changed lately).
 */

import { API_KEY_ENV, CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "../../client.ts";
import { NotFound } from "../../errors.ts";
import { VERSION } from "../../version.ts";
import { UsageError, type Values } from "../args.ts";
import * as changelog from "../changelog.ts";
import * as completion from "../completion.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import { type Io, printJson, withRun } from "../output.ts";
import {
  CommandError, PROFILE_ENV, PROFILE_SOURCES, type Profile, type ProfileSource, readProfiles, resolveCredentials,
  setDefaultProfile, signedIn,
} from "../store.ts";
import { configure } from "../../client.ts";
import { lookup, num, on, profileOf, str, table } from "./kit.ts";

export const CONSOLE_URL_ENV = "NOCLICK_CONSOLE_URL";

// --- profiles --------------------------------------------------------------------------------------------------

function view(name: string, login: Profile, active: string) {
  return {
    name, active: name === active, email: login.email ?? null, key_name: login.key_name ?? null,
    key_prefix: login.key_prefix ?? null, store: login.store ?? null, api_url: login.api_url || DEFAULT_BASE_URL,
  };
}

function stored(): Record<string, Profile> {
  return Object.fromEntries(Object.entries(readProfiles(host.env)).filter(([, login]) => login.store));
}

const sourceOf = (values: Values) => (str(values, "profile_source") ?? "default") as ProfileSource;

function envNote(io: Io): void {
  if (host.env[API_KEY_ENV]) io.err(`${API_KEY_ENV} is set in this shell: commands use it, whichever profile is active.`);
}

export async function profileList(values: Values, io: Io): Promise<number> {
  const active = profileOf(values);
  const why = sourceOf(values);
  const rows = Object.entries(stored()).sort(([a], [b]) => a.localeCompare(b)).map(([name, login]) => view(name, login, active));
  if (on(values, "json")) {
    printJson(io, { data: rows, active, active_source: why });
    return OK;
  }
  table(io, ["", "PROFILE", "ACCOUNT", "KEY", "API"], rows.map((r) => [r.active ? "*" : "", r.name, r.email ?? "-",
    r.key_name ?? r.key_prefix ?? "-", r.api_url]), "No stored logins: noclick login signs one in.");
  if (rows.length) io.err(`* is active (${PROFILE_SOURCES[why]}). Switch: noclick profile use <name>`);
  if (!rows.some((r) => r.name === active)) io.err(`The active profile, ${active} (${PROFILE_SOURCES[why]}), has no stored login.`);
  envNote(io);
  return OK;
}

export async function profileUse(values: Values, io: Io): Promise<number> {
  const name = String(values.name);
  const logins = stored();
  if (!logins[name]) {
    const names = Object.keys(logins).sort();
    throw withRun(new NotFound(`No stored login is called ${name}${names.length ? ` (stored: ${names.join(", ")}).` : "."}`,
      { nextStep: "Sign in under that name." }), [`noclick login --profile ${name}`]);
  }
  setDefaultProfile(host.env, name);
  const email = logins[name]!.email;
  if (on(values, "json")) printJson(io, { active: name, email: email ?? null });
  else io.out(`Commands now use the profile ${name}${email ? ` (${email})` : ""}.`);
  const fromEnv = host.env[PROFILE_ENV];
  if (fromEnv && fromEnv !== name) io.err(`${PROFILE_ENV}=${fromEnv} is set in this shell and still wins: unset it.`);
  envNote(io);
  return OK;
}

export async function profileShow(values: Values, io: Io): Promise<number> {
  const active = profileOf(values);
  const why = sourceOf(values);
  const name = str(values, "name") ?? active;
  const login = stored()[name];
  if (!login) {
    throw withRun(new NotFound(`No stored login is called ${name}.`, { nextStep: "Sign in under that name." }),
      [`noclick login --profile ${name}`]);
  }
  const shown = { ...view(name, login, active), ...(name === active ? { active_source: why } : {}) };
  if (on(values, "json")) {
    printJson(io, shown);
    return OK;
  }
  const where = login.store === "keychain" ? "the OS keychain" : "a file only you can read";
  const rows: [string, string | null][] = [
    ["Profile", name === active ? `${name} (${PROFILE_SOURCES[why]})` : name], ["Account", shown.email],
    ["Key", `${shown.key_name ?? "unnamed"} (${shown.key_prefix ?? "?"}…), in ${where}`], ["API", shown.api_url],
  ];
  for (const [label, value] of rows) if (value) io.out(`${label.padEnd(8)} ${value}`);
  envNote(io);
  return OK;
}

// --- completion ------------------------------------------------------------------------------------------------

export async function completionCmd(values: Values, io: Io): Promise<number> {
  const shell = String(values.shell) as completion.Shell;
  if (!on(values, "install")) {
    io.out(completion.SCRIPTS[shell].replace(/\n$/, ""));
    return OK;
  }
  for (const line of completion.install(shell)) io.out(line);
  io.err("Open a new shell to use it.");
  return OK;
}

// --- the console -----------------------------------------------------------------------------------------------

function consoleUrl(apiUrl: string): string {
  const given = host.env[CONSOLE_URL_ENV];
  if (given) return given.replace(/\/+$/, "");
  if (apiUrl.replace(/\/+$/, "") !== DEFAULT_BASE_URL) {
    throw new CommandError(`This profile's API (${apiUrl}) has no console NoClick knows the address of.`,
      { nextStep: `Set ${CONSOLE_URL_ENV} to its address.` });
  }
  return CONSOLE_BASE_URL;
}

/** Whether a browser can be opened here: a terminal on a machine with a display. */
function canOpen(io: Io): boolean {
  if (!io.terminal?.().out) return false;
  return process.platform === "darwin" || process.platform === "win32" || Boolean(host.env.DISPLAY || host.env.WAYLAND_DISPLAY);
}

export async function dashboard(values: Values, io: Io): Promise<number> {
  const profile = profileOf(values);
  let url = consoleUrl(resolveCredentials(host.env, profile).apiUrl);
  const app = str(values, "app");
  if (app) {
    const creds = signedIn(host.env, profile);
    configure({ apiKey: creds.key!, baseUrl: creds.apiUrl, fetch: host.fetch });
    url = `${url}/resources/apps/${(await lookup(app)).id}`;
  }
  if (on(values, "json")) {
    printJson(io, { url, opened: false });
    return OK;
  }
  if (canOpen(io) && host.openUrl(url)) io.err("Opened it in your browser.");
  io.out(url);
  return OK;
}

// --- the changelog ---------------------------------------------------------------------------------------------

async function changes(): Promise<changelog.Change[]> {
  const url = changelog.pageUrl(host.env);
  let response: Response;
  try {
    response = await (host.fetch ?? fetch)(url, { headers: { "User-Agent": `noclick-cli/${VERSION}` } });
  } catch (err) {
    throw new CommandError(`Couldn't read the changelog at ${url}: ${(err as Error).message}.`,
      { nextStep: `Check your connection, or ${changelog.DOCS_URL_ENV}.` });
  }
  if (response.status !== 200) {
    throw new CommandError(`Couldn't read the changelog at ${url}: it answered ${response.status}.`,
      { nextStep: `Check ${changelog.DOCS_URL_ENV}, which names the docs it's read from.` });
  }
  return changelog.parse(await response.text(), changelog.docsUrl(host.env));
}

export async function changelogCmd(values: Values, io: Io): Promise<number> {
  const entries = await changes();
  const asked = str(values, "change");
  if (asked) {
    const found = changelog.find(entries, asked);
    if (!found.length) throw withRun(new NotFound(`No change in the changelog is called '${asked}'.`, { nextStep: "List the changes." }), ["noclick changelog"]);
    if (found.length > 1) {
      throw new UsageError(`${found.length} changes match '${asked}': ${found.slice(0, 5).map((e) => changelog.ref(e, entries)).join(", ")}`
        + `${found.length > 5 ? ", …" : ""}.`, "Name one.", [`noclick changelog ${changelog.ref(found[0]!, entries)}`]);
    }
    const entry = found[0]!;
    if (on(values, "json")) {
      printJson(io, entry);
      return OK;
    }
    const kind = [entry.kind && entry.kind[0]!.toUpperCase() + entry.kind.slice(1), entry.areas].filter(Boolean).join(" · ");
    io.out(`## ${entry.title}\n${entry.date}${kind ? ` · ${kind}` : ""}\n\n${entry.body}`);
    io.err(`On the web: ${entry.url}`);
    return OK;
  }
  const shown = entries.slice(0, num(values, "limit") ?? 10);
  if (on(values, "json")) {
    printJson(io, { data: shown });
    return OK;
  }
  table(io, ["DATE", "CHANGE"], shown.map((e) => [e.date, e.title]), "No changelog entries.");
  if (shown.length) io.err(`Read one whole: noclick changelog ${changelog.ref(shown[0]!, entries)}`);
  return OK;
}
