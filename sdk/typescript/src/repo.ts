/**
 * Repos: git repositories for the code your agents and apps write. A repo is plain git: clone
 * it, push to it, copy one in from a public URL, or move it to GitHub whole. A project (`Project`)
 * deploys one to a URL.
 */

import { TrashItem, trashed } from "./trash.ts";
import type { NoClick } from "./client.ts";
import type { Connection } from "./connection.ts";
import { Conflict, NotFound } from "./errors.ts";
import type { UsedBy } from "./database.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import {
  ApiObject, asList, asObject, compact, createNamed, fetchPage, listAll, listPage, num, paginate, parseTime, refId, str, toBase64,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";
import type { UserOption, UserRef } from "./scope.ts";

/** One commit, and how many files it added, changed or deleted. */
/**
 * One commit: the `branch` it was made on, and `filesChanged`, how many files it added, changed or
 * deleted. A branch's history (`commits()`) names that branch and counts no files (`filesChanged` is
 * null); `diff()` counts them and names no branch.
 */
export interface Commit {
  sha: string;
  message: string;
  author: string | null;
  branch: string | null;
  createdAt: Date | null;
  filesChanged: number | null;
  raw: JsonObject;
}

/**
 * One file a commit changed: `status` is `added`, `modified`, `deleted`, `renamed`, `copied` or
 * `type_changed`; `patch` is its unified diff in git's format, null (with the line counts) for a file
 * that isn't shown: one that isn't text, or is too large.
 */
export interface FileChange {
  path: string;
  oldPath: string | null;
  status: string;
  additions: number | null;
  deletions: number | null;
  size: number | null;
  patch: string | null;
  raw: JsonObject;
}

/** What one commit changed against its first parent (`parents` is empty for the first commit). */
export interface CommitDiff {
  commit: Commit;
  parents: string[];
  additions: number;
  deletions: number;
  files: FileChange[];
}

/** A branch and the sha of its head commit. */
export interface Branch {
  name: string;
  head: string | null;
  updatedAt: Date | null;
  raw: JsonObject;
}

/**
 * A branch's old head NoClick kept before an agent's push rewrote it (`reason` `"rewritten"`: a force-push)
 * or deleted it (`"deleted"`): the `branch`, the commit `sha` it was at, the platform agent whose push it was
 * (`agentId`, else null), and when it was kept. It's kept 30 days, until `expiresAt`, out of the branch list
 * and clones; `repo.restoreBackup` makes the branch again.
 */
export interface RepoBackup {
  id: string;
  branch: string;
  sha: string;
  reason: string;
  agentId: string | null;
  createdAt: Date | null;
  expiresAt: Date | null;
  raw: JsonObject;
}

/**
 * An entry in a repo's tree; `size` is in bytes, null for a directory, and
 * `sha` is git's blob id for a file's content (it changes whenever the content does).
 * A `link` is a symbolic link someone committed: listed as the entry it is, with no
 * size or sha, and never followed.
 */
export interface RepoFile {
  path: string;
  type: "file" | "dir" | "link";
  size: number | null;
  sha: string | null;
  raw: JsonObject;
}

function toCommit(value: unknown): Commit {
  const raw = asObject(value);
  return {
    sha: str(raw.sha) ?? "",
    message: str(raw.message) ?? "",
    author: str(raw.author),
    branch: str(raw.branch),
    createdAt: parseTime(raw.created_at),
    filesChanged: num(raw.files_changed),
    raw,
  };
}

function toFileChange(value: unknown): FileChange {
  const raw = asObject(value);
  return {
    path: str(raw.path) ?? "",
    oldPath: str(raw.old_path),
    status: str(raw.status) ?? "modified",
    additions: num(raw.additions),
    deletions: num(raw.deletions),
    size: num(raw.size),
    patch: str(raw.patch),
    raw,
  };
}

