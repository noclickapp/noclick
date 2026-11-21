// Helpers for "list" references — values like `{{nodeId.items[].title}}` whose
// `[]` maps a field over an array, producing a LIST value (no loop). Used by the
// "Loop over each item" affordance, which detects a list ref in a scalar field
// and rewrites it to an explicit iteration node's per-item form
// (`{{iterationId.item.title}}`). Added alongside the removal of implicit `[]`
// auto-iteration so looping is always an explicit, visible node.

// Matches a single {{ before[].after }} reference. `before` is the source
// (nodeId optionally followed by the array path); `after` is the per-item path.
const SINGLE_LIST_REF = /\{\{\s*([^}[\]]*?)\[\]([^}[\]]*?)\s*\}\}/;

export interface ParsedListReference {
  /** The full matched `{{...}}` substring. */
  raw: string;
  /** Source node id (the segment before the first dot / the `[]`). */
  nodeId: string;
  /** Path to the array on the source output, before `[]` (e.g. "items",
   *  "data.records"); empty when the node output itself is the array. */
  arrayPath: string;
  /** Per-item path after `[]`, leading dot stripped (e.g. "snippet.title", ""). */
  remainder: string;
}

function splitBefore(before: string): { nodeId: string; arrayPath: string } {
  const dot = before.indexOf('.');
  return dot === -1
    ? { nodeId: before, arrayPath: '' }
    : { nodeId: before.slice(0, dot), arrayPath: before.slice(dot + 1) };
}

/** True if the string contains at least one `[]` list reference. */
export function hasListReference(value: unknown): value is string {
  return typeof value === 'string' && SINGLE_LIST_REF.test(value);
}

/** Parse the first list reference in `value`, or null if there is none. */
export function parseListReference(value: string): ParsedListReference | null {
  const m = value.match(SINGLE_LIST_REF);
  if (!m) return null;
  const { nodeId, arrayPath } = splitBefore(m[1]);
  if (!nodeId) return null;
  return { raw: m[0], nodeId, arrayPath, remainder: m[2].replace(/^\./, '') };
}

// A field whose ENTIRE value is one plain `{{node.path}}` reference — where the
// path may include nested fields and numeric indices (`{{split-out.items}}`,
// `{{sheets.values[5]}}`, `{{api.data.rows[0]}}`), but NOT the `[]` map syntax
// (empty brackets route to the list-ref path instead). This is the natural way a
// user references an array; whether the path actually resolves to an array is
// decided by the caller (which has the upstream output), since a ref can equally
// point at a scalar. `[^}[\]]+` is the leading non-bracket path; each `[\d+]`
// index may be followed by more path (`values[5].cells`).
const WHOLE_REF = /^\s*\{\{\s*([^}[\]]+(?:\[\d+\][^}[\]]*)*)\s*\}\}\s*$/;

/** Parse a value that is exactly one whole `{{node.path}}` ref (numeric indices
 *  allowed), else null. nodeId is the leading id; arrayPath is the rest of the
 *  path (`.field` / `[n]` chain, leading dot stripped). */
