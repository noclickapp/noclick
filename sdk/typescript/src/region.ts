/**
 * Regions: where a resource runs and keeps its data, in NoClick's own names
 * (`us-east`, `us-west`, `eu`, `ap`, and `in` for machines), never a cloud's. A resource takes its region
 * when it's created and keeps it: the `region` you pass, else (for a child agent) its
 * parent's, else your account's default, else none, which means wherever NoClick has
 * capacity. Pass `region: other.region` to put two resources together.
 *
 *     const eu = (await regions()).find((r) => r.name === "eu");
 *     const sandbox = await Sandbox.create({ region: "eu" });
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

export type RegionName = "us-east" | "us-west" | "eu" | "ap" | "in";
/**
 * The resource kinds placed by region today: `project` is an app; `browser` in `us-east`, `eu` and
 * `ap`; `dict` and `queue` in `us-east`; `in` (India) places `machine` alone; the rest everywhere but `in`.
 */
export type RegionKind =
  | "sandbox" | "agent" | "bucket" | "database" | "project" | "machine" | "browser" | "dict" | "queue";

export interface Region {
  /** What `region` takes. */
  name: RegionName;
  /** For people: `US East`, `US West`, `Europe`, `Asia-Pacific`. */
  label: string;
  location: string;
  kinds: RegionKind[];
  /** Whether it's your account's default region, which a resource takes when you name none. */
  default: boolean;
  raw: JsonObject;
}

function toRegion(raw: JsonObject): Region {
  return {
    name: str(raw.name) as RegionName,
    label: str(raw.label) ?? "",
    location: str(raw.location) ?? "",
    kinds: asList(raw.kinds) as RegionKind[],
    default: raw.default === true,
    raw,
  };
}

/**
 * Every region, or those that place `kind` (another kind throws `InvalidRequest` naming those
 * that are). Dicts and queues are kept in `us-east` only for now, and browsers run everywhere but
 * `us-west`. Your account's default is set in the console. Needs the scope of any kind it places:
 * `sandboxes`, `agents`, `storage`, `databases`, `apps`, `machines`, `browsers`, `dicts`, `queues` or
 * `volumes`.
 *
 *     const where = await regions({ kind: "agent" });
 */
export async function regions(options: { kind?: RegionKind; client?: NoClick } = {}): Promise<Region[]> {
  const page = await resolveClient(options.client).request("GET", "/v1/regions", {
    query: { kind: options.kind }, user: null,
  });
  return asList(page).map((row) => toRegion(asObject(row)));
}

/** `region` on what holds data or runs compute: fixed when it's created. */
export interface PlacementOptions {
  /** Where it runs or keeps its data (`regions()`); omitted, your account's default region. */
  region?: RegionName;
}
