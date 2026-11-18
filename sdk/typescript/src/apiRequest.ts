/**
 * The API request log: every write and every failed request made with your
 * keys and sessions (successful reads aren't logged), newest first.
 *
 *     const { data } = await ApiRequest.listPage({ method: "POST", status: "4xx", key: "nk_live_ab12" });
 */

import { isoTime, listAll, listPage, num, parseTime, str } from "./object.ts";
import type { JsonObject, Page, PageOptions, ReadOptions } from "./object.ts";

export interface ApiRequestFilters extends ReadOptions {
  method?: string;
  /** A class (`2xx`, `4xx`, `5xx`) or one code. */
  status?: string | number;
  /** An error type such as `spend_cap_exceeded`. */
  errorType?: string;
  /** A key id or prefix. */
  key?: string;
  /** A route template such as `/v1/policy`. */
  route?: string;
  since?: Date | string;
  until?: Date | string;
}

function query(filters: ApiRequestFilters) {
  return {
    method: filters.method,
    status: filters.status,
    error_type: filters.errorType,
    key_id: filters.key,
    route: filters.route,
    since: isoTime(filters.since),
    until: isoTime(filters.until),
  };
}

/** One logged API request. */
export class ApiRequest {
  readonly id: string;
  /** `key`, `session` or `owner`. */
  readonly actor: string | null;
  readonly keyId: string | null;
  readonly userId: string | null;
  readonly sessionId: string | null;
  readonly method: string;
  /** The route template, e.g. `/v1/agents/{agent_id}/messages`. */
  readonly route: string;
  readonly pathParams: JsonObject;
  readonly status: number | null;
  readonly errorType: string | null;
  readonly durationMs: number | null;
  readonly idempotencyReplayed: boolean;
  /** The operation the request started, if any. */
  readonly operationId: string | null;
  readonly requestId: string | null;
  readonly createdAt: Date | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(raw: JsonObject) {
    this.id = String(raw.id);
    this.actor = str(raw.actor);
    this.keyId = str(raw.key_id);
    this.userId = str(raw.user_id);
    this.sessionId = str(raw.session_id);
    this.method = str(raw.method) ?? "";
    this.route = str(raw.route) ?? "";
    this.pathParams = raw.path_params && typeof raw.path_params === "object" ? (raw.path_params as JsonObject) : {};
    this.status = num(raw.status);
    this.errorType = str(raw.error_type);
    this.durationMs = num(raw.duration_ms);
    this.idempotencyReplayed = raw.idempotency_replayed === true;
    this.operationId = str(raw.operation_id);
    this.requestId = str(raw.request_id);
    this.createdAt = parseTime(raw.created_at);
    this.raw = raw;
  }

  /** Every matching request (or the first `limit`). */
  static async list(options: ApiRequestFilters & { limit?: number } = {}): Promise<ApiRequest[]> {
    return await listAll({ ...options, path: "/v1/requests", query: query(options) }, (raw) => new ApiRequest(raw));
  }

  /** One page of matching requests; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ApiRequestFilters & PageOptions = {}): Promise<Page<ApiRequest>> {
    return await listPage({ ...options, path: "/v1/requests", query: query(options) }, (raw) => new ApiRequest(raw));
  }
}
