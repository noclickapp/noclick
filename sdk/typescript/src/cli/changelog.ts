/**
 * `noclick changelog`'s source: the docs' changelog page as Markdown (`<docs>/changelog.md`), read with no key, as the
 * Python CLI reads it (`noclick/_cli/changelog.py`).
 *
 * The page has a `## <Month D, YYYY>` heading a day, newest first, and under it a `### <title>` an entry: a
 * `<Kind> · <areas>` line, then its body. Each entry's `slug` is its title's (`noclick changelog <slug>` prints it
 * whole), and its URL its anchor on its month's page. `NOCLICK_DOCS_URL` points at another site's docs (a self-hosted
 * install's).
 */

export const DOCS_URL_ENV = "NOCLICK_DOCS_URL";
export const DEFAULT_DOCS_URL = "https://www.noclick.com/docs";
const DAY = /^## ([A-Z][a-z]+) (\d{1,2}), (\d{4})\s*$/;
const KIND = /^(New|Improved|Fixed) · (.+)$/;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];

export interface Change {
  date: string;
  title: string;
  slug: string;
  url: string;
  kind: string | null;
  areas: string | null;
  body: string;
}

export const docsUrl = (env: Record<string, string | undefined>) => (env[DOCS_URL_ENV] || DEFAULT_DOCS_URL).replace(/\/+$/, "");
export const pageUrl = (env: Record<string, string | undefined>) => `${docsUrl(env)}/changelog.md`;

export function slugify(text: string): string {
  return text.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function dayOf(line: string): string | null {
  const m = DAY.exec(line);
  const month = m ? MONTHS.indexOf(m[1]!) + 1 : 0;
  return m && month ? `${m[3]}-${String(month).padStart(2, "0")}-${m[2]!.padStart(2, "0")}` : null;
}

/** The page's entries, newest day first and a day's in the page's order. */
export function parse(markdown: string, base: string): Change[] {
  const entries: Change[] = [];
  let date: string | null = null;
  let current: Omit<Change, "kind" | "areas" | "body"> | null = null;
  let lines: string[] = [];
  const close = () => {
    if (!current) return;
    while (lines.length && !lines[0]!.trim()) lines.shift();
    const kind = lines.length ? KIND.exec(lines[0]!) : null;
    if (kind) lines.shift();
    entries.push({ ...current, kind: kind ? kind[1]!.toLowerCase() : null, areas: kind ? kind[2]! : null, body: lines.join("\n").trim() });
  };
  for (const line of markdown.split(/\r?\n/)) {
    if (line.startsWith("## ")) {
      close();
      current = null;
      lines = [];
      date = dayOf(line);
    } else if (line.startsWith("### ") && date) {
      close();
      const title = line.slice(4).trim();
      const slug = slugify(title);
      current = { date, title, slug, url: `${base}/changelog/${date.slice(0, 7)}#${date}-${slug}` };
      lines = [];
    } else if (current) lines.push(line);
  }
  close();
  return entries.sort((a, b) => b.date.localeCompare(a.date));
}

/** The entries `query` names: by slug (with its date, after or before it, or without) or title, else those whose
 *  title holds it. */
export function find(entries: Change[], query: string): Change[] {
  const wanted = query.trim().toLowerCase();
  const exact = entries.filter((e) => [e.slug, `${e.slug}-${e.date}`, `${e.date}-${e.slug}`, e.title.toLowerCase()].includes(wanted));
  const slug = slugify(wanted);
  return exact.length ? exact : entries.filter((e) => wanted && (e.title.toLowerCase().includes(wanted) || (slug && e.slug.includes(slug))));
}

/** What names `entry` alone: its slug, followed by its date where another day has a change so called. */
export function ref(entry: Change, entries: Change[]): string {
  return entries.filter((e) => e.slug === entry.slug).length === 1 ? entry.slug : `${entry.slug}-${entry.date}`;
}