function toCommitDiff(value: unknown): CommitDiff {
  const raw = asObject(value);
  const parents = Array.isArray(raw.parents) ? raw.parents.filter((p): p is string => typeof p === "string") : [];
  const files = Array.isArray(raw.files) ? raw.files.map(toFileChange) : [];
  return { commit: toCommit(raw), parents, additions: num(raw.additions) ?? 0, deletions: num(raw.deletions) ?? 0, files };
}

function toBranch(value: unknown): Branch {
  const raw = asObject(value);
  return { name: str(raw.name) ?? "", head: str(raw.head), updatedAt: parseTime(raw.updated_at), raw };
}

function toRepoBackup(value: unknown): RepoBackup {
  const raw = asObject(value);
  return {
    id: str(raw.id) ?? "",
    branch: str(raw.branch) ?? "",
    sha: str(raw.sha) ?? "",
    reason: str(raw.reason) ?? "",
    agentId: str(raw.agent_id),
    createdAt: parseTime(raw.created_at),
    expiresAt: parseTime(raw.expires_at),
    raw,
  };
}

function toRepoFile(value: unknown): RepoFile {
  const raw = asObject(value);
  const type = raw.type === "dir" || raw.type === "link" ? raw.type : "file";
  return { path: str(raw.path) ?? "", type, size: num(raw.size), sha: str(raw.sha), raw };
}

/** Where a checkout goes and what it may push. */
export interface CheckoutOptions {
  /** The branch it checks out (the repository's default when omitted). */
  branch?: string;
  /** The folder under `/workspace` it's cloned into (the repository's name when omitted). */
  path?: string;
  /** Branches it may push to, exact or a prefix ending in `/*` (`"noclick/*"`); without it the checkout is read-only. */
  push?: string | string[];
}

/**
 * A git repository an agent works in, for `Agent` `repos`: a connection's repository
 * (`connection.checkout("acme/docs")`) or a NoClick repo of the agent's scope (`repo.checkout()`).
 * NoClick clones it into `/workspace/<path>` at a conversation's first turn, and the agent's
 * git reaches that repository only, through NoClick, with a key made for its sandbox; the
 * connection's own token never enters it. `push` lists the branches it may push to: exact names, or a
 * prefix ending in `/*` (`"noclick/*"` reaches `noclick/fix` and `noclick/a/b`), which NoClick's git
 * endpoint enforces; without it the checkout is read-only. Whatever `push` allows, the agent can't
 * force-push or delete the repository's default branch, and before its push rewrites or deletes any other
 * branch NoClick keeps the old head as a backup for 30 days (on a git host,
 * `refs/noclick/backups/<branch>/<time>` in the repository, which you push back to restore; on a NoClick repo,
 * `repo.backups()` and `repo.restoreBackup()`). A policy can't do this job:
 * a coding harness runs `git push` in its own shell, which is no tool call for a policy to judge.
 * `gh` only reads the repository there.
 */
export class RepoCheckout {
  /** `owner/name` on the connection's service (null for a NoClick repo). */
  readonly repository: string | null;
  readonly connection: Connection | null;
  readonly repo: Repo | null;
  readonly branch: string | null;
  readonly path: string | null;
  readonly push: string[] | null;

  /** @internal Made by `connection.checkout(...)` or `repo.checkout(...)`. */
  constructor(source: { repository: string; connection: Connection } | { repo: Repo }, options: CheckoutOptions = {}) {
    if ("repo" in source) {
      this.repository = null;
      this.connection = null;
      this.repo = source.repo;
    } else {
      if (typeof source.repository !== "string" || !source.repository.includes("/") || /\s/.test(source.repository)) {
        throw new TypeError(`repository is "owner/name" on the connection's service, not ${JSON.stringify(source.repository)}`);
      }
      this.repository = source.repository;
      this.connection = source.connection;
      this.repo = null;
    }
    this.branch = options.branch ?? null;
    this.path = options.path === undefined ? null : workspaceFolder(options.path);
    this.push = options.push === undefined ? null : branchGlobs(options.push);
  }

