/**
 * The team workspaces of the NoClick app you're in, as its workspace settings show them.
 *
 *     const acme = await Organization.create("Acme Ops");
 *     await Organization.invite(acme, "sam@example.com", { role: "admin" });
 *     for (const member of await Organization.members(acme)) console.log(member.email, member.role);
 *
 * A team workspace's members are people, so every call is a signed-in person's own: a client holding a person's
 * session token (never a key, which refuses them all). Not `Workspace`, which is one of Work's spaces. Members,
 * invites and single sign-on come back as the API answers them.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject } from "./object.ts";
import type { JsonObject } from "./object.ts";

type Ref = string | Organization;
type Options = { client?: NoClick };

const idOf = (ref: Ref) => (typeof ref === "string" ? ref : ref.id);
const at = (ref: Ref) => `/v1/organizations/${encodeURIComponent(idOf(ref))}`;

async function call(options: Options, method: string, path: string, body?: JsonObject): Promise<JsonObject> {
  const json = body && Object.fromEntries(Object.entries(body).filter(([, v]) => v !== undefined));
  return asObject(await resolveClient(options.client).request(method, path, { json, user: null }));
}

const list = (raw: JsonObject): JsonObject[] => (Array.isArray(raw.data) ? raw.data.map((row) => asObject(row)) : []);

/** A team workspace you're in. */
export class Organization {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  /** Your role in it: `owner`, `admin` or `member`. */
  readonly role: string | null;
  readonly iconUrl: string | null;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.id = String(raw.id);
    this.name = String(raw.name ?? "");
    this.slug = String(raw.slug ?? "");
    this.role = (raw.role as string | undefined) ?? (raw.user_role as string | undefined) ?? null;
    this.iconUrl = (raw.icon_url as string | null | undefined) ?? null;
    this.raw = raw;
  }

  /** The team workspaces you're in, each with your `role`. */
  static async list(options: Options = {}): Promise<Organization[]> {
    return list(await call(options, "GET", "/v1/organizations")).map((row) => new Organization(row));
  }

  /** One you're in, by id. */
  static async get(organization: Ref, options: Options = {}): Promise<Organization> {
    return new Organization(asObject((await call(options, "GET", at(organization))).organization));
  }

  /**
   * Make a team workspace with you as its owner (`slug` made from the name when left out); your session acts in it
   * from then on. How many you may own is your plan's.
   */
  static async create(name: string, options: Options & { slug?: string } = {}): Promise<Organization> {
    const made = await call(options, "POST", "/v1/organizations", { name, slug: options.slug });
    return new Organization({ ...asObject(made.organization), role: "owner" });
  }

  /** Rename it or change its settings (its owner or an admin). */
  static async update(organization: Ref, changes: { name?: string; settings?: JsonObject }, options: Options = {}): Promise<JsonObject> {
    return await call(options, "PATCH", at(organization), changes as JsonObject);
  }

  /** Delete it for good, its members and invites with it (its owner only). */
  static async delete(organization: Ref, options: Options = {}): Promise<void> {
    await call(options, "DELETE", at(organization));
  }

  /** Whether a new team workspace could take `slug`. */
  static async slugAvailable(slug: string, options: Options = {}): Promise<boolean> {
    return (await call(options, "GET", `/v1/organizations/slugs/${encodeURIComponent(slug)}`)).available === true;
  }

  /** Its members, each with their `user_id`, `email` and `role`. */
  static async members(organization: Ref, options: Options = {}): Promise<JsonObject[]> {
    return list(await call(options, "GET", `${at(organization)}/members`));
  }

  /**
   * Invite someone by email (its owner or an admin): they're emailed a link that joins them as `role`. How many people
   * it holds is its plan's. Answers the invite, with `email_sent`: `false` when its email couldn't go (`email_error`
   * says why), and the invite stands all the same, so share its link yourself.
   */
  static async invite(organization: Ref, email: string, options: Options & { role?: "admin" | "member" } = {}): Promise<JsonObject> {
    const made = asObject(await call(options, "POST", `${at(organization)}/members`, { email, role: options.role ?? "member" }));
    const told = Object.fromEntries(["email_sent", "email_error"].filter((k) => k in made).map((k) => [k, made[k]]));
    return { ...asObject(made.invite), ...told };
  }

  /** Change a member's role (its owner or an admin; never the owner's). */
  static async setRole(organization: Ref, userId: string, role: "admin" | "member", options: Options = {}): Promise<void> {
    await call(options, "PATCH", `${at(organization)}/members/${encodeURIComponent(userId)}`, { role });
  }

  /** Take a member out (its owner or an admin; never the owner). */
  static async removeMember(organization: Ref, userId: string, options: Options = {}): Promise<void> {
    await call(options, "DELETE", `${at(organization)}/members/${encodeURIComponent(userId)}`);
  }

  /** Hand it to another of its members (its owner only): they become its owner, you an admin. */
  static async transfer(organization: Ref, userId: string, options: Options = {}): Promise<void> {
    await call(options, "POST", `${at(organization)}/transfer`, { user_id: userId });
  }

  /** Its invites still waiting to be accepted. */
  static async invites(organization: Ref, options: Options = {}): Promise<JsonObject[]> {
    return list(await call(options, "GET", `${at(organization)}/invites`));
  }

  /** Call an invite off: its link stops working. */
  static async revokeInvite(organization: Ref, inviteId: string, options: Options = {}): Promise<void> {
    await call(options, "DELETE", `${at(organization)}/invites/${encodeURIComponent(inviteId)}`);
  }

  /** Join the team workspace an invite to your email asks you to. */
  static async acceptInvite(token: string, options: Options = {}): Promise<JsonObject> {
    return await call(options, "POST", `/v1/organizations/invites/${encodeURIComponent(token)}/accept`);
  }

  /** Make the workspace your session acts in a team one you're in, or your own (`null`). */
  static async switchTo(organization: Ref | null, options: Options = {}): Promise<void> {
    await call(options, "POST", "/v1/me/organization", { organization_id: organization === null ? null : idOf(organization) });
  }
}
