/**
 * How the CLI looks to a person at a terminal: headings with a rule under them, dimmed descriptions, an accent, the
 * colours of a result (ok, warn, error) and bordered tables. Plain ANSI, no dependencies; the Python CLI's
 * `noclick/_cli/style.py` draws the same.
 *
 * Never for a machine: each stream is styled only when it's a terminal, never under `NO_COLOR`, `TERM=dumb` or `CI`,
 * and `--color always|never` decides past all of that. Unstyled, every command prints exactly what it printed before
 * there were styles, so what a script or an agent reads never changes.
 *
 * The colours are NoClick's own: the violet and blue of the one mark the product draws in colour (Automations'), its
 * zinc greys for what's quiet, and the status hues of the app (emerald, red; orange where the app has amber, no
 * yellow).
 */

export const MODES = ["auto", "always", "never"] as const;
export type Mode = (typeof MODES)[number];
export type Role = "accent" | "link" | "dim" | "rule" | "ok" | "warn" | "error";

/** Each role's colour: 24-bit where the terminal says it takes it, else the nearest of the 256. */
export const PALETTE: Record<Role, [[number, number, number], number]> = {
  accent: [[180, 156, 255], 147], // #b49cff, the mark's violet: headings, command names
  link: [[127, 212, 255], 117], // #7fd4ff, the mark's blue: URLs and commands to copy
  dim: [[161, 161, 170], 248], // zinc-400, the app's muted text
  rule: [[82, 82, 91], 240], // zinc-600: rules and table borders
  ok: [[52, 211, 153], 79], // emerald-400
  warn: [[251, 146, 60], 209], // orange-400
  error: [[248, 113, 113], 210], // red-400
};