  /** @internal The `repos` entry for an agent in `scope` (a connection from another scope goes by id). */
  async _wire(scope: UserRef | null): Promise<JsonObject> {
    const extra = compact({ branch: this.branch, path: this.path, push: this.push });
    if (this.repo) return { repo_id: await refId(this.repo), ...extra };
    return { connection: await this.connection!._refIn(scope), repository: this.repository, ...extra };
  }
}

function workspaceFolder(path: string): string {
  const parts = path.split("/").filter(Boolean);
  if (!parts.length || path.startsWith("/") || parts.some((p) => p === "." || p === "..")) {
    throw new TypeError(`path is a folder under /workspace, like "docs" or "repos/docs", not ${JSON.stringify(path)}`);
  }
  return parts.join("/");
}

/** `push` as branch patterns: exact names or a prefix ending in `/*`, the one glob a git endpoint enforces. */
function branchGlobs(push: string | string[]): string[] {
  const globs = typeof push === "string" ? [push] : [...push];
  if (!globs.length || !globs.every((g) => typeof g === "string" && g)) {
    throw new TypeError('push takes branch globs like "noclick/*"; leave it out for a read-only checkout');
  }
  for (const glob of globs) {
    if ((glob.endsWith("/*") ? glob.slice(0, -2) : glob).includes("*")) {
      throw new TypeError(`${JSON.stringify(glob)} isn't a push pattern: name a branch exactly ("main"), or a prefix ending in "/*" ("noclick/*")`);
    }
  }
  return globs;
}

const readGithubUrl = (result: unknown): string | null => str(asObject(result).url);
/** An import settles with `{ repo: <the repo's view>, ... }`. */
const readImport = (result: unknown, op: Operation<unknown>): Repo => Repo._fromImport(result, op);

registerResult("repo.export", toExportBundle);
registerResult("repo.export_to_github", readGithubUrl);
registerResult("repo.import", readImport);

/**
 * A file NoClick reads for a commit, byte for byte, rather than one you send: one of the account's files
 * (`attachments()` lists them), the file at an https URL, or a bucket's file.
 */
export type FileSource = { attachmentId: string } | { url: string } | { bucketId: string; key: string };

/** One file of a commit on the wire: text as UTF-8, bytes as base64, null deletes, a source by reference. */
function change(path: string, content: string | Uint8Array | FileSource | null): JsonObject {
  if (content === null) return { path, delete: true };
  if (typeof content === "string") return { path, content, encoding: "utf-8" };
  if (content instanceof Uint8Array) return { path, content: toBase64(content), encoding: "base64" };
  if ("attachmentId" in content) return { path, attachment_id: content.attachmentId };
  if ("url" in content) return { path, url: content.url };
  return { path, bucket_id: content.bucketId, key: content.key };
}

