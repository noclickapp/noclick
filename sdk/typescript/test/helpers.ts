/** A tiny fetch double: routes by method + path, records every call. */

import { configure } from "../src/index.ts";
import type { NoClick } from "../src/index.ts";

export const BASE = "https://api.test";
export const USER_ID = "user_42";

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: Headers;
  body: unknown;
}

type Reply = Response | Error | ((call: Call) => Response | Promise<Response>);

export function json(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

export function apiError(status: number, type: string, message = "no", extra: Record<string, unknown> = {}, headers?: Record<string, string>) {
  return json({ error: { type, message, ...extra } }, { status, headers });
}

export class Route {
  readonly calls: Call[] = [];
  private readonly replies: Reply[];

  constructor(replies: Reply[]) {
    this.replies = replies;
  }

  get count(): number {
    return this.calls.length;
  }
  get last(): Call {
    const call = this.calls.at(-1);
    if (!call) throw new Error("route was never called");
    return call;
  }

  async reply(call: Call): Promise<Response> {
    this.calls.push(call);
    const reply = this.replies[Math.min(this.calls.length - 1, this.replies.length - 1)];
    if (reply instanceof Error) throw reply;
    if (typeof reply === "function") return await reply(call);
    return reply.clone();
  }
}

export class MockApi {
  private readonly routes = new Map<string, Route>();

  on(method: string, path: string, ...replies: Reply[]): Route {
    const route = new Route(replies);
    this.routes.set(`${method} ${path}`, route);
    return route;
  }

  readonly fetch = async (input: string | URL | Request, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    let body: unknown = init.body ?? null;
    if (typeof body === "string") {
      try {
        body = JSON.parse(body);
      } catch {
        // a raw text body stays a string
      }
    }
    const call: Call = { method, path: url.pathname, query: url.searchParams, headers: new Headers(init.headers), body };
    const route = this.routes.get(`${method} ${url.pathname}`);
    if (!route) return apiError(404, "not_found", `no mock route for ${method} ${url.pathname}`);
    return await route.reply(call);
  };
}

export interface Setup {
  api: MockApi;
  client: NoClick;
  sleeps: number[];
}

/** Point the default client at a fresh mock API, with instant (recorded) backoff. */
export function setup(): Setup {
  const api = new MockApi();
  const client = configure({ apiKey: "nk_live_test", baseUrl: BASE, maxRetries: 2, fetch: api.fetch });
  const sleeps: number[] = [];
  client._sleep = async (ms) => {
    sleeps.push(ms);
  };
  return { api, client, sleeps };
}

export function operation(fields: Record<string, unknown> = {}) {
  return {
    object: "operation", id: "op_1", kind: "human.ask", status: "awaiting_human", result: null, error: null,
    created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z", ...fields,
  };
}

export function userRow(fields: Record<string, unknown> = {}) {
  return {
    object: "user", id: USER_ID, name: null, email: null, phone: null,
    spend_cap_usd_per_month: null, metadata: {}, status: "active", created_at: "2026-09-25T10:00:00Z", ...fields,
  };
}

export function trashItem(kind: string, resourceId: string, name: string, id = "tr_1") {
  return {
    object: "trash_item", id, kind, resource_id: resourceId, name, user_id: null,
    trashed_at: "2026-09-25T10:00:00Z", purge_after: "2026-10-25T10:00:00Z",
  };
}

/** What a delete answers: the resource gone to the trash, with the operation that undoes it. */
export function trashed(kind: string, resourceId: string, name: string, id = "tr_1") {
  const trash = trashItem(kind, resourceId, name, id);
  return { object: kind, id: resourceId, deleted: true, trash, restorable_until: trash.purge_after, operation_id: "op_del" };
}

export function listing(rows: unknown[] = [], nextCursor: string | null = null) {
  return { object: "list", data: rows, next_cursor: nextCursor };
}