export const ESCAPE = /\x1b\[[0-9;]*m/g;
const ELLIPSIS = "…";
/** Columns whose cells are copied whole (an id, a commit, a key), cut only once nothing else can give. */
const KEPT_WHOLE = new Set(["ID", "KEY", "COMMIT", "URL"]);
const DONE = /^(Ready:|Signed (in|up|out)|Set |Deleted |Linked |Unlinked |Made |Promoted |Rolled back |Bound |Added |Bought |Revoked )/;
const STEP = /^(Deploying|Building|Shipping|Checking|Waiting|Stopping)\b/;
const STATUS: Record<"ok" | "warn" | "error", Set<string>> = {
  ok: new Set(["ready", "live", "active", "available", "yes", "succeeded", "completed", "claimed", "running", "confirmed", "done"]),
  warn: new Set(["building", "queued", "pending", "deploying", "waiting", "unclaimed", "paused", "starting"]),
  error: new Set(["failed", "error", "canceled", "cancelled", "expired", "no", "revoked", "stopped"]),
};

/** A status screen's line, its label padded to 12; and the app's name and URL heading it. */
const FIELD = /^( {0,2})([a-z][a-z ]{10}) (\S.*)$/;
const HEAD = /^([\w.-]+) {2}(https?:\/\/\S+)$/;

const statusRole = (value: string): Role | null =>
  (Object.entries(STATUS).find(([, words]) => words.has(value.trim().toLowerCase()))?.[0] as Role | undefined) ?? null;

type Env = Record<string, string | undefined>;

/** Whether to style a stream under `--color mode`. */
export function wanted(mode: string, isTty: boolean, env: Env): boolean {
  if (mode === "always") return true;
  if (mode === "never" || env.NO_COLOR || env.TERM === "dumb" || env.CI) return false;
  return isTty;
}

export const clip = (text: string, width: number) => (text.length <= width ? text : text.slice(0, Math.max(width - 1, 0)) + ELLIPSIS);
export const visible = (text: string) => text.replace(ESCAPE, "");

/** Column widths narrowed, widest first, until the box (borders and padding included) fits `total`; a column `keep`
 *  marks (an id to copy) only once nothing else can give. */
export function fit(widths: number[], floors: number[], total: number, keep: boolean[] = []): number[] {
  const w = [...widths];
  const floor = floors.map((f, i) => Math.min(Math.max(f, 3), w[i]!));
  const over = () => w.reduce((a, b) => a + b, 0) + 3 * w.length + 1 > total;
  while (over()) {
    let room = w.map((_, i) => i).filter((i) => w[i]! > floor[i]! && !keep[i]);
    if (!room.length) room = w.map((_, i) => i).filter((i) => w[i]! > floor[i]!);
    if (!room.length) break;
    const widest = room.reduce((a, b) => (w[b]! > w[a]! ? b : a));
    w[widest]! -= 1;
  }
  return w;
}

/** One stream's styles; every method answers `text` as it is when the stream isn't styled. */
export class Style {
  on: boolean;
  truecolor: boolean;
  columns: () => number;

  constructor(on = false, options: { truecolor?: boolean; columns?: () => number } = {}) {
    this.on = on;
    this.truecolor = options.truecolor ?? false;
    this.columns = options.columns ?? (() => 100);
  }

  width(): number {
    return this.columns() || 100;
  }

  paint(text: string, role?: Role | null, bold = false): string {
    if (!this.on || !text || !(role || bold)) return text;
    const codes = bold ? ["1"] : [];
    if (role) {
      const [[r, g, b], nearest] = PALETTE[role];
      codes.push(this.truecolor ? `38;2;${r};${g};${b}` : `38;5;${nearest}`);
    }
    return `\x1b[${codes.join(";")}m${text}\x1b[0m`;
  }

  bold = (text: string) => this.paint(text, null, true);
  dim = (text: string) => this.paint(text, "dim");
  accent = (text: string) => this.paint(text, "accent");
  link = (text: string) => this.paint(text, "link");
  ok = (text: string) => this.paint(text, "ok");
  warn = (text: string) => this.paint(text, "warn");
  error = (text: string) => this.paint(text, "error", true);

  /** A section's heading: bold in the accent, a thin rule under it as wide as the terminal allows. */
  section(title: string): string[] {
    if (!this.on) return [`${title}:`];
    return [this.paint(title, "accent", true), this.paint("─".repeat(Math.min(this.width(), 100)), "rule")];
  }

  /** A note for a person: a check before what was done, an arrow before a step under way, the rest dimmed. A line
   *  already styled (an error's) is left as it is. */
  note(text: string): string {
    if (!this.on || text.includes("\x1b[")) return text;
    if (DONE.test(text)) return `${this.ok("✓")} ${text}`;
    if (STEP.test(text)) return `${this.accent("›")} ${text}`;
    return this.dim(text);
  }

  /** A screen of `label  value` lines (`noclick status`): labels dimmed, a status word in its colour, a URL in the
   *  link colour, the app's own name bold. */
  fields(lines: string[]): string[] {
    if (!this.on) return lines;
    return lines.map((line) => {
      const head = HEAD.exec(line);
      if (head) return `${this.bold(head[1]!)}  ${this.link(head[2]!)}`;
      const field = FIELD.exec(line);
      if (!field) return line;
      const [, indent, label, value] = field;
      const space = value!.indexOf(" ");
      const word = space < 0 ? value! : value!.slice(0, space);
      const rest = space < 0 ? "" : value!.slice(space);
      const role: Role | null = word === "unread" ? "warn" : statusRole(word);
      return `${indent}${this.dim(label!)} ${this.paint(word, role)}${rest}`;
    });
  }

  /** Rows under bold headers in a box, its columns fitted to the terminal, a cell too long cut with "…". */
  table(headers: string[], rows: string[][], title?: string): string[] {
    const widths = fit(headers.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i]!.length))),
      headers.map((h) => h.length), this.width(), headers.map((h) => KEPT_WHOLE.has(h.trim().toUpperCase())));
    const edge = (left: string, mid: string, right: string) => this.paint(left + widths.map((w) => "─".repeat(w + 2)).join(mid) + right, "rule");
    const bar = this.paint("│", "rule");
    const status = headers.map((h) => ["STATUS", "STATE", "AVAILABLE"].includes(h.trim().toUpperCase()));
    const line = (cells: string[], header = false) => bar + cells.map((c, i) => {
      const text = clip(c, widths[i]!).padEnd(widths[i]!);
      return ` ${header ? this.bold(text) : status[i] ? this.paint(text, statusRole(c)) : text} `;
    }).join(bar) + bar;
    const out: string[] = [];
    if (title) {
      const total = widths.reduce((a, b) => a + b, 0) + 3 * widths.length + 1;
      const shown = clip(title, total);
      const left = Math.floor((total - shown.length) / 2);
      out.push(this.bold(" ".repeat(left) + shown));
    }
    out.push(edge("╭", "┬", "╮"), line(headers, true), edge("├", "┼", "┤"), ...rows.map((r) => line(r)), edge("╰", "┴", "╯"));
    return out;
  }
}

export const OUT = new Style();
export const ERR = new Style();

/** Decide, once a command starts, whether its stdout and stderr are styled. */
export function configure(mode: string, streams: { out: boolean; err: boolean }, env: Env, columns: () => number): void {
  const truecolor = env.COLORTERM === "truecolor" || env.COLORTERM === "24bit";
  for (const [style, tty] of [[OUT, streams.out], [ERR, streams.err]] as const) {
    style.on = wanted(mode, tty, env);
    style.truecolor = truecolor;
    style.columns = columns;
  }
}

/** `--color`'s value among the flags before the command (`auto` without one). */
export function modeIn(argv: string[]): string {
  for (let i = 0; i < argv.length; i++) {
    const word = argv[i]!;
    if (!word.startsWith("-")) break;
    if (word.startsWith("--color=")) return word.slice(8);
    if (word === "--color") return argv[i + 1] ?? "auto";
    if (word === "--profile") i++;
  }
  return "auto";
}
