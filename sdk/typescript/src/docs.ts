/**
 * NoClick's docs as Markdown: the guides, skills (task playbooks), SDK reference, examples and API operations,
 * searched and read with no key, as `noclick docs` and `noclick skill` print them.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** A doc a search found, or one a listing names: its `id` (`guide:apps`, `skill:ship-an-app`) reads it whole. */
export interface DocHit {
  id: string;
  kind: string;
  title: string;
  url: string | null;
  snippet: string;
  /** `built`, or `designed` for an API call that doesn't work yet. */
  status: string;
  raw: JsonObject;
}

/** One guide page or section, skill, reference entry, example or API operation, whole: `text` is Markdown. */
export interface Doc {
  id: string;
  kind: string;
  title: string;
  summary: string;
  url: string | null;
  status: string;
  text: string;
  /** A page's sections, by id. */
  sections: string[];
  raw: JsonObject;
}

/** NoClick's docs, for code and coding agents: no key needed. */
export class Docs {
  /**
   * Search the docs, best first; with no `query`, list every guide page and skill (or `kind`'s: `guide`, `skill`,
   * `reference`, `example`, `event`, `api`).
   *
   *     for (const hit of await Docs.search("send email from an agent", { limit: 5 })) console.log(hit.id, hit.title);
   */
  static async search(query?: string, options: { kind?: string; limit?: number; client?: NoClick } = {}): Promise<DocHit[]> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/docs", {
      query: { q: query || undefined, kind: options.kind, limit: query ? options.limit ?? 20 : undefined },
      user: null, anonymous: true,
    }));
    return asList(raw.data).map((row) => {
      const hit = asObject(row);
      return { id: str(hit.id) ?? "", kind: str(hit.kind) ?? "", title: str(hit.title) ?? "", url: str(hit.url),
               snippet: str(hit.snippet) ?? "", status: str(hit.status) ?? "built", raw: hit };
    });
  }

  /**
   * Read one doc whole: a hit's `id`, or a bare name (`apps`), which reads the guide, else the skill, so named. One
   * nobody has rejects with `NotFound`.
   *
   *     console.log((await Docs.read("skill:ship-an-app")).text);
   */
  static async read(id: string, options: { client?: NoClick } = {}): Promise<Doc> {
    const raw = asObject(await resolveClient(options.client).request("GET", `/v1/docs/${id}`, {
      user: null, anonymous: true,
    }));
    return { id: str(raw.id) ?? "", kind: str(raw.kind) ?? "", title: str(raw.title) ?? "",
             summary: str(raw.summary) ?? "", url: str(raw.url), status: str(raw.status) ?? "built",
             text: str(raw.text) ?? "", sections: asList(raw.sections).map(String), raw };
  }
}