export function parseWholeReference(
  value: unknown,
): { nodeId: string; arrayPath: string } | null {
  if (typeof value !== 'string') return null;
  const m = value.match(WHOLE_REF);
  if (!m) return null;
  const path = m[1].trim(); // greedy capture can keep a trailing space before }}
  const sep = path.search(/[.[]/); // nodeId ends at the first '.' or '['
  const nodeId = sep === -1 ? path : path.slice(0, sep);
  if (!nodeId) return null;
  const arrayPath = sep === -1 ? '' : path.slice(sep).replace(/^\./, '');
  return { nodeId, arrayPath };
}

/** Split a reference path at its FIRST literal `[n]` index — the point at which
 *  the loop is offered. The prefix is the OUTERMOST array to iterate
 *  (`values[8][1]` -> loop `values`; the row becomes `item`, leaving `[1]` as a
 *  per-item accessor). `hasIndex` says whether a literal index was present; with
 *  none, the whole path is the prefix (a plain whole-array ref). */
export function splitAtFirstIndex(path: string): { prefix: string; hasIndex: boolean } {
  const i = path.search(/\[\d+\]/);
  return i === -1 ? { prefix: path, hasIndex: false } : { prefix: path.slice(0, i), hasIndex: true };
}

/** The `{{...}}` an iteration node's `items` config should hold to iterate the
 *  array a list reference points at (`{{src.items[].x}}` -> `{{src.items}}`). */
export function buildItemsReference(ref: ParsedListReference): string {
  return `{{${ref.nodeId}${ref.arrayPath ? '.' + ref.arrayPath : ''}}}`;
}

/** Shallow-clip one array item into a small display sample: keep top-level keys
 *  (what the iteration panel surfaces as `item.<key>`), truncate long strings,
 *  and summarize nested arrays/objects. Keeps the persisted preview tiny. */
export function clipSampleItem(item: unknown): unknown {
  if (!item || typeof item !== 'object' || Array.isArray(item)) {
    return typeof item === 'string' && item.length > 80 ? item.slice(0, 80) + '…' : item;
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(item as Record<string, unknown>)) {
    if (v === null || typeof v !== 'object') {
      out[k] = typeof v === 'string' && v.length > 80 ? v.slice(0, 80) + '…' : v;
    } else if (Array.isArray(v)) {
      out[k] = `[${v.length} item${v.length === 1 ? '' : 's'}]`;
    } else {
      out[k] = `{${Object.keys(v as object).length} fields}`;
    }
  }
  return out;
}

/** Read a value at a dotted path with optional `[n]` indices (e.g.
 *  "data.items", "results[0].rows"). Returns undefined for any missing
 *  segment. Used to pull the source array out of a node's output. */
export function getValueAtPath(obj: unknown, path: string): unknown {
  if (!path) return obj;
  let cur: any = obj;
  for (const part of path.split('.')) {
    if (cur == null) return undefined;
    const m = part.match(/^([^[]*)((?:\[\d+\])*)$/);
    if (!m) return undefined;
    if (m[1]) cur = typeof cur === 'object' ? cur[m[1]] : undefined;
    if (m[2]) {
      for (const im of m[2].matchAll(/\[(\d+)\]/g)) {
        const idx = Number(im[1]);
        cur = Array.isArray(cur) && idx < cur.length ? cur[idx] : undefined;
      }
    }
  }
  return cur;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Rewrite every reference to the SAME source array into the iteration node's
 *  per-item form. `arrayPath` is the array being looped — the path up to its
 *  first literal index. All three ways of reaching that array map onto `item`:
 *    {{src.arrayPath}}          -> {{iter.item}}          (whole array)
 *    {{src.arrayPath[].title}}  -> {{iter.item.title}}    ([] map)
 *    {{src.arrayPath[8][1]}}    -> {{iter.item[1]}}        (literal index -> loop var)
 *  References to other sources / other fields are left untouched (`base` is
 *  followed only by `}`, `[]`, or `[n]`, so `items_count` never matches). */
export function rewriteListRefsForIteration(
  value: string,
  sourceNodeId: string,
  arrayPath: string,
  iterationId: string,
): string {
  const base = escapeRegExp(`${sourceNodeId}${arrayPath ? '.' + arrayPath : ''}`);
  const item = `{{${iterationId}.item`;
  return value
    // [] map: keep the post-`[]` accessor (".title", "")
    .replace(new RegExp(`\\{\\{\\s*${base}\\[\\]([^}]*?)\\s*\\}\\}`, 'g'), (_f, rest: string) => `${item}${rest}}}`)
    // literal index [n]: drop the looped index, keep any deeper accessor ("[1]", ".name", "")
    .replace(new RegExp(`\\{\\{\\s*${base}\\[\\d+\\]([^}]*?)\\s*\\}\\}`, 'g'), (_f, rest: string) => `${item}${rest}}}`)
    // whole-array ref
    .replace(new RegExp(`\\{\\{\\s*${base}\\s*\\}\\}`, 'g'), `${item}}}`);
}
