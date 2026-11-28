/** What the curated commands take from the process they run in: tests hand in their own. */

import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { hostname } from "node:os";
import { createInterface } from "node:readline";

export interface Host {
  env: Record<string, string | undefined>;
  cwd(): string;
  /** All of stdin, as text. */
  stdin(): Promise<string>;
  stdinIsTty(): boolean;
  sleep(ms: number): Promise<void>;
  /** The fetch every client a command makes uses (the global one unless a test sets it). */
  fetch?: typeof fetch;
  /** Put the profile's key on the default client: what a command that signs in itself (`whoami`) calls. */
  signIn(profile: string): void;
  /** All of stdin, as bytes. */
  stdinBytes(): Buffer;
  /** What's typed, a line at a time, after `prompt()` at a terminal; or each line piped in. Ends at Ctrl-D (or the
   *  pipe's end). */
  lines(prompt: () => string): AsyncIterable<string>;
  /** Bytes to stdout as they are (a file copied to `-`). */
  writeOut(data: Uint8Array): void;
  hostname(): string;
  /** Ctrl-C, caught while `catching` (a release being followed stops following rather than exiting): its promise
   *  settles on the next Ctrl-C until `release()`. */
  interrupted(): { promise: Promise<void>; release(): void };
  /** Open a URL in the browser; whether it was handed to one. */
  openUrl(url: string): boolean;
  /** Start `node <args>` on its own, never waited on (the update check, a completion cache's read). */
  detached(args: string[]): void;
  /** Run a program to its end with `input` on its stdin (the OS keychain's own tools): null when there's no such
   *  program. */
  run(command: string, args: string[], input?: string): { status: number; stdout: string; stderr: string } | null;
  /** The OS, which decides how the keychain is reached. */
  platform: NodeJS.Platform;
}


const OPENER: Record<string, [string, string[]]> = { darwin: ["open", []], win32: ["cmd", ["/c", "start", '""']] };

function spawned(command: string, args: string[]): boolean {
  try {
    spawn(command, args, { detached: true, stdio: "ignore", windowsHide: true }).on("error", () => {}).unref();
    return true;
  } catch {
    return false;
  }
}


async function* typed(prompt: () => string): AsyncGenerator<string> {
  if (!process.stdin.isTTY) {
    const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
    for await (const line of reader) yield line;
    return;
  }
  const reader = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
  try {
    for (;;) {
      const line = await new Promise<string | null>((done) => {
        const closed = () => done(null);
        reader.once("close", closed);
        reader.question(prompt(), (answer) => {
          reader.off("close", closed);
          done(answer);
        });
      });
      if (line === null) {
        process.stdout.write("\n");
        return;
      }
      yield line;
    }
  } finally {
    reader.close();
  }
}

const catchers: (() => void)[] = [];

/** Whether a command catches this Ctrl-C itself (`bin.ts` exits on it otherwise). */
export function takeInterrupt(): boolean {
  const catcher = catchers.at(-1);
  if (!catcher) return false;
  catcher();
  return true;
}

export const host: Host = {
  env: process.env,
  cwd: () => process.cwd(),
  stdin: async () => readFileSync(0, "utf8"),
  stdinIsTty: () => Boolean(process.stdin.isTTY),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  signIn: () => {
    throw new Error("host.signIn is set by main");
  },
  stdinBytes: () => readFileSync(0),
  lines: typed,
  writeOut: (data) => process.stdout.write(data),
  hostname: () => hostname(),
  interrupted: () => {
    let release = () => {};
    const promise = new Promise<void>((resolve) => {
      catchers.push(resolve);
      release = () => {
        const at = catchers.indexOf(resolve);
        if (at >= 0) catchers.splice(at, 1);
      };
    });
    return { promise, release };
  },
  openUrl: (url) => {
    const [command, args] = OPENER[process.platform] ?? ["xdg-open", []];
    return spawned(command, [...args, url]);
  },
  detached: (args) => {
    spawned(process.execPath, args);
  },
  platform: process.platform,
  run: (command, args, input) => {
    const ran = spawnSync(command, args, { input: input ?? "", encoding: "utf8", windowsHide: true, timeout: 60_000 });
    if ((ran.error as NodeJS.ErrnoException | undefined)?.code === "ENOENT") return null;
    if (ran.error) return { status: -1, stdout: "", stderr: ran.error.message };
    return { status: ran.status ?? -1, stdout: ran.stdout ?? "", stderr: ran.stderr ?? "" };
  },
};
