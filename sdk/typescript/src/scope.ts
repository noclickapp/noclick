/**
 * The user a call acts for.
 *
 * `asUser(user, async () => ...)` scopes every call inside the callback
 * (through `AsyncLocalStorage`, so concurrent requests never see each other's
 * user). A method's `{ user }` option wins over it; `user: null` means
 * the account itself.
 */

import { InvalidRequest, NoClickError } from "./errors.ts";

export const USER_HEADER = "NoClick-User";

/** Anything that can name a user lazily (a `User`). */
export interface UserLike {
  _userId(): Promise<string>;
}

/** A `User` or your own id for the user. */
export type UserRef = string | UserLike;

/** `undefined` = the ambient user (from `asUser`), `null` = the account itself. */
export type UserOption = UserRef | null | undefined;

interface Store {
  user: UserRef | null;
}
interface Storage {
  getStore(): Store | undefined;
  run<R>(store: Store, fn: () => R): R;
}
type StorageCtor = new () => Storage;

type Globals = {
  AsyncLocalStorage?: StorageCtor;
  process?: { getBuiltinModule?: (id: string) => { AsyncLocalStorage?: StorageCtor } | undefined };
};

function syncStorageCtor(): StorageCtor | undefined {
  const g = globalThis as unknown as Globals;
  if (typeof g.AsyncLocalStorage === "function") return g.AsyncLocalStorage; // Workers (nodejs_compat)
  const builtin = g.process?.getBuiltinModule?.("node:async_hooks"); // Node >= 20.16, Bun, Deno
  return builtin?.AsyncLocalStorage;
}

let storage: Storage | null = (() => {
  const Ctor = syncStorageCtor();
  return Ctor ? new Ctor() : null;
})();

async function loadStorage(): Promise<Storage> {
  if (storage) return storage;
  let Ctor: StorageCtor | undefined;
  try {
    const specifier = "node:async_hooks"; // a variable keeps browser bundlers from resolving it
    Ctor = ((await import(/* @vite-ignore */ specifier)) as { AsyncLocalStorage?: StorageCtor }).AsyncLocalStorage;
  } catch {
    Ctor = undefined;
  }
  if (!Ctor) {
    throw new NoClickError("asUser() needs AsyncLocalStorage, which this runtime does not provide.", {
      nextStep: "Pass { user } to each call instead, or enable nodejs_compat on Cloudflare Workers.",
    });
  }
  storage ??= new Ctor();
  return storage;
}

const MAX_USER_ID_LENGTH = 255;

/** `"all"` and `"none"` are list filters (`ALL_USERS`, `NO_USER`), never a user's id. */
const RESERVED_IDS = new Set(["all", "none"]);

/**
 * `id` if it can be a user's id, else `InvalidRequest` naming the rule: 1 to 255 characters of
 * printable ASCII (no spaces), no `/`, and not `all` or `none`.
 */
export function checkUserId(id: string): string {
  const fail = (message: string) => new InvalidRequest(message, {
    nextStep: 'Pass your own id for the user: 1 to 255 printable ASCII characters, no spaces or "/", and not "all", "none", "." or "..".',
    details: { field: "id" },
  });
  if (id.length < 1 || id.length > MAX_USER_ID_LENGTH) throw fail(`A user id is 1 to ${MAX_USER_ID_LENGTH} characters, not ${id.length}.`);
  if (!/^[\x21-\x7e]+$/.test(id)) throw fail(`A user id is printable ASCII without spaces: ${JSON.stringify(id)} is not.`);
  if (id.includes("/")) throw fail(`A user id can't contain "/": ${JSON.stringify(id)}.`);
  if (RESERVED_IDS.has(id)) throw fail(`"${id}" is reserved for list filters and can't be a user id.`);
  if (id === "." || id === "..") throw fail(`"${id}" can't be a user id: URLs resolve it away.`);
  return id;
}

function checkUser(user: unknown): UserRef | null {
  if (user === null) return user;
  if (typeof user === "string") return checkUserId(user);
  if (user && typeof (user as UserLike)._userId === "function") return user as UserLike;
  throw new TypeError(`asUser() takes a User or your id for one, not ${typeof user}`);
}

/** Run `fn` acting for `user` (`null` = the account). Nests; the inner scope wins. */
export async function asUser<T>(user: UserRef | null, fn: () => T | Promise<T>): Promise<T> {
  const checked = checkUser(user);
  const store = storage ?? (await loadStorage());
  return await store.run({ user: checked }, fn);
}

/** The user set by the innermost `asUser` (or null). */
export function currentUser(): UserRef | null {
  return storage?.getStore()?.user ?? null;
}

/** Turn a `{ user }` option into what a call carries: explicit, else ambient. */
export function resolveScope(user: UserOption): UserRef | null {
  return user === undefined ? currentUser() : user;
}

/**
 * The user id a resolved scope names (the `NoClick-User` header and every `user_id` field), or
 * null for the account. A lazy `User` with `createIfMissing` is created first.
 */
export async function userIdOf(user: UserRef | null): Promise<string | null> {
  if (user === null) return null;
  if (typeof user === "string") return checkUserId(user);
  return await user._userId();
}

/** Every user plus account-level rows, for a read's `userFilter`. */
export const ALL_USERS = "all";
/** Account-level rows only (no user), for a read's `userFilter`. */
export const NO_USER = "none";

/**
 * Which users a read covers: `ALL_USERS`, `NO_USER`, a `User` or your id for one. Sent as the
 * `user_id` query parameter, never as the `NoClick-User` header, so it filters without acting as the user.
 */
export type UserFilter = typeof ALL_USERS | typeof NO_USER | UserRef;

/** The `user_id` query value for a filter. */
export async function userFilterParam(filter: UserFilter): Promise<string> {
  if (filter === ALL_USERS || filter === NO_USER) return filter;
  if (typeof filter === "string") return checkUserId(filter);
  if (filter && typeof (filter as UserLike)._userId === "function") return await filter._userId();
  throw new TypeError(`userFilter takes "all", "none", a User or your id for one, not ${typeof filter}`);
}