/** Git's blob id for `data`, to tell an unchanged file without sending it. */
async function blobSha(data: Uint8Array): Promise<string> {
  const head = new TextEncoder().encode(`blob ${data.length}\0`);
  const whole = new Uint8Array(head.length + data.length);
  whole.set(head);
  whole.set(data, head.length);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-1", whole));
  return [...digest].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A glob as `fnmatch` reads it: `*` any run of characters, `?` one, `[...]` a class. */
function globRegex(glob: string): RegExp {
  let out = "";
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i];
    const close = c === "[" ? glob.indexOf("]", i + 2) : -1;
    if (c === "*") out += ".*";
    else if (c === "?") out += ".";
    else if (close > 0) {
      out += `[${glob.slice(i + 1, close).replace(/^!/, "^").replace(/\\/g, "\\\\")}]`;
      i = close;
    } else out += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${out}$`);
}

/** Whether a path (or a folder above it) matches one of the `exclude` globs. */
function excluded(path: string, exclude: readonly RegExp[]): boolean {
  const parts = path.split("/");
  return parts.some((_, i) => exclude.some((glob) => glob.test(parts.slice(0, i + 1).join("/"))));
}

type Fs = {
  readdir(path: string, options: { withFileTypes: true }): Promise<{ name: string; isDirectory(): boolean; isFile(): boolean }[]>;
  readFile(path: string): Promise<Uint8Array>;
};

/** Every file under `folder` by its path from there, `.git` and `exclude` left out (Node, Deno and Bun). */
async function readFolder(folder: string, exclude: readonly RegExp[]): Promise<Map<string, Uint8Array>> {
  const specifier = "node:fs/promises"; // a variable keeps browser bundlers from resolving it
  const fs = (await import(/* @vite-ignore */ specifier)) as Fs;
  const found = new Map<string, Uint8Array>();
  const walk = async (relative: string): Promise<void> => {
    for (const entry of await fs.readdir(relative ? `${folder}/${relative}` : folder, { withFileTypes: true })) {
      const path = relative ? `${relative}/${entry.name}` : entry.name;
      if (entry.isDirectory() && entry.name !== ".git") await walk(path);
      else if (entry.isFile() && !excluded(path, exclude)) found.set(path, new Uint8Array(await fs.readFile(`${folder}/${path}`)));
    }
  };
  await walk("");
  return found;
}

export interface RepoCreateOptions extends CallOptions {
  /** The branch a project deploys to production (`main` unless set). */
  defaultBranch?: string;
}

/** A repo made as a copy of a public git repository (`Repo.create(name, { fromUrl })`). */
export interface RepoImportOptions extends CallOptions {
  /** The https URL you'd `git clone`, with no login in it. */
  fromUrl: string;
  /** One branch, tag or commit (its full sha) to copy alone, with its history; every branch and tag when omitted. */
  ref?: string;
  /**
   * The branch a project deploys to production (`main` unless set). Copying, it's one of the source's branches
   * (the source's own default when omitted), or with `ref` the branch the copy lands on (the branch's own name,
   * else `main`).
   */
  defaultBranch?: string;
}

export interface RepoCommitOptions {
  message: string;
  /** The default branch when omitted; created from the default branch's head if it doesn't exist. */
  branch?: string;
  /** `Name <email>`. */
  author?: string;
}

/**
 * A git repository NoClick hosts. `Repo.fromName("agent-tools", { createIfMissing: true })` is
 * lazy; commit to it from code, or clone it and push with plain git.
 */
export class Repo extends ApiObject {
  private _createWith: JsonObject | null = null;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /**
   * Create an empty repo (unique per user; a duplicate throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the repo already there, commits and all).
   *
   * With `fromUrl`, the repo is a copy of a public git repository, history and all, and this resolves
   * to the `RepoImport` doing the copy, whose `wait()` resolves to the repo once it's copied. Every
   * branch and tag is copied, the repo's default branch the source's own unless `defaultBranch` names
   * another of its branches; `ref` copies one branch, tag or commit (its full sha) instead, as the
   * repo's one branch. Submodules and LFS files aren't copied (their pointers are, as committed). The
   * copy takes up to 5 GiB of history and 15 minutes. That size is measured as git transfers the
   * history (compressed), which isn't the same figure as the repo's `sizeBytes` afterwards. The copy is
   * charged what it uses: its seconds of compute and the bytes it stores, at NoClick's vendors'
   * prices. An import always makes a new repo, so it takes no `allowExisting`.
   *
   *     const copy = await Repo.create("blog", { fromUrl: "https://github.com/acme/blog" });
   *     const repo = await copy.wait(); // its error, if NoClick can't copy it (the repo is deleted)
   *     console.log(repo.defaultBranch, repo.lastCommit?.sha);
   */
  static async create(name: string, options: RepoImportOptions): Promise<RepoImport>;
  static async create(name: string, options?: RepoCreateOptions & AllowExisting): Promise<Repo>;
  static async create(
    name: string,
    options: (RepoCreateOptions & AllowExisting) | RepoImportOptions = {},
  ): Promise<Repo | RepoImport> {
    const scope = resolveScope(options.user);
    if (!("fromUrl" in options) || options.fromUrl === undefined) {
      const raw = await createNamed("/v1/repos", compact({ name, default_branch: options.defaultBranch }), {
        allowExisting: (options as AllowExisting).allowExisting, user: scope, client: options.client,
      });
      return new Repo({ raw, client: options.client, user: scope });
    }
    if ((options as AllowExisting).allowExisting) {
      throw new TypeError("an import always makes a new repo, so allowExisting doesn't apply to it");
    }
    const raw = await createNamed("/v1/repos", compact({
      name, default_branch: options.defaultBranch, source: compact({ url: options.fromUrl, ref: options.ref }),
    }), { user: scope, client: options.client });
    return RepoImport._fromResponse(raw.operation, { client: options.client, user: scope });
  }

  /** @internal What an import settles with, as its `Repo`. */
  static _fromImport(result: unknown, op: Operation<unknown>): Repo {
    const raw = asObject(asObject(result).repo);
    return new Repo({ raw, hints: { id: str(op._known("repo_id")) ?? str(raw.id) ?? "" }, client: op._client, user: op._scope });
  }

  /**
   * A lazy reference to the repo called `name` for the current (or given) user. With
   * `createIfMissing` it's created, empty, on first use; an existing repo is used as it is.
   */
  static fromName(name: string, options: RepoCreateOptions & { createIfMissing?: boolean } = {}): Repo {
    const repo = new Repo({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) repo._createWith = compact({ name, default_branch: options.defaultBranch });
    return repo;
  }

  static fromId(repoId: string, options: CallOptions = {}): Repo {
    return new Repo({ hints: { id: repoId }, client: options.client, user: options.user });
  }

  static async get(repoId: string, options: CallOptions = {}): Promise<Repo> {
    return await Repo.fromId(repoId, options).hydrate();
  }

  /** The current user's repos (the account's own outside `asUser`, or those `userFilter` covers). */
  static async list(options: ReadOptions & { limit?: number } = {}): Promise<Repo[]> {
    return await listAll({ ...options, path: "/v1/repos" }, (raw, user) => new Repo({ raw, client: options.client, user }));
  }

  /** One page of repos; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions = {}): Promise<Page<Repo>> {
    return await listPage({ ...options, path: "/v1/repos" }, (raw, user) => new Repo({ raw, client: options.client, user }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** The branch a project deploys to production. */
  get defaultBranch(): string {
    return this._field("default_branch");
  }
  get sizeBytes(): number | null {
    return this._field("size_bytes");
  }
  /** The newest commit on the default branch (null in an empty repo). */
  get lastCommit(): Commit | null {
    const raw = this._field<JsonObject | null>("last_commit");
    return raw ? toCommit(raw) : null;
  }
  /** The apps that deploy it (`binding` is always null). */
  get usedBy(): UsedBy[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "project", id: str(u.id) ?? "", name: str(u.name) ?? "", binding: null,
    }));
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** Copied from someone's public work on NoClick: `{address}`, the address it was copied from; null for a repo of your own. */
  get forkedFrom(): { address: string } | null {
    return this._field<{ address: string } | null>("forked_from") ?? null;
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/repos/${id}`);
    const name = String(this._hints.name);
    const page = await this._request("GET", "/v1/repos", { query: { name } });
    const row = (asList(page) as JsonObject[]).find((r) => r.name === name);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No repo is named "${name}".`, {
        nextStep: "Create it with Repo.create(...) or pass { createIfMissing: true }.",
        details: { name },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/repos", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/repos/${err.existingId}`);
    }
  }

  /** @internal */
  async _repoPath(...rest: string[]): Promise<string> {
    return [`/v1/repos/${await refId(this)}`, ...rest].join("/");
  }

  /**
   * A git URL with a short-lived token inside, for `git clone`, `fetch` and, with `write`, `push`.
   * `ttlS` is 3,600 by default, at most 86,400; the token reaches this repo only. Treat it as a secret
   * until it expires. Clones and pushes cost nothing extra, within fair use. An agent's writing URL (asked
   * for through NoClick's MCP server, by the coordinator or by a platform agent) goes through NoClick, which
   * never lets it force-push or delete the default branch, and keeps the old head of any other branch its
   * push rewrites or deletes (`backups`).
   */
  async cloneUrl(options: { write?: boolean; ttlS?: number } = {}): Promise<string> {
    const response = asObject(await this._request("POST", await this._repoPath("clone_url"), {
      json: compact({ write: options.write ?? false, ttl_s: options.ttlS }),
    }));
    return String(response.url);
  }

  /**
   * This repo checked out in an agent's workspace, for `Agent` `repos`: cloned into
   * `/workspace/<path>` (the repo's name when omitted) on `branch` (the default branch when omitted);
   * `push` is the branches it may push to, exact or `prefix/*`, else it's read-only. The repo must be in
   * the agent's own scope, and the agent's commits name it as their author. Sends nothing.
   *
   *     const site = Repo.fromName("booking");
   *     await Agent.create("site-builder", { instructions, repos: [site.checkout({ push: "agent/*" })] });
   */
  checkout(options: CheckoutOptions = {}): RepoCheckout {
    return new RepoCheckout({ repo: this }, options);
  }

  /**
   * Commit `files` in one commit: each path maps to its new content (text, or bytes for binary
   * files) or to `null` to delete it. At most 1,000 files and 50 MB in one commit.
   *
   * A file NoClick can reach goes by reference instead (`FileSource`), and NoClick reads it byte for
   * byte, so it never passes through your code: `{ attachmentId }` (one of the account's files, or a
   * file this key uploaded to an agent or a channel before a message sends it), `{ url }` or
   * `{ bucketId, key }`. Those bytes count toward the 50 MB too. Files that change nothing (each
   * already holds what it's given) reject with `Conflict` (409), naming the commit that holds them.
   *
   *     const [page] = await attachments({ query: "game.html" });
   *     await site.commit({ "index.html": { attachmentId: page.id! } }, { message: "Publish the game" });
   *
   * Given a folder on disk instead (Node, Deno or Bun), the branch's tree is made to match it and
   * only what changed is sent: new and changed files written, files the folder no longer has
   * deleted. `.git` is skipped, and so is any path matching one of the `exclude` globs, which also
   * keeps the repo's own copies of those paths. Nothing changed resolves to null.
   *
   *     const commit = await site.commit("./dist", { message: "Rebuild the site", exclude: ["*.map"] });
   */
  async commit(files: Record<string, string | Uint8Array | FileSource | null>, options: RepoCommitOptions): Promise<Commit>;
  async commit(folder: string, options: RepoCommitOptions & { exclude?: string[] }): Promise<Commit | null>;
  async commit(
    files: Record<string, string | Uint8Array | FileSource | null> | string,
    options: RepoCommitOptions & { exclude?: string[] },
  ): Promise<Commit | null> {
    const changes = typeof files === "string" ? await this.folderChanges(files, options.branch, options.exclude ?? []) : files;
    if (typeof files === "string" && !Object.keys(changes).length) return null;
    const json = compact({
      message: options.message,
      branch: options.branch,
      author: options.author,
      files: Object.entries(changes).map(([path, content]) => change(path, content)),
    });
    return toCommit(await this._request("POST", await this._repoPath("commits"), { json }));
  }

  /**
   * What a commit of `folder` must send: changed and new files, and null for the repo's files the
   * folder no longer has. A branch that doesn't exist yet starts from the default one.
   */
  private async folderChanges(folder: string, branch: string | undefined, exclude: readonly string[]): Promise<Record<string, Uint8Array | null>> {
    const globs = exclude.map(globRegex);
    const local = await readFolder(folder, globs);
    const ref = branch && (await this.branches()).some((b) => b.name === branch) ? branch : undefined;
    // A link in the repo is left as it is: a commit through the API writes files, so it can't put one back.
    const listed = (await this.files("", { ref, recursive: true })).filter((f) => f.type === "file");
    const remote = new Map(listed.map((f) => [f.path, f.sha]));
    const changes: Record<string, Uint8Array | null> = {};
    for (const [path, data] of local) if (remote.get(path) !== (await blobSha(data))) changes[path] = data;
    for (const path of remote.keys()) if (!local.has(path) && !excluded(path, globs)) changes[path] = null;
    return changes;
  }

  /**
   * One file's bytes at `ref` (a branch, tag or sha; the default branch's head when omitted). A link is
   * never followed: its path reads as the path it points to.
   */
  async read(path: string, options: { ref?: string } = {}): Promise<Uint8Array> {
    return await this._request<Uint8Array>("GET", await this._repoPath("files"), {
      query: { path, ref: options.ref },
      responseType: "bytes",
    });
  }

  /** One file as UTF-8 text. */
  async readText(path: string, options: { ref?: string } = {}): Promise<string> {
    return new TextDecoder().decode(await this.read(path, options));
  }

  /**
   * What's in the directory `prefix` (the root when empty), directories first; `recursive` lists
   * every file below it instead, without the directories. A symbolic link is one entry of type
   * `link`, whatever it points to.
   */
  async files(prefix = "", options: { ref?: string; recursive?: boolean } = {}): Promise<RepoFile[]> {
    const page = await this._request("GET", await this._repoPath("files"), {
      query: { prefix, ref: options.ref, recursive: options.recursive ? "true" : undefined },
    });
    return asList(page).map(toRepoFile);
  }

  /** The repo's branches, the default one first. */
  async branches(): Promise<Branch[]> {
    const rows = await paginate(this._api, await this._repoPath("branches"), { user: this._callScope() ?? null });
    return rows.map(toBranch);
  }

  /**
   * The branches agents' pushes rewrote or deleted, as NoClick kept them first: newest first, `limit` of them
   * (50 by default), of `branch` alone when it's given; each is kept 30 days. Through NoClick an agent never
   * force-pushes or deletes the default branch at all.
   *
   *     for (const backup of await repo.backups({ branch: "agent/new-form" })) console.log(backup.reason, backup.sha);
   */
  async backups(options: { branch?: string; limit?: number } = {}): Promise<RepoBackup[]> {
    const rows = await paginate(this._api, await this._repoPath("backups"), {
      query: { branch: options.branch },
      user: this._callScope() ?? null,
      limit: options.limit ?? 50,
    });
    return rows.map(toRepoBackup);
  }

  /**
   * Make a backup's branch again at the commit it was kept at (`backup`: a `RepoBackup` or its id). When the
   * repo has a branch by that name again, the backup comes back as `<branch>-restored-<time>` instead; nothing
   * that's there moves. Resolves to the branch made.
   */
  async restoreBackup(backup: RepoBackup | string): Promise<Branch> {
    const id = typeof backup === "string" ? backup : backup.id;
    return toBranch(await this._request("POST", await this._repoPath("backups", encodeURIComponent(id), "restore"), {
      json: {},
    }));
  }

  /** The history of `branch` (the default branch when omitted), newest first: `limit` commits (20 by default). */
  async commits(options: { branch?: string; limit?: number } = {}): Promise<Commit[]> {
    const rows = await paginate(this._api, await this._repoPath("commits"), {
      query: { branch: options.branch },
      user: this._callScope() ?? null,
      limit: options.limit ?? 20,
    });
    return rows.map(toCommit);
  }

  /** One page of `commits`, newest first; pass `nextCursor` back as `cursor` (null on the last page). */
  async commitsPage(options: { branch?: string } & PageOptions = {}): Promise<Page<Commit>> {
    const page = await fetchPage(this._api, await this._repoPath("commits"), {
      query: { branch: options.branch },
      user: this._callScope() ?? null,
      cursor: options.cursor,
      limit: options.limit,
    });
    return { data: page.data.map(toCommit), nextCursor: page.nextCursor };
  }

  /** What the commit `sha` (full or short) changed against its first parent, file by file; an unknown one throws `NotFound`. */
  async diff(sha: string): Promise<CommitDiff> {
    return toCommitDiff(await this._request("GET", await this._repoPath("commits", encodeURIComponent(sha))));
  }

  /** Package every branch and its history as a git bundle; `wait()` resolves to the `ExportBundle`. */
  async export(): Promise<Operation<ExportBundle>> {
    const payload = await this._request("POST", await this._repoPath("export"), { json: {} });
    return Operation._fromPayload<ExportBundle>(payload, {
      client: this._client, user: this._callScope(), kind: "repo.export", reader: toExportBundle,
    });
  }

  /**
   * Copy the repo, every branch and tag with its history, into a new GitHub repository `owner/name`
   * (`name` defaults to this repo's), through `connection`: a GitHub connection (a `Connection` or its
   * name) of the repo's user, or of the account. `owner` is the connected account's own login or an
   * organization it may create repositories in; the NoClick repo stays as it was. A connection with
   * no GitHub account connected yet throws `NeedsConnection`, whose `connectUrl` connects it. The
   * operation fails with `Conflict` when GitHub already has `owner/name`, and `PermissionDenied` when
   * the connected account can't create repositories there. `wait()` resolves to the new repository's URL.
   */
  async exportToGithub(options: {
    connection: string | Connection; owner: string; name?: string; private?: boolean;
  }): Promise<Operation<string | null>> {
    const payload = await this._request("POST", await this._repoPath("export"), {
      json: compact({
        to: "github", connection: await refId(options.connection), owner: options.owner, name: options.name,
        private: options.private ?? true,
      }),
    });
    return Operation._fromPayload<string | null>(payload, {
      client: this._client, user: this._callScope(), kind: "repo.export_to_github", reader: readGithubUrl,
    });
  }

  /**
   * Delete the repo and its history: it goes to the trash, restorable for 30 days. One an app
   * deploys from (`usedBy`) throws `Conflict`. Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this._repoPath()), this);
  }
}

/**
 * A public git repository being copied, history and all, into a new repo: the operation
 * `Repo.create(name, { fromUrl })` returns. The repo is listed at once (`repo`) but takes no commits or
 * pushes until the copy succeeds. `wait()` resolves to the `Repo` then: its `defaultBranch` the source's
 * own (or the one you named) and its `lastCommit` that branch's head. A copy that can't finish (no
 * repository at the URL, one that asks for a sign-in, over 5 GiB of history as git transfers it, which
 * isn't the repo's `sizeBytes` afterwards, longer than 15 minutes) rejects from `wait()` saying why, and
 * the repo is deleted; so is one you `cancel()`. `progress` shows how far it got.
 */
export class RepoImport extends Operation<Repo> {
  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal */
  static _fromResponse(payload: unknown, init: { client?: NoClick; user?: UserOption }): RepoImport {
    const made = new RepoImport(Operation._init(payload, { ...init, kind: "repo.import" }));
    made._reader = readImport;
    return made;
  }

  /** The new repo's id. */
  get repoId(): string | null {
    return str(this._known("repo_id"));
  }
  /** The new repo: it reads while the copy runs, and takes writes once `wait()` resolves. */
  get repo(): Repo {
    return Repo.fromId(String(this._known("repo_id")), { client: this._client, user: this._callScope() });
  }
}
